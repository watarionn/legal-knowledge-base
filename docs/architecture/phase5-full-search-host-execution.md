# Phase 5.2 full-search host execution

The hardened full-search benchmark is intentionally not forced onto a standard GitHub-hosted runner. The verified Phase 4 relational database is about 17 GB before the Phase 5 search layer, and the full rebuild can exceed the practical disk and runtime envelope of a normal ephemeral runner.

## One-command Windows entrypoint

On a Windows host with PostgreSQL 16+, Python 3.11+, the four verified ZIP parts, and sufficient free disk space, set the database DSN only in the environment and run:

```powershell
$env:LEGAL_KB_DSN = "postgresql://USER:PASSWORD@127.0.0.1:5432/legal_kb"

powershell -ExecutionPolicy Bypass -File implementation/phase5/018_run_full_search.ps1 `
  -ArchiveDir "D:\legal-kb\all_xml" `
  -WorkDir "D:\legal-kb\run-20260906"
```

The launcher first runs `017_full_search_execution_preflight.py` and writes `phase5-full-search-host-preflight.json`.

It then chooses the execution mode automatically:

- `benchmark-only` when the database contains exactly 10,705 `law_document` rows and 32,116,330 `provision_node` rows;
- `full-rebuild` otherwise, using the resumable Phase 3 and Phase 4 pipeline before the Phase 5.2 benchmark.

## Disk guard

The preflight blocks execution when free space is below the conservative guardrail:

- benchmark-only: 40 GiB free;
- full rebuild: 80 GiB free.

These are execution guardrails rather than measured final storage requirements. The benchmark v2 result is the authoritative measurement of the Phase 5 search-layer build delta.

## Input validation

The preflight requires all four archive names and validates their byte sizes against `docs/validation/xml_snapshot_manifest.public.json`. The Phase 4 importer subsequently performs the stronger SHA-256 and XML-count validation before import.

## Database reuse

The launcher never discards a verified Phase 3 or Phase 4 dataset merely to rerun the benchmark. When the exact completed Phase 4 counts are present it skips API history bootstrap and relational XML import, and proceeds directly to the hardened Phase 5.2 search build.

If the full Phase 4 counts are not present, the normal resumable import behavior applies. Already completed Phase 3 laws and already imported reconciled Phase 4 documents are reused rather than fetched/imported again.

## Output

The work directory contains the compact execution evidence, including:

- `phase5-full-search-host-preflight.json`
- `phase3-full.json` when Phase 3 is executed
- `phase4-full-relational-import.json` when Phase 4 is executed
- `phase5-full-search-benchmark.json`
- `phase5-full-search-pipeline.json`

Credentials and the database DSN are not written to these reports. After a successful full benchmark, only public-safe compact evidence should be committed under `docs/validation/`.
