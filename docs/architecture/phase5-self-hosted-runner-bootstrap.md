# Phase 5.2 Windows self-hosted runner bootstrap

## Purpose

`implementation/phase5/020_setup_self_hosted_runner.ps1` prepares a Windows x64 host for the manual `Phase 5 Full Search Benchmark` workflow. It downloads the latest GitHub Actions runner, registers it to `watarionn/legal-knowledge-base`, adds the dedicated `legal-kb-full-benchmark` label, and starts the runner unless service mode is selected.

The script never stores a registration token in the repository. When `-RegistrationToken` is omitted, it asks GitHub CLI (`gh`) for a short-lived registration token using the currently authenticated account.

## Host prerequisites

The target host must satisfy the full-search execution prerequisites documented by Phase 5.2: Windows x64, PostgreSQL 16+, Python, sufficient local disk, and local access to `all_xml_01.zip` through `all_xml_04.zip`. The runner host must also be able to reach GitHub and e-Gov while Phase 3 history recovery is needed.

For automatic token acquisition, install GitHub CLI and authenticate an account with repository administration access:

```powershell
gh auth login
```

## Bootstrap

From a checkout of the repository, run:

```powershell
powershell -ExecutionPolicy Bypass -File implementation/phase5/020_setup_self_hosted_runner.ps1
```

The default runner directory is `C:\actions-runner-legal-kb`. The default runner name is derived from the Windows computer name. The script refuses to overwrite an already configured runner directory.

A registration token may be supplied explicitly when GitHub CLI cannot be used:

```powershell
powershell -ExecutionPolicy Bypass -File implementation/phase5/020_setup_self_hosted_runner.ps1 `
  -RegistrationToken '<short-lived-runner-registration-token>'
```

Do not commit or paste the token into repository files, issues, pull requests, or benchmark evidence.

## Interactive versus service mode

The default starts `run.cmd` in a separate interactive window. This is preferred when the XML ZIPs live in a user-scoped Google Drive sync folder because an interactive runner naturally uses the same user account and filesystem permissions.

For a dedicated machine where all required paths are accessible to the runner service account, configure service mode with:

```powershell
powershell -ExecutionPolicy Bypass -File implementation/phase5/020_setup_self_hosted_runner.ps1 -RunAsService
```

Service mode can require an elevated shell depending on Windows configuration.

## After registration

Confirm the runner is online and carries the `legal-kb-full-benchmark` label. Then manually dispatch `.github/workflows/phase5-full-search-self-hosted.yml` with the local archive directory and work directory. The workflow reads the PostgreSQL DSN from the repository secret `LEGAL_KB_DSN`, runs host preflight, reuses a complete Phase 4 dataset when possible, and uploads compact benchmark evidence.

The benchmark workflow is intentionally `workflow_dispatch` only. It must never be changed to execute untrusted pull-request code on the self-hosted host.
