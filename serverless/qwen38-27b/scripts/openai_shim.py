#!/usr/bin/env python3
"""Small OpenAI-compatible HTTP shim for a RunPod queue endpoint.

This process belongs beside the RunPod endpoint, not inside the queue worker.
It translates synchronous OpenAI chat-completion requests into RunPod /run
jobs, polls /status, and returns the worker's OpenAI-shaped output.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
DEFAULT_MODEL = "qwen38-27b-q4_k_m"
JsonRequest = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]


class ShimError(Exception):
    """An error that can be rendered as an OpenAI-style HTTP error."""

    def __init__(self, message: str, *, status: int = 502, error_type: str = "runpod_error", job_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type
        self.job_id = job_id


def request_json(
    url: str,
    api_key: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ShimError(
            f"RunPod API returned HTTP {exc.code}: {body}",
            status=502,
            error_type="runpod_api_error",
        ) from exc
    except URLError as exc:
        raise ShimError(f"Could not reach RunPod API: {exc.reason}", error_type="runpod_network_error") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ShimError("RunPod API returned invalid JSON", error_type="runpod_invalid_response") from exc
    if not isinstance(value, dict):
        raise ShimError("RunPod API returned a non-object JSON response", error_type="runpod_invalid_response")
    return value


def run_chat_completion(
    endpoint_id: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    wait_seconds: float = 180,
    poll_seconds: float = 2,
    request_fn: JsonRequest = request_json,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Submit one OpenAI-shaped request and synchronously return its output."""
    if payload.get("stream") is True:
        raise ShimError(
            "stream=true is not supported by this queue-based shim",
            status=400,
            error_type="invalid_request_error",
        )
    if not isinstance(payload.get("messages"), list) or not payload["messages"]:
        raise ShimError(
            "messages must be a non-empty JSON array",
            status=400,
            error_type="invalid_request_error",
        )

    base_url = f"https://api.runpod.ai/v2/{endpoint_id}"
    submitted = request_fn(f"{base_url}/run", api_key, {"input": payload}, 15)
    job_id = submitted.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise ShimError("RunPod submission did not return a job ID", error_type="runpod_invalid_response")

    deadline = clock() + wait_seconds
    while True:
        status_payload = request_fn(f"{base_url}/status/{job_id}", api_key, None, 15)
        status = status_payload.get("status")
        if status == "COMPLETED":
            output = status_payload.get("output")
            if not isinstance(output, dict):
                raise ShimError(
                    "Completed RunPod job did not contain an object output",
                    error_type="runpod_invalid_response",
                    job_id=job_id,
                )
            if isinstance(output.get("error"), dict):
                message = output["error"].get("message", "worker returned an error")
                raise ShimError(str(message), status=502, error_type="worker_error", job_id=job_id)
            return output
        if status in TERMINAL_STATUSES:
            raise ShimError(
                f"RunPod job ended with status {status}",
                status=502,
                error_type="runpod_job_error",
                job_id=job_id,
            )
        if clock() >= deadline:
            raise ShimError(
                f"RunPod job {job_id} is still {status or 'unknown'} after {wait_seconds:g}s; do not retry automatically",
                status=504,
                error_type="runpod_timeout",
                job_id=job_id,
            )
        sleeper(min(poll_seconds, max(0, deadline - clock())))


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class ShimHandler(BaseHTTPRequestHandler):
    server: "ShimServer"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)

    def _write_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: ShimError) -> None:
        body: dict[str, Any] = {"message": error.message, "type": error.error_type}
        if error.job_id:
            body["job_id"] = error.job_id
        self._write_json({"error": body}, error.status)

    def _authorized(self) -> bool:
        expected = self.server.shim_api_key
        supplied = self.headers.get("Authorization", "")
        return supplied == f"Bearer {expected}"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path in {"/health", "/v1/health", "/openai/v1/health"}:
            self._write_json({"status": "ok"})
            return
        if self.path in {"/v1/models", "/openai/v1/models"}:
            if not self._authorized():
                self._write_json({"error": {"message": "authentication required", "type": "authentication_error"}}, 401)
                return
            self._write_json({
                "object": "list",
                "data": [{"id": self.server.model_name, "object": "model", "owned_by": "runpod"}],
            })
            return
        self._write_json({"error": {"message": "not found", "type": "not_found_error"}}, 404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path not in {"/v1/chat/completions", "/openai/v1/chat/completions"}:
            self._write_json({"error": {"message": "not found", "type": "not_found_error"}}, 404)
            return
        if not self._authorized():
            self._write_json({"error": {"message": "authentication required", "type": "authentication_error"}}, 401)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 1 or content_length > 1_000_000:
                raise ShimError("request body must be between 1 byte and 1 MB", status=400, error_type="invalid_request_error")
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ShimError("request body must be a JSON object", status=400, error_type="invalid_request_error")
            output = run_chat_completion(
                self.server.endpoint_id,
                self.server.runpod_api_key,
                payload,
                wait_seconds=self.server.wait_seconds,
            )
            self._write_json(output)
        except ShimError as exc:
            self._error(exc)
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(ShimError(f"invalid JSON request: {exc}", status=400, error_type="invalid_request_error"))
        except Exception as exc:  # keep the HTTP server alive for later requests
            self._error(ShimError(f"shim error: {exc}", error_type="shim_error"))


class ShimServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], endpoint_id: str, runpod_api_key: str, shim_api_key: str, model_name: str, wait_seconds: float):
        super().__init__(address, ShimHandler)
        self.endpoint_id = endpoint_id
        self.runpod_api_key = runpod_api_key
        self.shim_api_key = shim_api_key
        self.model_name = model_name
        self.wait_seconds = wait_seconds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint-id", default=os.getenv("RUNPOD_ENDPOINT_ID"))
    parser.add_argument("--host", default=os.getenv("OPENAI_SHIM_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("OPENAI_SHIM_PORT", "8000")))
    parser.add_argument("--wait-seconds", type=float, default=float(os.getenv("OPENAI_SHIM_WAIT_SECONDS", "180")))
    args = parser.parse_args()
    runpod_api_key = os.getenv("RUNPOD_API_KEY")
    shim_api_key = os.getenv("OPENAI_SHIM_API_KEY")
    if not args.endpoint_id:
        parser.error("set RUNPOD_ENDPOINT_ID or pass --endpoint-id")
    if not runpod_api_key:
        parser.error("set RUNPOD_API_KEY")
    if not shim_api_key:
        parser.error("set OPENAI_SHIM_API_KEY to a separate client-facing secret")
    if args.port < 1 or args.port > 65535:
        parser.error("--port must be between 1 and 65535")
    if args.wait_seconds <= 0:
        parser.error("--wait-seconds must be positive")

    server = ShimServer(
        (args.host, args.port),
        args.endpoint_id,
        runpod_api_key,
        shim_api_key,
        os.getenv("OPENAI_SHIM_MODEL", DEFAULT_MODEL),
        args.wait_seconds,
    )
    print(f"OpenAI shim listening on http://{args.host}:{args.port}/v1", flush=True)
    print(f"RunPod endpoint: {args.endpoint_id}; request wait: {args.wait_seconds:g}s", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping OpenAI shim", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
