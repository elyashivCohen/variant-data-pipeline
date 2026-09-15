"""Unit tests for Stage 3 Aggregate pipeline stage."""

import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from src.aggregate import (
    aggregate,
    count_variants_by_chromosome,
    main,
    read_process_results,
    write_summary,
)
from src.convert import convert
from src.process import process, process_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class AggregateTests(unittest.TestCase):
    """Test suite for Stage 3 aggregation of Convert and Process outputs."""

    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.csv_dir = self.root / "csv"
        self.csv_dir.mkdir()
        self.convert_dir = self.root / "converted"
        self.process_dir = self.root / "processed"

    def _build_pipeline(self, fixture_names):
        """Run real Convert then Process over the given fixture CSVs, sleep_duration=0."""
        for name in fixture_names:
            shutil.copyfile(FIXTURES / name, self.csv_dir / name)
        convert(self.csv_dir, self.convert_dir)
        return process(self.convert_dir, self.process_dir, sleep_duration=0)

    def test_write_summary_uses_shared_atomic_helper(self):
        """write_summary is wired to the shared atomic writer: a write failure preserves output."""
        output_path = self.root / "output" / "summary.json"
        output_path.parent.mkdir(parents=True)
        output_path.write_bytes(b"previous summary\n")
        previous = output_path.read_bytes()

        with patch("src.json_io.tempfile.NamedTemporaryFile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_summary(output_path, {"total_variant_count": 0})

        self.assertEqual(output_path.read_bytes(), previous)

    def test_aggregation_across_multiple_files(self):
        """Chromosome counts, totals, and file list are correct across two valid files."""
        self._build_pipeline(["variants_clean.csv", "variants_messy.csv"])

        summary = aggregate(self.convert_dir, self.process_dir)

        # variants_clean.csv: chr1, chr2, chr3, chr12, chrY, chrX (6 variants, 0 skipped)
        # variants_messy.csv: chr1, chrY, chrX accepted; 3 rows skipped
        self.assertEqual(summary["variant_counts_by_chromosome"], {
            "chr1": 2, "chr12": 1, "chr2": 1, "chr3": 1, "chrX": 2, "chrY": 2,
        })
        self.assertEqual(summary["total_variant_count"], 9)
        self.assertEqual(summary["total_skipped_rows"], 3)
        self.assertIsInstance(summary["total_processing_time_seconds"], float)
        self.assertGreaterEqual(summary["total_processing_time_seconds"], 0.0)
        self.assertEqual(
            summary["input_files_processed"],
            ["variants_clean.json", "variants_messy.json"],
        )

    def test_skipped_rows_from_malformed_file_contribute_to_total(self):
        """A file with skipped/malformed rows still contributes its skipped count."""
        self._build_pipeline(["one_invalid_row.csv"])

        summary = aggregate(self.convert_dir, self.process_dir)

        # one_invalid_row.csv: chr1 and chrX accepted, 1 row skipped (bad POS)
        self.assertEqual(summary["total_skipped_rows"], 1)
        self.assertEqual(summary["variant_counts_by_chromosome"], {"chr1": 1, "chrX": 1})
        self.assertEqual(summary["total_variant_count"], 2)

    def test_failed_process_file_excluded_from_variant_counts_but_listed(self):
        """A FAILED Stage 2 file is listed as processed but excluded from variant counts."""
        self._build_pipeline(["variants_clean.csv"])

        # Simulate a second file that Process attempted but failed on (e.g. missing Convert
        # output); its Convert counterpart is never created, so Stage 3 must not try to read it.
        missing_convert_file = self.convert_dir / "ghost.json"
        failed_metrics = process_file(missing_convert_file, self.process_dir, sleep_duration=0)
        self.assertEqual(failed_metrics["status"], "FAILED")

        summary = aggregate(self.convert_dir, self.process_dir)

        self.assertIn("ghost.json", summary["input_files_processed"])
        self.assertEqual(len(summary["input_files_processed"]), 2)
        # Only the successful file's chromosomes are counted.
        self.assertEqual(summary["variant_counts_by_chromosome"], {
            "chr1": 1, "chr12": 1, "chr2": 1, "chr3": 1, "chrX": 1, "chrY": 1,
        })
        self.assertEqual(summary["total_variant_count"], 6)
        # The FAILED file contributes 0 skipped rows but nonzero (or zero) duration.
        self.assertEqual(summary["total_skipped_rows"], 0)

    def test_convert_output_with_no_process_outcome_fails(self):
        """A Convert output that Process never even attempted fails aggregation."""
        self._build_pipeline(["variants_clean.csv"])
        # An extra Convert output with no corresponding Process attempt at all -
        # e.g. Process was pointed at a different/stale directory pairing.
        extra = self.convert_dir / "extra.json"
        extra.write_text(json.dumps({
            "source_file": "extra.csv", "row_count": 0, "skipped_rows": 0, "variants": [],
        }), encoding="utf-8")

        with self.assertRaises(ValueError) as error:
            aggregate(self.convert_dir, self.process_dir)
        self.assertIn("extra.json", str(error.exception))

    def test_matching_failed_outcome_satisfies_completeness(self):
        """A Convert output with a matching FAILED Process outcome is not treated as missing."""
        self._build_pipeline(["variants_clean.csv"])
        # Corrupt the Convert output so Process rejects it, while the file itself
        # still exists in convert_dir - a genuine matched pair, just a FAILED one.
        converted = self.convert_dir / "variants_clean.json"
        converted.write_text(json.dumps({"source_file": "variants_clean.csv"}), encoding="utf-8")
        failed = process_file(converted, self.process_dir, sleep_duration=0)
        self.assertEqual(failed["status"], "FAILED")

        summary = aggregate(self.convert_dir, self.process_dir)

        self.assertEqual(summary["input_files_processed"], ["variants_clean.json"])
        self.assertEqual(summary["variant_counts_by_chromosome"], {})
        self.assertEqual(summary["total_variant_count"], 0)

    def test_idempotent_rerun_produces_identical_summary(self):
        """Running aggregation twice on unchanged inputs yields an identical summary file."""
        self._build_pipeline(["variants_clean.csv", "variants_messy.csv"])
        output_file = self.root / "output" / "summary.json"

        exit_code_1 = main([
            "--convert-dir", str(self.convert_dir),
            "--process-dir", str(self.process_dir),
            "--output-file", str(output_file),
        ])
        first_content = output_file.read_text(encoding="utf-8")

        exit_code_2 = main([
            "--convert-dir", str(self.convert_dir),
            "--process-dir", str(self.process_dir),
            "--output-file", str(output_file),
        ])
        second_content = output_file.read_text(encoding="utf-8")

        self.assertEqual(exit_code_1, 0)
        self.assertEqual(exit_code_2, 0)
        self.assertEqual(first_content, second_content)

    def test_missing_process_dir_fails_clearly(self):
        """A missing Process directory raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            aggregate(self.convert_dir, self.process_dir)

    def test_empty_process_dir_fails_clearly(self):
        """An existing but empty Process directory raises ValueError."""
        self.process_dir.mkdir()
        with self.assertRaises(ValueError):
            read_process_results(self.process_dir)

    def test_missing_convert_dir_fails_clearly(self):
        """A missing Convert directory raises FileNotFoundError."""
        self.process_dir.mkdir()
        (self.process_dir / "x.json").write_text(json.dumps({
            "input_file": "x.json", "status": "SUCCESS", "start_time": "t", "end_time": "t",
            "duration_seconds": 0.0, "row_count": 0, "skipped_row_count": 0,
        }), encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            aggregate(self.convert_dir, self.process_dir)

    def test_success_file_without_matching_convert_output_fails_clearly(self):
        """A SUCCESS record with no matching Convert file raises FileNotFoundError."""
        self.convert_dir.mkdir()
        with self.assertRaises(FileNotFoundError):
            count_variants_by_chromosome(self.convert_dir, ["nonexistent.json"])

    def test_cli_exit_codes(self):
        """CLI main returns 0 on success and 1 on aggregation failure."""
        self._build_pipeline(["variants_clean.csv"])
        output_file = self.root / "output" / "summary.json"

        code_success = main([
            "--convert-dir", str(self.convert_dir),
            "--process-dir", str(self.process_dir),
            "--output-file", str(output_file),
        ])
        self.assertEqual(code_success, 0)
        self.assertTrue(output_file.is_file())

        code_missing = main([
            "--convert-dir", str(self.convert_dir),
            "--process-dir", str(self.root / "nonexistent"),
            "--output-file", str(output_file),
        ])
        self.assertEqual(code_missing, 1)

    def test_cli_catches_output_write_failure_without_a_raw_traceback(self):
        """A write failure after a successful aggregation is caught at the CLI boundary, not raised."""
        # main() reconfigures the logger's handlers on every call, which also
        # replaces any handler assertLogs attaches beforehand - so this checks
        # the actual console stream main() writes to (stdout), matching the
        # pattern used for the equivalent Convert test.
        self._build_pipeline(["variants_clean.csv"])
        output_file = self.root / "output" / "summary.json"
        stdout_capture = io.StringIO()

        with patch("src.json_io.tempfile.NamedTemporaryFile", side_effect=OSError("disk full")):
            with patch("sys.stdout", stdout_capture):
                code = main([
                    "--convert-dir", str(self.convert_dir),
                    "--process-dir", str(self.process_dir),
                    "--output-file", str(output_file),
                ])

        output = stdout_capture.getvalue()
        self.assertEqual(code, 1)
        self.assertEqual(output.count("ERROR:"), 1)
        self.assertIn("ERROR: Aggregation failed", output)
        self.assertNotIn("Traceback (most recent call last)", output)

    def test_log_file_appends_across_reruns_and_fails_clearly_when_unopenable(self):
        """--log-file records timestamped entries, appends on rerun, and fails clearly if unopenable."""
        self._build_pipeline(["variants_clean.csv"])
        output_file = self.root / "output" / "summary.json"
        log_file = self.root / "logs" / "aggregate.log"
        run_args = ["--convert-dir", str(self.convert_dir), "--process-dir", str(self.process_dir),
                    "--output-file", str(output_file), "--log-file", str(log_file)]

        self.assertEqual(main(run_args), 0)
        self.assertEqual(main(run_args), 0)

        content = log_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("Aggregate stage starting"), 2)
        self.assertRegex(content, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO src\.aggregate:")

        blocked = self.root / "blocked"
        blocked.write_text("occupies the path a log directory would need", encoding="utf-8")
        code = main(["--convert-dir", str(self.convert_dir), "--process-dir", str(self.process_dir),
                     "--output-file", str(output_file), "--log-file", str(blocked / "aggregate.log")])
        self.assertEqual(code, 2)

    def test_end_to_end_with_original_samples(self):
        """Aggregate consumes real Convert+Process output from the original sample CSVs."""
        sample_dir = PROJECT_ROOT / "input"
        for csv_file in sorted(sample_dir.glob("*.csv")):
            shutil.copyfile(csv_file, self.csv_dir / csv_file.name)
        convert(self.csv_dir, self.convert_dir)
        process(self.convert_dir, self.process_dir, sleep_duration=0)

        summary = aggregate(self.convert_dir, self.process_dir)

        self.assertEqual(len(summary["input_files_processed"]), 5)
        self.assertEqual(
            summary["total_variant_count"], sum(summary["variant_counts_by_chromosome"].values())
        )


if __name__ == "__main__":
    unittest.main()
