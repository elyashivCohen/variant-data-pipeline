"""Stage 2: Process converted variant JSON files and record execution metrics."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Optional


DEFAULT_SLEEP_SECONDS = 30.0
ENV_SLEEP_VAR = "PROCESS_SLEEP_SECONDS"


def validate_sleep_duration(duration: float) -> float:
    """Validate that sleep duration is a finite, nonnegative float or int."""
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        raise ValueError(f"Sleep duration must be a number, got {type(duration).__name__}")
    if not math.isfinite(duration) or duration < 0:
        raise ValueError(f"Sleep duration must be a finite nonnegative number, got {duration}")
    return float(duration)


def get_sleep_duration() -> float:
    """Retrieve simulated compute delay in seconds from environment or default."""
    raw = os.environ.get(ENV_SLEEP_VAR)
    if raw is None or raw.strip() == "":
        return DEFAULT_SLEEP_SECONDS
    try:
        duration = float(raw)
    except ValueError as err:
        raise ValueError(
            f"{ENV_SLEEP_VAR} environment variable must be a valid number, got {raw!r}"
        ) from err
    return validate_sleep_duration(duration)


def read_converted_file(file_path: Path) -> dict:
    """Read and decode a JSON output file produced by Stage 1."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Root JSON element in {file_path} must be an object")
    return data


def write_metrics(output_path: Path, metrics: dict) -> None:
    """Write the metrics JSON file, overwriting any existing output."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")


def process_file(
    input_path: Path,
    output_dir: Path,
    sleep_duration: Optional[float] = None,
) -> dict:
    """Process a single converted file, simulate compute, and persist execution metrics."""
    sleep_duration = (
        get_sleep_duration() if sleep_duration is None else validate_sleep_duration(sleep_duration)
    )

    start_dt = datetime.now(timezone.utc)
    t0 = time.monotonic()
    status = "SUCCESS"
    row_count = 0
    skipped_row_count = 0

    try:
        payload = read_converted_file(input_path)

        raw_row_count = payload.get("row_count")
        if not isinstance(raw_row_count, int) or isinstance(raw_row_count, bool) or raw_row_count < 0:
            raise ValueError(f"Invalid or missing row_count in {input_path.name}")
        row_count = raw_row_count

        raw_skipped = payload.get("skipped_rows")
        if not isinstance(raw_skipped, int) or isinstance(raw_skipped, bool) or raw_skipped < 0:
            raise ValueError(f"Invalid or missing skipped_rows in {input_path.name}")
        skipped_row_count = raw_skipped

        if sleep_duration > 0:
            time.sleep(sleep_duration)

    except (OSError, ValueError) as err:
        # Expected input problems (unreadable file, malformed JSON, missing or
        # invalid schema fields). Anything else is a programming error and
        # must propagate, not be disguised as a per-file failure.
        status = "FAILED"
        row_count = 0
        skipped_row_count = 0
        sys.stdout.write(f"ERROR: Failed processing {input_path.name}: {err}\n")
        sys.stdout.flush()

    end_dt = datetime.now(timezone.utc)
    duration_seconds = round(time.monotonic() - t0, 6)

    metrics = {
        "input_file": input_path.name,
        "status": status,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "duration_seconds": duration_seconds,
        "row_count": row_count,
        "skipped_row_count": skipped_row_count,
    }

    write_metrics(output_dir / input_path.name, metrics)
    return metrics


def process(
    input_dir: Path,
    output_dir: Path,
    sleep_duration: Optional[float] = None,
) -> list[dict]:
    """Iterate through all Stage 1 JSON files, process them, and write metrics.

    A file that fails to read or validate is recorded with status FAILED and
    does not stop the rest of the batch; an unexpected error or a failure
    while writing an output still propagates and aborts the batch immediately.
    The batch fails - raising ValueError after writing whatever per-file
    metrics it could - if zero files succeed, including when input_dir has no
    eligible *.json files at all.
    """
    resolved_sleep = (
        get_sleep_duration() if sleep_duration is None else validate_sleep_duration(sleep_duration)
    )

    if not input_dir.is_dir():
        sys.stdout.write(f"ERROR: Input directory does not exist: {input_dir}\n")
        sys.stdout.flush()
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    input_files = sorted(input_dir.glob("*.json"))
    results = [process_file(input_file, output_dir, resolved_sleep) for input_file in input_files]

    succeeded = sum(1 for result in results if result["status"] == "SUCCESS")
    if succeeded == 0:
        sys.stdout.write(f"ERROR: No files processed successfully from {input_dir}\n")
        sys.stdout.flush()
        raise ValueError(f"No files processed successfully from {input_dir}")

    return results


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for Stage 2 Process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/converted"),
        help="Directory containing Stage 1 converted JSON files (default: data/converted)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory where Stage 2 metrics JSON files will be written (default: data/processed)",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=None,
        help=f"Simulated compute sleep duration (default: ${ENV_SLEEP_VAR} or {DEFAULT_SLEEP_SECONDS}s)",
    )
    args = parser.parse_args(argv)

    try:
        sleep_dur = (
            validate_sleep_duration(args.sleep_seconds)
            if args.sleep_seconds is not None
            else get_sleep_duration()
        )
    except ValueError as err:
        sys.stdout.write(f"ERROR: Configuration error: {err}\n")
        sys.stdout.flush()
        return 2

    try:
        results = process(args.input_dir, args.output_dir, sleep_dur)
    except Exception as err:
        sys.stdout.write(f"ERROR: Pipeline execution failed: {err}\n")
        sys.stdout.flush()
        return 1

    succeeded = sum(1 for r in results if r["status"] == "SUCCESS")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    sys.stdout.write(f"Processed {len(results)} file(s): {succeeded} SUCCESS, {failed} FAILED\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
