# IdentifAI Genetics — Variant Data Pipeline

## 1. Project Overview

This Software Engineering Intern take-home assignment builds a three-stage pipeline to convert CSV variant data, simulate processing, and aggregate results. This README outlines the initial local design; implementation is pending.

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

JSON is the proposed intermediate and summary format: it is readable and supports records alongside metadata. Each input will have one converted output and one processed output.

Files persisted to disk between stages will act as the local pipeline state. Inputs will remain unchanged, and shared host directories will preserve outputs across container runs. No database is planned. This approach keeps the batch workflow simple; concurrent execution is outside the initial design.

## 6. Logging Strategy

Logs will go to stdout/stderr so Docker can collect them. Informational messages will report stage progress and completion. Each skipped row will generate a warning with the input filename, row location, and reason. Errors will identify file-level or stage-level failures. Aggregation will use persisted metrics rather than parse logs.

## 7. Idempotency Strategy

Outputs will use deterministic paths: `input/sample.csv` will map to `data/converted/sample.json` and `data/processed/sample.json`. Reruns will regenerate and overwrite expected outputs instead of appending duplicates.

The summary will be rebuilt from the current run's processed results, excluding stale outputs. Safe overwrite behavior will be defined and tested during implementation to prevent partial writes from corrupting data.

Unchanged inputs will produce the same variant and skipped-row totals on repeated runs. Timing metadata may change because processing runs again.

## 8. Initial Development Plan

1. Define row validation, JSON structures, and handling for missing headers, unreadable files, empty inputs, and files with no valid rows.
2. Implement Convert with per-row warnings and safe output writes.
3. Implement Process with a configurable delay and per-input metrics.
4. Implement Aggregate and a sequential runner that selects current-run outputs.
5. Test valid and malformed data, aggregation, repeat runs, stale outputs, and failure handling.
6. Containerize the stages and verify the full local workflow with shared persistent directories.
7. Add verified run/test commands, AI workflow notes, and implementation trade-offs to this README.
