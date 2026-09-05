# Phase 3 law / law_revision bootstrap runbook

This runbook executes the Phase 3 metadata bootstrap defined by `001_law_history_schema.sql` and `002_ingestion_contract.yaml`.

## Scope

The bootstrap imports only Phase 3 metadata entities:

- `law`
- `law_revision`
- `ingestion_run`
- `source_file`
- `source_assertion`
- `reconciliation_issue`

It does not import XML bodies, provision nodes, attachments, search documents, or external documents. Those belong to later phases.

## Prerequisites

- PostgreSQL database reachable from the execution host
- `psql` for DDL and validation execution
- Python 3.11 or later
- psycopg 3 (`psycopg[binary]>=3.1` is sufficient for a standalone runner)
- outbound HTTPS access to `https://laws.e-gov.go.jp/api/2`

Set the database DSN without committing credentials:

```bash
export LEGAL_KB_DSN='postgresql://USER:PASSWORD@HOST:5432/DBNAME'
```

On PowerShell:

```powershell
$env:LEGAL_KB_DSN = 'postgresql://USER:PASSWORD@HOST:5432/DBNAME'
```

## 1. Apply the Phase 3 DDL

From `implementation/phase3`:

```bash
psql "$LEGAL_KB_DSN" -v ON_ERROR_STOP=1 -f 001_law_history_schema.sql
```

The DDL is intentionally separate from the importer. If this step fails, do not start bootstrap ingestion.

## 2. Run offline temporal tests

```bash
python 005_bootstrap_import_test.py -v
```

These tests do not require PostgreSQL or network access. They verify revision-ID parsing, non-baseline date derivation, date-conflict ambiguity, baseline non-classification, and same-day interval behavior.

## 3. Install the database driver

```bash
python -m pip install "psycopg[binary]>=3.1"
```

The importer itself otherwise uses the Python standard library for HTTP and JSON handling.

## 4. Run a smoke bootstrap

Use a small cap first:

```bash
python 004_bootstrap_import.py \
  --max-laws 10 \
  --raw-dir /path/outside/repository/legal-kb-raw \
  --report /path/outside/repository/legal-kb-reports/phase3-smoke.json
```

A run with `--max-laws` is marked `partial` by definition. It deliberately does **not** create unresolved `amendment_law_id` issues, because most referenced laws have not been enumerated in a capped run.

Review the JSON report and database rows before continuing.

## 5. Run the full bootstrap

Remove `--max-laws`:

```bash
python 004_bootstrap_import.py \
  --raw-dir /path/outside/repository/legal-kb-raw \
  --report /path/outside/repository/legal-kb-reports/phase3-full.json
```

Optional: record the SHA-256 of the exact OpenAPI document used for the run:

```bash
python 004_bootstrap_import.py \
  --openapi-sha256 <64-hex-sha256> \
  --raw-dir /path/outside/repository/legal-kb-raw \
  --report /path/outside/repository/legal-kb-reports/phase3-full.json
```

Raw API responses are written under a run-specific directory so one ingestion run does not overwrite another. Large raw responses, reports, database dumps, and downloaded attachments should remain outside Git history. Commit only compact validation results, hashes, documentation, fixtures, and reproducible implementation files.

## 6. Run the validation package

```bash
psql "$LEGAL_KB_DSN" -v ON_ERROR_STOP=1 -f 003_validation_queries.sql > phase3-validation.txt
```

Review at minimum:

- law and revision counts
- revision-ID identity mismatches
- non-baseline amendment-law-ID mismatches
- revision-ID date versus API enforcement-date mismatches
- same-day revision groups
- interval inversions
- duplicate revision sequences
- unresolved amendment-law references
- temporal quality distribution
- revision date-kind distribution
- unresolved reconciliation issues

Same-day groups and unresolved amendment-law references are measurements, not automatic ingestion failures. Identity and date conflicts must remain visible as reconciliation issues rather than being silently normalized.

## 7. Phase 3 completion evidence

Phase 3 completion should be supported by reproducible evidence showing that:

1. DDL applied successfully to PostgreSQL.
2. Smoke bootstrap completed and was reviewed.
3. Full bootstrap completed or residual failures are explicitly explained.
4. Validation output records same-day groups, baseline/unknown distribution, unresolved amendment-law references, and conflict counts.
5. Historical bulk/API reconciliation results are recorded with acquisition dates and source hashes rather than treated as permanent constants.

Public-safe aggregate evidence is stored under `docs/validation/`. Private storage locators and credentials must never be committed.
