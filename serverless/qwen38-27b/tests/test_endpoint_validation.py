import unittest

from scripts.validate_endpoint import validate_endpoint


GPU = "NVIDIA GeForce RTX 4090"


def safe_endpoint(**overrides):
    document = {
        "id": "ep-1",
        "gpuCount": 1,
        "gpu": {"name": GPU, "memoryGb": 24},
        "workersMin": 0,
        "workersMax": 1,
        "executionTimeout": 180,
    }
    document.update(overrides)
    return document


class EndpointValidationTests(unittest.TestCase):
    def test_accepts_exact_single_gpu_with_scaling_and_timeout(self):
        validate_endpoint(safe_endpoint(), GPU)

    def test_accepts_memory_reported_in_megabytes(self):
        validate_endpoint(safe_endpoint(gpu={"name": GPU, "memoryMb": 24576}), GPU)

    def test_rejects_wrong_memory(self):
        with self.assertRaisesRegex(ValueError, "exactly 24 GB"):
            validate_endpoint(safe_endpoint(gpu={"name": GPU, "memoryGb": 48}), GPU)

    def test_rejects_non_finite_memory(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite"):
                    validate_endpoint(
                        safe_endpoint(gpu={"name": GPU, "memoryGb": value}), GPU
                    )

    def test_rejects_non_finite_gpu_count(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite"):
                    validate_endpoint(safe_endpoint(gpuCount=value), GPU)

    def test_rejects_mixed_gpu_records(self):
        document = safe_endpoint(
            gpus=[
                {"name": GPU, "memoryGb": 24},
                {"name": "NVIDIA L4", "memoryGb": 24},
            ]
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_endpoint(document, GPU)

    def test_rejects_gpu_count_above_one(self):
        with self.assertRaisesRegex(ValueError, "GPU count"):
            validate_endpoint(safe_endpoint(gpuCount=2), GPU)

    def test_rejects_missing_memory_in_gpu_payload(self):
        with self.assertRaisesRegex(ValueError, "no explicit memory"):
            validate_endpoint(safe_endpoint(gpu={"name": GPU}), GPU)

    def test_rejects_ambiguous_gpu_shape(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_endpoint(
                safe_endpoint(gpu=[GPU, {"name": GPU, "memoryGb": 24}]), GPU
            )

    def test_rejects_missing_worker_fields(self):
        document = safe_endpoint()
        del document["workersMax"]
        with self.assertRaisesRegex(ValueError, "workers maximum"):
            validate_endpoint(document, GPU)

    def test_rejects_unsafe_worker_scaling(self):
        with self.assertRaisesRegex(ValueError, "workers maximum"):
            validate_endpoint(safe_endpoint(workersMax=2), GPU)

    def test_rejects_missing_execution_timeout(self):
        document = safe_endpoint()
        del document["executionTimeout"]
        with self.assertRaisesRegex(ValueError, "execution timeout"):
            validate_endpoint(document, GPU)

    def test_rejects_unsafe_execution_timeout(self):
        with self.assertRaisesRegex(ValueError, "execution timeout"):
            validate_endpoint(safe_endpoint(executionTimeout=181), GPU)

    def test_update_preflight_can_repair_scaling_but_not_timeout(self):
        validate_endpoint(
            safe_endpoint(workersMin=1, workersMax=2),
            GPU,
            require_scaling=False,
        )
        with self.assertRaisesRegex(ValueError, "execution timeout"):
            validate_endpoint(
                safe_endpoint(
                    workersMin=1, workersMax=2, executionTimeout=181
                ),
                GPU,
                require_scaling=False,
            )


if __name__ == "__main__":
    unittest.main()
