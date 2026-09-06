import unittest

from scripts.openai_shim import ShimError, model_listing, run_chat_completion


class OpenAIShimTests(unittest.TestCase):
    def test_model_listing_advertises_proxy_capabilities(self):
        model = model_listing("qwen", 32768, 2048)["data"][0]
        self.assertEqual(model["capabilities"]["chat"], True)
        self.assertEqual(model["capabilities"]["streaming"], False)
        self.assertEqual(model["metadata"]["quantization"], "Q4_K_M")
        self.assertEqual(model["metadata"]["context_window"], 32768)

    def test_wraps_input_polls_and_unwraps_openai_output(self):
        calls = []
        responses = iter([
            {"id": "job-1", "status": "IN_QUEUE"},
            {"id": "job-1", "status": "COMPLETED", "output": {"choices": [{"message": {"content": "pong"}}]}},
        ])

        def request(url, api_key, payload, timeout):
            calls.append((url, api_key, payload, timeout))
            return next(responses)

        output = run_chat_completion(
            "endpoint-1",
            "runpod-secret",
            {"model": "qwen", "messages": [{"role": "user", "content": "ping"}]},
            request_fn=request,
            sleeper=lambda _: None,
        )

        self.assertEqual(output["choices"][0]["message"]["content"], "pong")
        self.assertEqual(calls[0][2], {"input": {"model": "qwen", "messages": [{"role": "user", "content": "ping"}]}})
        self.assertIn("/status/job-1", calls[1][0])

    def test_rejects_streaming(self):
        with self.assertRaises(ShimError) as context:
            run_chat_completion(
                "endpoint-1",
                "runpod-secret",
                {"stream": True, "messages": [{"role": "user", "content": "ping"}]},
            )
        self.assertEqual(context.exception.status, 400)

    def test_timeout_includes_job_id_and_refuses_implicit_retry(self):
        now = iter([0.0, 1.0])

        def request(url, api_key, payload, timeout):
            if url.endswith("/run"):
                return {"id": "job-2", "status": "IN_QUEUE"}
            return {"id": "job-2", "status": "IN_PROGRESS"}

        with self.assertRaises(ShimError) as context:
            run_chat_completion(
                "endpoint-1",
                "runpod-secret",
                {"messages": [{"role": "user", "content": "ping"}]},
                wait_seconds=0.5,
                request_fn=request,
                clock=lambda: next(now),
                sleeper=lambda _: None,
            )
        self.assertEqual(context.exception.status, 504)
        self.assertEqual(context.exception.job_id, "job-2")


if __name__ == "__main__":
    unittest.main()
