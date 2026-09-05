import os
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Settings


class ConfigTests(unittest.TestCase):
    def assert_invalid(self, **environment):
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaises(ValueError):
                Settings.from_env()

    def test_rejects_invalid_port(self):
        self.assert_invalid(SERVER_PORT="70000")

    def test_rejects_invalid_batch_relationship(self):
        self.assert_invalid(N_BATCH="64", N_UBATCH="128")

    def test_rejects_request_timeout_above_endpoint_timeout(self):
        self.assert_invalid(REQUEST_TIMEOUT_SECONDS="181")

    def test_rejects_default_tokens_above_request_cap(self):
        self.assert_invalid(DEFAULT_MAX_TOKENS="3000", MAX_REQUEST_TOKENS="2048")

    def test_create_cli_pins_exact_safe_defaults(self):
        ops = Path("scripts/ops.sh").read_text()
        self.assertIn("--gpu-count 1", ops)
        self.assertIn("--workers-min 0", ops)
        self.assertIn("--workers-max 1", ops)
        self.assertIn("--execution-timeout 180", ops)
        self.assertIn("--include-template", ops)
        self.assertIn("--include-workers", ops)
        self.assertNotIn("--network-volume-id", ops)
        self.assertIn("--env MODEL_CACHE_DIR=/models", ops)
        self.assertIn("--env LLAMA_CACHE=/models", ops)

    def test_docker_uses_pinned_prebuilt_cuda_server(self):
        dockerfile = Path("Dockerfile").read_text()
        self.assertIn("ghcr.io/ggml-org/llama.cpp@sha256:", dockerfile)
        self.assertIn("LLAMA_SERVER_BIN=/app/llama-server", dockerfile)
        self.assertIn("LD_LIBRARY_PATH=/app:/usr/local/cuda/lib64", dockerfile)
        self.assertIn("--break-system-packages", dockerfile)
        self.assertNotIn("git clone https://github.com/ggml-org/llama.cpp.git", dockerfile)


if __name__ == "__main__":
    unittest.main()
