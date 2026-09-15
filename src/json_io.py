"""Shared atomic JSON-writing helper used by all three pipeline stages."""

import json
import sys
import tempfile
from pathlib import Path


def write_json_safely(output_path: Path, payload: dict[str, object]) -> None:
    """Replace output only after writing and closing a temporary sibling file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_path.parent,
            prefix=output_path.name + ".", suffix=".tmp", delete=False,
        ) as destination:
            temporary_path = Path(destination.name)
            destination.write(json.dumps(payload, indent=2) + "\n")
        temporary_path.replace(output_path)
    finally:
        # Cleanup must not replace an error already propagating from the write.
        error_in_progress = sys.exc_info()[0] is not None
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                if not error_in_progress:
                    raise
