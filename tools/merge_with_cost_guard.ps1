param(
    [Parameter(Mandatory = $true)]
    [int]$PullRequest,
    [string]$Repository = "watarionn/legal-knowledge-base",
    [string]$ExpectedHeadSha = "",
    [ValidateSet("merge", "squash", "rebase")]
    [string]$MergeMethod = "merge"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "Checking GitHub Actions cost guard..."
python (Join-Path $PSScriptRoot "check_github_actions_cost_guard.py") `
    --repo-root $RepoRoot `
    --repository $Repository
if ($LASTEXITCODE -ne 0) {
    throw "Cost guard blocked merge."
}

$Pr = gh pr view $PullRequest -R $Repository `
    --json number,state,isDraft,mergeable,headRefOid,url | ConvertFrom-Json
if ($Pr.state -ne "OPEN") { throw "PR is not open." }
if ($Pr.isDraft) { throw "PR is still draft." }
if ($Pr.mergeable -ne "MERGEABLE") { throw "PR is not mergeable." }

if ($ExpectedHeadSha) {
    if ($Pr.headRefOid -ne $ExpectedHeadSha) {
        throw "PR HEAD moved: expected $ExpectedHeadSha, actual $($Pr.headRefOid)."
    }
} else {
    $ExpectedHeadSha = $Pr.headRefOid
}

Write-Host "Cost guard passed for PR #$PullRequest at $ExpectedHeadSha"
Write-Host "This script must only be run after explicit merge approval."

$MethodFlag = "--$MergeMethod"
gh pr merge $PullRequest -R $Repository $MethodFlag --match-head-commit $ExpectedHeadSha
if ($LASTEXITCODE -ne 0) { throw "Merge failed." }

python (Join-Path $PSScriptRoot "check_github_actions_cost_guard.py") `
    --repo-root $RepoRoot `
    --repository $Repository
if ($LASTEXITCODE -ne 0) {
    throw "Post-merge cost guard verification failed."
}

Write-Host "Merge completed with GitHub Actions cost guard still active."
