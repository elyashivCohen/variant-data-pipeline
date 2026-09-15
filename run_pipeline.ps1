<#
.SYNOPSIS
    Allocate a fresh run_<N> directory and run the Dockerized pipeline for it.

.DESCRIPTION
    Requires only Docker Desktop with Compose - no host Python. Scans
    output/ for existing run_<N> directories, picks the next number (max+1,
    or 1 if none exist), creates output/run_<N>/{convert,process,aggregate,logs}
    without overwriting anything, then invokes the single Compose command
    that runs Convert, Process, and Aggregate in order (see README section
    13). All three stages read/write only this run's own directory tree.

    Does not run the stages individually and does not duplicate Compose's
    own depends_on/service_completed_successfully sequencing - it only
    allocates RUN_ID and calls `docker compose up`.

    Sequential local invocations only: running this script twice at the same
    time is unsupported (see README section 13).
#>

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

    $env:RUN_ID = $runId
    docker compose -f docker-compose.pipeline.yml up --build --force-recreate
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
