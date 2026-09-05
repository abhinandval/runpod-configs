"""Run native llama-server as a RunPod Load Balancing HTTP worker."""

from __future__ import annotations

from .config import Settings
from .runtime import LlamaServer


def run_http_worker(settings: Settings) -> None:
    """Start llama-server, wait for readiness, then own its process lifetime."""
    if settings.worker_mode != "http":
        raise ValueError("HTTP worker entrypoint requires RUNPOD_WORKER_MODE=http")

    runtime = LlamaServer(settings)
    try:
        runtime.ensure_started()
        print(
            f"HTTP worker ready on http://{settings.server_host}:{settings.server_port}; "
            "OpenAI base path: /v1",
            flush=True,
        )
        exit_code = runtime.wait()
        if exit_code:
            raise RuntimeError(f"llama-server exited with code {exit_code}")
    finally:
        runtime.stop()


def main() -> None:
    settings = Settings.from_env()
    run_http_worker(settings)


if __name__ == "__main__":
    main()
