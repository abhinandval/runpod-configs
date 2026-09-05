# Qwen3.8-27B Q4_K_M on RunPod Serverless

This project runs the `ggml-org/Qwen3.8-27B-GGUF:Q4_K_M` model behind a RunPod Serverless handler and a local `llama-server` process. It is designed as a disposable memory-envelope test for a single 24-GB NVIDIA worker, with the eventual RX 7900 XTX as the local target.

The worker is text-only in v1. It accepts OpenAI-style chat messages, returns the llama.cpp chat-completion object, and supports `enable_thinking` by translating it to llama.cpp’s `chat_template_kwargs`.

## Cost guardrails

This repository does not execute RunPod operations automatically. `scripts/ops.sh` and `scripts/smoke.sh` refuse billed or mutating commands unless an explicit confirmation environment variable/flag is supplied. The safe default is to inspect endpoints with `list`, `get`, and one-shot `status`.

The intended disposable endpoint configuration is:

```text
workers-min       0
workers-max       1
idle-timeout      60 seconds
execution-timeout 180 seconds
GPU               NVIDIA GeForce RTX 4090 (24 GB)
GPU count         1
```

`workers-min=0` prevents an always-on worker. A request can still start a billed worker. Review the request and endpoint before using any command that includes `CONFIRM_BILLED=1` or `--confirm-billed`.

## Build and publish

The repository contains a manual-only workflow at
`.github/workflows/publish-qwen38-image.yml`. From the GitHub Actions tab,
select **Publish Qwen3.8-27B image**, choose **Run workflow**, and run it for
the commit you want to publish. It builds `serverless/qwen38-27b/Dockerfile`
for `linux/amd64` and publishes exactly one immutable tag:

```text
ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-<full-commit-sha>
```

The workflow authenticates with the repository `GITHUB_TOKEN` and does not
deploy or modify anything in RunPod. After the first publication, make the
GHCR package public once in GitHub: open the package page under your profile's
**Packages**, open **Package settings**, choose **Change visibility**, select
**Public**, and confirm. Check the package name and repository before
confirming because visibility changes can be difficult to reverse.

For a local, non-publishing build, run this from `serverless/qwen38-27b`:

```bash
docker build --platform linux/amd64 \
  -t ghcr.io/abhinandval/llama-cpp-qwen38-27b:local .
```

The Dockerfile layers the worker onto the official CUDA-enabled llama.cpp
`server-cuda` image, pinned by digest. The prebuilt image supplies
`llama-server` and its CUDA libraries, so CI does not compile llama.cpp.

The guarded deployment script creates a Serverless template from the
published SHA-tagged image and then creates the endpoint. It does not attach a
Network Volume, start a worker, or submit a job. Review the image and names
before running it:

```bash
CONFIRM_CREATE=1 scripts/deploy.sh
```

To deploy a different published SHA tag or use different names:

```bash
CONFIRM_CREATE=1 scripts/deploy.sh \
  ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-<full-commit-sha> \
  qwen38-27b-llama-cpp qwen38-27b-llama-cpp
```

The script requires an immutable SHA-tagged image and pins workers to one
RTX 4090 with workers-min `0`, workers-max `1`, and a 180-second execution
timeout. It prints the created template and endpoint JSON; save the endpoint
ID for the smoke test and later deletion.

Run one bounded smoke test and delete the endpoint afterward:

```bash
CONFIRM_BILLED=1 scripts/smoke.sh ENDPOINT_ID
CONFIRM_DELETE=1 scripts/ops.sh delete ENDPOINT_ID
```

The template must expose the container entrypoint and have a 24-GB-compatible GPU configuration. Do not attach a Network Volume for this disposable test. The model and llama.cpp cache use `/models` on container disk; that disk is ephemeral, so every new worker may need to redownload the roughly 19-GB model.

The model can also be cached/configured through endpoint environment variables:

```text
MODEL_HF_REF=ggml-org/Qwen3.8-27B-GGUF:Q4_K_M
MODEL_CACHE_DIR=/models
LLAMA_CACHE=/models
```

For deterministic local-file loading within a worker, place the GGUF at `/models/Qwen3.8-27B-Q4_K_M.gguf` and set `MODEL_PATH` accordingly. This file is also ephemeral and will not be available on a new worker. When `MODEL_PATH` is set, it takes precedence over `MODEL_HF_REF` and startup fails clearly if the file is absent.

## Operations

Read-only commands:

```bash
scripts/ops.sh list
scripts/ops.sh get ENDPOINT_ID
scripts/ops.sh status ENDPOINT_ID JOB_ID
```

To enforce the agreed settings on an existing endpoint, review the command and explicitly confirm it:

```bash
CONFIRM_UPDATE=1 scripts/ops.sh update ENDPOINT_ID
```

Delete only after checking the endpoint ID. This is intentionally guarded:

```bash
CONFIRM_DELETE=1 scripts/ops.sh delete ENDPOINT_ID
```

## Bounded smoke test

The smoke test first performs a read-only, fail-closed endpoint preflight, then uses `runpodctl serverless run` (not `/runsync`). The preflight requests `--include-template --include-workers` and requires exactly one `NVIDIA GeForce RTX 4090`, explicit 24-GB memory, `workersMin=0`, `workersMax=1`, and an explicit execution timeout from 1 through 180 seconds. Missing, conflicting, or ambiguous fields are rejected; memory is never inferred from the GPU name. It submits one tiny prompt, disables reasoning, limits generation to 8 tokens, and waits at most 90 seconds. It may start a billed worker:

```bash
CONFIRM_BILLED=1 scripts/smoke.sh ENDPOINT_ID
```

If the wait expires, the job may still be running. Use the printed job ID with the read-only status command rather than submitting duplicates:

```bash
scripts/ops.sh status ENDPOINT_ID JOB_ID 30s
```

## Benchmark

The benchmark performs the same read-only safety preflight immediately before every billed job submission. It defaults to one request, permits at most three requests, limits each `runpodctl` wait to the endpoint’s 180-second execution timeout, and enforces a low client-side total wall-time budget (180 seconds by default, 300 seconds maximum). It never calls `/runsync` and refuses to run without an explicit billing acknowledgement:

```bash
python3 scripts/benchmark.py ENDPOINT_ID --requests 1 --max-tokens 32 --wait-seconds 90 --total-timeout-seconds 180 --confirm-billed
```

Use the default single request for this disposable test. Results include cold-start time; tokens/sec should be taken from llama.cpp worker logs/metrics because the RunPod job response alone does not reliably expose prompt and generation timings. The client wait and total wall-time budgets only limit this local benchmark process: they cannot cancel a remote job or cap its billing if the job remains server-side after the client stops waiting. If a wait expires, use its job ID with the read-only status command and do not submit a duplicate.

## Request shape

Example handler payload:

```json
{
  "messages": [
    {"role": "system", "content": "You are concise."},
    {"role": "user", "content": "Reply with exactly: pong"}
  ],
  "max_tokens": 64,
  "temperature": 0.2,
  "enable_thinking": false
}
```

`stream=true` is rejected in v1 because RunPod job output is synchronous. `max_tokens` is clamped to `MAX_REQUEST_TOKENS` (default 2048). The handler returns an `{"error": ...}` object for validation, startup, or llama-server failures so failures remain visible in the job output.

## Configuration and memory tuning

See `.env.example`. Defaults intentionally start conservatively:

```text
N_CTX=32768
N_PARALLEL=1
N_GPU_LAYERS=999
N_BATCH=256
N_UBATCH=128
```

The 32K context is a stress target, not a promise that every 24-GB card will fit it. Record actual VRAM usage and reduce `N_CTX`, `N_BATCH`, or `N_UBATCH` if startup reports an out-of-memory error. Do not enable a larger GPU as a hidden fallback; the point of this test is the 24-GB envelope.

The official CUDA image targets the NVIDIA runtime used by this endpoint. The
later RX 7900 XTX deployment requires a separate HIP/ROCm image; this NVIDIA
endpoint validates model loading and memory behavior, not AMD performance.

When loading from Hugging Face, the worker passes `--no-mmproj` so the text-only v1 worker does not fetch a vision projector. Container-disk caching reduces duplicate downloads only while the same worker/container remains alive; it is not persistent storage.

`runpodctl serverless update` cannot change an endpoint’s execution timeout. The guarded update command reads endpoint JSON with template and worker details, rejects missing or unsafe GPU/memory/timeout data before mutation, changes only scaling and idle timeout, then runs the full strict preflight again. Endpoint creation explicitly sets `--gpu-count 1`, workers-min `0`, workers-max `1`, and execution-timeout `180`; no unsupported update timeout flag is invented.

## Local checks

No GPU or model download is required for the unit checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
```

The Docker build, model download, GPU offload, RunPod startup, and exact VRAM ceiling were not tested in this workspace.
