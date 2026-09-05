"""RunPod Serverless entrypoint."""

from __future__ import annotations

import runpod

from .handler import handler, runtime


def main() -> None:
    # Register immediately so RunPod can mark the worker ready. The first job
    # lazily downloads/loads the model inside the handler, making startup
    # failures visible in the job result instead of leaving work in the queue.
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
