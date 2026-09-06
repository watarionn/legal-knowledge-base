param(
    [string]$RepoUrl = "https://github.com/watarionn/legal-knowledge-base",
    [string]$RepoSlug = "watarionn/legal-knowledge-base",
    [string]$RunnerDir = "C:\actions-runner-legal-kb",
    [string]$RunnerName = "$env:COMPUTERNAME-legal-kb-full-benchmark",
    [string]$RegistrationToken = "",
    [switch]$RunAsService,
    [bool]$StartRunner = $true
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-RegistrationToken {
    param([string]$ExplicitToken, [string]$Repository)

    if ($ExplicitToken) {
        return $ExplicitToken
    }

    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        throw "GitHub CLI (gh) is required when -RegistrationToken is not supplied. Install gh, run 'gh auth login', and retry."
    }

    & gh auth status | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "gh is not authenticated. Run 'gh auth login' with repository administration access."
    }

    $json = & gh api -X POST "repos/$Repository/actions/runners/registration-token"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not obtain a self-hosted runner registration token. The authenticated GitHub account must have repository administration access."
    }

    $obj = $json | ConvertFrom-Json
    if (-not $obj.token) {
        throw "GitHub did not return a runner registration token."
    }
    return [string]$obj.token
}

function Get-LatestRunnerAsset {
    $release = Invoke-RestMethod -Headers @{ "User-Agent" = "legal-kb-runner-bootstrap" } `
        -Uri "https://api.github.com/repos/actions/runner/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-.*\.zip$' } | Select-Object -First 1
    if (-not $asset) {
        throw "Could not find the latest Windows x64 GitHub Actions runner asset."
    }
    return $asset
}

$RunnerDir = [System.IO.Path]::GetFullPath($RunnerDir)
New-Item -ItemType Directory -Force -Path $RunnerDir | Out-Null

if (Test-Path (Join-Path $RunnerDir ".runner")) {
    throw "A GitHub Actions runner is already configured in $RunnerDir. Refusing to overwrite it."
}

$token = Get-RegistrationToken -ExplicitToken $RegistrationToken -Repository $RepoSlug
$asset = Get-LatestRunnerAsset
$zipPath = Join-Path $env:TEMP $asset.name

Write-Host "Downloading GitHub Actions runner: $($asset.name)"
Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $zipPath

Write-Host "Extracting runner to $RunnerDir"
Expand-Archive -Path $zipPath -DestinationPath $RunnerDir -Force
Remove-Item -Force $zipPath

Push-Location $RunnerDir
try {
    $configArgs = @(
        "--unattended",
        "--url", $RepoUrl,
        "--token", $token,
        "--name", $RunnerName,
        "--labels", "legal-kb-full-benchmark",
        "--work", "_work"
    )
    if ($RunAsService) {
        $configArgs += "--runasservice"
    }

    & .\config.cmd @configArgs
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub Actions runner configuration failed with exit code $LASTEXITCODE"
    }

    Write-Host "Runner configured successfully."
    Write-Host "Runner name: $RunnerName"
    Write-Host "Required workflow label: legal-kb-full-benchmark"

    if ($StartRunner -and -not $RunAsService) {
        Write-Host "Starting runner in a separate window. Keep that process running while the full benchmark executes."
        Start-Process -FilePath (Join-Path $RunnerDir "run.cmd") -WorkingDirectory $RunnerDir
    }
    elseif ($RunAsService) {
        Write-Host "Runner was configured as a Windows service."
    }
    else {
        Write-Host "Runner is configured but not started. Run '$RunnerDir\run.cmd' before dispatching the benchmark workflow."
    }
}
finally {
    Pop-Location
}
