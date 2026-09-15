"""Unit tests for the shared stage logging setup helper."""

import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.logging_setup import LOG_FILE_ENV_VAR, configure_stage_logging, resolve_log_file


class ResolveLogFileTests(unittest.TestCase):
    def test_explicit_path_takes_precedence_over_env_var(self):
        with patch.dict("os.environ", {LOG_FILE_ENV_VAR: "from_env.log"}):
            self.assertEqual(resolve_log_file(Path("from_arg.log")), Path("from_arg.log"))

    def test_env_var_used_when_no_explicit_path(self):
        with patch.dict("os.environ", {LOG_FILE_ENV_VAR: "from_env.log"}):
            self.assertEqual(resolve_log_file(None), Path("from_env.log"))

    def test_none_when_neither_is_set(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(resolve_log_file(None))

    def test_blank_env_var_treated_as_unset(self):
        with patch.dict("os.environ", {LOG_FILE_ENV_VAR: ""}):
            self.assertIsNone(resolve_log_file(None))


class ConfigureStageLoggingTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.addCleanup(self._close_test_logger_handlers)

    @staticmethod
    def _close_test_logger_handlers():
        logger = logging.getLogger("test.logging_setup")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_console_and_file_both_receive_the_message(self):
        """A single log call reaches both the console stream and the log file."""
        console = io.StringIO()
        log_file = self.root / "logs" / "stage.log"

        logger = configure_stage_logging("test.logging_setup", console, log_file)
        logger.info("hello")

        self.assertIn("INFO: hello", console.getvalue())
        content = log_file.read_text(encoding="utf-8")
        self.assertIn("INFO", content)
        self.assertIn("test.logging_setup", content)
        self.assertIn("hello", content)
        # File format includes a timestamp before the level.
        self.assertRegex(content, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO")

    def test_no_file_handler_when_log_file_is_none(self):
        """Console-only logging works without requiring a log file (existing local CLI use)."""
        console = io.StringIO()
        logger = configure_stage_logging("test.logging_setup", console, None)
        logger.info("hello")
        self.assertIn("INFO: hello", console.getvalue())
        self.assertEqual(len(logger.handlers), 1)

    def test_reconfiguring_does_not_duplicate_handlers_or_messages(self):
        """Calling configure_stage_logging again replaces handlers instead of accumulating them."""
        log_file = self.root / "stage.log"
        console1 = io.StringIO()
        logger = configure_stage_logging("test.logging_setup", console1, log_file)
        logger.info("first run")

        console2 = io.StringIO()
        logger = configure_stage_logging("test.logging_setup", console2, log_file)
        logger.info("second run")

        self.assertEqual(len(logger.handlers), 2)  # one console + one file, not accumulated
        self.assertNotIn("first run", console2.getvalue())  # old console handler was detached
        self.assertNotIn("second run", console1.getvalue())  # and no longer receives new messages

        content = log_file.read_text(encoding="utf-8")
        self.assertEqual(content.count("first run"), 1)
        self.assertEqual(content.count("second run"), 1)

    def test_rerun_with_same_log_file_appends(self):
        """A log file is appended to, not overwritten, across separate configure calls."""
        log_file = self.root / "stage.log"

        configure_stage_logging("test.logging_setup", io.StringIO(), log_file).info("run 1")
        configure_stage_logging("test.logging_setup", io.StringIO(), log_file).info("run 2")

        content = log_file.read_text(encoding="utf-8")
        self.assertIn("run 1", content)
        self.assertIn("run 2", content)

    def test_unopenable_log_file_raises_oserror(self):
        """A log file path that cannot be created raises instead of silently continuing."""
        blocked = self.root / "blocked"
        blocked.write_text("this is a file, not a directory", encoding="utf-8")
        log_file = blocked / "stage.log"  # parent exists as a file, not a directory

        with self.assertRaises(OSError):
            configure_stage_logging("test.logging_setup", io.StringIO(), log_file)


if __name__ == "__main__":
    unittest.main()
