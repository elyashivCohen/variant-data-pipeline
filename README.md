# IdentifAI Genetics — Variant Data Pipeline

## 1. Project Overview

This Software Engineering Intern take-home assignment builds a three-stage pipeline to convert CSV variant data, simulate processing, and aggregate results. Convert, Process, and Aggregate are implemented; orchestration remains planned.

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

Convert validates rows and records valid variants, source-file identity, and row counts. Process applies the delay and produces status, timing metrics, and the data needed for aggregation. Aggregate produces the final summary.

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

Row-level errors (blank records, incorrect field counts, empty required values, invalid positions, and strict CSV parser errors within a file) are skipped with warnings and do not stop the rest of that file. Malformed quoting can consume subsequent physical lines, so a parser error still ends that one file's parsing at that point - continuing within the file cannot reliably recover record boundaries or skipped counts - but it does not stop the batch: the rest of the file's already-accepted records are discarded (the file did not complete) and the batch moves on to the next file.

File-level errors - a file that cannot be opened or decoded, has a missing or duplicate header, or hits a CSV parser error - are logged (`ERROR`, with the file path and reason) and that file is skipped; the rest of the batch keeps going. A failure while *writing* an output (creating the output directory, the temporary file, or the atomic replace) is never treated as a skippable input error: it stops the batch immediately, even if earlier files already succeeded, since it is not a property of any one input file. Missing or invalid input directories are directory-level configuration errors and fail immediately without attempting any file.

The batch fails - raising `ConversionError` - if no input file converts successfully, whether because `input_dir` has no CSV files at all or because every CSV present failed to convert. A file with a valid header and zero valid rows (header-only, or every row skipped) is still a successful conversion: it produces the same metadata shape with an empty `variants` array, and counts toward batch success. Success is judged only by outputs produced during the current call; files already present in `output_dir` from an earlier run are never consulted to decide whether this run succeeded.

The CLI exits with status 0 on success (including success with skipped files - check the log for `ERROR` lines), 1 on conversion failure, and 2 for argparse usage errors. Files converted before a fatal (output-write or directory-level) failure remain on disk; old outputs for files that were skipped or never attempted this run are not removed. Callers should use the returned paths only after a successful batch call.

Input and output referring to the same file are rejected for that file (skipped, like any other file-level error). Each JSON output is written to a uniquely named temporary sibling file, closed, and then used to replace the expected output, via a small shared helper (`write_json_safely` in `src/json_io.py`) used by all three stages. This preserves previous output on writing or replacement failure and avoids appending duplicates on reruns. Cleanup is attempted on failure; if cleanup also fails, the original error is preserved and a temporary file may remain. Concurrent runs are not supported.

Run-directory isolation (so a rerun can never mix outputs from two different pipeline invocations) is planned for the orchestration milestone via a per-run `RUN_ID`-scoped output directory, not implemented at the stage level; see §13.

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

Files are processed independently. If one file fails an expected input check — missing file, malformed JSON, or missing/invalid `row_count`/`skipped_rows` — it is recorded with `status: "FAILED"`, `row_count: 0`, `skipped_row_count: 0`, and an `ERROR` line on stdout, and the batch continues to the next file. An unexpected (non-input) exception, or a failure while writing a metrics file, is not disguised as a FAILED record: it propagates and aborts the batch immediately, the same as Convert's write-failure policy. `write_metrics` uses the same temporary-file-then-replace helper as Convert (`src/json_io.py`), so a write failure can never leave a corrupt or partial metrics file behind.

`variant_counts_by_chromosome` is **not** produced by this stage. Per-chromosome variant counts, total variant and skipped-row counts, total processing time, and the list of processed input files are Stage 3 (Aggregate)'s responsibility, computed by combining every Stage 2 output into one summary file.

The batch fails - raising `ValueError` after writing whatever per-file FAILED metrics it could - if zero files succeed, including when `input_dir` has no eligible `*.json` files at all. The CLI exits with status 0 on success (including success with some FAILED files), 1 if the input directory is missing or zero files succeeded, and 2 for an invalid `--sleep-seconds` value or argparse usage errors.

## 12. Aggregate Stage

Requires Python 3.9 or later and uses only the standard library. From the repository root:

```sh
python -m src.aggregate --convert-dir data/converted --process-dir data/processed --output-file output/summary.json
```

Input and output paths are configurable; defaults are `data/converted`, `data/processed`, and `output/summary.json`.

Aggregate reads from two directories rather than one. Stage 2's metrics files carry status, timing, and row/skipped-row counts but no per-variant data, so computing a chromosome breakdown requires reading Stage 1's `variants` arrays directly. Files are matched by identical filename between `--convert-dir` and `--process-dir` — Process always writes its output under the same filename it read from Convert, so this pairing is exact and requires no separate mapping.

Completeness is checked in both directions before any summary is built. Forward: every `SUCCESS` Stage 2 record must have a matching file in `--convert-dir` (`count_variants_by_chromosome`), since its chromosome data has to come from there. Reverse: every `*.json` file currently in `--convert-dir` must have *some* Stage 2 outcome — `SUCCESS` or `FAILED` — in `--process-dir` (`verify_process_covers_convert_outputs`); a Convert output Process never even attempted indicates a broken pairing between the two directories (for example, pointing Aggregate at mismatched runs), not a normal partial-success outcome, so it fails aggregation rather than silently vanishing from the summary. A file skipped by Convert itself never appears in `--convert-dir` in the first place, so it is correctly invisible to both checks — it was never a completed unit of work this run. Both checks, plus Stage 2's own file validation, complete before the summary object is built, so a validation failure never produces a partial or empty `--output-file`.

`aggregate(convert_dir: Path, process_dir: Path) -> dict` returns the summary object; `main()` writes it to `--output-file`. Example output:

```json
{
  "variant_counts_by_chromosome": {"chr1": 2, "chr12": 1, "chr2": 1, "chr3": 1, "chrX": 2, "chrY": 2},
  "total_variant_count": 9,
  "total_skipped_rows": 3,
  "total_processing_time_seconds": 0.000421,
  "input_files_processed": ["variants_clean.json", "variants_messy.json"]
}
```

`variant_counts_by_chromosome` and `total_variant_count` are computed only from files whose Stage 2 record has `status: "SUCCESS"`: a `FAILED` file didn't pass Stage 2's own validation, so its variant data isn't trusted for the final counts, and this also guarantees the per-chromosome values always sum exactly to `total_variant_count`. `total_skipped_rows` and `total_processing_time_seconds` sum across every Stage 2 record regardless of status, since a `FAILED` file still consumed real processing time and, per Stage 2's own behavior, always contributes zero skipped rows. `input_files_processed` lists every file Stage 2 attempted — `SUCCESS` and `FAILED` alike — in sorted filename order.

Errors are surfaced the same way as Convert and Process: plain stdlib exceptions with a stdout `ERROR:` line, no custom exception type. A missing `--convert-dir` or `--process-dir`, an empty `--process-dir` (no `.json` files), a `SUCCESS` record with no matching filename in `--convert-dir`, or a Convert output with no Process outcome at all, each fail the run with a specific message rather than producing a partial or empty summary. The CLI exits 0 on success, 1 on any of these failures, and 2 for argparse usage errors.

Aggregate recomputes the full summary from scratch on every run and overwrites `--output-file` using the same shared atomic write helper as Convert and Process (`src/json_io.py`); rerunning with unchanged inputs reproduces an identical file, with no accumulation across runs and no risk of a partially written summary.

## 13. Orchestration (Planned)

Not implemented yet. Each stage's own CLI exit code is already the authoritative, tested signal of that stage's outcome (0 = success, including success with skipped/FAILED files; 1 = the stage failed; 2 = usage error) - no stage parses another stage's logs or output to decide whether it may proceed. A future runner must use exactly this signal: **run Convert, wait for it to exit, and only start Process if Convert exited 0; run Process, wait for it to exit, and only start Aggregate if Process exited 0; if any stage exits nonzero, the runner must stop the pipeline there and itself exit nonzero, without starting the next stage.** Run-directory isolation (a per-invocation `RUN_ID` selecting fresh `converted`/`processed`/`output` directories, so two pipeline invocations can never mix outputs) and the persistent per-run log file are also planned for this milestone, not present today.
