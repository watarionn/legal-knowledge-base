param(
    [Parameter(Mandatory = $true)]
    [string]$ArchiveDir,

    [Parameter(Mandatory = $true)]
    [string]$WorkDir,

    [string]$RepoSlug = "watarionn/legal-knowledge-base",
    [string]$RunnerDir = "C:\actions-runner-legal-kb",
    [string]$RunnerName = "$env:COMPUTERNAME-legal-kb-full-benchmark",
    [int]$Workers = 2,
    [int]$BenchmarkRepeats = 5,
    [double]$HistoryRequestInterval = 0.6,
    [int]$RunnerOnlineTimeoutSeconds = 120,
    [switch]$SkipRunnerSetup,
    [switch]$ConfigureSecretFromEnvironment
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found."
    }
}

function Get-RunnerState {
    param([string]$Repository, [string]$Name)
    $json = & gh api "repos/$Repository/actions/runners?per_page=100"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not query self-hosted runners for $Repository. Repository administration access is required."
    }
    $obj = $json | ConvertFrom-Json
    return $obj.runners | Where-Object { $_.name -eq $Name } | Select-Object -First 1
}

function Ensure-LegalKbSecret {
    param([string]$Repository, [switch]$AllowConfigure)

    $names = @(& gh secret list --repo $Repository --json name --jq '.[].name')
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list repository Actions secrets."
    }
    if ($names -contains "LEGAL_KB_DSN") {
        Write-Host "Repository secret LEGAL_KB_DSN is configured."
        return
    }

    if (-not $AllowConfigure) {
        throw "Repository secret LEGAL_KB_DSN is not configured. Set it first, or rerun with -ConfigureSecretFromEnvironment after setting `$env:LEGAL_KB_DSN locally."
    }
    if (-not $env:LEGAL_KB_DSN) {
        throw "-ConfigureSecretFromEnvironment requires local environment variable LEGAL_KB_DSN."
    }

    $env:LEGAL_KB_DSN | & gh secret set LEGAL_KB_DSN --repo $Repository
    if ($LASTEXITCODE -ne 0) {
        throw "Could not configure repository secret LEGAL_KB_DSN."
    }
    Write-Host "Repository secret LEGAL_KB_DSN configured from the local environment."
}

Assert-Command gh
Assert-Command python

& gh auth status | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "gh is not authenticated. Run 'gh auth login' and retry."
}

$ArchiveDir = [System.IO.Path]::GetFullPath($ArchiveDir)
$WorkDir = [System.IO.Path]::GetFullPath($WorkDir)
if (-not (Test-Path $ArchiveDir -PathType Container)) {
    throw "ArchiveDir does not exist: $ArchiveDir"
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

if (-not $SkipRunnerSetup) {
    $setup = Join-Path $PSScriptRoot "020_setup_self_hosted_runner.ps1"
    & $setup -RepoSlug $RepoSlug -RepoUrl "https://github.com/$RepoSlug" -RunnerDir $RunnerDir -RunnerName $RunnerName
    if ($LASTEXITCODE -ne 0) {
        throw "Self-hosted runner bootstrap failed."
    }
}

$runner = $null
$deadline = [DateTime]::UtcNow.AddSeconds($RunnerOnlineTimeoutSeconds)
do {
    $runner = Get-RunnerState -Repository $RepoSlug -Name $RunnerName
    if ($runner -and $runner.status -eq "online") {
        break
    }
    Start-Sleep -Seconds 2
} while ([DateTime]::UtcNow -lt $deadline)

if (-not $runner) {
    throw "Runner '$RunnerName' was not found in $RepoSlug after setup."
}
if ($runner.status -ne "online") {
    throw "Runner '$RunnerName' did not become online within $RunnerOnlineTimeoutSeconds seconds. Current status: $($runner.status)"
}

$labels = @($runner.labels | ForEach-Object { $_.name })
if ($labels -notcontains "legal-kb-full-benchmark") {
    throw "Runner '$RunnerName' is online but missing required label legal-kb-full-benchmark."
}
Write-Host "Runner is online with required label: $RunnerName"

Ensure-LegalKbSecret -Repository $RepoSlug -AllowConfigure:$ConfigureSecretFromEnvironment

$workflow = "phase5-full-search-self-hosted.yml"
& gh workflow run $workflow --repo $RepoSlug --ref main `
    -f "archive_dir=$ArchiveDir" `
    -f "work_dir=$WorkDir" `
    -f "workers=$Workers" `
    -f "benchmark_repeats=$BenchmarkRepeats" `
    -f "history_request_interval=$HistoryRequestInterval"
if ($LASTEXITCODE -ne 0) {
    throw "Could not dispatch $workflow."
}

Start-Sleep -Seconds 2
$run = & gh run list --repo $RepoSlug --workflow $workflow --event workflow_dispatch --limit 1 --json databaseId,status,conclusion,url,headBranch,createdAt | ConvertFrom-Json | Select-Object -First 1
if ($run) {
    Write-Host "Full-search benchmark dispatched."
    Write-Host "Run ID: $($run.databaseId)"
    Write-Host "Status: $($run.status)"
    Write-Host "URL: $($run.url)"
}
else {
    Write-Host "Workflow dispatch accepted, but the new run was not visible yet. Check GitHub Actions for '$workflow'."
}
