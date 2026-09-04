"""RunPod Serverless entrypoint."""

from __future__ import annotations

import runpod

from .handler import handler, runtime


def main() -> None:
    # Starting before registration makes model download/load part of the
    # worker cold start and guarantees the first job sees a ready server.
    runtime.ensure_started()
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
