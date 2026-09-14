# IdentifAI Genetics — Variant Data Pipeline

## 1. Project Overview

This Software Engineering Intern take-home assignment builds a three-stage pipeline to convert CSV variant data, simulate processing, and aggregate results. Convert is implemented; Process, Aggregate, and orchestration remain planned.

## 2. Requirements

- **Convert:** Read one or more CSV files with columns `index`, `CHROM`, `POS`, `REF`, and `ALT`. Convert each file into structured output. Skip malformed rows, log a warning for each, and continue processing valid rows in the same file.
- **Process:** Read converted output and simulate a compute-intensive operation with a default 30-second delay per input. Produce per-input status and metrics, such as start/end times, valid row count, and skipped row count.
- **Aggregate:** Combine processed results into one summary containing variant counts per chromosome, total variant count, total skipped rows, total processing time, and the list of processed input files.
- Handle malformed input gracefully. Re-running the same inputs must not duplicate or corrupt data.
- Include tests and containerize at least the Convert stage.
- Provide a simple way to run the pipeline end-to-end.
- Document design decisions, assumptions, run instructions, AI workflow, and trade-offs.

## 3. Assumptions

- Each input CSV has a header containing the required columns.
- Each input file is processed independently before aggregation.
- Total processing time means the sum of Process-stage durations, including the simulated delay.

## 4. Initial High-Level Architecture

```text
input/*.csv
    |
    v
Convert
    |
    v
data/converted/*.json
    |
    v
Process
    |
    v
data/processed/*.json
    |
    v
Aggregate
    |
    v
output/summary.json
```

Convert will validate rows and record valid variants, source-file identity, and row counts. Process will apply the delay and produce status, timing metrics, and the data needed for aggregation. Aggregate will produce the final summary.

The local design uses sequential stage execution and a configurable Process delay for tests and development, retaining the 30-second default. All three stages are planned for containerization, with Docker Compose as the likely local runner. These are design choices, not assignment requirements.

## 5. Data / Persistence Strategy

JSON is the implemented conversion format and the proposed downstream format: it is readable and supports records alongside metadata. Each input has one converted output and will have one processed output. The assignment allows JSON without prescribing its exact schema; the metadata object is a project choice.

Files persisted to disk between stages will act as the local pipeline state. Inputs will remain unchanged, and shared host directories will preserve outputs across container runs. No database is planned. This approach keeps the batch workflow simple; concurrent execution is outside the initial design.

## 6. Logging Strategy

The Convert CLI configures logging to stderr so Docker can collect it. Each written file generates an INFO message with accepted and skipped counts. Each skipped record generates one WARNING with its input path, starting physical line number, and reason. Expected failures produce one concise ERROR at the CLI boundary; unexpected exceptions include a traceback. Aggregation will use persisted metrics rather than parse logs.

## 7. Idempotency Strategy

Outputs will use deterministic paths: `input/sample.csv` will map to `data/converted/sample.json` and `data/processed/sample.json`. Reruns will regenerate and overwrite expected outputs instead of appending duplicates.

The summary will be rebuilt from the current run's processed results, excluding stale outputs. Convert already writes temporary files before replacing outputs to prevent partial writes from corrupting existing data.

Unchanged inputs will produce the same variant and skipped-row totals on repeated runs. Timing metadata may change because processing runs again.

## 8. Initial Development Plan

1. Define row validation, JSON structures, and handling for missing headers, unreadable files, empty inputs, and files with no valid rows.
2. Implement Convert with per-row warnings and safe output writes.
3. Implement Process with a configurable delay and per-input metrics.
4. Implement Aggregate and a sequential runner that selects current-run outputs.
5. Test valid and malformed data, aggregation, repeat runs, stale outputs, and failure handling.
6. Containerize the stages and verify the full local workflow with shared persistent directories.
7. Add verified run/test commands, AI workflow notes, and implementation trade-offs to this README.

## 9. Convert Stage

Requires Python 3.9 or later and uses only the standard library. From the repository root:

```sh
python -m src.convert --input-dir input --output-dir data/converted
```

`convert(input_dir: Path, output_dir: Path)` reads CSV files directly inside the input directory and returns the JSON paths written during that call. `convert_file(input_path: Path, output_path: Path)` converts a single file independently. JSON contains `source_file`, `row_count`, `skipped_rows`, and `variants`.

Validation choices: files use UTF-8 (an optional BOM is accepted). Header names are trimmed, must be unique after trimming, and must include all required columns. Columns may be reordered and extra columns are ignored. Rows must match the header's field count. Required values are trimmed and must be nonempty; `POS` must be a positive integer. Other required values remain strings, including multi-character alleles. Accepted records retain their input order and supplied index values; no biological validation or deduplication is performed.

Blank records, incorrect field counts, empty required values, and invalid positions are skipped with warnings. Strict CSV parser errors fail the file: malformed quoting can consume subsequent physical lines, so continuing cannot reliably recover record boundaries or skipped counts. This parser-error policy is a project decision, separate from skipping records whose fields can be parsed.

Missing inputs, invalid headers, completely empty files, decoding errors, and I/O errors also fail conversion. Missing input directories or no CSV files fail the batch. Header-only files and files with no valid rows produce the same metadata object with an empty `variants` array and accurate counts. `source_file` is the input filename, `row_count` counts accepted records, and `skipped_rows` counts rejected parsed records.

The CLI exits with status 0 on success, 1 on conversion failure, and 2 for argparse usage errors. Batches stop at the first failed file; files completed earlier remain on disk, and old outputs are not removed. Callers should use the returned paths only after a successful batch call.

Input and output referring to the same file are rejected. Each JSON output is written to a uniquely named temporary sibling file, closed, and then used to replace the expected output. This preserves previous output on writing or replacement failure and avoids appending duplicates on reruns. Cleanup is attempted on failure; if cleanup also fails, the original error is preserved and a temporary file may remain. Concurrent runs are not supported.

Paths are supplied through function arguments or the existing `--input-dir` and `--output-dir` CLI options. Future containers can pass mounted directory paths through these same options; conversion contains no Docker-specific logic. The commands above require a working local Python installation.
