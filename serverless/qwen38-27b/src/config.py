"""Environment-backed configuration for the worker and llama-server."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value in (None, ""):
        return None
    return _int(name, 0)


@dataclass(frozen=True)
class Settings:
    worker_mode: str
    model_hf_ref: str
    model_path: str | None
    model_cache_dir: str
    llama_cache: str
    llama_server_bin: str
    server_host: str
    server_port: int
    startup_timeout_seconds: int
    request_timeout_seconds: int
    n_ctx: int
    n_parallel: int
    n_gpu_layers: int
    n_batch: int
    n_ubatch: int
    threads: int | None
    flash_attn: str | None
    llama_api_key: str | None
    extra_args: str | None
    default_max_tokens: int
    max_request_tokens: int

    @classmethod
    def from_env(cls) -> "Settings":
        worker_mode = (os.getenv("RUNPOD_WORKER_MODE") or "queue").strip().lower()
        if worker_mode not in {"queue", "http"}:
            raise ValueError("RUNPOD_WORKER_MODE must be one of: queue, http")

        model_path = os.getenv("MODEL_PATH") or None
        llama_cache = os.getenv("LLAMA_CACHE") or os.getenv(
            "MODEL_CACHE_DIR", "/models"
        )
        model_cache_dir = os.getenv("MODEL_CACHE_DIR", llama_cache)
        flash_attn = os.getenv("FLASH_ATTN") or None
        if flash_attn and flash_attn not in {"on", "off", "auto"}:
            raise ValueError("FLASH_ATTN must be one of: on, off, auto")

        default_host = "0.0.0.0" if worker_mode == "http" else "127.0.0.1"
        if worker_mode == "http":
            # RunPod Load Balancing supplies PORT. SERVER_PORT remains a useful
            # local fallback, but PORT always wins when the platform sets it.
            default_port = _int("SERVER_PORT", 8080)
            default_port = _int("PORT", default_port)
        else:
            default_port = 8080

        settings = cls(
            worker_mode=worker_mode,
            model_hf_ref=os.getenv(
                "MODEL_HF_REF", "ggml-org/Qwen3.8-27B-GGUF:Q4_K_M"
            ),
            model_path=model_path,
            model_cache_dir=model_cache_dir,
            llama_cache=llama_cache,
            llama_server_bin=os.getenv("LLAMA_SERVER_BIN", "llama-server"),
            server_host=(os.getenv("SERVER_HOST") or default_host).strip(),
            server_port=_int("SERVER_PORT", default_port) if worker_mode == "queue" else default_port,
            startup_timeout_seconds=_int("SERVER_STARTUP_TIMEOUT_SECONDS", 900),
            request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 180),
            n_ctx=_int("N_CTX", 32768),
            n_parallel=_int("N_PARALLEL", 1),
            n_gpu_layers=_int("N_GPU_LAYERS", 999),
            n_batch=_int("N_BATCH", 256),
            n_ubatch=_int("N_UBATCH", 128),
            threads=_optional_int("THREADS"),
            flash_attn=flash_attn,
            llama_api_key=os.getenv("LLAMA_API_KEY") or None,
            extra_args=os.getenv("LLAMA_EXTRA_ARGS") or None,
            default_max_tokens=_int("DEFAULT_MAX_TOKENS", 256),
            max_request_tokens=_int("MAX_REQUEST_TOKENS", 2048),
        )
        if settings.model_path is None and not settings.model_hf_ref:
            raise ValueError("Set MODEL_PATH or MODEL_HF_REF")
        if not settings.server_host:
            raise ValueError("SERVER_HOST must not be empty")
        if not 1 <= settings.server_port <= 65535:
            raise ValueError("SERVER_PORT must be between 1 and 65535")
        positive_fields = {
            "SERVER_STARTUP_TIMEOUT_SECONDS": settings.startup_timeout_seconds,
            "REQUEST_TIMEOUT_SECONDS": settings.request_timeout_seconds,
            "N_CTX": settings.n_ctx,
            "N_PARALLEL": settings.n_parallel,
            "N_BATCH": settings.n_batch,
            "N_UBATCH": settings.n_ubatch,
            "DEFAULT_MAX_TOKENS": settings.default_max_tokens,
            "MAX_REQUEST_TOKENS": settings.max_request_tokens,
        }
        invalid = [name for name, value in positive_fields.items() if value < 1]
        if invalid:
            raise ValueError(f"{', '.join(invalid)} must be positive")
        if settings.n_ubatch > settings.n_batch:
            raise ValueError("N_UBATCH must not exceed N_BATCH")
        if settings.threads is not None and settings.threads < 0:
            raise ValueError("THREADS must be zero or positive")
        if settings.default_max_tokens > settings.max_request_tokens:
            raise ValueError("DEFAULT_MAX_TOKENS must not exceed MAX_REQUEST_TOKENS")
        if settings.max_request_tokens > settings.n_ctx:
            raise ValueError("MAX_REQUEST_TOKENS must not exceed N_CTX")
        if settings.request_timeout_seconds > 180:
            raise ValueError(
                "REQUEST_TIMEOUT_SECONDS must not exceed the 180-second endpoint timeout"
            )
        if settings.n_gpu_layers < 0:
            raise ValueError("N_GPU_LAYERS must be zero or positive")
        return settings
