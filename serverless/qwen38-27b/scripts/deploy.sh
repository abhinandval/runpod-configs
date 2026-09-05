#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Create a disposable Qwen3.8-27B RunPod Serverless deployment.

Usage:
  CONFIRM_CREATE=1 deploy.sh [image-ref] [template-name] [endpoint-name]

Defaults:
  image-ref      ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-d08269d410c0e28082b32695b28607ad934b9ec1
  template-name  qwen38-27b-llama-cpp
  endpoint-name  qwen38-27b-llama-cpp

This creates a serverless template and endpoint only. It does not start a
worker or submit a job: workers-min remains 0 and no network volume is used.
Run smoke.sh separately with CONFIRM_BILLED=1 after reviewing the endpoint.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

[[ $# -le 3 ]] || { usage; exit 2; }
[[ "${CONFIRM_CREATE:-}" == "1" ]] || {
  echo "Refusing deployment; set CONFIRM_CREATE=1 after reviewing the image and names." >&2
  exit 2
}

image_ref="${1:-ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-d08269d410c0e28082b32695b28607ad934b9ec1}"
template_name="${2:-qwen38-27b-llama-cpp}"
endpoint_name="${3:-qwen38-27b-llama-cpp}"

[[ "$image_ref" =~ ^ghcr\.io/abhinandval/llama-cpp-qwen38-27b:sha-[0-9a-f]{40}$ ]] || {
  echo "Image must be the immutable GHCR SHA tag for llama-cpp-qwen38-27b." >&2
  exit 2
}

for name in "$template_name" "$endpoint_name"; do
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]] || {
    echo "Names must be 1-63 characters: letters, digits, '.', '_' or '-'." >&2
    exit 2
  }
done

echo "WARNING: creating a serverless template from $image_ref" >&2
echo "No Network Volume will be attached; container disk is ephemeral." >&2
echo "The endpoint will use workers-min=0, so this script will not start a worker." >&2

template_json="$(runpodctl template create \
  --name "$template_name" \
  --image "$image_ref" \
  --serverless \
  --container-disk-in-gb 30 \
  --output json)"

printf '%s\n' "$template_json"
template_id="$(printf '%s' "$template_json" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
for candidate in (
    payload.get("id"),
    payload.get("templateId"),
    payload.get("template_id"),
    (payload.get("template") or {}).get("id") if isinstance(payload.get("template"), dict) else None,
):
    if isinstance(candidate, str) and candidate.strip():
        print(candidate)
        break
else:
    raise SystemExit("template create response did not contain a template ID")
')"

echo "Created template $template_id; creating endpoint $endpoint_name." >&2
runpodctl serverless create \
  --template-id "$template_id" \
  --name "$endpoint_name" \
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
