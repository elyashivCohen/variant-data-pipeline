"""Shared console + optional file logging setup for all three pipeline stages."""

import logging
import os
from pathlib import Path
from typing import Optional, TextIO


LOG_FILE_ENV_VAR = "LOG_FILE"

CONSOLE_FORMAT = "%(levelname)s: %(message)s"
FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def resolve_log_file(explicit: Optional[Path]) -> Optional[Path]:
    """Return the log file path from --log-file, else the LOG_FILE env var, else None."""
    if explicit is not None:
        return explicit
    raw = os.environ.get(LOG_FILE_ENV_VAR)
    return Path(raw) if raw else None


def configure_stage_logging(
    logger_name: str,
    console_stream: TextIO,
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """Configure logger_name with a console handler and an optional appending file handler.

    Re-configuring the same logger (for example, main() called more than once
    within one process, as tests do) replaces rather than accumulates
    handlers, so messages are never duplicated. Raises OSError if log_file is
    given but cannot be opened; callers should report this clearly and exit
    nonzero rather than continue without logging.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console_handler = logging.StreamHandler(console_stream)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    logger.addHandler(console_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")  # append mode by default
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        logger.addHandler(file_handler)

    return logger
