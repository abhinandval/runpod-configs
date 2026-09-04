#!/usr/bin/env python3
"""Small, bounded benchmark using runpodctl serverless run (never /runsync)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

try:
    from .validate_endpoint import validate_endpoint
except ImportError:  # Direct invocation: python3 scripts/benchmark.py ...
    from validate_endpoint import validate_endpoint


DEFAULT_ENDPOINT_TIMEOUT_SECONDS = 180
MAX_REQUESTS = 3
MAX_TOTAL_TIMEOUT_SECONDS = 300
PREFLIGHT_TIMEOUT_SECONDS = 30


def preflight_endpoint(endpoint_id: str) -> None:
    """Read and strictly validate endpoint safety before any billed run."""
    try:
        completed = subprocess.run(
            [
                "runpodctl", "serverless", "get", endpoint_id,
                "--include-template", "--include-workers", "--output", "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=PREFLIGHT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"endpoint safety preflight could not complete: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"endpoint safety preflight command failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("endpoint safety preflight returned invalid JSON") from exc
    try:
        validate_endpoint(document, "NVIDIA GeForce RTX 4090")
    except ValueError as exc:
        raise RuntimeError(f"endpoint safety preflight rejected endpoint: {exc}") from exc


def _submit_job(
    endpoint_id: str,
    payload: dict[str, object],
    wait_seconds: int,
    remaining_seconds: float,
) -> subprocess.CompletedProcess[str]:
    """Submit one job with a client-side wait and process-time budget."""
    return subprocess.run(
        [
            "runpodctl",
            "serverless",
            "run",
            endpoint_id,
            "--input",
            json.dumps(payload, separators=(",", ":")),
            "--wait",
            f"{wait_seconds}s",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=max(1, int(remaining_seconds)),
    )


def run_benchmark_jobs(
    endpoint_id: str,
    request_count: int,
    max_tokens: int,
    prompt: str,
    wait_seconds: int,
    total_timeout_seconds: int,
) -> tuple[int, list[dict[str, object]]]:
    """Run bounded jobs, preflighting immediately before every billed submit.

    The deadline bounds this client process only. It cannot cancel a remote job
    or cap its billing if runpodctl stops waiting while the job remains active.
    """
    results: list[dict[str, object]] = []
    deadline = time.monotonic() + total_timeout_seconds
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "enable_thinking": False,
    }
    for index in range(request_count):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            print(
                "Total client wall-time budget exhausted before the next job; "
                "no additional job was submitted.",
                file=sys.stderr,
            )
            return 124, results

        # This must remain immediately before each billed submission. Endpoint
        # settings can change between otherwise separate benchmark requests.
        try:
            preflight_endpoint(endpoint_id)
        except RuntimeError as exc:
            print(
                f"Refusing to submit job {index + 1}: endpoint safety preflight "
                f"failed: {exc}",
                file=sys.stderr,
            )
            return 2, results
        remaining = deadline - time.monotonic()
        if remaining < 1:
            print(
                "Total client wall-time budget exhausted after preflight; "
                "no additional job was submitted.",
                file=sys.stderr,
            )
            return 124, results
        job_wait = min(wait_seconds, int(remaining))
        started = time.monotonic()
        try:
            completed = _submit_job(
                endpoint_id, payload, job_wait, remaining
            )
        except subprocess.TimeoutExpired as exc:
            print(
                "runpodctl exceeded the client benchmark wall-time budget. "
                "The remote job may still be running; this client timeout "
                "does not cancel it or cap remote billing. Do not submit a "
                f"duplicate job: {exc}",
                file=sys.stderr,
            )
            return 124, results
        elapsed = time.monotonic() - started
        try:
            output = json.loads(completed.stdout)
        except json.JSONDecodeError:
            output = completed.stdout.strip()
        results.append(
            {
                "request": index + 1,
                "exit_code": completed.returncode,
                "elapsed_seconds": round(elapsed, 3),
                "output": output,
                "stderr": completed.stderr.strip(),
            }
        )
        if completed.returncode != 0:
            return completed.returncode, results
    return 0, results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint_id")
    parser.add_argument("--requests", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=90,
        help="per-job wait budget in seconds (1-180; default: 90)",
    )
    parser.add_argument(
        "--total-timeout-seconds",
        type=int,
        default=180,
        help="total wall-time budget for all jobs (1-300; default: 180)",
    )
    parser.add_argument("--prompt", default="Answer with one short sentence: what is 2+2?")
    parser.add_argument(
        "--confirm-billed",
        action="store_true",
        help="acknowledge that requests can start a billed worker",
    )
    args = parser.parse_args()
    if args.requests < 1 or args.requests > MAX_REQUESTS:
        parser.error(f"--requests must be between 1 and {MAX_REQUESTS}")
    if args.max_tokens < 1 or args.max_tokens > 256:
        parser.error("--max-tokens must be between 1 and 256")
    if args.wait_seconds < 1 or args.wait_seconds > DEFAULT_ENDPOINT_TIMEOUT_SECONDS:
        parser.error(
            f"--wait-seconds must be between 1 and {DEFAULT_ENDPOINT_TIMEOUT_SECONDS}"
        )
    if args.total_timeout_seconds < 1 or args.total_timeout_seconds > MAX_TOTAL_TIMEOUT_SECONDS:
        parser.error(
            f"--total-timeout-seconds must be between 1 and {MAX_TOTAL_TIMEOUT_SECONDS}"
        )
    if args.wait_seconds > args.total_timeout_seconds:
        parser.error("--wait-seconds must not exceed --total-timeout-seconds")
    if not args.confirm_billed:
        print(
            "Refusing to submit jobs: this benchmark may start a billed RunPod worker. "
            "Re-run with --confirm-billed.",
            file=sys.stderr,
        )
        return 2

    print(
        f"WARNING: submitting {args.requests} bounded RunPod jobs; billing may begin.",
        file=sys.stderr,
    )
    exit_code, results = run_benchmark_jobs(
        args.endpoint_id,
        args.requests,
        args.max_tokens,
        args.prompt,
        args.wait_seconds,
        args.total_timeout_seconds,
    )
    if exit_code != 0:
        print(json.dumps(results, indent=2), file=sys.stderr)
        return exit_code

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
