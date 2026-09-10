from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys
import uuid
from datetime import date, datetime, timezone

import psycopg

HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


adapter = _load("phase6_gazette_adapter_live", "015_official_gazette_adapter.py")
persistence = _load("phase6_gazette_persistence_live", "016_official_gazette_persistence.py")
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch exactly one operator-specified Gazette PDF; never crawl/discover links."
    )
    parser.add_argument("--issued-on", required=True)
    parser.add_argument("--publication-kind", required=True, choices=sorted(adapter.ALLOWED_KINDS))
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--pdf-url", required=True)
    parser.add_argument("--page-start", required=True, type=int)
    parser.add_argument("--page-end", required=True, type=int)
    parser.add_argument("--output-dir")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    issue = adapter.GazetteIssueSpec(
        date.fromisoformat(args.issued_on),
        args.publication_kind,
        args.issue_number,
    )
    asset = adapter.GazettePdfAssetSpec(
        issue,
        args.pdf_url,
        args.page_start,
        args.page_end,
    )
    fetched = adapter.fetch_explicit_pdf(asset)
    stored_path = None
    if args.output_dir:
        out_dir = pathlib.Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = pathlib.PurePosixPath(asset.pdf_url).name
        output_path = out_dir / filename
        output_path.write_bytes(fetched.raw_payload)
        stored_path = str(output_path)

    persisted = None
    if args.database_url:
        run_id = f"phase63-live-{uuid.uuid4().hex[:12]}"
        with psycopg.connect(args.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO legal_kb.ingestion_run "
                    "(ingestion_run_id, started_at, result_status) "
                    "VALUES (%s, %s, 'succeeded')",
                    (run_id, datetime.now(timezone.utc)),
                )
            persisted = persistence.persist_fetched_gazette_asset(
                conn,
                fetched,
                ingestion_run_id=run_id,
                stored_path=stored_path,
            )
            conn.commit()

    cert = fetched.certificate
    result = {
        "status": "passed",
        "provider_code": adapter.PROVIDER_CODE,
        "provider_document_id": issue.provider_document_id,
        "issued_on": issue.issued_on.isoformat(),
        "publication_kind": issue.publication_kind,
        "issue_number": issue.issue_number,
        "page_start": asset.page_start,
        "page_end": asset.page_end,
        "byte_size": fetched.byte_size,
        "payload_sha256": fetched.payload_sha256,
        "signature_field_count": cert.signature_field_count,
        "document_timestamp_count": cert.document_timestamp_count,
        "byte_range_count": cert.byte_range_count,
        "cades_detached_count": cert.cades_detached_count,
        "cryptographic_verification_status": cert.cryptographic_verification_status,
        "crawler_used": False,
        "database_url_recorded": False,
        "stored_path": stored_path,
    }
    if persisted:
        result.update(
            {
                "external_document_id": persisted.external_document_id,
                "snapshot_id": persisted.snapshot_id,
                "source_file_id": persisted.source_file_id,
                "gazette_asset_id": persisted.gazette_asset_id,
            }
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
