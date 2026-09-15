"""Unit tests for Stage 2 Process pipeline stage."""

from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.convert import convert
from src.process import (
    get_sleep_duration,
    main,
    process,
    process_file,
    read_converted_file,
    write_metrics,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_METRIC_KEYS = {
    "input_file",
    "status",
    "start_time",
    "end_time",
    "duration_seconds",
    "row_count",
    "skipped_row_count",
}


class ProcessTests(unittest.TestCase):
    """Test suite for Stage 2 processing and execution metrics generation."""

    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.input_dir = self.root / "converted"
        self.input_dir.mkdir(parents=True)
        self.output_dir = self.root / "processed"

    def _create_sample_stage1_file(
        self,
        name: str = "variants_test.json",
        row_count: int = 4,
        skipped_rows: int = 1,
    ) -> Path:
        """Helper to create a standard Stage 1 JSON file."""
        file_path = self.input_dir / name
        payload = {
            "source_file": f"{Path(name).stem}.csv",
            "row_count": row_count,
            "skipped_rows": skipped_rows,
            "variants": [
                {
                    "index": f"chr1:{i * 10}_A/T",
                    "CHROM": "chr1",
                    "POS": i * 10,
                    "REF": "A",
                    "ALT": "T",
                }
                for i in range(1, row_count + 1)
            ],
        }
        file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return file_path

    def test_write_metrics_uses_shared_atomic_helper(self):
        """write_metrics is wired to the shared atomic writer: a write failure preserves output."""
        output_path = self.output_dir / "existing.json"
        self.output_dir.mkdir(parents=True)
        output_path.write_bytes(b"previous metrics\n")
        previous = output_path.read_bytes()

        with patch("src.json_io.tempfile.NamedTemporaryFile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_metrics(output_path, {"input_file": "existing.json", "status": "SUCCESS"})

        self.assertEqual(output_path.read_bytes(), previous)

    def test_standard_file_processing_content_and_schema(self):
        """Standard valid input produces metrics matching the required schema."""
        input_file = self._create_sample_stage1_file(
            "variants_sample.json", row_count=3, skipped_rows=2
        )

        metrics = process_file(input_file, self.output_dir, sleep_duration=0)

        output_file = self.output_dir / "variants_sample.json"
        self.assertTrue(output_file.is_file(), "Output metrics file should exist")

        persisted = json.loads(output_file.read_text(encoding="utf-8"))
        self.assertEqual(metrics, persisted)
        self.assertEqual(set(persisted.keys()), REQUIRED_METRIC_KEYS)

        self.assertEqual(persisted["input_file"], "variants_sample.json")
        self.assertEqual(persisted["status"], "SUCCESS")
        self.assertEqual(persisted["row_count"], 3)
        self.assertEqual(persisted["skipped_row_count"], 2)
        self.assertIsInstance(persisted["duration_seconds"], float)
        self.assertGreaterEqual(persisted["duration_seconds"], 0.0)

        # Verify timestamps are valid ISO 8601
        start = datetime.fromisoformat(persisted["start_time"])
        end = datetime.fromisoformat(persisted["end_time"])
        self.assertGreaterEqual(end, start)

    def test_sleep_duration_from_env_override(self):
        """PROCESS_SLEEP_SECONDS controls delay and defaults to 30s."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_sleep_duration(), 30.0)

        with patch.dict(os.environ, {"PROCESS_SLEEP_SECONDS": "0"}):
            self.assertEqual(get_sleep_duration(), 0.0)

        with patch.dict(os.environ, {"PROCESS_SLEEP_SECONDS": "0.25"}):
            self.assertEqual(get_sleep_duration(), 0.25)

        with patch.dict(os.environ, {"PROCESS_SLEEP_SECONDS": "invalid"}):
            with self.assertRaises(ValueError):
                get_sleep_duration()

        with patch.dict(os.environ, {"PROCESS_SLEEP_SECONDS": "-5"}):
            with self.assertRaises(ValueError):
                get_sleep_duration()

    def test_simulated_compute_calls_sleep(self):
        """Process simulates compute by calling time.sleep with the specified duration."""
        input_file = self._create_sample_stage1_file("variants_sleep.json")
        with patch("time.sleep") as mock_sleep:
            process_file(input_file, self.output_dir, sleep_duration=12.5)
            mock_sleep.assert_called_once_with(12.5)

    def test_corrupted_json_input_writes_failed_metrics_without_crash(self):
        """Corrupted JSON logs informative error to stdout and produces FAILED metrics."""
        corrupt_file = self.input_dir / "corrupted.json"
        corrupt_file.write_text("{ unclosed json content", encoding="utf-8")

        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            metrics = process_file(corrupt_file, self.output_dir, sleep_duration=0)

        self.assertEqual(metrics["status"], "FAILED")
        self.assertEqual(metrics["row_count"], 0)
        self.assertEqual(metrics["skipped_row_count"], 0)
        self.assertEqual(metrics["input_file"], "corrupted.json")
        self.assertIn("ERROR: Failed processing corrupted.json", stdout_capture.getvalue())

        output_file = self.output_dir / "corrupted.json"
        self.assertTrue(output_file.exists())
        persisted = json.loads(output_file.read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "FAILED")

    def test_missing_input_file_handling(self):
        """Processing a missing input file produces FAILED metrics gracefully."""
        nonexistent = self.input_dir / "missing.json"

        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            metrics = process_file(nonexistent, self.output_dir, sleep_duration=0)

        self.assertEqual(metrics["status"], "FAILED")
        self.assertIn("ERROR: Failed processing missing.json", stdout_capture.getvalue())

    def test_batch_processing_resilience(self):
        """Batch continues processing all files even if one fails."""
        self._create_sample_stage1_file("1_valid.json", row_count=10)
        corrupt = self.input_dir / "2_corrupt.json"
        corrupt.write_text("not json", encoding="utf-8")
        self._create_sample_stage1_file("3_valid.json", row_count=20)

        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            results = process(self.input_dir, self.output_dir, sleep_duration=0)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["row_count"], 10)
        self.assertEqual(results[1]["status"], "FAILED")
        self.assertEqual(results[2]["status"], "SUCCESS")
        self.assertEqual(results[2]["row_count"], 20)

    def test_idempotency_clean_overwrites(self):
        """Rerunning process cleanly overwrites existing outputs without corruption."""
        self._create_sample_stage1_file("sample_a.json", row_count=5, skipped_rows=1)
        self._create_sample_stage1_file("sample_b.json", row_count=8, skipped_rows=0)

        first_results = process(self.input_dir, self.output_dir, sleep_duration=0)
        first_files = sorted(self.output_dir.iterdir())
        self.assertEqual(len(first_files), 2)

        # Modify output to test overwrite
        (self.output_dir / "sample_a.json").write_text("corrupted existing", encoding="utf-8")

        second_results = process(self.input_dir, self.output_dir, sleep_duration=0)
        second_files = sorted(self.output_dir.iterdir())

        self.assertEqual(len(second_files), 2)
        for r1, r2 in zip(first_results, second_results):
            self.assertEqual(r1["input_file"], r2["input_file"])
            self.assertEqual(r1["status"], r2["status"])
            self.assertEqual(r1["row_count"], r2["row_count"])
            self.assertEqual(r1["skipped_row_count"], r2["skipped_row_count"])

        # Ensure no leftover temporary files
        all_names = [f.name for f in self.output_dir.iterdir()]
        self.assertTrue(all(name.endswith(".json") and not name.endswith(".tmp") for name in all_names))

    def test_cli_execution_success_and_failures(self):
        """CLI main returns expected exit codes for success, errors, and invalid args."""
        self._create_sample_stage1_file("cli_sample.json")

        # Success run with sleep override
        code = main([
            "--input-dir", str(self.input_dir),
            "--output-dir", str(self.output_dir),
            "--sleep-seconds", "0",
        ])
        self.assertEqual(code, 0)

        # Missing input directory returns 1
        code_missing = main([
            "--input-dir", str(self.root / "nonexistent"),
            "--output-dir", str(self.output_dir),
        ])
        self.assertEqual(code_missing, 1)

        # Invalid sleep seconds returns 2
        code_invalid_sleep = main([
            "--input-dir", str(self.input_dir),
            "--output-dir", str(self.output_dir),
            "--sleep-seconds", "-1",
        ])
        self.assertEqual(code_invalid_sleep, 2)

    def test_mixed_success_and_failure_continues_batch(self):
        """Mixed SUCCESS/FAILED outcomes still let the batch complete."""
        self._create_sample_stage1_file("good_a.json", row_count=2, skipped_rows=0)
        (self.input_dir / "corrupt.json").write_text("not json", encoding="utf-8")
        self._create_sample_stage1_file("good_b.json", row_count=3, skipped_rows=1)

        results = process(self.input_dir, self.output_dir, sleep_duration=0)

        statuses = {r["input_file"]: r["status"] for r in results}
        self.assertEqual(statuses, {
            "good_a.json": "SUCCESS", "corrupt.json": "FAILED", "good_b.json": "SUCCESS",
        })

    def test_all_files_failing_raises_value_error(self):
        """A batch where every file fails raises ValueError instead of a quiet success."""
        (self.input_dir / "bad_a.json").write_text("not json", encoding="utf-8")
        (self.input_dir / "bad_b.json").write_text("{}", encoding="utf-8")  # missing row_count

        with self.assertRaises(ValueError):
            process(self.input_dir, self.output_dir, sleep_duration=0)

        # Individual FAILED records are still written for inspection.
        self.assertEqual({p.name for p in self.output_dir.iterdir()}, {"bad_a.json", "bad_b.json"})

    def test_empty_input_directory_raises_value_error(self):
        """An existing input directory with no eligible *.json files fails the stage."""
        with self.assertRaises(ValueError):
            process(self.input_dir, self.output_dir, sleep_duration=0)
        self.assertFalse(self.output_dir.exists())

    def test_unexpected_error_propagates_instead_of_becoming_failed(self):
        """A programming-error-shaped exception is not disguised as an input failure."""
        self._create_sample_stage1_file("sample.json")
        with patch("src.process.read_converted_file", side_effect=TypeError("boom")):
            with self.assertRaises(TypeError):
                process(self.input_dir, self.output_dir, sleep_duration=0)

    def test_output_write_failure_propagates_after_earlier_success(self):
        """An output-write failure is fatal immediately, not recorded as a FAILED result."""
        self._create_sample_stage1_file("first.json")
        self._create_sample_stage1_file("second.json")
        real_write_metrics = write_metrics

        def fail_on_second(output_path, metrics):
            if output_path.name == "second.json":
                raise OSError("disk full")
            real_write_metrics(output_path, metrics)

        with patch("src.process.write_metrics", side_effect=fail_on_second):
            with self.assertRaises(OSError):
                process(self.input_dir, self.output_dir, sleep_duration=0)

        self.assertTrue((self.output_dir / "first.json").exists())
        self.assertFalse((self.output_dir / "second.json").exists())

    def test_end_to_end_integration_with_stage1_convert(self):
        """Stage 2 successfully consumes actual output from Stage 1 Convert."""
        sample_csv = PROJECT_ROOT / "input" / "variants_1.csv"
        csv_dir = self.root / "csv_input"
        csv_dir.mkdir()
        import shutil
        shutil.copyfile(sample_csv, csv_dir / "variants_1.csv")

        # Run Stage 1 Convert
        convert(csv_dir, self.input_dir)

        # Run Stage 2 Process
        results = process(self.input_dir, self.output_dir, sleep_duration=0)

        self.assertEqual(len(results), 1)
        metrics = results[0]
        self.assertEqual(metrics["input_file"], "variants_1.json")
        self.assertEqual(metrics["status"], "SUCCESS")
        self.assertEqual(metrics["row_count"], 30)
        self.assertEqual(metrics["skipped_row_count"], 0)


if __name__ == "__main__":
    unittest.main()
