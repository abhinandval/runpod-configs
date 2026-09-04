"""RunPod job handler that proxies chat requests to llama-server."""

from __future__ import annotations

from typing import Any

from .config import Settings
from .runtime import LlamaServer

settings = Settings.from_env()
runtime = LlamaServer(settings)


def _payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("input", job)
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    return payload


def _build_request(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty JSON array")
    if payload.get("stream") is True:
        raise ValueError("stream=true is not supported by this synchronous worker")

    request = dict(payload)
    request["model"] = str(payload.get("model") or "qwen38-27b-q4_k_m")
    request.pop("stream", None)
    max_tokens = payload.get("max_tokens", settings.default_max_tokens)
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    request["max_tokens"] = min(max_tokens, settings.max_request_tokens)

    if "enable_thinking" in payload:
        enable_thinking = payload["enable_thinking"]
        if not isinstance(enable_thinking, bool):
            raise ValueError("enable_thinking must be a boolean")
        kwargs = payload.get("chat_template_kwargs", {})
        if not isinstance(kwargs, dict):
            raise ValueError("chat_template_kwargs must be an object")
        request["chat_template_kwargs"] = {
            **kwargs,
            "enable_thinking": enable_thinking,
        }
        request.pop("enable_thinking", None)
    return request


def handler(job: dict[str, Any]) -> dict[str, Any]:
    """Handle one RunPod job and return the llama.cpp OpenAI response."""
    try:
        request = _build_request(_payload(job))
        return runtime.chat_completion(request)
    except Exception as exc:  # RunPod serializes the returned error object.
        return {"error": {"type": type(exc).__name__, "message": str(exc)}}
