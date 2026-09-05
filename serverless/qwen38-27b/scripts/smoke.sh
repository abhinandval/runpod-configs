#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || "$1" == "-h" || "$1" == "--help" ]]; then
  cat >&2 <<'EOF'
Submit one bounded RunPod Serverless ping and validate the exact response.

Usage:
  CONFIRM_BILLED=1 scripts/smoke.sh ENDPOINT_ID

Environment:
  SMOKE_WAIT                Maximum wait per job (default: 180s)
  SMOKE_MAX_ATTEMPTS        Attempts; retry only after terminal failure (default: 1)
  SMOKE_RETRY_DELAY_SECONDS Delay before a retry (default: 5)

An ambiguous timeout is never retried because the remote job may still be
running. The deployment E2E flow handles retry by purging and redeploying.
EOF
  [[ $# -eq 1 ]] && exit 0
  exit 2
fi
if [[ "${CONFIRM_BILLED:-}" != "1" ]]; then
  cat >&2 <<'EOF'
This command submits a RunPod job. It may start a billed worker.
The prompt is intentionally tiny and the wait is bounded to the endpoint timeout.
Re-run with CONFIRM_BILLED=1 if you explicitly accept that cost.
EOF
  exit 2
fi

endpoint_id="$1"
smoke_wait="${SMOKE_WAIT:-180s}"
max_attempts="${SMOKE_MAX_ATTEMPTS:-1}"
retry_delay="${SMOKE_RETRY_DELAY_SECONDS:-5}"
[[ "$smoke_wait" =~ ^[1-9][0-9]*(s|m)$ ]] || {
  echo "SMOKE_WAIT must be a positive duration such as 180s or 3m." >&2
  exit 2
}
[[ "$max_attempts" =~ ^[1-3]$ ]] || {
  echo "SMOKE_MAX_ATTEMPTS must be 1, 2, or 3." >&2
  exit 2
}
[[ "$retry_delay" =~ ^[0-9]+$ ]] || {
  echo "SMOKE_RETRY_DELAY_SECONDS must be a non-negative integer." >&2
  exit 2
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
endpoint_json="$(runpodctl serverless get "$endpoint_id" \
  --include-template --include-workers --output json)"
printf '%s' "$endpoint_json" | python3 "$script_dir/validate_endpoint.py" \
  --gpu-id "NVIDIA GeForce RTX 4090"

payload='{"messages":[{"role":"user","content":"Reply with exactly: pong"}],"max_tokens":8,"enable_thinking":false}'

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

extract_job_id() {
  python3 -c '
import json
import re
import sys

raw = sys.stdin.read().strip()
try:
    value = json.loads(raw)
except json.JSONDecodeError:
    value = None
if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value):
    print(value)
    raise SystemExit(0)
if isinstance(value, dict) and isinstance(value.get("id"), str):
    print(value["id"])
    raise SystemExit(0)
for line in reversed(raw.splitlines()):
    candidate = line.strip().strip(chr(34))
    if re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        print(candidate)
        raise SystemExit(0)
raise SystemExit("job submission did not return a job ID")
'
}

response_is_pong() {
  printf '%s' "$1" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
result = payload.get("output", payload) if isinstance(payload, dict) else {}
choices = result.get("choices") if isinstance(result, dict) else None
if choices and choices[0].get("message", {}).get("content") == "pong":
    raise SystemExit(0)
raise SystemExit("response did not contain exactly pong")
'
}

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  if (( attempt > 1 )); then
    echo "Retrying ping after terminal worker/job failure (attempt $attempt/$max_attempts) ..." >&2
    sleep "$retry_delay"
  fi

  echo "Submitting bounded ping attempt $attempt/$max_attempts; billing may begin." >&2
  job_submission="$(runpodctl serverless run "$endpoint_id" \
    --input "$payload" --no-wait --output json)" || {
    echo "Job submission failed without a safe job ID; refusing an automatic duplicate." >&2
    exit 1
  }
  job_id="$(printf '%s' "$job_submission" | extract_job_id)" || {
    echo "Could not capture the submitted job ID; refusing an automatic duplicate." >&2
    exit 1
  }
  echo "Ping job: $job_id" >&2

  status_output=""
  status_exit=0
  status_output="$(runpodctl serverless status "$endpoint_id" "$job_id" \
    --wait "$smoke_wait" --output json 2>&1)" || status_exit=$?
  printf '%s\n' "$status_output"
  status_json="$(printf '%s' "$status_output" | extract_json 2>/dev/null || true)"
  job_status="$(printf '%s' "$status_json" | python3 -c \
    'import json, sys; print(json.load(sys.stdin).get("status", "UNKNOWN"))' \
    2>/dev/null || printf 'UNKNOWN')"

  if [[ "$job_status" == "COMPLETED" ]] && response_is_pong "$status_json"; then
    echo "Ping passed: model returned exactly pong." >&2
    exit 0
  fi

  if [[ "$job_status" == "FAILED" || "$job_status" == "CANCELLED" || "$job_status" == "TIMED_OUT" ]]; then
    echo "Ping attempt $attempt reached terminal status: $job_status." >&2
    runpodctl serverless logs "$endpoint_id" --source both --tail 200 || \
      echo "Could not read recent worker logs." >&2
    if (( attempt < max_attempts )); then
      continue
    fi
  else
    echo "Ping status is $job_status (CLI exit $status_exit); it may still be running." >&2
    echo "No retry was submitted because the remote job is not known to be terminal." >&2
  fi
  exit 1
done

exit 1
