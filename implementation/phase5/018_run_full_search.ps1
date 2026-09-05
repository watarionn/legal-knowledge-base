param(
    [Parameter(Mandatory = $true)]
    [string]$ArchiveDir,

    [Parameter(Mandatory = $true)]
    [string]$WorkDir,

    [int]$Workers = 2,
    [int]$BenchmarkRepeats = 5,
    [double]$HistoryRequestInterval = 0.6
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $env:LEGAL_KB_DSN -and -not $env:DATABASE_URL) {
    throw "LEGAL_KB_DSN or DATABASE_URL must be set in the environment."
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Preflight = Join-Path $PSScriptRoot "017_full_search_execution_preflight.py"
$Pipeline = Join-Path $PSScriptRoot "015_full_search_pipeline_hardened.py"
$WorkDir = [System.IO.Path]::GetFullPath($WorkDir)
$ArchiveDir = [System.IO.Path]::GetFullPath($ArchiveDir)
$PreflightResult = Join-Path $WorkDir "phase5-full-search-host-preflight.json"

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

python $Preflight `
    --archive-dir $ArchiveDir `
    --work-dir $WorkDir `
    --result $PreflightResult
if ($LASTEXITCODE -ne 0) {
    throw "Host preflight failed. Review $PreflightResult"
}

$State = Get-Content -Raw -Encoding UTF8 $PreflightResult | ConvertFrom-Json
if (-not $State.ready) {
    throw "Host is not ready for the full-search benchmark. Review $PreflightResult"
}

$Args = @(
    $Pipeline,
    "--archive-dir", $ArchiveDir,
    "--work-dir", $WorkDir,
    "--workers", $Workers,
    "--benchmark-repeats", $BenchmarkRepeats,
    "--history-request-interval", $HistoryRequestInterval
)

if ($State.recommended_mode -eq "benchmark-only") {
    Write-Host "Phase 4 full dataset detected. Running benchmark-only mode."
    $Args += @("--skip-phase3", "--skip-phase4")
}
elseif ($State.recommended_mode -eq "full-rebuild") {
    Write-Host "Phase 4 full dataset not detected. Running resumable full rebuild before benchmark."
}
else {
    throw "Unknown recommended mode: $($State.recommended_mode)"
}

Push-Location $RepoRoot
try {
    python @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Hardened full-search pipeline failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "Full-search execution completed."
Write-Host "Benchmark result: $(Join-Path $WorkDir 'phase5-full-search-benchmark.json')"
