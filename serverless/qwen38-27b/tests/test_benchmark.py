import subprocess
import sys
import unittest
import json
from unittest.mock import patch

from scripts.benchmark import preflight_endpoint, run_benchmark_jobs


class BenchmarkGuardTests(unittest.TestCase):
    def run_benchmark(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/benchmark.py", "endpoint", *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_default_requires_billing_confirmation_without_submitting(self):
        result = self.run_benchmark()
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing to submit jobs", result.stderr)

    def test_request_count_has_low_hard_cap(self):
        result = self.run_benchmark("--requests", "4")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("between 1 and 3", result.stderr)

    def test_wait_cannot_exceed_endpoint_timeout(self):
        result = self.run_benchmark("--wait-seconds", "181")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("between 1 and 180", result.stderr)

    def test_wait_cannot_exceed_total_budget(self):
        result = self.run_benchmark(
            "--wait-seconds", "90", "--total-timeout-seconds", "30"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not exceed", result.stderr)

    def test_preflight_rejects_unsafe_endpoint(self):
        endpoint = {
            "gpu": {"name": "NVIDIA GeForce RTX 4090", "memoryGb": 24},
            "workersMin": 0,
            "workersMax": 1,
            "executionTimeout": 181,
        }
        completed = subprocess.CompletedProcess(
            ["runpodctl"], 0, stdout=json.dumps(endpoint), stderr=""
        )
        with patch("scripts.benchmark.subprocess.run", return_value=completed) as run:
            with self.assertRaisesRegex(RuntimeError, "execution timeout"):
                preflight_endpoint("endpoint")
        command = run.call_args.args[0]
        self.assertEqual(command[2:4], ["get", "endpoint"])
        self.assertIn("--include-template", command)
        self.assertIn("--include-workers", command)

    def test_preflights_before_every_billed_submission(self):
        completed = subprocess.CompletedProcess(
            ["runpodctl"], 0, stdout='{"ok": true}', stderr=""
        )
        with patch("scripts.benchmark.preflight_endpoint") as preflight, patch(
            "scripts.benchmark.subprocess.run", return_value=completed
        ) as run:
            with patch(
                "scripts.benchmark.time.monotonic",
                side_effect=[0, 0, 0, 1, 1, 1, 2, 2, 2],
            ):
                exit_code, results = run_benchmark_jobs(
                    "endpoint", 2, 8, "ping", 10, 20
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(results), 2)
        self.assertEqual(preflight.call_count, 2)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertIn("run", call.args[0])

    def test_second_job_is_not_submitted_after_preflight_rejection(self):
        completed = subprocess.CompletedProcess(
            ["runpodctl"], 0, stdout='{"ok": true}', stderr=""
        )
        with patch(
            "scripts.benchmark.preflight_endpoint",
            side_effect=[None, RuntimeError("unsafe endpoint")],
        ) as preflight, patch(
            "scripts.benchmark.subprocess.run", return_value=completed
        ) as run:
            with patch(
                "scripts.benchmark.time.monotonic",
                side_effect=[0, 0, 0, 1, 1, 1],
            ):
                exit_code, results = run_benchmark_jobs(
                    "endpoint", 2, 8, "ping", 10, 20
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(preflight.call_count, 2)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
