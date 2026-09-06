# Phase 5.2 full-search one-command launch

## Purpose

`021_bootstrap_and_dispatch_full_search.ps1` joins the two previously separate host operations:

1. bootstrap and start the dedicated Windows self-hosted runner;
2. wait until GitHub reports that runner online with `legal-kb-full-benchmark`;
3. verify that repository secret `LEGAL_KB_DSN` exists;
4. dispatch `phase5-full-search-self-hosted.yml` against `main` with the selected archive/work directories.

The benchmark itself remains implemented by the existing hardened execution chain. This launcher only removes manual coordination between runner setup and workflow dispatch.

## Prerequisites

The Windows host must have:

- GitHub CLI `gh`, authenticated with repository administration access;
- Python available on `PATH`;
- the four split XML archives in one local directory;
- enough free disk for the host preflight guard;
- PostgreSQL 16+ reachable through the DSN stored as the repository Actions secret `LEGAL_KB_DSN`.

For a first run, the simplest invocation from a checkout of `main` is:

```powershell
& implementation/phase5/021_bootstrap_and_dispatch_full_search.ps1 `
  -ArchiveDir "D:\legal-kb\xml" `
  -WorkDir "D:\legal-kb\work"
```

If a matching runner is already configured and running, use `-SkipRunnerSetup`.

## Secret handling

By default, the launcher only checks that the repository Actions secret named `LEGAL_KB_DSN` exists. It never reads the secret value back from GitHub.

If the secret is not yet configured, an explicit opt-in is available:

```powershell
$env:LEGAL_KB_DSN = "postgresql://..."
& implementation/phase5/021_bootstrap_and_dispatch_full_search.ps1 `
  -ArchiveDir "D:\legal-kb\xml" `
  -WorkDir "D:\legal-kb\work" `
  -ConfigureSecretFromEnvironment
```

The local environment variable is piped directly to `gh secret set`; it is not written to repository files or benchmark evidence.

## Runner readiness gate

The launcher polls the repository runner API for the exact configured runner name and requires:

- status `online`;
- label `legal-kb-full-benchmark`.

The default online timeout is 120 seconds. A dispatch is not attempted until both conditions are true.

## Dispatch contract

The launcher dispatches the workflow file `phase5-full-search-self-hosted.yml` on `main` with:

- `archive_dir`;
- `work_dir`;
- `workers`;
- `benchmark_repeats`;
- `history_request_interval`.

It then prints the newest matching workflow-dispatch run ID, status, and GitHub URL when the run is visible.

## Security boundary

The self-hosted benchmark workflow remains manual `workflow_dispatch` only. It is not reachable from `pull_request` events. Runner registration tokens are short-lived and are not persisted by the bootstrap script. Database credentials remain in GitHub Actions secrets or the user's local environment and must never be committed to the public repository.
