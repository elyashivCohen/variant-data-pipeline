# IdentifAI Genetics — Variant Data Pipeline

A three-stage batch pipeline (Convert → Process → Aggregate) that turns CSV variant data into a JSON summary. Built for the IdentifAI Genetics Software Engineering Intern take-home assessment (assignment brief kept out of this repo per its own instructions; `AGENTS.md` records that convention).

## Prerequisites

- **Docker Desktop (or engine) with Compose v2, running.** `docker compose version` should succeed before anything below will work.
- **Windows + PowerShell** to run `run_pipeline.ps1` (Windows PowerShell 5.1 or PowerShell 7+). On macOS/Linux, or without PowerShell, use the Bash commands in "Running stages manually" below — the depends_on chain does the same sequencing either way; only the automatic run-numbering launcher is PowerShell-only.
- No Python installation is required on the host, for either the pipeline or the tests.

## Quick start

```powershell
.\run_pipeline.ps1
if ($LASTEXITCODE -ne 0) { Write-Output "Pipeline failed (exit $LASTEXITCODE)" } else { Write-Output "Pipeline succeeded" }
```

This allocates a fresh `output/run_<N>/` directory (see "Run numbering" below), prints its `RUN_ID` and path, builds the image if needed, and runs Convert → Process → Aggregate in order. **Only Aggregate's own log output streams to the console** (see "Exit codes and dependency behavior" below for why); Convert's and Process's build/lifecycle events are still shown, but their `INFO`/`WARNING`/`ERROR` lines are not printed live — they're always in `output/<RUN_ID>/logs/{convert,process}.log`, complete, whether or not the run succeeded. `$LASTEXITCODE` is **0** only if all three stages completed; any other value means something failed — check `output/<RUN_ID>/logs/*.log` for which stage and why.

**Run the test suite (containerized, no host Python):**

```
docker compose run --build --rm tests
```

Runs the full `unittest` suite inside the image; exits nonzero on any failure. Works from a fresh shell with no `RUN_ID` set (see "Two Compose files" below for why that's guaranteed, not incidental).

## Run numbering

- Runs are numbered `run_1`, `run_2`, `run_3`, ... under `output/`. The launcher lists `output/`, keeps only entries matching `run_<number>` exactly (everything else is ignored), and allocates the highest existing number plus 1 — or `run_1` if none exist. E.g. `run_1`, `run_2`, `run_5` present → next is `run_6`.
- No separate counter file: numbering is derived fresh each time, so deleting all `run_<N>` directories resets it to `run_1`.
- One `RUN_ID` is allocated per invocation and passed to all three stages; each reads/writes only `output/<RUN_ID>/...` and never touches another run's directory. The target directory is created without overwriting an existing one — if that fails, the launcher reports the error and stops before touching Docker.
- **Sequential local use only.** Two launchers racing to allocate at the same moment are unsupported (the scan-then-create step isn't locked). Run one at a time.

## Output and log locations

```
output/<RUN_ID>/convert/    Convert's JSON output (one file per input CSV)
output/<RUN_ID>/process/    Process's per-input metrics
output/<RUN_ID>/aggregate/  summary.json
output/<RUN_ID>/logs/       convert.log, process.log, aggregate.log
```

## Configuring the Process delay

Process defaults to a 30-second simulated compute delay per input file, as required. Override with `PROCESS_SLEEP_SECONDS` (passed through to the container) for faster local runs:

```powershell
$env:PROCESS_SLEEP_SECONDS = "0"; .\run_pipeline.ps1; Remove-Item Env:\PROCESS_SLEEP_SECONDS
```
```bash
PROCESS_SLEEP_SECONDS=0 docker compose -f docker-compose.pipeline.yml run --rm process
```

## Architecture and data flow

```
input/*.csv → Convert → output/<RUN_ID>/convert/*.json
                              → Process → output/<RUN_ID>/process/*.json
                                              → Aggregate → output/<RUN_ID>/aggregate/summary.json
```

Stages communicate only through JSON files in mounted host directories — no network calls, no shared database. Convert and Aggregate are containerized; Process is too (all three, exceeding the assignment's "containerize at least Convert" requirement). One shared `Dockerfile`/image backs all stage containers plus a separate `tests` container; Compose's `depends_on: condition: service_completed_successfully` is the *only* place stage sequencing is implemented — `run_pipeline.ps1` just allocates the RUN_ID and invokes one Compose command.

### Two Compose files

`docker-compose.yml` (the Compose default, auto-loaded) holds only the `tests` service — no `RUN_ID`, no volumes, so `docker compose run --build --rm tests` works from a fresh shell. `docker-compose.pipeline.yml` holds Convert/Process/Aggregate and requires `RUN_ID` (`${RUN_ID:?RUN_ID must be set}` — refuses to run, before any container starts, if unset). They're two files because Compose interpolates every service's variables in a file up front regardless of which service is targeted, so a `RUN_ID` requirement anywhere in the same file as `tests` would break the no-`RUN_ID` tests command.

### Exit codes and dependency behavior

`run_pipeline.ps1` runs `docker compose -f docker-compose.pipeline.yml run --build --rm aggregate` — not `up`. Compose's `depends_on` still starts Convert then Process first unchanged (the only sequencing implementation), but `docker compose run <service>` returns that service's own exit code directly, which `up` does not reliably do once nothing downstream is blocked by a failure (verified directly: forcing Aggregate alone to fail left `docker compose up` returning 0 despite Aggregate exiting 1). `--abort-on-container-exit`/`--exit-code-from` were tried and rejected for the same reason: verified to abort the whole run the moment Convert exited *successfully*, racing Process starting.

Verified against real Docker: success returns 0; Convert, Process, or Aggregate each failing returns nonzero, with every stage after the failure never starting. Individual stage exit codes (0/1/2 — see "Stage contracts") aren't distinguished in the launcher's own final code; check `output/<RUN_ID>/logs/*.log` for which stage failed and why.

**Trade-off:** `docker compose run <service>` only streams the *primary* service's own log output to the console — Convert's and Process's `INFO`/`WARNING`/`ERROR` lines don't print live (only their container lifecycle events do; `docker compose up` would stream everything, but doesn't fix the exit-code problem above). Nothing is lost: every stage's complete log is always in `output/<RUN_ID>/logs/*.log`.

## Running stages manually (debugging reference)

```powershell
$env:RUN_ID = "run_1"
New-Item -ItemType Directory -Force -Path `
  "output/$env:RUN_ID/convert", "output/$env:RUN_ID/process", `
  "output/$env:RUN_ID/aggregate", "output/$env:RUN_ID/logs" | Out-Null

docker compose -f docker-compose.pipeline.yml build

docker compose -f docker-compose.pipeline.yml run --rm convert
if ($LASTEXITCODE -ne 0) { throw "Convert failed (exit $LASTEXITCODE)" }

docker compose -f docker-compose.pipeline.yml run --no-deps --rm process
if ($LASTEXITCODE -ne 0) { throw "Process failed (exit $LASTEXITCODE)" }

docker compose -f docker-compose.pipeline.yml run --no-deps --rm aggregate
if ($LASTEXITCODE -ne 0) { throw "Aggregate failed (exit $LASTEXITCODE)" }

Get-Content "output/$env:RUN_ID/aggregate/summary.json"
```

```bash
export RUN_ID=run_1
mkdir -p "output/$RUN_ID"/{convert,process,aggregate,logs}

docker compose -f docker-compose.pipeline.yml build
docker compose -f docker-compose.pipeline.yml run --rm convert            || { echo "Convert failed"; exit 1; }
docker compose -f docker-compose.pipeline.yml run --no-deps --rm process   || { echo "Process failed"; exit 1; }
docker compose -f docker-compose.pipeline.yml run --no-deps --rm aggregate || { echo "Aggregate failed"; exit 1; }

cat "output/$RUN_ID/aggregate/summary.json"
```

`--no-deps` on `process` and `aggregate` is required, not optional: both declare `depends_on`, and without `--no-deps`, `docker compose run --rm process` was verified to *also* run `convert` first — defeating the point of running one stage in isolation. `convert` has no dependency, so it's unaffected. `docker compose run --rm <service>` always creates a fresh, ephemeral container. A different `RUN_ID` starts a completely independent run.

To point `convert` at a different input directory manually, set `INPUT_DIR` before running it: `$env:INPUT_DIR = (Resolve-Path <path>).Path` / `export INPUT_DIR=$(pwd)/<path>`. Unset, it defaults to `./input`.

*Verification scope:* the PowerShell block above, and every underlying `docker compose` command in the Bash block, have been run directly against real Docker on this Windows host (Git Bash, not a separate Linux/macOS machine) during this project. The Bash block as one literal end-to-end sequence, and any behavior specific to a real Linux or macOS host, were reviewed for syntax but not executed there — labeled here rather than left unstated.

### Mounts

| Service | Reads | Writes |
|---|---|---|
| `convert` | `input/` (ro; or `$INPUT_DIR`, see above) | `output/<RUN_ID>/convert/`, `output/<RUN_ID>/logs/` |
| `process` | `output/<RUN_ID>/convert/` (ro) | `output/<RUN_ID>/process/`, `output/<RUN_ID>/logs/` |
| `aggregate` | `output/<RUN_ID>/convert/` (ro), `output/<RUN_ID>/process/` (ro) | `output/<RUN_ID>/aggregate/`, `output/<RUN_ID>/logs/` |

## Error-handling examples

Four small, reusable example inputs live under `examples/error_handling/`, separate from `input/` and never used by default — pass `-InputDir` to run one:

```powershell
$env:PROCESS_SLEEP_SECONDS = "0"
.\run_pipeline.ps1 -InputDir examples\error_handling\<scenario>
Write-Output "Exit code: $LASTEXITCODE"
```

On Bash (no PowerShell launcher — use the manual commands from "Running stages manually" with `INPUT_DIR` set):

```bash
export RUN_ID=example_run
mkdir -p "output/$RUN_ID"/{convert,process,aggregate,logs}
export INPUT_DIR=$(pwd)/examples/error_handling/<scenario>
export PROCESS_SLEEP_SECONDS=0
docker compose -f docker-compose.pipeline.yml run --rm convert            || { echo "Convert failed"; exit 1; }
docker compose -f docker-compose.pipeline.yml run --no-deps --rm process   || { echo "Process failed"; exit 1; }
docker compose -f docker-compose.pipeline.yml run --no-deps --rm aggregate || { echo "Aggregate failed"; exit 1; }
```

| Scenario | Input | Demonstrates | Result (verified) |
|---|---|---|---|
| `valid/` | 4 well-formed rows | Full success | `wrote 4 records; skipped 0`; summary shows 4 variants/0 skipped; exit **0** |
| `mixed/` | 5 rows, 3 deliberately invalid (empty `index`, non-numeric `POS`, empty `ALT`) | **Skipped row**: bad records logged and dropped, file still succeeds | 3× `WARNING`, then `wrote 2 records; skipped 3`; exit **0** |
| `partial_failure/` | One valid file + one file missing the `REF` column | **Failed input file**: bad file skipped and logged, good file still processed | `ERROR: ...skipping file: ...missing required columns: REF`; summary reflects only the good file (3 variants); exit **0** |
| `missing_column/` | One file only, missing the `ALT` column | **Stage failure**: the *only* file fails, so the whole batch fails | `ERROR` naming the file and column, then `No input file ... converted successfully`; Process/Aggregate never start (their directories stay empty); exit **1** |

The difference between `partial_failure/` (batch still succeeds) and `missing_column/` (batch fails) is exactly the "zero successes" rule in Convert's contract below — same file-level error, different outcome, because of what else is in the batch.

## Stage contracts

All three stages are stdlib-only Python, log via `src.logging_setup` (console always; `--log-file`/`LOG_FILE` optionally appends to a file — console format `LEVEL: message`, file format adds a timestamp and logger name), and write output via `src/json_io.py`'s atomic temp-file-then-replace helper (a write failure never leaves a corrupt or partial output). Exit codes are consistent across all three: **0** success (including success with skipped rows/files), **1** stage failure, **2** configuration/usage error (bad CLI args, unopenable `--log-file`).

**Convert** (`--input-dir`, `--output-dir`, columns `index`/`CHROM`/`POS`/`REF`/`ALT`): validates UTF-8 CSVs, trims/deduplicates headers, requires all five columns (extra columns ignored, order-independent). Per-row errors (blank/malformed fields, non-positive `POS`, wrong field count) are logged as `WARNING` and skipped — the rest of the file continues. Per-file errors (unreadable, bad/duplicate header, CSV parse failure) are logged as `ERROR` and that file is skipped — the rest of the batch continues. The batch fails only if **zero** files convert successfully. A write failure is always fatal, immediately, regardless of earlier successes.

**Process** (`--input-dir`, `--output-dir`, `--sleep-seconds` or `PROCESS_SLEEP_SECONDS`, default 30s): reads each Convert output, sleeps the configured duration, and writes one metrics file (`input_file`, `status`, `start_time`, `end_time`, `duration_seconds`, `row_count`, `skipped_row_count`). A file that fails an input check (missing/malformed JSON, bad schema) is recorded `status: "FAILED"` and the batch continues; an unexpected error or write failure propagates and aborts the batch. Fails only if **zero** files succeed.

**Aggregate** (`--convert-dir`, `--process-dir`, `--output-file`): cross-checks that every `SUCCESS` Process record has a matching Convert file, and every Convert output has *some* Process outcome (`SUCCESS` or `FAILED`) — a mismatch fails aggregation before any output is written. Combines everything into `summary.json`: `variant_counts_by_chromosome` and `total_variant_count` from `SUCCESS` files only; `total_skipped_rows` and `total_processing_time_seconds` across all files; `input_files_processed` lists every file Process attempted. Recomputes from scratch every run — no accumulation.

## Idempotency

Every write goes through the same atomic temp-file-then-replace helper, so a rerun replaces outputs cleanly rather than appending or corrupting them, and a failed write leaves the previous output untouched. Beyond that, run-directory isolation is what actually prevents cross-run corruption: each `RUN_ID` gets its own `output/<RUN_ID>/` tree, so **the launcher's normal flow is always safe** — it never reuses a directory, so there is no stale output to worry about.

**Manually reusing a fixed `RUN_ID` (the debugging path above) is safe only if the input set is unchanged.** Verified: rerunning with the exact same input files reproduces an identical summary (timing fields aside). But rerunning with a *changed* input set against the same `RUN_ID` — a file removed, renamed, or replaced with something Convert would now reject — was verified to leave that file's **previous** JSON output sitting in `output/<RUN_ID>/convert/` untouched, since Convert only writes output for files it currently sees; Process and Aggregate then pick that stale file up as if it were current, because neither stage compares against the live input directory. The result: a "successful" run (exit 0) whose summary silently still includes data for a file that's no longer part of the input. This is a real limitation of the manual-reuse path, not yet fixed. Use a fresh `RUN_ID` (the default launcher behavior) whenever the input set changes.

## Assumptions

- Each input CSV has a header containing the required columns; extra columns and reordering are tolerated.
- Each input file is converted/processed independently; aggregation is the only cross-file step.
- "Total processing time" means the sum of Process-stage durations, including the simulated delay.
- `RUN_ID` is a local output namespace for one invocation, not a dataset/job identity — a distributed version would need a real dataset/job ID instead.
- The reviewer's Docker install can reach Docker Hub to pull `python:3.12-slim` on first build.

## Design decisions and trade-offs

- **JSON everywhere** for readability and because the assignment doesn't prescribe a schema; no database — the pipeline is a local batch job, and shared host directories are sufficient state between stages.
- **Compose depends_on over a custom orchestrator**: initially built a small Python/PowerShell runner that manually invoked each stage in sequence; replaced it once verification showed Compose's own dependency graph does the same job with no custom sequencing code to maintain (see git history for that iteration — kept, not squashed).
- **Numbered run directories over a single fixed output path**: chosen so a rerun can never mix or corrupt another run's output, without needing a cleanup step.
- **`--no-deps` for manual single-stage runs**: `depends_on` is correct for full pipeline runs but actively wrong for isolated debugging of one stage; documented explicitly since it's easy to miss.
- **Non-root container user**: all four services (`convert`/`process`/`aggregate`/`tests`) run as UID 1000 by default (`appuser` in the image), not root. Every file each stage writes is created at mode `0600` (owner-only - Python's own `tempfile` default, used by `json_io.write_json_safely`), so **all three pipeline services must run as the same UID**, or a later stage gets `Permission denied` reading an earlier stage's output - confirmed directly by deliberately mismatching them. A per-command `docker compose run --user ...` flag does **not** fix this: it only overrides the one service named on the command line, not the `depends_on` services Compose starts alongside it - also confirmed directly (`convert`/`process` kept running as UID 1000 despite `--user` being set on the `aggregate` invocation). The actual fix, `PIPELINE_UID`/`PIPELINE_GID` (optional env vars, default `1000`/`1000`), is applied uniformly to all three services via `user:` in `docker-compose.pipeline.yml` itself - confirmed working for both the default and an overridden, consistent UID across all three. Needed on native Linux hosts where the host user isn't UID 1000 (the launcher creates `output/<RUN_ID>/...` as whatever user runs it, and that directory's host-filesystem ownership must be readable/writable by whichever UID the containers run as): set `PIPELINE_UID=$(id -u) PIPELINE_GID=$(id -g)` before running. **Verified on Docker Desktop (Windows) only** - real Linux host-directory ownership enforcement (distinct from the container-to-container UID mismatch confirmed above, which reproduces identically on Docker Desktop) was not tested on an actual Linux host in this session.

## Testing

```
docker compose run --build --rm tests
```

or, with a host Python install, `python -B tests/run_tests.py` (also available as `python -B -m unittest discover -s tests -v`). Covers: row/file/batch-level error handling for all three stages, header and CSV-parser failures, output preservation and safe reruns, mocked I/O failures, CLI exit codes, and end-to-end runs against the real sample data. 71 tests total; one pre-existing skip on Windows (a symlink-permission test Windows denies outside admin).

## Part 2 — Cloud scale (AWS)

*Design proposal only — nothing below is implemented or deployed. This is a sketch of how the same three stages would run on AWS for thousands of files, not a description of the local Compose pipeline above.*

**Services and why:** container images in **ECR**; input/output in **S3** (`s3://bucket/<dataset_id>/{input,convert,process,aggregate}/...` — `dataset_id` replaces the local `RUN_ID` as the output namespace). Compute is **AWS Batch on Fargate**: one job definition per stage, same container images and CLI entry points unchanged. `src/convert.py`/`process.py`/`aggregate.py` still only know how to read and write local paths - they are not modified to understand `s3://` URLs. A small wrapper around the existing entrypoint downloads that job's input file(s) from S3 to local container storage before invoking the unchanged CLI, and uploads the resulting output file(s) back to S3 afterward. Batch was chosen because it has **native job dependencies** (a job only starts once its declared dependencies succeed, and **automatically transitions to FAILED if a dependency fails** — confirmed against current AWS Batch documentation) — the same semantics as Compose's `depends_on`, re-hosted rather than redesigned. Convert and Process each run as one Batch job **per input file** (the unit of work is one file, not the dataset); Aggregate stays one job per dataset.

**Establishing the file set, without racing live uploads:** the set of expected files must be known *before* completion is ever checked, so it can't come from listing S3 mid-upload. Instead, the uploader writes every input file, then writes one explicit **manifest object** last (`s3://bucket/<dataset_id>/manifest.json`, listing every expected file key). Only the manifest's own `ObjectCreated` event registers the dataset in DynamoDB (`expected_file_count`, `completed_count: 0`) and triggers fan-out — individual file uploads before the manifest exists don't start anything on their own, so there's no window where "processing" can run ahead of "how many files there are."

**Fan-out and per-file terminal status, including a Convert failure:** the manifest event goes to **SQS** (buffering a burst of one event instead of thousands); a **Lambda** consuming that queue submits, for each listed file, a Convert Batch job and a Process Batch job with `dependsOn` the Convert job's ID. If Convert fails, Process **never runs** but still transitions PENDING→FAILED automatically (Batch's own dependency-failure behavior) — and that transition **is itself a job state-change event**, identical in shape to a normal SUCCEEDED/FAILED one. A second small Lambda, subscribed to Process job state-change events via EventBridge, is the **single place** that ever records a file's terminal outcome — whether Process actually ran and failed, or never ran because Convert failed, the event looks the same and is handled the same way. Nothing upstream (Convert) needs its own separate reporting path.

**Consistency and idempotency under retries/duplicate events:** that Lambda does one **DynamoDB `TransactWriteItems`** call per event — conditionally updating the file's own item (only if its status is still `PENDING`) *and* incrementing the dataset's `completed_count`, atomically (confirmed against current DynamoDB documentation: an all-or-nothing, conditioned multi-item write). A duplicate or retried event for an already-terminal file fails its condition and changes nothing, so the counter can never be incremented twice for the same file. S3 keys are deterministic per `dataset_id/file_id/stage`, so a retried job also overwrites its own prior output rather than creating a new one, and because every key and counter is namespaced by `dataset_id`, two datasets processed concurrently never share either.

**Submitting Aggregate without duplicates - not a guaranteed exactly-once:** after the transaction above, the same Lambda checks `completed_count == expected_file_count`. If true, it does one more conditional update - `SET aggregate_submitted = true` only if that flag isn't already set - and only the invocation that wins this check calls Batch `SubmitJob` for Aggregate; every other concurrent/duplicate invocation sees the flag already set and does nothing - the conditional flag prevents competing handlers from *both* submitting in this normal path. It doesn't cover every case: if `SubmitJob` itself fails after the flag was already set (a transient AWS API error), the dataset is left with every file terminal, the flag set, and no Aggregate job ever created - an ambiguous outcome (was it submitted or not?) that needs a recovery path, not just the flag. The honest gap: a small scheduled reconciliation job (e.g. an hourly EventBridge Scheduler rule) checking for datasets stuck in exactly that state would be needed to actually close it - and that reconciliation retry is itself a second submission attempt, so it has to tolerate Aggregate possibly already having run rather than assume the flag alone guarantees it never did; not built here.

**What Aggregate does with partial or total failure:** Aggregate always runs once triggered, and lists `FAILED` files while excluding them from variant counts - the same per-file distinction the local Aggregate already makes. **This is a deliberate change from local behavior for the total-failure case, not a restatement of it:** locally, if zero files convert successfully, Convert's own stage-level failure blocks Process and Aggregate from ever starting - no summary is produced at all. At the cloud design's per-file granularity, "zero files succeeded across the dataset" is an ordinary outcome of the same fan-out that lets healthy files succeed independently, so Aggregate still runs and reports it: an all-FAILED summary (zero variants, every file listed as FAILED), not a suppressed run. Whether that's the right choice, or whether a total failure should instead skip Aggregate and alert directly, is a real product decision this sketch doesn't resolve.

**One thing that could go wrong at scale, and the mitigation:** a burst of uploads across many datasets at once could submit more Batch jobs than the compute environment's `maxvCpus` ceiling supports. Mitigation: Batch queues the excess instead of failing it - the pipeline slows down under load rather than erroring - and the SQS buffer already smooths the submission burst itself.

**What to monitor:** the percentage of files reaching `FAILED` status per dataset (is the *data* healthy) and the Batch job queue's age/backlog (is the *pipeline* keeping up).

**Assumptions:** one AWS account/region; the uploader can reliably write a manifest last (or an equivalent explicit "done" signal - a real upload client, not S3 listing, is what defines "the file set"); "thousands of files" means thousands of *jobs*, not files large enough to need multipart/streaming reads within a single job.

## What I'd improve with more time

- Detect a changed input set when a `RUN_ID` is manually reused, instead of silently leaving stale per-file output behind (see "Idempotency" above).
- A cross-platform (Bash/`Makefile`) equivalent of `run_pipeline.ps1`'s run-numbering logic, so the automatic launcher isn't Windows-only.
- Structured (JSON) logging, to make `output/<RUN_ID>/logs/*.log` machine-parseable instead of just human-readable.
- Locking around run-ID allocation, if concurrent local launches ever became a real need (currently explicitly unsupported).

## AI tool usage

A few tools were tried early on to get started, including **Codex**. The project then settled on **Claude Code** (Claude Sonnet 5) as the main implementation tool — design discussion, all three stages and their tests, the Dockerfile and both Compose files, the PowerShell launcher, and this README. **ChatGPT** was used separately, alongside Claude Code, to help understand the pipeline, the existing code, and the reasoning behind specific design decisions, rather than for implementation.

**An example of correcting/overriding AI output:** Claude Code's default instinct for making a rerun-safe `RUN_ID` was to build a dedicated "cleanup" container — its own image, symlink-safety checks, the works — to reset a run directory before reuse. That was rejected explicitly ("I want to finish the assignment without adding unnecessary infrastructure") in favor of the much simpler design actually shipped: numbered `run_<N>` directories that are never reused, so there's nothing to clean up. The same pattern happened with orchestration itself — an initial custom Python runner that duplicated Compose's own sequencing logic was removed once it was clear `depends_on` already did the job.

**Best for this kind of work:** exploring Docker Compose/exit-code semantics quickly (many small hypotheses to test), writing thorough unit tests once a contract is pinned down, and keeping documentation in sync with a fast-moving implementation.

**Worst for this kind of work:** defaulting to more infrastructure than a task needs unless explicitly reined in (see the cleanup-container example above), and confidently asserting how a tool (Compose flags, shell exit-code propagation) behaves without having actually run it — several claims in this README were only made *after* being verified against real Docker specifically because an earlier AI-stated assumption turned out to be wrong once tested.
