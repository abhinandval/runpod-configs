#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || "$1" == "-h" || "$1" == "--help" ]]; then
  cat >&2 <<'EOF'
Purge a disposable RunPod Serverless endpoint and its queued work.

Usage:
  CONFIRM_PURGE=1 purge.sh ENDPOINT_ID

Deleting the endpoint is the supported deterministic cleanup operation: it
removes the endpoint, queued jobs, and worker allocations. This is
irreversible and must be followed by deploy.sh before another test.
EOF
  [[ $# -eq 1 ]] && exit 0
  exit 2
fi

[[ "${CONFIRM_PURGE:-}" == "1" ]] || {
  echo "Refusing purge; set CONFIRM_PURGE=1 after reviewing the endpoint ID." >&2
  exit 2
}

endpoint_id="$1"
[[ "$endpoint_id" =~ ^[A-Za-z0-9_-]+$ ]] || {
  echo "Endpoint ID contains unexpected characters." >&2
  exit 2
}

echo "WARNING: deleting endpoint $endpoint_id and purging queued work/workers." >&2
exec runpodctl serverless delete "$endpoint_id" --output json
