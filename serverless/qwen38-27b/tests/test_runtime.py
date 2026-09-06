import os
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from src.config import Settings
from src.runtime import LlamaServer


class RuntimeTests(unittest.TestCase):
    def test_command_uses_hugging_face_reference(self):
        with patch.dict(os.environ, {"MODEL_PATH": "", "MODEL_HF_REF": "org/model:Q4_K_M"}, clear=False):
            server = LlamaServer(Settings.from_env())
        command = server.command()
        self.assertIn("-hf", command)
        self.assertIn("org/model:Q4_K_M", command)
        self.assertIn("-ngl", command)
        self.assertNotIn("--no-mmproj", command)

    def test_command_does_not_disable_mmproj_for_local_model(self):
        with patch.dict(os.environ, {"MODEL_PATH": "/models/model.gguf"}, clear=False):
            server = LlamaServer(Settings.from_env())
        self.assertNotIn("--no-mmproj", server.command())

    def test_command_uses_local_model_when_configured(self):
        with patch.dict(os.environ, {"MODEL_PATH": "/models/model.gguf"}, clear=False):
            server = LlamaServer(Settings.from_env())
        command = server.command()
        self.assertIn("-m", command)
        self.assertIn("/models/model.gguf", command)
        self.assertNotIn("-hf", command)
        self.assertNotIn("--no-mmproj", command)

    def test_public_http_bind_healthcheck_uses_loopback(self):
        with patch.dict(
            os.environ,
            {
                "RUNPOD_WORKER_MODE": "http",
                "SERVER_HOST": "0.0.0.0",
                "PORT": "9090",
            },
            clear=False,
        ):
            server = LlamaServer(Settings.from_env())
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("src.runtime.urllib.request.urlopen", return_value=response) as urlopen:
            server._healthcheck()
        self.assertEqual(urlopen.call_args.args[0].full_url, "http://127.0.0.1:9090/health")


if __name__ == "__main__":
    unittest.main()
