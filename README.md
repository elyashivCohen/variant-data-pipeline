# IdentifAI Genetics — Variant Data Pipeline

## Overview and architecture

A three-stage batch pipeline — **Convert** (CSV → JSON) → **Process** (simulated compute + metrics) → **Aggregate** (summary JSON) — built for the IdentifAI Genetics Software Engineering Intern take-home assessment (assignment brief kept out of this repo per its own instructions; `AGENTS.md` records that convention).

All three stages are containerized from one image and sequenced by Docker Compose's `depends_on: condition: service_completed_successfully` — there is no other orchestration code, and everything lives in one `docker-compose.yml`. Stages hand off data as JSON files in one Docker-managed named volume; nothing touches the network or a database. Every stage runs as a fixed non-root user; the one exception is a one-off `init` step (root, solely to fix the shared volume's ownership) that runs before Convert on every invocation and also resets the volume — see "Output locations, inspection, and export" below.

## Prerequisites

- Docker (or Docker Desktop) with Compose v2, running — `docker compose version` should succeed.
- No host Python installation is required for the pipeline or the tests.
- The image build pulls `python:3.12-slim` from Docker Hub on first use.

> GitHub Codespaces uses Bash by default: copy the Bash blocks. On Windows, use the PowerShell blocks when running in PowerShell.

## Running the pipeline

**Default run** — the original `input/` directory (`INPUT_DIR` unset) and the required 30s simulated compute delay per file (`PROCESS_SLEEP_SECONDS` unset):

**All platforms — Bash or PowerShell**

```bash
docker compose run --build --rm aggregate
```

Exit code **0** means all three stages completed; anything else means a stage failed — see "Output locations, inspection, and export" below to find out which one and why.

**Fast run** (skip the delay, for local iteration):

**Linux / macOS / GitHub Codespaces — Bash**

```bash
PROCESS_SLEEP_SECONDS=0 docker compose run --build --rm aggregate
```

**Windows — PowerShell**

```powershell
$env:PROCESS_SLEEP_SECONDS = "0"
docker compose run --build --rm aggregate
Remove-Item Env:\PROCESS_SLEEP_SECONDS
```

`PROCESS_SLEEP_SECONDS` accepts any finite, non-negative number; unset, it defaults to **30**. An invalid value (non-numeric or negative) fails clearly: Process exits **2** and the primary command's own exit code is nonzero.

> **Bash vs. PowerShell environment overrides:** the Bash form (`VAR=value command`) scopes the override to that one command only — nothing to clean up afterward. PowerShell's `$env:VAR = ...` instead persists for the rest of the current session until you `Remove-Item Env:\VAR` or close the shell, so every PowerShell block below removes what it sets. Also note `$LASTEXITCODE` (not `$?`, which is a boolean, not a numeric exit code) is what carries a command's real exit code in PowerShell.

## Running tests

**All platforms — Bash or PowerShell**

```
docker compose run --build --rm tests
```

Runs the full `unittest` suite inside the image. `tests` has no dependency on the pipeline services and never mounts the output volume, so running it never touches pipeline output.

## Output locations, inspection, and export

All three stages write into one Docker-managed named volume (`pipeline-output`), mounted at `/app/run` in every stage container:

```
/app/run/convert/    Convert's JSON output (one file per input CSV)
/app/run/process/    Process's per-input metrics
/app/run/aggregate/  summary.json
/app/run/logs/       convert.log, process.log, aggregate.log
```

**Every pipeline run starts from a clean slate.** The `init` service wipes and recreates the four directories above, then hands them to the same non-root user every stage runs as, before Convert ever starts. So a run never sees a previous run's leftover files, and a run that fails never leaves a stale `summary.json` behind. **Concurrent pipeline invocations are unsupported — run one at a time**; two overlapping `docker compose run` calls would race to wipe and repopulate the same volume.

View the summary or a log without knowing Docker's internal volume name (same command in both shells):

**All platforms — Bash or PowerShell**

```
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/aggregate/summary.json
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint sh aggregate -c "cat /app/run/logs/*.log"
```

All three use `--no-deps`, so they never run `init` or the pipeline — they only read whatever the last real run left behind.

**Export everything to a host folder.** This copies all four directories under `/app/run` straight into a folder you choose — it never mounts or modifies the repository itself:

**Linux / macOS / GitHub Codespaces — Bash**

```bash
mkdir -p exported-output
docker compose run --rm --no-deps -v "$(pwd)/exported-output:/export" -u root --entrypoint sh aggregate -c "cp -a /app/run/. /export/ && chmod -R a+rX /export"
```

**Windows — PowerShell**

```powershell
New-Item -ItemType Directory -Force -Path exported-output | Out-Null
docker compose run --rm --no-deps -v "${PWD}\exported-output:/export" -u root --entrypoint sh aggregate -c "cp -a /app/run/. /export/ && chmod -R a+rX /export"
```

`-u root` + `chmod -R a+rX` (read/traverse only, not `chmod 777`) guarantees the copy is host-readable regardless of the container's internal UID. Reusing the same destination across multiple exports can leave old files behind if a later run no longer produces them, so use a fresh or emptied destination for an exact snapshot. Outputs persist in the volume across container removal but are replaced by the next pipeline run.

## Error-handling examples

Four small inputs under `examples/error_handling/` (separate from `input/`, never used by default) exercise Convert's error handling end to end. Each block below is self-contained and ready to copy — no placeholder to fill in.

### `valid/` — full success

**Linux / macOS / GitHub Codespaces — Bash**

```bash
INPUT_DIR="$(pwd)/examples/error_handling/valid" PROCESS_SLEEP_SECONDS=0 docker compose run --build --rm aggregate
code=$?
echo "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/aggregate/summary.json
```

**Windows — PowerShell**

```powershell
$env:INPUT_DIR = (Resolve-Path examples\error_handling\valid).Path
$env:PROCESS_SLEEP_SECONDS = "0"
docker compose run --build --rm aggregate
$code = $LASTEXITCODE
Write-Output "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/aggregate/summary.json
Remove-Item Env:\INPUT_DIR, Env:\PROCESS_SLEEP_SECONDS
```

Expect: `wrote 4 records; skipped 0` in the log; summary shows 4 variants across 4 chromosomes, 0 skipped; **exit 0**.

### `mixed/` — bad rows skipped, file still succeeds

**Linux / macOS / GitHub Codespaces — Bash**

```bash
INPUT_DIR="$(pwd)/examples/error_handling/mixed" PROCESS_SLEEP_SECONDS=0 docker compose run --build --rm aggregate
code=$?
echo "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/aggregate/summary.json
```

**Windows — PowerShell**

```powershell
$env:INPUT_DIR = (Resolve-Path examples\error_handling\mixed).Path
$env:PROCESS_SLEEP_SECONDS = "0"
docker compose run --build --rm aggregate
$code = $LASTEXITCODE
Write-Output "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/aggregate/summary.json
Remove-Item Env:\INPUT_DIR, Env:\PROCESS_SLEEP_SECONDS
```

Expect: 3× `WARNING` (empty `index`, non-numeric `POS`, empty `ALT`), then `wrote 2 records; skipped 3`; summary shows 2 variants, 3 skipped rows; **exit 0**.

### `partial_failure/` — one bad file skipped, one good file still processed

**Linux / macOS / GitHub Codespaces — Bash**

```bash
INPUT_DIR="$(pwd)/examples/error_handling/partial_failure" PROCESS_SLEEP_SECONDS=0 docker compose run --build --rm aggregate
code=$?
echo "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/aggregate/summary.json
```

**Windows — PowerShell**

```powershell
$env:INPUT_DIR = (Resolve-Path examples\error_handling\partial_failure).Path
$env:PROCESS_SLEEP_SECONDS = "0"
docker compose run --build --rm aggregate
$code = $LASTEXITCODE
Write-Output "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/aggregate/summary.json
Remove-Item Env:\INPUT_DIR, Env:\PROCESS_SLEEP_SECONDS
```

Expect: `ERROR: ...skipping file: ...missing required columns: REF`; summary reflects only the good file (3 variants); **exit 0**.

### `missing_column/` — the only file fails, so the whole batch fails

**Linux / macOS / GitHub Codespaces — Bash**

```bash
INPUT_DIR="$(pwd)/examples/error_handling/missing_column" PROCESS_SLEEP_SECONDS=0 docker compose run --build --rm aggregate
code=$?
echo "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint sh aggregate -c "test -f /app/run/aggregate/summary.json && echo 'STALE SUMMARY FOUND' || echo 'No summary.json (expected: Convert failed, so Aggregate never ran)'"
```

**Windows — PowerShell**

```powershell
$env:INPUT_DIR = (Resolve-Path examples\error_handling\missing_column).Path
$env:PROCESS_SLEEP_SECONDS = "0"
docker compose run --build --rm aggregate
$code = $LASTEXITCODE
Write-Output "Exit code: $code"
docker compose run --rm --no-deps --entrypoint cat aggregate /app/run/logs/convert.log
docker compose run --rm --no-deps --entrypoint sh aggregate -c "test -f /app/run/aggregate/summary.json && echo 'STALE SUMMARY FOUND' || echo 'No summary.json (expected: Convert failed, so Aggregate never ran)'"
Remove-Item Env:\INPUT_DIR, Env:\PROCESS_SLEEP_SECONDS
```

Expect: `ERROR` naming the file and the missing `ALT` column; Process/Aggregate never start; the `test -f` check reports no `summary.json`; **exit 1**.

`partial_failure/` succeeds and `missing_column/` fails for the same reason: Convert only fails the batch when **zero** files convert successfully (see below).

## Stage behavior and limitations

All three stages are stdlib-only Python, log via `src.logging_setup` (console always; `--log-file`/`LOG_FILE` optionally appends to a file), and write output via `src/json_io.py`'s atomic temp-file-then-replace helper (a write failure never leaves a corrupt or partial output). Exit codes: **0** success (including skipped rows/files), **1** stage failure, **2** configuration/usage error.

**Convert** (`--input-dir`, `--output-dir`, columns `index`/`CHROM`/`POS`/`REF`/`ALT`): validates UTF-8 CSVs, trims header whitespace, and **rejects** (does not silently drop) a header with duplicate column names; requires all five required columns (extra columns ignored, order-independent). Per-row errors are logged as `WARNING` and skipped; per-file errors (unreadable, bad header, parse failure) are logged as `ERROR` and that file is skipped. From that per-file-skipping path alone, the batch fails only if **zero** files convert successfully. Separately — regardless of how many files already succeeded — a failure while *writing* an output, or any other unexpected error, is never treated as skippable: it aborts the run immediately (exit 1), even if earlier files in the same run were already converted and written to disk.

**Process** (`--input-dir`, `--output-dir`, `--sleep-seconds` or `PROCESS_SLEEP_SECONDS`, default 30s): reads each Convert output, sleeps the configured duration, and writes one metrics file (`input_file`, `status`, `start_time`, `end_time`, `duration_seconds`, `row_count`, `skipped_row_count`). A file with a bad input (missing/malformed JSON, bad schema) is recorded `status: "FAILED"` and the batch continues; from that path alone, the batch fails only if zero files succeed. Separately, a write failure or any other unexpected error aborts the batch immediately, even if earlier files already succeeded.

**Aggregate** (`--convert-dir`, `--process-dir`, `--output-file`): before writing anything, cross-checks two directions — every current Convert output must have some Process outcome recorded, `SUCCESS` or `FAILED` (one Process never even attempted fails aggregation), and every `SUCCESS` Process record must have a matching Convert output file (a `SUCCESS` with no corresponding file also fails aggregation; a `FAILED` record needs no matching file). It then combines everything into `summary.json`: `variant_counts_by_chromosome`/`total_variant_count` from `SUCCESS` files only, `total_skipped_rows` and `total_processing_time_seconds` (the sum of Process durations, including the simulated delay) across all files, and `input_files_processed` listing every file Process attempted. Recomputes from scratch every run.

**Idempotency:** rerunning never duplicates or accumulates data — every write goes through the same atomic replace, and `init` wipes the volume's four output directories before every run, so a rerun (same, smaller, or larger input set) never mixes in a previous run's files. The resulting *counts* stay consistent across reruns of unchanged input, but Process/Aggregate outputs also record real timestamps and measured durations, so those files are **not byte-identical** between runs.

## What I'd improve with more time

- A convenient way to debug a single stage in isolation (today, that means reading its log after a full run).
- A lightweight lock around the output volume for concurrent local invocations, if that ever became a real need.
- Structured (JSON) logging, to make `/app/run/logs/*.log` machine-parseable.

## Part 2 — Cloud scale (AWS)

*Design proposal only — not implemented.* Images in ECR; input/output in S3, isolated per dataset under `s3://bucket/<dataset_id>/{input,convert,process,aggregate}/`. Compute on AWS Batch (Fargate): one Convert+Process job pair per input file, one Aggregate job per dataset; each Process job depends on its Convert job succeeding, and Batch auto-fails a dependent job when its dependency fails. The stages only read/write local paths and stay unchanged; a thin wrapper around the entrypoint downloads each job's S3 input first and uploads its output after.

An uploader writes a `manifest.json` last, listing the dataset's expected files; a Lambda fans out jobs per file, and a second Lambda records each file's terminal outcome — success or failure — via a conditional, atomic DynamoDB write, so retries can't double-count completion. When Convert fails and Process never runs, that coordination layer — not Aggregate — creates a `FAILED` record matching Aggregate's existing schema, so Aggregate's code stays unmodified. Once every file is terminal, Aggregate runs and reports on all of them, including an all-failed dataset — unlike local behavior, where zero Convert successes stops the pipeline before any summary exists. Submission is retry-safe, not exactly-once; a periodic reconciliation job resubmits Aggregate for any dataset stuck mid-flight. At scale, upload bursts could exceed the compute environment's job ceiling; Batch's own queuing absorbs it. Monitor per-dataset `FAILED` rate and queue backlog age.

References: [AWS Batch job dependencies](https://docs.aws.amazon.com/batch/latest/userguide/job_dependencies.html), [DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html).

## AI tool usage

**Claude Code** (Claude Sonnet 5) was the main implementation tool: design discussion, all three stages and their tests, the Dockerfile and Compose file, and this README. **ChatGPT** was used separately to help understand the pipeline and the reasoning behind specific decisions, not for implementation.

**Correcting AI output:** the storage design went through two rejected iterations (a dedicated "cleanup" container, then a host-bind-mount design needing a PowerShell launcher and host-UID matching) before settling on the current single named volume plus `init` service — each earlier design was explicitly rejected as more infrastructure than the task needed (full history in git log, not repeated here). Separately, an earlier README draft overstated some stage contracts with more confidence than the code actually supported (e.g. "Convert fails only if zero files succeed," omitting that a write failure aborts immediately regardless of prior successes) — caught by checking the actual source rather than restating the claim.

**Best for this kind of work:** exploring Compose/exit-code and dependency-rerun semantics quickly by testing many small hypotheses directly against real Docker, and writing thorough unit tests once a contract is pinned down.

**Worst for this kind of work:** defaulting to more infrastructure than a task needs unless explicitly reined in, and stating a contract or a tool's behavior slightly more confidently than the code or documentation actually supports until it's checked directly.
