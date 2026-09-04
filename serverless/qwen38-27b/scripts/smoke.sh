#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: CONFIRM_BILLED=1 $0 <endpoint-id>" >&2
  exit 2
fi
if [[ "${CONFIRM_BILLED:-}" != "1" ]]; then
  cat >&2 <<'EOF'
This command submits a RunPod job. It may start a billed worker.
The prompt is intentionally tiny and the wait is bounded to 90 seconds.
Re-run with CONFIRM_BILLED=1 if you explicitly accept that cost.
EOF
  exit 2
fi

endpoint_id="$1"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
endpoint_json="$(runpodctl serverless get "$endpoint_id" \
  --include-template --include-workers --output json)"
printf '%s' "$endpoint_json" | python3 "$script_dir/validate_endpoint.py" \
  --gpu-id "NVIDIA GeForce RTX 4090"
payload='{"messages":[{"role":"user","content":"Reply with exactly: pong"}],"max_tokens":8,"enable_thinking":false}'
echo "WARNING: starting one bounded RunPod Serverless smoke job; billing may begin." >&2
runpodctl serverless run "$endpoint_id" --input "$payload" --wait 90s
