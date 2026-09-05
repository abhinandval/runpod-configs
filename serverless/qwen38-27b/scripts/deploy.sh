#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_image="ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-bd868371608b997643b8d8c5419ace8a82f933dc"
default_template_id="zyhg00liv1"

usage() {
  cat >&2 <<'EOF'
End-to-end Qwen3.8-27B RunPod Serverless deployment and smoke test.

Usage:
  CONFIRM_CREATE=1 CONFIRM_BILLED=1 deploy.sh [image-ref] [template-name] [endpoint-name]

Environment:
  RUNPOD_TEMPLATE_ID  Existing template to verify and reuse (default: zyhg00liv1)
  RUNPOD_LOG_FILE     Exact log path (default: <TMPDIR>/runpod-qwen38-deploy-<UTC>.log)
  RUNPOD_LOG_DIR      Log directory when RUNPOD_LOG_FILE is not set
  DEPLOY_MAX_ATTEMPTS Maximum purge/redeploy attempts, capped at 3 (default: 3)
  CONFIRM_PURGE       Auto-accept purge/redeploy prompts when set to 1

Defaults:
  image-ref      ghcr.io/abhinandval/llama-cpp-qwen38-27b:sha-bd868371608b997643b8d8c5419ace8a82f933dc
  template-name  qwen38-27b-llama-cpp
  endpoint-name  qwen38-27b-llama-cpp

The script checks CLI/API access, image/template identity, endpoint safety, GPU,
CUDA floor, scaling, timeout, and storage before deployment. It creates a
timestamped log, prints deployment details, submits a bounded tiny `pong` job,
retries only after a terminal failure, validates the response, and prints final
endpoint/job status.

A billed worker may start during the smoke test. The endpoint is retained at
workers-min=0 for inspection; purge it afterward with:
  CONFIRM_PURGE=1 scripts/purge.sh ENDPOINT_ID
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
[[ $# -le 3 ]] || { usage; exit 2; }
[[ "${CONFIRM_CREATE:-}" == "1" ]] || {
  echo "Refusing deployment; set CONFIRM_CREATE=1 after reviewing the command." >&2
  exit 2
}
[[ "${CONFIRM_BILLED:-}" == "1" ]] || {
  echo "Refusing E2E smoke test; set CONFIRM_BILLED=1 to accept possible billing." >&2
  exit 2
}

image_ref="${1:-$default_image}"
template_name="${2:-qwen38-27b-llama-cpp}"
endpoint_name="${3:-qwen38-27b-llama-cpp}"
template_id="${RUNPOD_TEMPLATE_ID-$default_template_id}"

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
if [[ -n "$template_id" ]]; then
  [[ "$template_id" =~ ^[A-Za-z0-9_-]+$ ]] || {
    echo "RUNPOD_TEMPLATE_ID contains unexpected characters." >&2
    exit 2
  }
fi

log_dir="${RUNPOD_LOG_DIR:-${TMPDIR:-/tmp}}"
if [[ -n "${RUNPOD_LOG_FILE:-}" ]]; then
  log_file="$RUNPOD_LOG_FILE"
else
  mkdir -p "$log_dir"
  log_file="$log_dir/runpod-qwen38-deploy-$(date -u +%Y%m%dT%H%M%SZ).log"
fi
mkdir -p "$(dirname "$log_file")"
touch "$log_file"
exec > >(tee -a "$log_file") 2>&1

cleanup() {
  [[ -n "${smoke_capture:-}" && -f "$smoke_capture" ]] && rm -f "$smoke_capture"
}
trap cleanup EXIT

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

section "1/5 PREFLIGHT"
command -v runpodctl >/dev/null || die "runpodctl is not installed"
command -v python3 >/dev/null || die "python3 is not installed"
ok "Required commands are available"
runpodctl version || die "runpodctl version check failed"
ok "RunPod CLI is installed; checking API access and template next"

template_json=""
if [[ -n "$template_id" ]]; then
  template_raw="$(runpodctl template get "$template_id" --output json)" || die "Could not read template $template_id"
  template_json="$(printf '%s' "$template_raw" | extract_json)" || die "Template response was not valid JSON"
else
  warn "No template ID supplied; creating template $template_name"
  template_raw="$(runpodctl template create \
    --name "$template_name" \
    --image "$image_ref" \
    --serverless \
    --container-disk-in-gb 30 \
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
fi

template_image="$(printf '%s' "$template_json" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("imageName", ""))')"
[[ "$template_image" == "$image_ref" ]] || die "Template image mismatch: expected $image_ref, found ${template_image:-<missing>}"
template_is_serverless="$(printf '%s' "$template_json" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("isServerless", False))')"
[[ "$template_is_serverless" == "True" ]] || die "Template $template_id is not marked serverless"
template_volume="$(printf '%s' "$template_json" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("volumeInGb", 0) or 0)')"
[[ "$template_volume" == "0" ]] || die "Template has a persistent volume; expected no Network Volume"
ok "RunPod API access confirmed"
ok "Template $template_id matches the immutable image and has no Network Volume"

max_attempts="${DEPLOY_MAX_ATTEMPTS:-3}"
[[ "$max_attempts" =~ ^[1-3]$ ]] || die "DEPLOY_MAX_ATTEMPTS must be 1, 2, or 3"

for ((deployment_attempt = 1; deployment_attempt <= max_attempts; deployment_attempt++)); do
endpoint_list="$(runpodctl serverless list --output json)" || die "Could not list serverless endpoints"
existing_endpoint_id="$(printf '%s' "$endpoint_list" | python3 -c '
import json
import sys

name = sys.argv[1]
for item in json.load(sys.stdin):
    if isinstance(item, dict) and item.get("name") == name:
        print(item.get("id", ""))
        break
' "$endpoint_name")"
if [[ -n "$existing_endpoint_id" ]]; then
  [[ "${CONFIRM_PURGE:-}" == "1" ]] || die "Endpoint $endpoint_name already exists as $existing_endpoint_id; set CONFIRM_PURGE=1 to replace it"
  warn "Purging existing endpoint $existing_endpoint_id before this test"
  CONFIRM_PURGE=1 "$script_dir/purge.sh" "$existing_endpoint_id" || die "Could not purge existing endpoint"
  ok "Previous endpoint purged"
else
  ok "No existing endpoint named $endpoint_name"
fi

section "2/5 DEPLOYMENT ATTEMPT $deployment_attempt/$max_attempts"
info "Image: $image_ref"
info "Template: $template_id ($template_name)"
info "GPU: NVIDIA GeForce RTX 4090 × 1"
info "CUDA floor: 12.8"
info "Scaling: workers-min=0, workers-max=1, idle-timeout=60s"
info "Storage: ephemeral container disk, no Network Volume"

endpoint_raw="$(runpodctl serverless create \
  --template-id "$template_id" \
  --name "$endpoint_name" \
  --gpu-id "NVIDIA GeForce RTX 4090" \
  --gpu-count 1 \
  --workers-min 0 \
  --workers-max 1 \
  --idle-timeout 60 \
  --execution-timeout 180 \
  --min-cuda-version 12.8 \
  --output json)" || die "Endpoint creation failed"
endpoint_json="$(printf '%s' "$endpoint_raw" | extract_json)" || die "Endpoint response was not valid JSON"
endpoint_id="$(printf '%s' "$endpoint_json" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("id", ""))')"
[[ "$endpoint_id" =~ ^[A-Za-z0-9_-]+$ ]] || die "Endpoint response did not contain a valid ID"
ok "Endpoint created: $endpoint_id"

section "3/5 SAFETY PREFLIGHT"
endpoint_detail="$(runpodctl serverless get "$endpoint_id" --include-template --include-workers --output json)" || die "Could not read created endpoint"
printf '%s' "$endpoint_detail" | python3 "$script_dir/validate_endpoint.py" --gpu-id "NVIDIA GeForce RTX 4090" || die "Created endpoint failed safety validation"
endpoint_min_cuda="$(printf '%s' "$endpoint_detail" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("minCudaVersion", ""))')"
[[ "$endpoint_min_cuda" == "12.8" ]] || die "Endpoint CUDA floor is ${endpoint_min_cuda:-<missing>}, expected 12.8"
endpoint_template_id="$(printf '%s' "$endpoint_detail" | python3 -c 'import json, sys; print(json.load(sys.stdin).get("templateId", ""))')"
[[ "$endpoint_template_id" == "$template_id" ]] || die "Endpoint template mismatch"
ok "Created endpoint passed GPU, scaling, timeout, CUDA, and template checks"
endpoint_run_url="$(printf '%s' "$endpoint_json" | python3 -c 'import json, sys; payload=json.load(sys.stdin); urls=payload.get("urls", {}); print(payload.get("url") or urls.get("run", ""))')"
endpoint_health_url="$(printf '%s' "$endpoint_json" | python3 -c 'import json, sys; payload=json.load(sys.stdin); urls=payload.get("urls", {}); print(payload.get("healthUrl") or urls.get("health", ""))')"

section "4/5 PING TEST"
smoke_capture="$(mktemp "${TMPDIR:-/tmp}/qwen38-smoke.XXXXXX")"
smoke_exit=0
SMOKE_WAIT=180s SMOKE_MAX_ATTEMPTS=1 CONFIRM_BILLED=1 \
  "$script_dir/smoke.sh" "$endpoint_id" 2>&1 | tee "$smoke_capture" || smoke_exit=$?
if [[ "$smoke_exit" -eq 0 ]] && python3 - "$smoke_capture" <<'PY'
import json
import sys

path = sys.argv[1]
decoder = json.JSONDecoder()
raw = open(path, encoding="utf-8").read()
for index, character in enumerate(raw):
    if character not in "[{":
        continue
    try:
        value, _ = decoder.raw_decode(raw[index:])
    except json.JSONDecodeError:
        continue
    objects = value if isinstance(value, list) else [value]
    for item in objects:
        if not isinstance(item, dict):
            continue
        result = item.get("output", item)
        choices = result.get("choices") if isinstance(result, dict) else None
        if choices and choices[0].get("message", {}).get("content") == "pong":
            raise SystemExit(0)
raise SystemExit("smoke response did not contain exactly 'pong'")
PY
then
  ok "Ping test passed: model returned exactly pong"
  test_ok=1
else
  warn "Ping test did not complete successfully; inspect the log and job status"
  test_ok=0
fi

job_id="$(python3 - "$smoke_capture" <<'PY'
import json
import sys

decoder = json.JSONDecoder()
raw = open(sys.argv[1], encoding="utf-8").read()
last_job_id = ""
for index, character in enumerate(raw):
    if character not in "[{":
        continue
    try:
        value, _ = decoder.raw_decode(raw[index:])
    except json.JSONDecodeError:
        continue
    objects = value if isinstance(value, list) else [value]
    for item in objects:
        if isinstance(item, dict) and item.get("id") and item.get("status"):
            last_job_id = item["id"]
if last_job_id:
    print(last_job_id)
raise SystemExit(0)
PY
)"

section "5/5 FINAL STATUS"
info "Endpoint: $endpoint_id"
[[ -n "$endpoint_run_url" ]] && info "Run URL: $endpoint_run_url"
[[ -n "$endpoint_health_url" ]] && info "Health URL: $endpoint_health_url"
info "Log file: $log_file"
if [[ -n "$job_id" ]]; then
  info "Smoke job: $job_id"
  runpodctl serverless status "$endpoint_id" "$job_id" --output json || warn "Could not read smoke job status"
fi
runpodctl serverless health "$endpoint_id" --output json || warn "Could not read endpoint health"
if [[ "$test_ok" -eq 1 ]]; then
  ok "E2E deployment and ping validation succeeded"
fi
if [[ "$test_ok" -eq 1 ]]; then
  exit 0
fi

warn "Attempt $deployment_attempt/$max_attempts failed; endpoint is retained until retry choice"
if (( deployment_attempt == max_attempts )); then
  die "E2E deployment failed after $max_attempts attempts"
fi

retry_choice=""
if [[ "${CONFIRM_PURGE:-}" == "1" ]]; then
  warn "CONFIRM_PURGE=1 is set; purging endpoint, queued work, and workers before retry"
  retry_choice="y"
elif [[ -t 0 ]]; then
  printf 'Purge endpoint %s, queued work, and workers, then redeploy? [y/N] ' "$endpoint_id"
  read -r retry_choice || retry_choice=""
else
  warn "No interactive terminal; set CONFIRM_PURGE=1 to purge and redeploy automatically"
  exit 1
fi

case "$retry_choice" in
  y|Y|yes|YES)
    CONFIRM_PURGE=1 "$script_dir/purge.sh" "$endpoint_id" || die "Could not purge failed endpoint"
    ok "Failed endpoint purged; continuing with a fresh deployment attempt"
    ;;
  *)
    warn "Retry declined; endpoint retained at workers-min=0"
    exit 1
    ;;
esac
done

die "E2E deployment failed"
