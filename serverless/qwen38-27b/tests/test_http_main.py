import os
import unittest
from unittest.mock import patch

from src.config import Settings
from src.http_main import run_http_worker
from src import main as worker_main


def http_settings() -> Settings:
    with patch.dict(
        os.environ,
        {
            "RUNPOD_WORKER_MODE": "http",
            "SERVER_HOST": "0.0.0.0",
            "PORT": "8080",
            "SERVER_PORT": "8080",
        },
        clear=False,
    ):
        return Settings.from_env()


class FakeRuntime:
    def __init__(self, settings):
        self.settings = settings
        self.calls = []

    def ensure_started(self):
        self.calls.append("ensure_started")

    def wait(self):
        self.calls.append("wait")
        return 0

    def stop(self):
        self.calls.append("stop")


class HttpMainTests(unittest.TestCase):
    def test_starts_before_waiting_and_stops_cleanly(self):
        runtime = FakeRuntime(http_settings())
        with patch("src.http_main.LlamaServer", return_value=runtime):
            run_http_worker(runtime.settings)
        self.assertEqual(runtime.calls, ["ensure_started", "wait", "stop"])

    def test_rejects_queue_settings(self):
        with patch.dict(os.environ, {"RUNPOD_WORKER_MODE": "queue"}, clear=False):
            settings = Settings.from_env()
        with self.assertRaisesRegex(ValueError, "RUNPOD_WORKER_MODE=http"):
            run_http_worker(settings)

    def test_stops_after_server_exit_failure(self):
        runtime = FakeRuntime(http_settings())
        runtime.wait = lambda: 1
        with patch("src.http_main.LlamaServer", return_value=runtime):
            with self.assertRaisesRegex(RuntimeError, "exited with code 1"):
                run_http_worker(runtime.settings)
        self.assertEqual(runtime.calls, ["ensure_started", "stop"])

    def test_main_dispatches_http_mode_without_registering_queue_handler(self):
        settings = http_settings()
        with patch("src.config.Settings.from_env", return_value=settings):
            with patch("src.http_main.run_http_worker") as run_http:
                worker_main.main()
        run_http.assert_called_once_with(settings)


if __name__ == "__main__":
    unittest.main()
