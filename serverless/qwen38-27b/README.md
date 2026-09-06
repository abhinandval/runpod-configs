# Qwen3.8-27B Q4_K_M on RunPod Serverless

This project runs the `ggml-org/Qwen3.8-27B-GGUF:Q4_K_M` model behind a RunPod Serverless handler and a local `llama-server` process. It is designed as a disposable memory-envelope test for a single 24-GB NVIDIA worker, with the eventual RX 7900 XTX as the local target.

The worker is text-only in v1. It accepts OpenAI-style chat messages, returns the llama.cpp chat-completion object, and supports `enable_thinking` by translating it to llama.cpp’s `chat_template_kwargs`.

The RunPod handler registers before starting llama-server. The first request
may therefore include model download/load time; if startup fails, the error is
returned by that job instead of leaving the request queued while the worker
initializes.

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

## Deployment modes

The image supports two explicit transports:

| Mode | Setting | Public API | Streaming | Use case |
| --- | --- | --- | --- | --- |
| Queue | `RUNPOD_WORKER_MODE=queue` (default) | RunPod `/run` and `/status` | No | Guarded Serverless jobs and the local shim |
| HTTP | `RUNPOD_WORKER_MODE=http` | `https://ENDPOINT_ID.api.runpod.ai/v1` | Yes | OpenAI clients and Open WebUI |

HTTP mode runs the same native `llama-server` already supplied by the pinned
CUDA image. It binds to `0.0.0.0` and uses RunPod's `PORT` value, so no second
FastAPI router or model proxy is installed in the image. The native server
provides `/v1/models`, `/v1/chat/completions`, streaming responses, and
`/health`.

This is the same basic architecture as RunPod's `worker-vllm` listing: the
worker image owns an OpenAI-compatible HTTP server and a Load Balancer routes
requests directly to that worker. It is different from a queue endpoint,
whose public transport is `/v2/ENDPOINT_ID/run` and whose request result is
polled through `/status`.

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

The guarded deployment script is an end-to-end flow. It checks the CLI and
template, creates the endpoint, validates its safety settings, writes a log,
submits a bounded `pong` prompt, validates the exact response, and prints the
endpoint/job status. It reuses the existing template `zyhg00liv1` by default
and requires that its image exactly match the requested immutable tag. Review
the image and names before running it:

```bash
CONFIRM_CREATE=1 CONFIRM_BILLED=1 scripts/deploy.sh
```

The E2E flow permits at most three deployment attempts per execution. Each
attempt captures a job ID before waiting for up to 180 seconds. After a failed
or ambiguous attempt, it shows status and asks whether to purge the endpoint,
queued work, and workers before redeploying. Set `CONFIRM_PURGE=1` for the
noninteractive equivalent. An ambiguous still-running job is never duplicated
without purging. The endpoint is retained with workers-min `0` after a
successful test or when retry is declined; the log path is printed in the
final status section. Set `RUNPOD_LOG_FILE` to choose an exact log path, or
`RUNPOD_LOG_DIR` to choose the default log directory.

To deploy a different published SHA tag or use different names:

```bash
CONFIRM_CREATE=1 CONFIRM_BILLED=1 scripts/deploy.sh \
  ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-<full-commit-sha> \
  qwen38-27b-llama-cpp qwen38-27b-llama-cpp
```

The script requires an immutable SHA-tagged image and pins workers to one
RTX 4090 with workers-min `0`, workers-max `1`, and a 180-second execution
timeout. It also requires a host driver compatible with CUDA 12.8, matching
the pinned llama.cpp CUDA image. If an endpoint with the same name already
exists, add `CONFIRM_PURGE=1` to explicitly replace it; the old endpoint,
queued work, and workers are purged first:

```bash
CONFIRM_CREATE=1 CONFIRM_BILLED=1 CONFIRM_PURGE=1 \
  RUNPOD_TEMPLATE_ID=zyhg00liv1 scripts/deploy.sh
```

Delete the retained endpoint after inspection:

```bash
CONFIRM_PURGE=1 scripts/purge.sh ENDPOINT_ID
```

While this worker is being stabilized, purge any stuck queue and worker before
starting another test. RunPod does not expose a separate serverless cancel
command; the guarded purge deletes the disposable endpoint, queued jobs, and
worker allocations together:

```bash
CONFIRM_PURGE=1 scripts/purge.sh ENDPOINT_ID
```

Deploy a fresh endpoint with `scripts/deploy.sh` after purging. To create a
new template instead of reusing `zyhg00liv1`, set `RUNPOD_TEMPLATE_ID` to an
empty value; the script will create a serverless template and verify it before
creating the endpoint.

### Direct HTTP / OpenAI deployment

Prepare an HTTP-capable template with the RunPod CLI:

```bash
CONFIRM_CREATE=1 scripts/deploy-http.sh prepare \
  ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-<full-commit-sha>
```

The helper creates or verifies the template only. It intentionally never runs
`runpodctl serverless create`, because the installed CLI does not provide a
Load Balancer endpoint-type flag. In the RunPod Console, create the endpoint
from the printed template with these settings:

```text
Endpoint type       Load Balancer
GPU                 NVIDIA GeForce RTX 4090
GPU count           1
Workers min/max     0 / 1
Container port      8080/http
Network Volume      none
RUNPOD_WORKER_MODE  http
SERVER_HOST         0.0.0.0
PORT                8080
PORT_HEALTH         8080
HEALTH_CHECK_PATH   /health
```

After the endpoint is created, validate routing and model discovery without
submitting a chat request:

```bash
CONFIRM_BILLED=1 RUNPOD_API_KEY=your-runpod-api-key \
  scripts/deploy-http.sh check ENDPOINT_ID
```

Because `workers-min=0` is retained as a cost guardrail, the first HTTP
request can cold-start the GPU worker and download the model to ephemeral
`/models`. Keep the endpoint at `workers-min=0` for disposable testing; use
`workers-min=1` only when the Open WebUI installation needs a continuously
warm worker and the ongoing GPU cost is intentional.

The direct OpenAI base URL is:

```text
https://ENDPOINT_ID.api.runpod.ai/v1
```

Use the RunPod API key as the bearer/API key and select the model ID returned
by `/v1/models`. For Open WebUI, add an OpenAI-compatible connection with that
base URL and key; do not append `/chat/completions` to the configured base URL.
The direct HTTP endpoint supports streaming, unlike the local queue shim.

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

The smoke test first performs a read-only, fail-closed endpoint preflight, then
uses `runpodctl serverless run --no-wait` (not `/runsync`) to capture a job ID
before polling `serverless status`. The preflight requests
`--include-template --include-workers` and requires exactly one `NVIDIA GeForce
RTX 4090`, explicit 24-GB memory, `workersMin=0`, `workersMax=1`, and an
explicit execution timeout from 1 through 180 seconds. Missing, conflicting,
or ambiguous fields are rejected; memory is never inferred from the GPU name.
It submits one tiny prompt, disables reasoning, limits generation to 8 tokens,
and waits at most 180 seconds. A terminal failure can be retried by setting
`SMOKE_MAX_ATTEMPTS`; an ambiguous timeout is never retried because the remote
job may still be running. The deployment flow uses one job per deployment
attempt and offers purge/redeploy between attempts. It may start a billed
worker:

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

## OpenAI-compatible shim

For the default queue mode, `scripts/openai_shim.py` provides a small local
gateway for applications that require the OpenAI SDK: it accepts
`/v1/chat/completions`, wraps the request as RunPod `input`, waits for the job,
and unwraps the OpenAI-shaped `output`. Use the direct HTTP mode above when a
public OpenAI-compatible endpoint or streaming is required.

Start the shim beside the endpoint:

```bash
export RUNPOD_ENDPOINT_ID=ENDPOINT_ID
export RUNPOD_API_KEY=your-runpod-api-key
export OPENAI_SHIM_API_KEY=local-shim-secret
python3 scripts/openai_shim.py
```

### VPS systemd service

The shim uses only the Python standard library and runs directly on the VPS;
the RunPod worker and model are not included. It uses the existing `uv`
installation and a user-level systemd service. Secrets are kept outside the
repository in a mode-600 environment file:

```bash
cd serverless/qwen38-27b/scripts
./install-openai-shim-systemd.sh
# Edit ~/.config/qwen38-openai-shim.env with the Queue endpoint ID and secrets.
./install-openai-shim-systemd.sh
```

The first invocation creates the environment file and stops. The second
installs and starts the service. It binds to `127.0.0.1:8000` by default;
terminate TLS and perform public routing in a VPS reverse proxy (for example
Caddy or nginx). For direct access over a private/Tailscale interface, set
`OPENAI_SHIM_HOST=0.0.0.0` (or the specific interface address) in the env file
before rerunning the installer. To follow service logs:

```bash
systemctl --user status qwen38-openai-shim
journalctl --user -u qwen38-openai-shim -f
```

Enable the user service to survive logout/reboot if required:

```bash
loginctl enable-linger "$USER"
```

The service requires these runtime values:

```text
RUNPOD_ENDPOINT_ID     Queue endpoint ID
RUNPOD_API_KEY         RunPod key permitted to submit/read this endpoint's jobs
OPENAI_SHIM_API_KEY    Separate client-facing bearer secret; never reuse the RunPod key
```

`GET /v1/models` also reports proxy metadata: llama.cpp backend, Q4_K_M
quantization, 32768-token context, 2048-token output cap, chat support, and
the fact that streaming, tools, vision, embeddings, and text completions are
not exposed by this queue shim. Override the context and output values with
`OPENAI_SHIM_CONTEXT_WINDOW` and `OPENAI_SHIM_MAX_OUTPUT_TOKENS` when the
worker configuration changes.

Check the local service before exposing it through a reverse proxy:

```bash
curl http://127.0.0.1:8000/health
curl -H "Authorization: Bearer $OPENAI_SHIM_API_KEY" http://127.0.0.1:8000/v1/models
```

Then use the standard OpenAI client against the local shim:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_SHIM_API_KEY"],
    base_url="http://127.0.0.1:8000/v1",
)
response = client.chat.completions.create(
    model="qwen38-27b-q4_k_m",
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=128,
)
print(response.choices[0].message.content)
```

The shim is synchronous and does not support streaming. It defaults to
localhost, requires its own bearer key, and waits up to 180 seconds. If the
wait expires, the remote RunPod job may still be running; the error includes
the job ID and must not be retried automatically. For public access, put the
shim behind TLS and an authenticated reverse proxy or gateway. It is not
automatically deployed inside the RunPod worker.

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
