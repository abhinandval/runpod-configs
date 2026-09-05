"""Dispatch the queue or direct HTTP worker entrypoint."""

from __future__ import annotations

def main() -> None:
    from .config import Settings

    settings = Settings.from_env()
    if settings.worker_mode == "http":
        from .http_main import run_http_worker

        run_http_worker(settings)
        return

    import runpod

    from .handler import handler

    # Register immediately so RunPod can mark the worker ready. The first job
    # lazily downloads/loads the model inside the handler, making startup
    # failures visible in the job result instead of leaving work in the queue.
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
