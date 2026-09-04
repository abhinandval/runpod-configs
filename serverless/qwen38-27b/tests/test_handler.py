import unittest
from unittest.mock import patch

from src.handler import _build_request, handler


class HandlerTests(unittest.TestCase):
    def test_builds_openai_request_and_disables_thinking(self):
        request = _build_request(
            {
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
                "enable_thinking": False,
            }
        )
        self.assertEqual(request["model"], "qwen38-27b-q4_k_m")
        self.assertEqual(request["max_tokens"], 8)
        self.assertEqual(request["chat_template_kwargs"]["enable_thinking"], False)
        self.assertNotIn("enable_thinking", request)

    def test_rejects_streaming(self):
        with self.assertRaises(ValueError):
            _build_request(
                {"messages": [{"role": "user", "content": "ping"}], "stream": True}
            )

    def test_handler_returns_worker_error_object(self):
        with patch("src.handler.runtime.chat_completion", side_effect=RuntimeError("boom")):
            result = handler({"input": {"messages": [{"role": "user", "content": "ping"}]}})
        self.assertEqual(result["error"]["type"], "RuntimeError")
        self.assertEqual(result["error"]["message"], "boom")


if __name__ == "__main__":
    unittest.main()
