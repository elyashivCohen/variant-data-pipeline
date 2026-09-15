"""Convert CSV variant files into JSON using only the standard library."""

import argparse
import csv
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Optional


REQUIRED_COLUMNS = ("index", "CHROM", "POS", "REF", "ALT")
logger = logging.getLogger(__name__)


class InvalidRowError(ValueError):
    """A parsed CSV record contains invalid values and can be skipped."""


class ConversionError(ValueError):
    """An expected validation failure prevents conversion."""


# A file that raises one of these while being read cannot be converted, but
# does not implicate any other file: skip it and keep processing the batch.
INPUT_ERRORS = (ConversionError, csv.Error, OSError, UnicodeError)


def validate_header(header: list[str]) -> list[str]:
    """Return normalized column names, or raise ConversionError."""
    header = [column.strip() for column in header]
    if len(header) != len(set(header)):
        raise ConversionError("header contains duplicate column names")
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing_columns:
        raise ConversionError(f"header is missing required columns: {', '.join(missing_columns)}")
    return header


def parse_variant(row: list[str], header: list[str]) -> dict[str, object]:
    """Return the required fields with integer POS, or raise InvalidRowError."""
    if len(row) != len(header):
        raise InvalidRowError("field count does not match header")
    fields = dict(zip(header, row))
    variant = {column: fields[column].strip() for column in REQUIRED_COLUMNS}
    for column, value in variant.items():
        if not value:
            raise InvalidRowError(f"{column} must not be empty")
    try:
        position = int(variant["POS"])
    except ValueError as error:
        raise InvalidRowError("POS must be a positive integer") from error
    if position <= 0:
        raise InvalidRowError("POS must be a positive integer")
    return {**variant, "POS": position}


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


def _reject_same_file(input_path: Path, output_path: Path) -> None:
    """Raise ConversionError if input and output resolve to the same file."""
    if input_path.resolve() == output_path.resolve() or (
        output_path.exists() and input_path.samefile(output_path)
    ):
        raise ConversionError(f"{input_path}: input and output refer to the same file")


def read_variants(input_path: Path) -> tuple[list[dict[str, object]], int]:
    """Read and validate one CSV file's rows into (variants, skipped_rows).

    Row-level errors are skipped with a warning and do not stop the file.
    Raises ConversionError or csv.Error for header or parser-level problems;
    OSError/UnicodeError propagate from opening or decoding the file itself.
    """
    variants = []
    skipped_rows = 0
    with input_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        try:
            header = validate_header(next(reader))
        except StopIteration as error:
            raise ConversionError(f"{input_path}: missing CSV header") from error
        except (ConversionError, csv.Error) as error:
            raise ConversionError(f"{input_path}: {error}") from error

        while True:
            row_line = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as error:
                raise csv.Error(f"{input_path}: line {row_line}: {error}") from error

            try:
                variant = parse_variant(row, header)
            except InvalidRowError as error:
                skipped_rows += 1
                logger.warning("%s: line %s: skipped record: %s", input_path, row_line, error)
                continue

            variants.append(variant)
    return variants, skipped_rows


def _build_payload(input_path: Path, variants: list[dict[str, object]], skipped_rows: int) -> dict:
    return {
        "source_file": input_path.name,
        "row_count": len(variants),
        "skipped_rows": skipped_rows,
        "variants": variants,
    }


def convert_file(input_path: Path, output_path: Path) -> Path:
    """Convert one CSV file to JSON independently; raise on any file-level failure."""
    _reject_same_file(input_path, output_path)
    variants, skipped_rows = read_variants(input_path)
    payload = _build_payload(input_path, variants, skipped_rows)
    write_json_safely(output_path, payload)
    logger.info("%s -> %s: wrote %s records; skipped %s", input_path, output_path,
                len(variants), skipped_rows)
    return output_path


def convert(input_dir: Path, output_dir: Path) -> list[Path]:
    """Convert every CSV file in input_dir; return this run's successful outputs.

    A file that cannot be opened or parsed is logged and skipped so the rest
    of the batch keeps going. A failure while writing an output is not an
    input problem, so it is never treated as skippable: it stops the batch
    immediately, even if earlier files already succeeded. Files completed
    before that point remain on disk and existing outputs are replaced, never
    appended.

    The batch fails - raising ConversionError - if input files exist but none
    convert successfully, including when input_dir has no CSV files at all.
    Success is judged solely by outputs produced during this call; files
    already present in output_dir from a previous run do not count.
    """
    if not input_dir.is_dir():
        raise ConversionError(f"Input path is not an existing directory: {input_dir}")
    input_paths = sorted(path for path in input_dir.glob("*.csv") if path.is_file())
    if not input_paths:
        raise ConversionError(f"No CSV files found in {input_dir}")

    output_paths = []
    for input_path in input_paths:
        output_path = output_dir / f"{input_path.stem}.json"
        try:
            _reject_same_file(input_path, output_path)
            variants, skipped_rows = read_variants(input_path)
        except INPUT_ERRORS as error:
            logger.error("%s: skipping file: %s", input_path, error)
            continue

        payload = _build_payload(input_path, variants, skipped_rows)
        write_json_safely(output_path, payload)  # not caught above: write failures are fatal
        logger.info("%s -> %s: wrote %s records; skipped %s", input_path, output_path,
                    len(variants), skipped_rows)
        output_paths.append(output_path)

    if not output_paths:
        raise ConversionError(f"No input file in {input_dir} converted successfully")
    return output_paths


def main(argv: Optional[list[str]] = None) -> int:
    """Run the CLI, returning zero on success or one on conversion failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/converted"))
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        outputs = convert(arguments.input_dir, arguments.output_dir)
    except (ConversionError, OSError, UnicodeError, csv.Error) as error:
        logger.error("Conversion failed: %s", error)
        return 1
    except Exception:
        logger.exception("Unexpected conversion failure")
        return 1
    logger.info("Converted %s input file(s)", len(outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
