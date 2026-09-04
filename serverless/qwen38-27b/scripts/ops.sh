#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Safe RunPod operations for qwen38-27b.

Read-only:
  ops.sh list
  ops.sh get <endpoint-id>
  ops.sh status <endpoint-id> <job-id> [wait]

Explicitly confirmed mutations / billed actions:
  CONFIRM_CREATE=1 ops.sh create <template-id> [name]
  CONFIRM_UPDATE=1 ops.sh update <endpoint-id>
  CONFIRM_BILLED=1 ops.sh run <endpoint-id>
  CONFIRM_DELETE=1 ops.sh delete <endpoint-id>

The create/update defaults enforce workers-min=0 and workers-max=1.
The run action submits one tiny prompt and waits at most 90 seconds.
Every billed action performs a read-only preflight requiring exact GPU/memory,
workers 0/1, and explicit execution-timeout <=180s. Update verifies GPU/memory
and timeout before changing scaling, then verifies the result.
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

check_endpoint_safety() {
  local endpoint_id="$1"
  local endpoint_json
  endpoint_json="$(runpodctl serverless get "$endpoint_id" \
    --include-template --include-workers --output json)"
  printf '%s' "$endpoint_json" | python3 "$script_dir/validate_endpoint.py" \
    --gpu-id "NVIDIA GeForce RTX 4090"
}

check_update_preflight() {
  local endpoint_id="$1"
  local endpoint_json
  endpoint_json="$(runpodctl serverless get "$endpoint_id" \
    --include-template --include-workers --output json)"
  VALIDATE_ENDPOINT_DIR="$script_dir" python3 -c \
    'import json, os, sys; sys.path.insert(0, os.environ["VALIDATE_ENDPOINT_DIR"]); from validate_endpoint import validate_endpoint; validate_endpoint(json.load(sys.stdin), "NVIDIA GeForce RTX 4090", require_scaling=False)' \
    <<< "$endpoint_json"
}

command_name="${1:-}"
shift || true

case "$command_name" in
  list)
    exec runpodctl serverless list --output json
    ;;
  get)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    exec runpodctl serverless get "$1" --output json
    ;;
  status)
    [[ $# -ge 2 && $# -le 3 ]] || { usage >&2; exit 2; }
    if [[ $# -eq 3 ]]; then
      exec runpodctl serverless status "$1" "$2" --wait "$3" --output json
    else
      exec runpodctl serverless status "$1" "$2" --output json
    fi
    ;;
  create)
    [[ $# -ge 1 && $# -le 2 ]] || { usage >&2; exit 2; }
    [[ "${CONFIRM_CREATE:-}" == "1" ]] || {
      echo "Refusing endpoint creation; set CONFIRM_CREATE=1 after reviewing the command." >&2
      exit 2
    }
    template_id="$1"
    name="${2:-qwen38-27b-llama-cpp}"
    echo "WARNING: creating an endpoint; workers-min=0 means no worker is started now." >&2
    echo "A later run can start a billed worker. Review the template/image first." >&2
    exec runpodctl serverless create \
      --template-id "$template_id" \
      --name "$name" \
      --gpu-id "NVIDIA GeForce RTX 4090" \
      --gpu-count 1 \
      --workers-min 0 \
      --workers-max 1 \
      --idle-timeout 60 \
      --execution-timeout 180 \
      --env MODEL_HF_REF=ggml-org/Qwen3.8-27B-GGUF:Q4_K_M \
      --env MODEL_CACHE_DIR=/models \
      --env LLAMA_CACHE=/models \
      --env N_CTX=32768 \
      --env N_PARALLEL=1 \
      --env N_GPU_LAYERS=999 \
      --output json
    ;;
  update)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    [[ "${CONFIRM_UPDATE:-}" == "1" ]] || {
      echo "Refusing endpoint update; set CONFIRM_UPDATE=1 after reviewing the command." >&2
      exit 2
    }
    check_update_preflight "$1"
    echo "Verified exact RTX 4090/24-GB GPU and explicit execution timeout <=180s." >&2
    echo "Updating endpoint scaling only: min=0, max=1, idle=60s." >&2
    runpodctl serverless update "$1" \
      --workers-min 0 \
      --workers-max 1 \
      --idle-timeout 60 \
      --output json
    check_endpoint_safety "$1"
    ;;
  run)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    [[ "${CONFIRM_BILLED:-}" == "1" ]] || {
      echo "Refusing billed job; set CONFIRM_BILLED=1 after reviewing the tiny payload." >&2
      exit 2
    }
    check_endpoint_safety "$1"
    echo "WARNING: starting one billed-capable RunPod job with a 90s wait." >&2
    exec runpodctl serverless run "$1" \
      --input '{"messages":[{"role":"user","content":"Reply with exactly: pong"}],"max_tokens":8,"enable_thinking":false}' \
      --wait 90s
    ;;
  delete)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    [[ "${CONFIRM_DELETE:-}" == "1" ]] || {
      echo "Refusing endpoint deletion; set CONFIRM_DELETE=1 only after reviewing the ID." >&2
      exit 2
    }
    echo "WARNING: deleting endpoint $1. This is irreversible from this script." >&2
    exec runpodctl serverless delete "$1" --output json
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
