#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
service_name="qwen38-openai-shim"
user_home="$(getent passwd "$(id -u)" | cut -d: -f6)"
config_dir="${XDG_CONFIG_HOME:-$user_home/.config}"
user_unit_dir="$config_dir/systemd/user"
unit_path="$user_unit_dir/$service_name.service"
env_path="$config_dir/$service_name.env"
uv_bin="$(command -v uv || true)"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }
[[ -n "$uv_bin" ]] || die "uv is not installed or is not on PATH"
command -v systemctl >/dev/null || die "systemctl is not installed"

if [[ ! -f "$env_path" ]]; then
  install -Dm600 "$script_dir/.env.openai-shim.example" "$env_path"
  printf 'Created %s; edit it with the RunPod endpoint and secrets, then rerun.\n' "$env_path"
  exit 2
fi

grep -q '^RUNPOD_ENDPOINT_ID=replace-' "$env_path" && die "edit $env_path before installing"
grep -q '^RUNPOD_API_KEY=replace-' "$env_path" && die "edit $env_path before installing"
grep -q '^OPENAI_SHIM_API_KEY=replace-' "$env_path" && die "edit $env_path before installing"

install -d "$user_unit_dir"
cat > "$unit_path" <<EOF
[Unit]
Description=OpenAI-compatible proxy for the RunPod queue endpoint
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$repo_dir
EnvironmentFile=$env_path
ExecStart=$uv_bin run --no-project python scripts/openai_shim.py
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.cache/uv

[Install]
WantedBy=default.target
EOF
chmod 600 "$env_path"

systemctl --user daemon-reload
systemctl --user enable --now "$service_name.service"
systemctl --user --no-pager --full status "$service_name.service" || true
printf '\nInstalled %s. Health check: curl http://127.0.0.1:8000/health\n' "$service_name.service"
printf 'Unit: %s\nEnvironment: %s\n' "$unit_path" "$env_path"
