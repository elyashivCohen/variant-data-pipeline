"""Stage 3: Aggregate Stage 1 and Stage 2 outputs into one pipeline summary."""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Optional

from src.json_io import write_json_safely
from src.logging_setup import configure_stage_logging, resolve_log_file


# A fixed name, not __name__: __name__ becomes "__main__" when this module is
# the entry point (python -m src.aggregate), which would otherwise make the
# stage unidentifiable in a shared log stream.
LOGGER_NAME = "src.aggregate"
logger = logging.getLogger(LOGGER_NAME)


def read_process_results(process_dir: Path) -> list[dict]:
    """Read every Stage 2 metrics file in sorted order, or raise on directory/schema errors."""
    if not process_dir.is_dir():
        raise FileNotFoundError(f"Process directory not found: {process_dir}")

    result_files = sorted(process_dir.glob("*.json"))
    if not result_files:
        raise ValueError(f"No Stage 2 output files found in {process_dir}")

    results = []
    for result_file in result_files:
        with result_file.open("r", encoding="utf-8") as stream:
            metrics = json.load(stream)
        if not isinstance(metrics, dict):
            raise ValueError(f"Root JSON element in {result_file} must be an object")
        if metrics.get("status") not in ("SUCCESS", "FAILED"):
            raise ValueError(f"Invalid or missing status in {result_file}")
        if not isinstance(metrics.get("input_file"), str) or not metrics["input_file"]:
            raise ValueError(f"Invalid or missing input_file in {result_file}")

        duration = metrics.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            raise ValueError(f"Invalid or missing duration_seconds in {result_file}")

        skipped = metrics.get("skipped_row_count")
        if not isinstance(skipped, int) or isinstance(skipped, bool) or skipped < 0:
            raise ValueError(f"Invalid or missing skipped_row_count in {result_file}")

        results.append(metrics)
    return results


def count_variants_by_chromosome(convert_dir: Path, filenames: list[str]) -> dict[str, int]:
    """Tally CHROM values across the given Stage 1 output files."""
    if not convert_dir.is_dir():
        raise FileNotFoundError(f"Convert directory not found: {convert_dir}")

    counts: dict[str, int] = {}
    for filename in filenames:
        convert_file = convert_dir / filename
        if not convert_file.is_file():
            raise FileNotFoundError(
                f"Convert-stage output not found for successfully processed file: {convert_file}"
            )
        with convert_file.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)

        variants = payload.get("variants") if isinstance(payload, dict) else None
        if not isinstance(variants, list):
            raise ValueError(f"Invalid or missing variants array in {convert_file}")

        for variant in variants:
            chrom = variant.get("CHROM") if isinstance(variant, dict) else None
            if not isinstance(chrom, str):
                raise ValueError(f"Invalid or missing CHROM value in {convert_file}")
            counts[chrom] = counts.get(chrom, 0) + 1
    return counts


def verify_process_covers_convert_outputs(convert_dir: Path, results: list[dict]) -> None:
    """Every current-run Convert output must have a Process outcome (SUCCESS or FAILED).

    A Convert output Process never even attempted is a broken pairing between
    the two directories, not a normal partial-success outcome, so it fails
    aggregation rather than silently vanishing from the summary.
    """
    if not convert_dir.is_dir():
        raise FileNotFoundError(f"Convert directory not found: {convert_dir}")

    convert_filenames = {path.name for path in convert_dir.glob("*.json") if path.is_file()}
    process_filenames = {r["input_file"] for r in results}
    missing = sorted(convert_filenames - process_filenames)
    if missing:
        raise ValueError(
            f"Convert output(s) in {convert_dir} have no Process outcome: {', '.join(missing)}"
        )


def aggregate(convert_dir: Path, process_dir: Path) -> dict:
    """Combine Stage 1 and Stage 2 outputs into one pipeline summary."""
    results = read_process_results(process_dir)
    verify_process_covers_convert_outputs(convert_dir, results)

    successful_filenames = [r["input_file"] for r in results if r["status"] == "SUCCESS"]
    chromosome_counts = count_variants_by_chromosome(convert_dir, successful_filenames)

    return {
        "variant_counts_by_chromosome": dict(sorted(chromosome_counts.items())),
        "total_variant_count": sum(chromosome_counts.values()),
        "total_skipped_rows": sum(r["skipped_row_count"] for r in results),
        "total_processing_time_seconds": round(sum(r["duration_seconds"] for r in results), 6),
        "input_files_processed": [r["input_file"] for r in results],
    }


def write_summary(output_path: Path, summary: dict) -> None:
    """Write the aggregate summary JSON file atomically, overwriting any existing output."""
    write_json_safely(output_path, summary)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for Stage 3 Aggregate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--convert-dir",
        type=Path,
        default=Path("data/converted"),
        help="Directory containing Stage 1 converted JSON files (default: data/converted)",
    )
    parser.add_argument(
        "--process-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory containing Stage 2 metrics JSON files (default: data/processed)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=Path("output/summary.json"),
        help="Path to write the aggregate summary JSON file (default: output/summary.json)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional log file to append to, in addition to the console "
             "(default: $LOG_FILE, or console only)",
    )
    args = parser.parse_args(argv)

    log_file = resolve_log_file(args.log_file)
    try:
        configure_stage_logging(LOGGER_NAME, sys.stdout, log_file)
    except OSError as error:
        print(f"ERROR: Configuration error: could not open log file {log_file}: {error}",
              file=sys.stderr)
        return 2

    logger.info("Aggregate stage starting: convert_dir=%s process_dir=%s output_file=%s",
                args.convert_dir, args.process_dir, args.output_file)
    try:
        summary = aggregate(args.convert_dir, args.process_dir)
        write_summary(args.output_file, summary)
    except Exception as err:
        logger.error("Aggregation failed: %s", err)
        return 1

    logger.info(
        "Aggregated %s file(s): %s variant(s) across %s chromosome(s)",
        len(summary["input_files_processed"]),
        summary["total_variant_count"],
        len(summary["variant_counts_by_chromosome"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
