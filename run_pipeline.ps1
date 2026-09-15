<#
.SYNOPSIS
    Allocate a fresh run_<N> directory and run the Dockerized pipeline for it.

.DESCRIPTION
    Requires only Docker Desktop with Compose - no host Python. Scans
    output/ for existing run_<N> directories, picks the next number (max+1,
    or 1 if none exist), creates output/run_<N>/{convert,process,aggregate,logs}
    without overwriting anything, then invokes the single Compose command
    that runs Convert, Process, and Aggregate in order (see README, "Exit
    codes and dependency behavior"). All three stages read/write only this
    run's own directory tree.

    Does not run the stages individually and does not duplicate Compose's
    own depends_on/service_completed_successfully sequencing - it only
    allocates RUN_ID and calls `docker compose run --rm aggregate`.

    Sequential local invocations only: running this script twice at the same
    time is unsupported (see README, "Run numbering").

.PARAMETER InputDir
    Optional. Directory of CSVs for Convert to read instead of the normal
    input/ directory - used to run the reproducible example scenarios under
    examples/error_handling/ (see README, "Error-handling examples") without
    touching input/ or any previous run's output. Must exist. When omitted,
    Convert reads input/ as usual.

.EXAMPLE
    .\run_pipeline.ps1
    Normal run against input/.

.EXAMPLE
    .\run_pipeline.ps1 -InputDir examples\error_handling\missing_column
    Run against one of the example scenarios instead.
#>

param(
    [string]$InputDir
)

$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot
try {
    $outputRoot = Join-Path $PSScriptRoot "output"
    New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

    $existingNumbers = Get-ChildItem -Path $outputRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^run_(\d+)$' } |
        ForEach-Object { [int]$Matches[1] }

    $nextNumber = if ($existingNumbers) { ($existingNumbers | Measure-Object -Maximum).Maximum + 1 } else { 1 }
    $runId = "run_$nextNumber"
    $runDir = Join-Path $outputRoot $runId

    try {
        New-Item -ItemType Directory -Path $runDir -ErrorAction Stop | Out-Null
    } catch {
        Write-Error "Failed to allocate run directory '$runDir': $_"
        exit 1
    }
    foreach ($subdirectory in "convert", "process", "aggregate", "logs") {
        New-Item -ItemType Directory -Force -Path (Join-Path $runDir $subdirectory) | Out-Null
    }

    Write-Output "RUN_ID=$runId"
    Write-Output "Output directory: $runDir"

    if ($InputDir) {
        try {
            $resolvedInputDir = (Resolve-Path -LiteralPath $InputDir -ErrorAction Stop).Path
        } catch {
            Write-Error "InputDir '$InputDir' does not exist: $_"
            exit 1
        }
        Write-Output "Input directory: $resolvedInputDir"
        $env:INPUT_DIR = $resolvedInputDir
    } else {
        Remove-Item Env:\INPUT_DIR -ErrorAction SilentlyContinue
    }

    $env:RUN_ID = $runId
    # `run --rm aggregate` (not `up`) is deliberate: Compose's depends_on still
    # starts convert and process first (unchanged - the only sequencing
    # implementation), but `run`'s own exit code is specifically aggregate's,
    # which `up` does not reliably provide for the last stage in a one-shot
    # dependency chain - verified directly, see README, "Exit codes and
    # dependency behavior".
    docker compose -f docker-compose.pipeline.yml run --build --rm aggregate
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
