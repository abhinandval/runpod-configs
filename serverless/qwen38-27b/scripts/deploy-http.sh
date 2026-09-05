#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_image="ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-bd868371608b997643b8d8c5419ace8a82f933dc"

usage() {
  cat >&2 <<'EOF'
Prepare and validate a RunPod Load Balancing HTTP deployment.

Usage:
  CONFIRM_CREATE=1 scripts/deploy-http.sh prepare [image-ref] [template-name]
  CONFIRM_BILLED=1 scripts/deploy-http.sh check ENDPOINT_ID

The prepare action creates or verifies an HTTP-capable template only. It never
calls `runpodctl serverless create`: the current CLI has no Load Balancer
endpoint-type flag. Select Load Balancer in the RunPod Console using the
printed configuration.

Environment:
  RUNPOD_HTTP_TEMPLATE_ID  Existing template to verify instead of creating one
  CONFIRM_CREATE            Required for template creation
  CONFIRM_BILLED            Required for check; a scale-to-zero endpoint may
                            start a billed worker while becoming healthy

The endpoint defaults are workers-min=0, workers-max=1, one RTX 4090/24-GB
GPU, no Network Volume, and a 30-GB ephemeral container disk.
EOF
}

section() {
  printf '\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
  printf '▶ %s\n' "$1"
  printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
}
ok() { printf '✓ %s\n' "$1"; }
info() { printf '• %s\n' "$1"; }
warn() { printf '⚠ %s\n' "$1" >&2; }
die() { printf '✗ %s\n' "$1" >&2; exit 1; }

extract_json() {
  python3 -c '
import json
import sys

raw = sys.stdin.read()
decoder = json.JSONDecoder()
for index, character in enumerate(raw):
    if character not in "[{":
        continue
    try:
        value, _ = decoder.raw_decode(raw[index:])
    except json.JSONDecodeError:
        continue
    print(json.dumps(value, sort_keys=True))
    break
else:
    raise SystemExit("CLI output did not contain JSON")
'
}

validate_template() {
  local template_json="$1"
  local expected_image="$2"
  EXPECTED_HTTP_IMAGE="$expected_image" python3 -c '
import json
import os
import sys

payload = json.load(sys.stdin)
expected_image = os.environ["EXPECTED_HTTP_IMAGE"]
image = payload.get("imageName") or payload.get("image") or ""
if image != expected_image:
    raise SystemExit(f"template image mismatch: expected {expected_image}, found {image or '<missing>'}")

volume = payload.get("volumeInGb", payload.get("volumeSize", 0)) or 0
if volume != 0:
    raise SystemExit("template has persistent volume; expected no Network Volume")

raw_env = payload.get("env") or payload.get("environment") or payload.get("environmentVariables") or {}
if isinstance(raw_env, str):
    try:
        raw_env = json.loads(raw_env)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"template environment is not valid JSON: {exc}") from exc
if isinstance(raw_env, list):
    raw_env = {
        item.get("name"): item.get("value")
        for item in raw_env
        if isinstance(item, dict) and item.get("name")
    }
if not isinstance(raw_env, dict):
    raise SystemExit("template environment has an unsupported shape")

required = {
    "RUNPOD_WORKER_MODE": "http",
    "SERVER_HOST": "0.0.0.0",
    "PORT": "8080",
    "PORT_HEALTH": "8080",
    "HEALTH_CHECK_PATH": "/health",
}
missing = [name for name, value in required.items() if str(raw_env.get(name, "")) != value]
if missing:
    raise SystemExit(
        "template is missing HTTP settings: " + ", ".join(missing)
    )
' <<< "$template_json"
}

prepare() {
  local image_ref="${1:-$default_image}"
  [[ "$image_ref" =~ ^ghcr\.io/abhinandval/llama-cpp-qwen38-27b:sha-[0-9a-f]{40}$ ]] || \
    die "Image must be the immutable GHCR SHA tag for llama-cpp-qwen38-27b."

  local image_sha="${image_ref##*:sha-}"
  local template_name="${2:-qwen38-27b-http-${image_sha:0:8}}"
  [[ "$template_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]] || \
    die "Template name must be 1-63 characters: letters, digits, '.', '_' or '-'."
  [[ "${CONFIRM_CREATE:-}" == "1" ]] || \
    die "Refusing template preparation; set CONFIRM_CREATE=1 after reviewing the image and settings."

  section "1/3 PREFLIGHT"
  command -v runpodctl >/dev/null || die "runpodctl is not installed"
  command -v python3 >/dev/null || die "python3 is not installed"
  runpodctl version || die "runpodctl version check failed"
  ok "Required commands and RunPod CLI are available"
  info "Image: $image_ref"
  info "Mode: HTTP Load Balancing via native llama-server"
  info "Port: 8080; health path: /health"
  info "Scaling: workers-min=0, workers-max=1"
  info "Storage: ephemeral container disk; no Network Volume"

  local http_env='{"RUNPOD_WORKER_MODE":"http","SERVER_HOST":"0.0.0.0","PORT":"8080","PORT_HEALTH":"8080","HEALTH_CHECK_PATH":"/health","MODEL_HF_REF":"ggml-org/Qwen3.8-27B-GGUF:Q4_K_M","MODEL_CACHE_DIR":"/models","LLAMA_CACHE":"/models","N_CTX":"32768","N_PARALLEL":"1","N_GPU_LAYERS":"999"}'
  local template_id="${RUNPOD_HTTP_TEMPLATE_ID:-}"
  local template_raw template_json
  if [[ -n "$template_id" ]]; then
    [[ "$template_id" =~ ^[A-Za-z0-9_-]+$ ]] || die "RUNPOD_HTTP_TEMPLATE_ID contains unexpected characters."
    template_raw="$(runpodctl template get "$template_id" --output json)" || die "Could not read template $template_id"
    template_json="$(printf '%s' "$template_raw" | extract_json)" || die "Template response was not valid JSON"
    validate_template "$template_json" "$image_ref" || die "Existing template is not configured for this immutable HTTP image"
    ok "Existing HTTP template $template_id passed image, storage, and environment checks"
  else
    section "2/3 TEMPLATE PREPARATION"
    warn "Creating a template only; no endpoint will be created by this script."
    template_raw="$(runpodctl template create \
      --name "$template_name" \
      --image "$image_ref" \
      --serverless \
      --container-disk-in-gb 30 \
      --ports "8080/http" \
      --port-labels "8080=http" \
      --env "$http_env" \
      --output json)" || die "Template creation failed"
    template_json="$(printf '%s' "$template_raw" | extract_json)" || die "Template response was not valid JSON"
    template_id="$(printf '%s' "$template_json" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
candidate = payload.get("id") or payload.get("templateId") or payload.get("template_id")
if not candidate and isinstance(payload.get("template"), dict):
    candidate = payload["template"].get("id")
if not isinstance(candidate, str) or not candidate:
    raise SystemExit("template response did not contain an ID")
print(candidate)
')" || die "Template response did not contain an ID"
    validate_template "$template_json" "$image_ref" || die "New template failed HTTP configuration validation"
    ok "HTTP template created: $template_id"
  fi

  section "3/3 CONSOLE HANDOFF"
  info "Template ID: $template_id"
  info "Endpoint type: Load Balancer (select this in RunPod Console)"
  info "GPU: NVIDIA GeForce RTX 4090 × 1"
  info "Workers: min 0, max 1; idle timeout 60 seconds"
  info "Network Volume: none"
  info "Container port: 8080/http"
  info "Environment: RUNPOD_WORKER_MODE=http, SERVER_HOST=0.0.0.0, PORT=8080"
  info "Health: PORT_HEALTH=8080, HEALTH_CHECK_PATH=/health"
  info "After creation, use: CONFIRM_BILLED=1 scripts/deploy-http.sh check ENDPOINT_ID"
  ok "No queue endpoint, worker, job, or cleanup action was created"
}

check_endpoint() {
  local endpoint_id="$1"
  [[ "$endpoint_id" =~ ^[A-Za-z0-9_-]+$ ]] || die "Endpoint ID contains unexpected characters."
  [[ "${CONFIRM_BILLED:-}" == "1" ]] || \
    die "Refusing HTTP endpoint check; set CONFIRM_BILLED=1 because scale-to-zero may start a worker."
  command -v curl >/dev/null || die "curl is not installed"
  [[ -n "${RUNPOD_API_KEY:-}" ]] || die "Set RUNPOD_API_KEY for endpoint authentication"

  local base_url="https://${endpoint_id}.api.runpod.ai"
  local headers=(--header "Authorization: Bearer ${RUNPOD_API_KEY}" --header "Accept: application/json")
  section "HTTP ENDPOINT CHECK"
  info "Base URL: ${base_url}/v1"
  info "Health URL: ${base_url}/health"
  info "This check performs GET requests only; it does not submit a chat job."

  local models_body
  curl --silent --show-error --fail-with-body --max-time 30 "${headers[@]}" "$base_url/health" >/dev/null || \
    die "HTTP health check failed; the worker may still be cold-starting"
  ok "Native llama-server health returned successfully"
  models_body="$(curl --silent --show-error --fail-with-body --max-time 30 "${headers[@]}" "$base_url/v1/models")" || \
    die "OpenAI models endpoint failed"
  printf '%s' "$models_body" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
if payload.get("object") != "list" or not isinstance(payload.get("data"), list) or not payload["data"]:
    raise SystemExit("/v1/models did not return a non-empty OpenAI model list")
print("models:", ", ".join(str(item.get("id", "<unknown>")) for item in payload["data"] if isinstance(item, dict)))
'
  ok "OpenAI /v1/models endpoint returned a model list"
  info "Inference base URL for Open WebUI: ${base_url}/v1"
}

command_name="${1:-prepare}"
shift || true
case "$command_name" in
  -h|--help)
    usage
    ;;
  prepare)
    [[ $# -le 2 ]] || { usage; exit 2; }
    prepare "$@"
    ;;
  check)
    [[ $# -eq 1 ]] || { usage; exit 2; }
    check_endpoint "$1"
    ;;
  *)
    usage
    exit 2
    ;;
esac
