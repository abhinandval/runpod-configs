#!/usr/bin/env python3
"""Fail-closed safety validation for JSON returned by runpodctl."""

from __future__ import annotations

import argparse
import json
import math
import sys
import re
from dataclasses import dataclass
from typing import Any


EXPECTED_MEMORY_GB = 24.0
MAX_EXECUTION_TIMEOUT_SECONDS = 180

GPU_CONTAINER_KEYS = {
    "gpu", "gpus", "gpudetails", "gpuinfo", "gpuconfiguration", "gpuconfig",
    "gpuids", "gpuid", "gputypeid", "gputype",
}
GPU_NAME_KEYS = {"name", "gpuname", "gputype", "gputypeid"}
GPU_MEMORY_GB_KEYS = {
    "memorygb", "memorygib", "vramb", "vramgb", "vramgib",
    "gpumemorygb", "gpumemorygib", "memoryingb", "memoryingib",
}
GPU_MEMORY_MB_KEYS = {"memorymb", "vramb", "gpumemorymb", "memoryinmb"}
GPU_GENERIC_MEMORY_KEYS = {"memory", "vram", "gpumemory"}
GPU_COUNT_KEYS = {"gpucount", "gpu_count"}
WORKERS_MIN_KEYS = {"workersmin", "workers_min", "minworkers"}
WORKERS_MAX_KEYS = {"workersmax", "workers_max", "maxworkers"}
EXECUTION_TIMEOUT_KEYS = {
    "executiontimeout", "execution_timeout", "executiontimeoutseconds",
    "execution_timeout_seconds",
}


@dataclass(frozen=True)
class _GPURecord:
    name: str | None
    memory_gb: float | None
    source: str


def _key(value: str) -> str:
    return value.casefold().replace("-", "").replace(" ", "")


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric; refusing ambiguous boolean")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{field} must be finite; refusing NaN or Infinity")
        return number
    if isinstance(value, str) and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value):
        return float(value)
    raise ValueError(f"{field} is missing or not a plain numeric value")


def _integer(value: Any, field: str) -> int:
    number = _number(value, field)
    if not number.is_integer():
        raise ValueError(f"{field} must be an integer")
    return int(number)


def _memory_gb(value: Any, key: str) -> float:
    normalized = _key(key)
    if normalized in GPU_GENERIC_MEMORY_KEYS:
        if not isinstance(value, str):
            raise ValueError(
                f"GPU field {key!r} has no explicit unit; refusing to guess memory"
            )
        match = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*(gb|gib|mb|mib)\s*", value, re.I
        )
        if not match:
            raise ValueError(
                f"GPU field {key!r} must include an explicit GB or MB unit"
            )
        amount = float(match.group(1))
        return amount / 1024 if match.group(2).lower() in {"mb", "mib"} else amount
    amount = _number(value, key)
    return amount / 1024 if normalized in GPU_MEMORY_MB_KEYS else amount


def _record(value: Any, source: str) -> list[_GPURecord]:
    if isinstance(value, list):
        if not value:
            raise ValueError(f"GPU field {source!r} is empty; refusing to guess")
        records: list[_GPURecord] = []
        for index, child in enumerate(value):
            records.extend(_record(child, f"{source}[{index}]"))
        return records
    if isinstance(value, str):
        return [_GPURecord(value.strip() or None, None, source)]
    if not isinstance(value, dict):
        raise ValueError(f"GPU field {source!r} has an ambiguous shape")

    names: set[str] = set()
    memories: list[float] = []
    for child_key, child_value in value.items():
        normalized = _key(str(child_key))
        if normalized in GPU_NAME_KEYS:
            if not isinstance(child_value, str) or not child_value.strip():
                raise ValueError(f"GPU name field {child_key!r} is ambiguous")
            names.add(child_value.strip())
        elif normalized in GPU_MEMORY_GB_KEYS | GPU_MEMORY_MB_KEYS | GPU_GENERIC_MEMORY_KEYS:
            memories.append(_memory_gb(child_value, str(child_key)))
    if len({name.casefold() for name in names}) > 1:
        raise ValueError(f"GPU record {source!r} exposes conflicting names")
    if memories and any(abs(memory - memories[0]) > 1e-9 for memory in memories[1:]):
        raise ValueError(f"GPU record {source!r} exposes conflicting memory values")
    return [_GPURecord(next(iter(names), None), memories[0] if memories else None, source)]


def _gpu_records(document: Any) -> list[_GPURecord]:
    records: list[_GPURecord] = []
    container_keys = {_key(item) for item in GPU_CONTAINER_KEYS}

    def visit(value: Any, path: str = "root") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_path = f"{path}.{child_key}"
                if _key(str(child_key)) in container_keys:
                    records.extend(_record(child_value, child_path))
                if isinstance(child_value, (dict, list)):
                    visit(child_value, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, (dict, list)):
                    visit(child, f"{path}[{index}]")

    visit(document)
    return records


def _merge_gpu_records(records: list[_GPURecord]) -> list[_GPURecord]:
    merged: list[_GPURecord] = []
    for record in records:
        match = next(
            (
                existing for existing in merged
                if existing.name and record.name
                and existing.source.split("[")[0] != record.source.split("[")[0]
                and existing.name.casefold() == record.name.casefold()
            ),
            None,
        )
        if match is None:
            merged.append(record)
            continue
        if match.memory_gb is not None and record.memory_gb is not None:
            if abs(match.memory_gb - record.memory_gb) > 1e-9:
                raise ValueError("endpoint exposes conflicting memory for the same GPU")
            continue
        if match.memory_gb is None and record.memory_gb is not None:
            merged[merged.index(match)] = _GPURecord(
                match.name, record.memory_gb, match.source
            )
    return merged


def _field_values(document: Any, keys: set[str]) -> list[Any]:
    values: list[Any] = []
    normalized_keys = {_key(item) for item in keys}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                if _key(str(child_key)) in normalized_keys:
                    values.append(child_value)
                if isinstance(child_value, (dict, list)):
                    visit(child_value)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(document)
    return values


def _one_field(document: Any, keys: set[str], label: str, *, required: bool) -> Any:
    values = _field_values(document, keys)
    if not values:
        if required:
            raise ValueError(f"endpoint JSON does not expose {label}; refusing to proceed")
        return None
    try:
        serialized = [json.dumps(value, sort_keys=True) for value in values]
    except TypeError as exc:
        raise ValueError(f"endpoint {label} field has an ambiguous shape") from exc
    if len(set(serialized)) != 1:
        raise ValueError(f"endpoint exposes conflicting {label} fields")
    return values[0]


def validate_endpoint(
    document: Any,
    expected_gpu: str,
    *,
    expected_memory_gb: float = EXPECTED_MEMORY_GB,
    require_scaling: bool = True,
    max_execution_timeout_seconds: int = MAX_EXECUTION_TIMEOUT_SECONDS,
) -> None:
    """Validate exact GPU, memory, worker scaling, and execution timeout.

    ``require_scaling=False`` is only for guarded update preflight, because
    update intentionally repairs worker scaling. Billed actions use the strict
    default.
    """
    if not isinstance(document, (dict, list)):
        raise ValueError("endpoint JSON has an ambiguous top-level shape")

    records = _merge_gpu_records(_gpu_records(document))
    if not records:
        raise ValueError("endpoint JSON does not expose GPU details; refusing to guess")
    if len(records) != 1:
        raise ValueError(
            f"endpoint exposes {len(records)} GPU records; exactly one is required"
        )
    gpu = records[0]
    if gpu.name is None:
        raise ValueError("endpoint GPU details do not expose an unambiguous GPU name")
    if gpu.name.casefold() != expected_gpu.casefold():
        raise ValueError(
            f"endpoint GPU must be exactly {expected_gpu!r}; found {gpu.name!r}"
        )
    if gpu.memory_gb is None:
        raise ValueError(
            f"endpoint JSON exposes {expected_gpu!r} but no explicit memory; "
            f"refusing to guess that it is {expected_memory_gb:g} GB"
        )
    if abs(gpu.memory_gb - expected_memory_gb) > 1e-9:
        raise ValueError(
            f"endpoint GPU memory must be exactly {expected_memory_gb:g} GB; "
            f"found {gpu.memory_gb:g} GB"
        )

    gpu_count = _one_field(document, GPU_COUNT_KEYS, "GPU count", required=False)
    if gpu_count is not None and _integer(gpu_count, "GPU count") != 1:
        raise ValueError("endpoint GPU count must be exactly 1")

    if require_scaling:
        workers_min = _one_field(document, WORKERS_MIN_KEYS, "workers minimum", required=True)
        workers_max = _one_field(document, WORKERS_MAX_KEYS, "workers maximum", required=True)
        if _integer(workers_min, "workers minimum") != 0:
            raise ValueError("endpoint workers minimum must be exactly 0")
        if _integer(workers_max, "workers maximum") != 1:
            raise ValueError("endpoint workers maximum must be exactly 1")

    execution_timeout = _one_field(
        document, EXECUTION_TIMEOUT_KEYS, "execution timeout", required=True
    )
    timeout = _integer(execution_timeout, "execution timeout")
    if timeout < 1 or timeout > max_execution_timeout_seconds:
        raise ValueError(
            f"endpoint execution timeout must be between 1 and "
            f"{max_execution_timeout_seconds} seconds; found {timeout}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-id", required=True)
    args = parser.parse_args()
    try:
        document = json.load(sys.stdin)
        validate_endpoint(document, args.gpu_id)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Endpoint safety check failed: {exc}", file=sys.stderr)
        return 2
    print(
        "Endpoint safety check passed: exactly one 24-GB GPU, workers 0/1, "
        "execution timeout <=180s",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
