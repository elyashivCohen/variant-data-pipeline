import csv
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.convert import ConversionError, convert, main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FINAL_VARIANT = {"index": "chrX:60_A/T", "CHROM": "chrX", "POS": 60, "REF": "A", "ALT": "T"}
CLEAN_VARIANTS = [
    {"index": "chr1:10_G/T", "CHROM": "chr1", "POS": 10, "REF": "G", "ALT": "T"},
    {"index": "chr2:20_ATCG/T", "CHROM": "chr2", "POS": 20, "REF": "ATCG", "ALT": "T"},
    {"index": "chr3:30_A/GCAT", "CHROM": "chr3", "POS": 30, "REF": "A", "ALT": "GCAT"},
    {"index": "chr12:40_GAAGTC/G", "CHROM": "chr12", "POS": 40, "REF": "GAAGTC", "ALT": "G"},
    {"index": "chrY:50_C/G", "CHROM": "chrY", "POS": 50, "REF": "C", "ALT": "G"},
    FINAL_VARIANT,
]


class ConvertTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.input_dir = self.root / "input"
        self.input_dir.mkdir()
        self.output_dir = self.root / "converted"
        self.output = self.output_dir / "result.json"

    def copy_fixture(self, name, target_name=None):
        path = self.input_dir / (target_name or name)
        shutil.copyfile(FIXTURES / name, path)
        self.output = self.output_dir / (path.stem + ".json")
        return path

    def assert_payload(self, source, variants, skipped):
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), {
            "source_file": source.name, "row_count": len(variants),
            "skipped_rows": skipped, "variants": variants,
        }, f"Unexpected JSON records or counts for {source.name}")

    def prepare_existing_output(self):
        self.output_dir.mkdir(exist_ok=True)
        self.output.write_bytes(b"previous output\n")
        return self.output.read_bytes()

    def test_valid_fixture_convert_returns_full_json_in_order(self):
        """Valid CSV produces the expected JSON."""
        source = self.copy_fixture("variants_clean.csv")
        with self.assertLogs("src.convert", level="INFO") as logs:
            self.assertEqual(convert(self.input_dir, self.output_dir), [self.output])
        self.assert_payload(source, CLEAN_VARIANTS, 0)
        payload = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertTrue(all(type(row["POS"]) is int for row in payload["variants"]))
        self.assertEqual([record.levelno for record in logs.records], [logging.INFO])
        self.assertIn("wrote 6 records; skipped 0", logs.output[0])
        self.assertEqual(list(self.output_dir.iterdir()), [self.output])

    def test_invalid_row_warns_and_convert_continues(self):
        """Invalid row logs a warning and is skipped."""
        source = self.copy_fixture("one_invalid_row.csv")
        with self.assertLogs("src.convert", level="WARNING") as logs:
            outputs = convert(self.input_dir, self.output_dir)
        self.assertEqual(outputs, [self.output])
        self.assert_payload(source, [CLEAN_VARIANTS[0], FINAL_VARIANT], 1)
        self.assertEqual(logs.output, [
            f"WARNING:src.convert:{source}: line 3: skipped record: POS must be a positive integer"
        ])

    def test_multiple_invalid_rows_warn_and_convert_continues(self):
        """Multiple invalid rows warn and valid records are retained."""
        cases = [
            ("variants_messy.csv", [CLEAN_VARIANTS[0], CLEAN_VARIANTS[4], FINAL_VARIANT],
             [3, 4, 6], ["index", "POS", "ALT"]),
            ("missing_values.csv", [FINAL_VARIANT], [2, 3, 4, 5, 6],
             ["index", "CHROM", "POS", "REF", "ALT"]),
            ("invalid_pos.csv", [FINAL_VARIANT], [2, 3, 4], ["POS"] * 3),
            ("wrong_field_counts.csv", [FINAL_VARIANT], [2, 3, 4], ["field count"] * 3),
        ]
        for name, variants, lines, reasons in cases:
            with self.subTest(fixture=name):
                source = self.copy_fixture(name)
                with self.assertLogs("src.convert", level="WARNING") as logs:
                    outputs = convert(self.input_dir, self.output_dir)
                self.assertEqual(outputs, [self.output])
                self.assert_payload(source, variants, len(lines))
                self.assertEqual(len(logs.records), len(lines))
                for record, line, reason in zip(logs.records, lines, reasons):
                    self.assertEqual(record.levelno, logging.WARNING)
                    self.assertIn(f"{source}: line {line}: skipped record:", record.getMessage())
                    self.assertIn(reason, record.getMessage())
                source.unlink()
                self.output.unlink()

    def test_normalized_reordered_extra_headers_and_bom(self):
        """Normalized headers and UTF-8 BOM are accepted."""
        source = self.copy_fixture("normalized_header.csv")
        self.assertTrue(source.read_bytes().startswith(b"\xef\xbb\xbf"))
        with self.assertLogs("src.convert", level="INFO") as logs:
            convert(self.input_dir, self.output_dir)
        self.assert_payload(source, [FINAL_VARIANT], 0)
        self.assertTrue(all(record.levelno == logging.INFO for record in logs.records))

    def test_missing_header_makes_convert_raise_conversion_error(self):
        """Missing or duplicate headers raise ConversionError."""
        for name in ("missing_header.csv", "duplicate_header.csv"):
            with self.subTest(fixture=name):
                source = self.copy_fixture(name)
                with self.assertRaises(ConversionError):
                    convert(self.input_dir, self.output_dir)
                self.assertFalse(self.output.exists())
                previous = self.prepare_existing_output()
                with self.assertRaises(ConversionError) as error:
                    convert(self.input_dir, self.output_dir)
                self.assertIn(str(source), str(error.exception))
                self.assertEqual(self.output.read_bytes(), previous)
                self.assertEqual(list(self.output_dir.iterdir()), [self.output])
                source.unlink()
                self.output.unlink()

    def test_empty_file_fails_without_creating_output(self):
        """An empty CSV raises ConversionError without output."""
        source = self.input_dir / "empty.csv"
        source.write_bytes(b"")
        with self.assertRaises(ConversionError):
            convert(self.input_dir, self.output_dir)
        self.assertFalse(self.output_dir.exists())

    def test_zero_variant_outputs(self):
        """Header-only and all-invalid CSV files produce zero-variant JSON."""
        for name, skipped in (("header_only.csv", 0), ("all_invalid.csv", 1)):
            with self.subTest(fixture=name):
                source = self.copy_fixture(name)
                with self.assertLogs("src.convert", level="INFO") as logs:
                    outputs = convert(self.input_dir, self.output_dir)
                self.assertEqual(outputs, [self.output])
                self.assert_payload(source, [], skipped)
                self.assertEqual(sum(record.levelno == logging.WARNING for record in logs.records), skipped)
                source.unlink()
                self.output.unlink()

    def test_malformed_csv_makes_convert_raise_csv_error(self):
        """Malformed CSV raises csv.Error and preserves output."""
        for name, line in (("bad_quote.csv", 2), ("unterminated_quote.csv", 3)):
            with self.subTest(fixture=name):
                source = self.copy_fixture(name)
                with self.assertRaises(csv.Error):
                    convert(self.input_dir, self.output_dir)
                self.assertFalse(self.output.exists())
                previous = self.prepare_existing_output()
                with self.assertRaises(csv.Error) as error:
                    convert(self.input_dir, self.output_dir)
                self.assertIn(f"{source}: line {line}:", str(error.exception))
                self.assertEqual(self.output.read_bytes(), previous)
                self.assertEqual(list(self.output_dir.iterdir()), [self.output])
                source.unlink()
                self.output.unlink()

    def test_warning_uses_starting_physical_line_after_multiline_record(self):
        """Warnings identify the starting physical line after multiline records."""
        source = self.input_dir / "multiline.csv"
        self.output = self.output_dir / "multiline.json"
        with source.open("w", encoding="utf-8", newline="") as stream:
            stream.write('index,CHROM,POS,REF,ALT\n"two\nlines",chr1,10,A,T\nid,chr1,bad,A,T\n')
        with self.assertLogs("src.convert", level="WARNING") as logs:
            convert(self.input_dir, self.output_dir)
        self.assertEqual(len(logs.records), 1)
        self.assertIn(f"{source}: line 4:", logs.records[0].getMessage())
        self.assert_payload(source, [{"index": "two\nlines", "CHROM": "chr1", "POS": 10, "REF": "A", "ALT": "T"}], 1)

    def test_original_samples_convert_returns_sorted_outputs_and_counts(self):
        """Original samples produce sorted outputs with expected counts."""
        originals = {}
        for number in range(1, 6):
            source = PROJECT_ROOT / "input" / f"variants_{number}.csv"
            originals[source] = source.read_bytes()
            shutil.copyfile(source, self.input_dir / source.name)
        with self.assertLogs("src.convert", level="INFO"):
            outputs = convert(self.input_dir, self.output_dir)
        self.assertEqual(outputs, [
            self.output_dir / f"variants_{number}.json" for number in range(1, 6)
        ])
        for output, count in zip(outputs, (30, 25, 25, 28, 53)):
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_file"], output.stem + ".csv")
            self.assertEqual(payload["row_count"], count)
            self.assertEqual(payload["skipped_rows"], 0)
            self.assertEqual(len(payload["variants"]), count)
            self.assertTrue(all(type(row["POS"]) is int for row in payload["variants"]))
        for source, original in originals.items():
            self.assertEqual(source.read_bytes(), original)

    def test_batch_reruns_are_identical(self):
        """Repeated conversion safely produces identical outputs."""
        self.copy_fixture("variants_messy.csv")
        self.copy_fixture("variants_clean.csv")
        with self.assertLogs("src.convert", level="WARNING") as first_logs:
            outputs = convert(self.input_dir, self.output_dir)
        previous = [path.read_bytes() for path in outputs]
        with self.assertLogs("src.convert", level="WARNING") as second_logs:
            self.assertEqual(convert(self.input_dir, self.output_dir), outputs)
        self.assertEqual([path.name for path in outputs], ["variants_clean.json", "variants_messy.json"])
        self.assertEqual([path.read_bytes() for path in outputs], previous)
        self.assertEqual(len(first_logs.records), 3)
        self.assertEqual(len(second_logs.records), 3)
        self.assertEqual(sorted(self.output_dir.iterdir()), outputs)

    def test_batch_stops_at_first_file_failure(self):
        """A batch stops at the first file failure."""
        self.copy_fixture("variants_clean.csv", "a.csv")
        self.copy_fixture("missing_header.csv", "b.csv")
        self.copy_fixture("variants_clean.csv", "c.csv")
        with self.assertRaises(ConversionError):
            convert(self.input_dir, self.output_dir)
        self.assertEqual([path.name for path in self.output_dir.iterdir()], ["a.json"])

    def test_missing_input_or_empty_batch(self):
        """Missing input or an empty batch raises ConversionError."""
        for directory in (self.root / "missing", self.input_dir):
            with self.subTest(directory=directory), self.assertRaises(ConversionError):
                convert(directory, self.output_dir)
        self.assertFalse(self.output_dir.exists())

    def test_invalid_utf8_preserves_output(self):
        """Invalid UTF-8 preserves existing output."""
        source = self.input_dir / "encoding.csv"
        self.output = self.output_dir / "encoding.json"
        source.write_bytes(b"index,CHROM,POS,REF,ALT\n\xff,chr1,10,A,T\n")
        previous = self.prepare_existing_output()
        with self.assertRaises(UnicodeError):
            convert(self.input_dir, self.output_dir)
        self.assertEqual(self.output.read_bytes(), previous)

    def test_output_symlink_to_input_makes_convert_raise_conversion_error(self):
        """Symbolic-link protection rejects overwriting input."""
        source = self.copy_fixture("variants_clean.csv")
        original = source.read_bytes()
        self.output_dir.mkdir()
        try:
            self.output.symlink_to(source)
        except OSError as error:
            self.skipTest(f"Symbolic links unavailable: {error}")
        with self.assertRaises(ConversionError):
            convert(self.input_dir, self.output_dir)
        self.assertEqual(source.read_bytes(), original)
        self.assertTrue(self.output.is_symlink())

    def test_output_hard_link_to_input_makes_convert_raise_conversion_error(self):
        """Hard-link protection rejects overwriting input."""
        source = self.copy_fixture("variants_clean.csv")
        self.output_dir.mkdir()
        try:
            os.link(source, self.output)
        except OSError as error:
            self.skipTest(f"Hard links unavailable: {error}")
        original = source.read_bytes()
        with self.assertRaises(ConversionError):
            convert(self.input_dir, self.output_dir)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.output.read_bytes(), original)

    def test_read_permission_failure_preserves_output(self):
        """Read permission failure preserves existing output."""
        source = self.copy_fixture("variants_clean.csv")
        previous = self.prepare_existing_output()
        with patch.object(Path, "open", side_effect=PermissionError("read denied")):
            with self.assertRaises(PermissionError):
                convert(self.input_dir, self.output_dir)
        self.assertEqual(self.output.read_bytes(), previous)

    def test_output_creation_failures_preserve_output(self):
        """Output creation failures preserve existing output."""
        source = self.copy_fixture("variants_clean.csv")
        previous = self.prepare_existing_output()
        for target in ("src.convert.Path.mkdir", "src.convert.tempfile.NamedTemporaryFile"):
            with self.subTest(target=target):
                with patch(target, side_effect=PermissionError("creation denied")):
                    with self.assertRaises(PermissionError):
                        convert(self.input_dir, self.output_dir)
                self.assertEqual(self.output.read_bytes(), previous)
                self.assertEqual(list(self.output_dir.iterdir()), [self.output])

    def test_partial_write_failure_preserves_output_and_cleans_temp(self):
        """Partial writes preserve output and clean temporary files."""
        source = self.copy_fixture("variants_clean.csv")
        previous = self.prepare_existing_output()
        original_error = OSError("disk full")
        real_temporary_file = tempfile.NamedTemporaryFile

        def failing_temporary_file(*args, **kwargs):
            destination = real_temporary_file(*args, **kwargs)
            real_write = destination.write

            def partial_write(text):
                real_write(text[:10])
                destination.flush()
                raise original_error

            destination.write = partial_write
            return destination

        with patch("src.convert.tempfile.NamedTemporaryFile", side_effect=failing_temporary_file):
            with self.assertRaises(OSError) as error:
                convert(self.input_dir, self.output_dir)
        self.assertIs(error.exception, original_error)
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(list(self.output_dir.iterdir()), [self.output])

    def test_replacement_failure_cleans_unique_temps_and_preserves_unrelated_file(self):
        """Replacement failure cleans temporary files and preserves unrelated files."""
        source = self.copy_fixture("variants_clean.csv")
        previous = self.prepare_existing_output()
        unrelated = self.output.with_suffix(".json.tmp")
        unrelated.write_bytes(b"unrelated")
        temporary_paths = []

        def fail_replacement(temporary_path, output_path):
            self.assertEqual(temporary_path.parent, self.output_dir)
            self.assertNotEqual(temporary_path, unrelated)
            self.assertEqual(output_path, self.output)
            self.assertEqual(json.loads(temporary_path.read_text(encoding="utf-8"))["row_count"], 6)
            temporary_paths.append(temporary_path)
            raise OSError("replacement failed")

        for _ in range(2):
            with patch.object(Path, "replace", autospec=True, side_effect=fail_replacement):
                with self.assertRaisesRegex(OSError, "replacement failed"):
                    convert(self.input_dir, self.output_dir)
            self.assertEqual(set(self.output_dir.iterdir()), {self.output, unrelated})
        self.assertEqual(len(set(temporary_paths)), 2)
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(unrelated.read_bytes(), b"unrelated")

    def test_cleanup_failure_does_not_hide_original_error(self):
        """Cleanup failure preserves the original exception."""
        source = self.copy_fixture("variants_clean.csv")
        previous = self.prepare_existing_output()
        original_error = OSError("original replacement failure")
        with patch.object(Path, "replace", side_effect=original_error):
            with patch.object(Path, "unlink", side_effect=PermissionError("cleanup denied")):
                with self.assertRaises(OSError) as error:
                    convert(self.input_dir, self.output_dir)
        self.assertIs(error.exception, original_error)
        self.assertEqual(self.output.read_bytes(), previous)
        leftovers = set(self.output_dir.iterdir()) - {self.output}
        self.assertEqual(len(leftovers), 1)
        self.assertTrue(next(iter(leftovers)).name.endswith(".tmp"))

    def test_cli_exit_codes_and_stderr_logging(self):
        """CLI reports exit codes and logs to stderr."""
        self.copy_fixture("variants_messy.csv")
        command = [sys.executable, "-B", "-m", "src.convert"]
        success = subprocess.run(command + ["--input-dir", str(self.input_dir), "--output-dir", str(self.output_dir)],
                                 cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(success.stdout, "")
        self.assertEqual(success.stderr.count("WARNING:"), 3)
        self.assertIn("wrote 3 records; skipped 3", success.stderr)
        failure = subprocess.run(command + ["--input-dir", str(self.root / "missing")],
                                 cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(failure.returncode, 1)
        self.assertEqual(failure.stdout, "")
        self.assertEqual(failure.stderr.count("ERROR:"), 1)
        self.assertNotIn("Traceback", failure.stderr)
        usage = subprocess.run(command + ["--unknown-option"], cwd=PROJECT_ROOT,
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(usage.returncode, 2)
        self.assertIn("usage:", usage.stderr)

    def test_unexpected_exception_logs_traceback_and_returns_failure(self):
        """Unexpected CLI errors include a traceback and return failure."""
        with patch("src.convert.convert", side_effect=RuntimeError("injected bug")):
            with self.assertLogs("src.convert", level="ERROR") as logs:
                self.assertEqual(main([]), 1)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelno, logging.ERROR)
        self.assertIsNotNone(logs.records[0].exc_info)
        self.assertIn("Traceback", logs.output[0])
        self.assertIn("injected bug", logs.output[0])


if __name__ == "__main__":
    unittest.main()
