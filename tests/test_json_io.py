"""Unit tests for the shared atomic JSON-writing helper."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.json_io import write_json_safely


class WriteJsonSafelyTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.output_dir = Path(temporary_directory.name) / "out"
        self.output = self.output_dir / "result.json"

    def test_successful_write_creates_output_and_no_leftover_temp_files(self):
        """A successful call creates the output and leaves no temporary files behind."""
        write_json_safely(self.output, {"a": 1})
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual(list(self.output_dir.iterdir()), [self.output])

    def test_write_failure_preserves_existing_destination(self):
        """A failure while writing the temporary file preserves the existing destination."""
        self.output_dir.mkdir(parents=True)
        self.output.write_bytes(b"previous output\n")
        previous = self.output.read_bytes()

        with patch("src.json_io.tempfile.NamedTemporaryFile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_json_safely(self.output, {"a": 1})

        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(list(self.output_dir.iterdir()), [self.output])

    def test_replacement_failure_preserves_existing_destination_and_cleans_temp(self):
        """A failure during the atomic replace preserves the destination and removes the temp file."""
        self.output_dir.mkdir(parents=True)
        self.output.write_bytes(b"previous output\n")
        previous = self.output.read_bytes()

        with patch.object(Path, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaisesRegex(OSError, "replacement failed"):
                write_json_safely(self.output, {"a": 1})

        self.assertEqual(self.output.read_bytes(), previous)
        leftovers = set(self.output_dir.iterdir()) - {self.output}
        self.assertEqual(leftovers, set())

    def test_cleanup_failure_does_not_hide_original_error(self):
        """If cleanup itself fails, the original write/replace error is what propagates."""
        self.output_dir.mkdir(parents=True)
        self.output.write_bytes(b"previous output\n")
        previous = self.output.read_bytes()
        original_error = OSError("original replacement failure")

        with patch.object(Path, "replace", side_effect=original_error):
            with patch.object(Path, "unlink", side_effect=PermissionError("cleanup denied")):
                with self.assertRaises(OSError) as error:
                    write_json_safely(self.output, {"a": 1})

        self.assertIs(error.exception, original_error)
        self.assertEqual(self.output.read_bytes(), previous)
        leftovers = set(self.output_dir.iterdir()) - {self.output}
        self.assertEqual(len(leftovers), 1)
        self.assertTrue(next(iter(leftovers)).name.endswith(".tmp"))


if __name__ == "__main__":
    unittest.main()
