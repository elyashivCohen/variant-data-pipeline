# IdentifAI Genetics — Variant Data Pipeline

## 1. Project Overview

This Software Engineering Intern take-home assignment builds a three-stage pipeline to convert CSV variant data, simulate processing, and aggregate results. Convert and Process are implemented; Aggregate and orchestration remain planned.

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

Convert validates rows and records valid variants, source-file identity, and row counts. Process applies the delay and produces status, timing metrics, and the data needed for aggregation. Aggregate will produce the final summary.

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

## 10. Automated Convert Verification

Run the existing standard-library unittest suite with readable console labels from the repository root:

```sh
python -B tests/run_tests.py
```

The runner uses test docstrings as display names, shows `[PASS]`, `[FAIL]`, `[ERROR]`, and `[SKIP]` labels, and retains unittest assertion details and tracebacks. Skips include their reasons. Discovery and project imports are resolved relative to the script. The standard verbose command remains available:

```sh
python -B -m unittest discover -s tests -v
```

`input/` contains the five unchanged original assignment CSV files. Authored valid and invalid examples live in `tests/fixtures/`; `tests/test_convert.py` reads these fixtures and the original samples, using temporary output directories with automatic cleanup. No manual-check directories or generated outputs are needed.

The suite checks exact JSON records and accepted/skipped counts, warnings and continued processing after invalid records, header and CSV parser failures, output preservation, reruns, mocked I/O failures, and CLI logs and exit codes. Error scenarios pass only when the expected exception, log, exit code, or output state is observed. Standard verbose unittest reporting shows each test's result and the final totals.

The readable summary counts successful test methods as passes and each failure, error, or skip event separately, including subtest events. A parent with a failed subtest is never reported as passed; several unsuccessful subtests can make event totals exceed the number of test methods. Expected failures are labeled and counted as skips; unexpected successes count as failures. Exit status is 0 when unittest reports success and 1 otherwise.

Verification on Windows with Python 3.13.14: the readable runner ran 23 tests in 0.329 seconds; standard unittest ran 23 tests in 0.319 seconds. Each reported 22 passed, 0 failures, 0 errors, and one symbolic-link test skipped because Windows denied permission (exit code 0). Python 3.9 was not tested. The multiline CSV test writes through `Path.open` with `newline=""` to prevent Windows newline translation while retaining Python 3.9 compatibility.

## 11. Process Stage

Requires Python 3.9 or later and uses only the standard library. From the repository root:

```sh
python -m src.process --input-dir data/converted --output-dir data/processed --sleep-seconds 0
```

Omit `--sleep-seconds` for the default 30-second simulated compute delay. The delay can also be set with the `PROCESS_SLEEP_SECONDS` environment variable; `--sleep-seconds` takes precedence when both are given. Input and output paths are configurable; defaults are `data/converted` and `data/processed`.

`process_file(input_path: Path, output_dir: Path, sleep_duration=None) -> dict` processes one Stage 1 JSON file and returns its metrics. `process(input_dir: Path, output_dir: Path, sleep_duration=None) -> list[dict]` processes every `*.json` file directly inside the input directory, in sorted order, sequentially, writing one metrics file per input.

Each output is a JSON object, written to `<output-dir>/<input filename>`, containing:

```json
{
  "input_file": "example.json",
  "status": "SUCCESS",
  "start_time": "2026-09-14T10:00:00.000000+00:00",
  "end_time": "2026-09-14T10:00:30.002123+00:00",
  "duration_seconds": 30.002123,
  "row_count": 3,
  "skipped_row_count": 1
}
```

`row_count` and `skipped_row_count` are read directly from the Stage 1 output's `row_count` and `skipped_rows` fields. `duration_seconds` is measured with `time.monotonic()` around reading, validation, and the simulated sleep.

Files are processed independently. If one file fails — missing file, malformed JSON, or missing/invalid `row_count`/`skipped_rows` — it is recorded with `status: "FAILED"`, `row_count: 0`, `skipped_row_count: 0`, and an `ERROR` line on stdout, and the batch continues to the next file. A single bad input does not stop the rest of the batch from being processed.

`variant_counts_by_chromosome` is **not** produced by this stage. Per-chromosome variant counts, total variant and skipped-row counts, total processing time, and the list of processed input files are Stage 3 (Aggregate)'s responsibility, computed by combining every Stage 2 output into one summary file.

The CLI exits with status 0 on success, 1 if the input directory is missing, and 2 for an invalid `--sleep-seconds` value or argparse usage errors.
