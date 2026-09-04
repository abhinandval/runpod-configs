import os
import unittest
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
        self.assertIn("--no-mmproj", command)

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


if __name__ == "__main__":
    unittest.main()
