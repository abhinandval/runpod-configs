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

    def test_queue_mode_remains_the_default_and_ignores_runpod_port(self):
        with patch.dict(
            os.environ,
            {
                "RUNPOD_WORKER_MODE": "queue",
                "SERVER_HOST": "",
                "SERVER_PORT": "",
                "PORT": "9999",
            },
            clear=False,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.worker_mode, "queue")
        self.assertEqual(settings.server_host, "127.0.0.1")
        self.assertEqual(settings.server_port, 8080)

    def test_http_mode_binds_publicly_and_prefers_runpod_port(self):
        with patch.dict(
            os.environ,
            {
                "RUNPOD_WORKER_MODE": "http",
                "SERVER_HOST": "",
                "SERVER_PORT": "8080",
                "PORT": "9090",
            },
            clear=False,
        ):
            settings = Settings.from_env()
        self.assertEqual(settings.worker_mode, "http")
        self.assertEqual(settings.server_host, "0.0.0.0")
        self.assertEqual(settings.server_port, 9090)

    def test_rejects_unknown_worker_mode(self):
        self.assert_invalid(RUNPOD_WORKER_MODE="grpc")

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
        self.assertIn("EXPOSE 8080", dockerfile)
        self.assertNotIn("SERVER_HOST=127.0.0.1", dockerfile)
        self.assertNotIn("git clone https://github.com/ggml-org/llama.cpp.git", dockerfile)

    def test_deploy_script_is_guarded_end_to_end(self):
        deploy = Path("scripts/deploy.sh").read_text()
        self.assertIn('CONFIRM_CREATE:-', deploy)
        self.assertIn('CONFIRM_BILLED:-', deploy)
        self.assertIn('tee -a "$log_file"', deploy)
        self.assertIn('validate_endpoint.py', deploy)
        self.assertIn('smoke.sh', deploy)
        self.assertIn('exactly \'pong\'', deploy)
        self.assertIn('serverless health', deploy)
        self.assertIn('SMOKE_MAX_ATTEMPTS', deploy)
        self.assertIn('SMOKE_WAIT=180s', deploy)
        self.assertIn('No retry was submitted', Path("scripts/smoke.sh").read_text())
        self.assertIn('--no-wait', Path("scripts/smoke.sh").read_text())
        self.assertIn('DEPLOY_MAX_ATTEMPTS', deploy)
        self.assertIn('Purge endpoint', deploy)
        self.assertIn('purge.sh', deploy)
        self.assertIn('--execution-timeout 180', deploy)

    def test_http_deployment_is_load_balancer_only(self):
        deploy = Path("scripts/deploy-http.sh").read_text()
        self.assertIn("RUNPOD_WORKER_MODE", deploy)
        self.assertIn("HEALTH_CHECK_PATH", deploy)
        self.assertIn("/health", deploy)
        self.assertIn('--ports "8080/http"', deploy)
        self.assertIn("Load Balancer", deploy)
        self.assertIn("no Load Balancer\nendpoint-type flag", deploy)
        self.assertNotIn('endpoint_raw="$(runpodctl serverless create', deploy)


if __name__ == "__main__":
    unittest.main()
