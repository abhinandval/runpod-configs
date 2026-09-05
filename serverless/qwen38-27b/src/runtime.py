"""Lifecycle and HTTP client for a single local llama-server process."""

from __future__ import annotations

import atexit
import json
import os
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import Settings


class LlamaServer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        atexit.register(self.stop)

    def command(self) -> list[str]:
        settings = self.settings
        command = [
            settings.llama_server_bin,
            "--host",
            settings.server_host,
            "--port",
            str(settings.server_port),
            "--no-webui",
            "--metrics",
            "--cont-batching",
            "-c",
            str(settings.n_ctx),
            "-np",
            str(settings.n_parallel),
            "-b",
            str(settings.n_batch),
            "-ub",
            str(settings.n_ubatch),
            "-ngl",
            str(settings.n_gpu_layers),
        ]
        if settings.model_path:
            command.extend(["-m", settings.model_path])
        else:
            command.extend(["-hf", settings.model_hf_ref, "--no-mmproj"])
        if settings.threads:
            command.extend(["-t", str(settings.threads)])
        if settings.flash_attn:
            command.extend(["--flash-attn", settings.flash_attn])
        if settings.llama_api_key:
            command.extend(["--api-key", settings.llama_api_key])
        if settings.extra_args:
            command.extend(shlex.split(settings.extra_args))
        return command

    def _display_command(self) -> str:
        command = self.command()
        if self.settings.llama_api_key:
            index = command.index("--api-key") + 1
            command[index] = "<redacted>"
        return shlex.join(command)

    def ensure_started(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return

            if self.settings.model_path and not Path(self.settings.model_path).is_file():
                raise FileNotFoundError(
                    f"MODEL_PATH does not exist or is not a file: {self.settings.model_path}"
                )

            os.makedirs(self.settings.model_cache_dir, exist_ok=True)
            os.makedirs(self.settings.llama_cache, exist_ok=True)
            environment = os.environ.copy()
            environment["LLAMA_CACHE"] = self.settings.llama_cache
            command = self.command()
            print(f"starting llama-server: {self._display_command()}", flush=True)
            self._process = subprocess.Popen(
                command,
                env=environment,
                stdout=None,
                stderr=subprocess.STDOUT,
                text=True,
            )

        deadline = time.monotonic() + self.settings.startup_timeout_seconds
        last_error = "not ready"
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited during startup with code {self._process.returncode}"
                )
            try:
                self._healthcheck()
                print("llama-server is healthy", flush=True)
                return
            except (OSError, urllib.error.URLError, RuntimeError) as exc:
                last_error = str(exc)
                time.sleep(1)
        self.stop()
        raise TimeoutError(
            f"llama-server did not become healthy within "
            f"{self.settings.startup_timeout_seconds}s: {last_error}"
        )

    def _healthcheck(self) -> None:
        health_host = self.settings.server_host
        if health_host in {"0.0.0.0", "::"}:
            health_host = "127.0.0.1"
        url = f"http://{health_host}:{self.settings.server_port}/health"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"llama-server health HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"llama-server health HTTP {exc.code}") from exc

    def _request(
        self, path: str, payload: dict[str, Any] | None, timeout: float
    ) -> dict[str, Any] | None:
        url = f"http://{self.settings.server_host}:{self.settings.server_port}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.settings.llama_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llama_api_key}"
        request = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"llama-server HTTP {exc.code}: {body[:1000]}") from exc
        if not raw:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("llama-server returned a non-object JSON response")
        return parsed

    def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_started()
        response = self._request(
            "/v1/chat/completions", payload, self.settings.request_timeout_seconds
        )
        if response is None:
            raise RuntimeError("llama-server returned an empty response")
        return response

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def wait(self) -> int:
        """Wait for the server process and return its exit code."""
        with self._lock:
            process = self._process
        if process is None:
            raise RuntimeError("llama-server is not running")
        return process.wait()
