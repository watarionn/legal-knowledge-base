# Phase 5.2 full-search execution runbook

This runbook turns the validated four-part official XML snapshot into a reproducible Phase 5.2 full-search benchmark run.

## Purpose

`implementation/phase5/015_full_search_pipeline_hardened.py` connects the already-defined stages while preserving their legal and provenance semantics and applying the Phase 5.2 search hardening overlay:

1. apply Phase 3 / Phase 4 / Phase 5 DDL plus `012_search_literal_hardening.sql`;
2. run the resumable Phase 3 e-Gov API history bootstrap;
3. run the Phase 4 full relational XML import from the four validated ZIP parts;
4. rebuild Phase 5.2 `search_unit` with `013_full_search_benchmark_v2.py` and measure storage/query latency from an explicitly empty search-unit baseline;
5. write compact JSON reports outside Git history.

The database DSN is never written to the pipeline report.

## Search hardening before the full benchmark

The full run must use the hardened pipeline rather than the original `010_full_search_pipeline.py` directly.

`012_search_literal_hardening.sql` keeps the existing `pg_trgm`/`LIKE` search design but escapes backslash, `%`, and `_` in user input so those characters are matched literally instead of becoming SQL wildcard operators.

`013_full_search_benchmark_v2.py` records three storage states:

- `storage_initial`: whatever search-unit state existed before the benchmark;
- `storage_empty_baseline`: immediately after `TRUNCATE legal_kb.search_unit`;
- `storage_after`: after the full rebuild and `ANALYZE`.

The authoritative first-build storage measurement is `storage_build_delta = storage_after - storage_empty_baseline`. `storage_replacement_delta` is retained separately so a rerun on a previously populated database is not confused with first-build cost.

## Prerequisites

- PostgreSQL 16 or later
- Python 3.11 or later
- `psycopg[binary]>=3,<4`
- outbound HTTPS access for the Phase 3 e-Gov API bootstrap
- the four ZIP files in one local directory:
  - `all_xml_01.zip`
  - `all_xml_02.zip`
  - `all_xml_03.zip`
  - `all_xml_04.zip`

The ZIP bytes are validated by the Phase 4 importer against `docs/validation/xml_snapshot_manifest.public.json` before XML import.

## Windows PowerShell example

```powershell
python -m pip install "psycopg[binary]>=3,<4"
$env:LEGAL_KB_DSN = "postgresql://USER:PASSWORD@127.0.0.1:5432/legal_kb"

python implementation/phase5/015_full_search_pipeline_hardened.py `
  --archive-dir "D:\legal-kb\all_xml" `
  --work-dir "D:\legal-kb\run-20260906" `
  --workers 2 `
  --benchmark-repeats 5
```

## Resume behavior

Phase 3 uses `007_parallel_full_bootstrap.py` with resume enabled. Laws already present in `law_revision` are skipped rather than fetched again.

Phase 4 uses `011_full_relational_import.py`. Reconciled revisions already present in `law_document` are skipped rather than re-imported. The known RAW-only unreconciled snapshot members remain deferred and are not converted into fabricated `law_revision` rows.

This means an interrupted run can be restarted with the same command. The pipeline does not require deleting successful Phase 3 or Phase 4 work.

## Existing full relational DB

When the target PostgreSQL database already contains the verified Phase 3 and Phase 4 full dataset, skip those stages and execute only the hardened search benchmark:

```powershell
python implementation/phase5/015_full_search_pipeline_hardened.py `
  --archive-dir "D:\legal-kb\all_xml" `
  --work-dir "D:\legal-kb\benchmark-only" `
  --skip-phase3 `
  --skip-phase4 `
  --benchmark-repeats 5
```

`--skip-ddl` is also available when schema application is managed separately. When `--skip-ddl` is used, make sure both `006_lexical_structural_search_schema.sql` and `012_search_literal_hardening.sql` have already been applied.

## Output

The work directory receives compact reports such as:

- `phase3-full.json`
- `phase4-full-relational-import.json`
- `phase5-full-search-benchmark.json`
- `phase5-full-search-pipeline.json`

Phase 3 RAW API responses are stored under `phase3-raw/` and should remain outside Git history.

After a successful full run, review the benchmark JSON and commit only a public-safe validation result under `docs/validation/`. Do not commit database dumps, RAW API responses, credentials, or private storage locators.

## Success boundary

A run is suitable for Phase 5.2 completion evidence when:

- Phase 3 completes without residual failed law IDs;
- Phase 4 reports zero failed documents;
- Phase 5.2 rebuild reports `search_units == eligible_nodes`;
- `storage_empty_baseline`, `storage_after`, and `storage_build_delta` are present;
- representative lexical / structural latency is present;
- literal `%` / `_` search behavior has passed PostgreSQL smoke;
- the resulting evidence preserves revision, logical node, and RAW SHA provenance boundaries.
