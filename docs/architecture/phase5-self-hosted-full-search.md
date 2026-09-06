# Phase 5.2 self-hosted full-search execution

## Purpose

The full Phase 5.2 benchmark needs a PostgreSQL 16+ host with substantially more disk than the chat execution environment. The repository therefore provides a manual-only GitHub Actions entrypoint for a dedicated Windows self-hosted runner.

Workflow: `.github/workflows/phase5-full-search-self-hosted.yml`

The workflow is intentionally `workflow_dispatch` only. It does not run on `pull_request` or arbitrary fork activity.

## Required runner labels

Register a Windows x64 self-hosted runner with all of the following labels:

- `self-hosted`
- `Windows`
- `X64`
- `legal-kb-full-benchmark`

The custom label prevents ordinary repository jobs from landing on the benchmark host.

## Host prerequisites

The runner host must have:

- PostgreSQL 16 or later, running and reachable through the configured DSN
- Python available as `python`
- the four validated archive files in one local directory:
  - `all_xml_01.zip`
  - `all_xml_02.zip`
  - `all_xml_03.zip`
  - `all_xml_04.zip`
- at least 40 GiB free for benchmark-only mode
- at least 80 GiB free for a full resumable rebuild

`017_full_search_execution_preflight.py` performs the final archive, PostgreSQL, existing-dataset, and disk checks before any heavy work starts.

## Repository secret

Configure repository secret `LEGAL_KB_DSN` with the PostgreSQL connection string used only by the runner. The workflow never prints the DSN and the pipeline reports explicitly avoid storing it.

## Dispatch inputs

When running `Phase 5 Full Search Benchmark`, provide:

- `archive_dir`: absolute local path containing the four ZIP files
- `work_dir`: absolute local path for reports and resumable work
- `workers`: Phase 3 worker count, default 2
- `benchmark_repeats`: default 5
- `history_request_interval`: default 0.6 seconds

The workflow invokes `018_run_full_search.ps1`, which first runs host preflight. If the verified full Phase 4 dataset already exists, it automatically selects benchmark-only mode. Otherwise it selects resumable full-rebuild mode.

## Evidence

The workflow uploads compact JSON evidence even when the heavy run fails after preflight:

- `phase5-full-search-host-preflight.json`
- `phase5-full-search-benchmark.json`
- `phase5-full-search-pipeline.json`
- `phase3-full.json` when produced
- `phase4-full-relational-import.json` when produced

Artifacts are retained for 14 days. After a successful run, review the benchmark JSON and commit only the public-safe validation summary under `docs/validation/`.

Do not commit database dumps, RAW Phase 3 API responses, credentials, private storage URLs, or runner-local paths that reveal sensitive infrastructure.
