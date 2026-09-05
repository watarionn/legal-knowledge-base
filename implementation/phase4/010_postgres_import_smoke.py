from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys

PHASE4_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = PHASE4_DIR / "fixtures" / "real"
RUN_ID = "phase4-postgres-smoke-public"
RETRIEVED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PARSER = _load("legal_kb_phase4_xml_parser", PHASE4_DIR / "005_xml_parser.py")
PG_IMPORT = _load("legal_kb_phase4_postgres_import", PHASE4_DIR / "009_postgres_import.py")


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def _scalar(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def _count(conn, sql: str, params=()) -> int:
    return int(_scalar(conn, f"SELECT count(*) FROM ({sql}) q", params))


def _seed_run(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.ingestion_run
              (ingestion_run_id, started_at, parser_version, result_status)
            VALUES (%s, now(), %s, 'running')
            """,
            (RUN_ID, PARSER.PARSER_VERSION),
        )


def _seed_prerequisites(conn, fixture: dict, parsed) -> None:
    revision_id = fixture["revision_id"]
    law_id, effective_token, amending_law_id = revision_id.split("_")
    law_type = parsed.law_document["root_attributes_jsonb"].get("LawType") or "Unknown"
    member_source_file_id = f"xml-sha256:{fixture['xml_sha256']}"
    container_source_file_id = f"archive-sha256:{fixture['archive_sha256']}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.source_file (
              source_file_id, source_family, provider_file_id, stored_path,
              retrieved_at, media_type, byte_size, sha256, original_file_name,
              immutable, ingestion_run_id
            ) VALUES (%s, 'egov-bulk-zip-snapshot', %s, %s, %s, 'application/zip',
                      NULL, %s, %s, true, %s)
            ON CONFLICT (source_file_id) DO NOTHING
            """,
            (
                container_source_file_id,
                fixture["archive"],
                f"snapshot-archive://{fixture['archive']}",
                RETRIEVED_AT,
                fixture["archive_sha256"],
                fixture["archive"],
                RUN_ID,
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.source_file (
              source_file_id, source_family, stored_path, retrieved_at,
              media_type, byte_size, sha256, original_file_name,
              immutable, ingestion_run_id
            ) VALUES (%s, 'egov-bulk-xml', %s, %s, 'application/xml',
                      %s, %s, %s, true, %s)
            """,
            (
                member_source_file_id,
                f"zip://{fixture['archive']}/{fixture['member_path']}",
                RETRIEVED_AT,
                fixture["uncompressed_size"],
                fixture["xml_sha256"],
                fixture["fixture_file"],
                RUN_ID,
            ),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.law (law_id, law_type, first_seen_run_id, last_seen_run_id)
            VALUES (%s, %s, %s, %s)
            """,
            (law_id, law_type, RUN_ID, RUN_ID),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.law_revision (
              law_revision_id, law_id, law_type,
              revision_id_effective_date, revision_id_amending_law_id,
              revision_date_kind, temporal_resolution_quality,
              first_seen_run_id, last_seen_run_id
            ) VALUES (%s, %s, %s, to_date(%s, 'YYYYMMDD'), %s,
                      'unknown', 'unknown', %s, %s)
            """,
            (
                revision_id,
                law_id,
                law_type,
                effective_token,
                amending_law_id,
                RUN_ID,
                RUN_ID,
            ),
        )

    PG_IMPORT.insert_source_file_member(
        conn,
        PARSER.build_source_file_member_row(
            member_source_file_id=member_source_file_id,
            container_source_file_id=container_source_file_id,
            member_path=fixture["member_path"],
            member_ordinal=fixture["member_ordinal"],
            compressed_size=fixture["compressed_size"],
            uncompressed_size=fixture["uncompressed_size"],
            crc32=fixture["crc32"],
        ),
    )


def _integrity(conn) -> dict:
    zero_queries = {
        "raw_backlink": """
          SELECT d.document_id
          FROM legal_kb.law_document d
          LEFT JOIN legal_kb.law_revision r ON r.law_revision_id=d.law_revision_id
          LEFT JOIN legal_kb.source_file s ON s.source_file_id=d.source_file_id
          WHERE r.law_revision_id IS NULL OR s.source_file_id IS NULL
             OR s.immutable IS DISTINCT FROM true
             OR lower(s.sha256) <> lower(d.source_xml_sha256)
        """,
        "root_count": """
          SELECT d.document_id
          FROM legal_kb.law_document d
          LEFT JOIN legal_kb.provision_node n ON n.document_pk=d.document_pk
          GROUP BY d.document_id
          HAVING count(n.document_order) FILTER (WHERE n.parent_document_order IS NULL) <> 1
        """,
        "orphan_parent": """
          SELECT c.document_pk,c.document_order
          FROM legal_kb.provision_node c
          LEFT JOIN legal_kb.provision_node p
            ON p.document_pk=c.document_pk AND p.document_order=c.parent_document_order
          WHERE c.parent_document_order IS NOT NULL AND p.document_order IS NULL
        """,
        "sibling_order": """
          SELECT document_pk,parent_document_order
          FROM legal_kb.provision_node
          GROUP BY document_pk,parent_document_order
          HAVING min(ordinal)<>1 OR max(ordinal)<>count(*)
             OR count(DISTINCT ordinal)<>count(*)
        """,
        "document_order": """
          SELECT document_pk
          FROM legal_kb.provision_node
          GROUP BY document_pk
          HAVING min(document_order)<>1 OR max(document_order)<>count(*)
             OR count(DISTINCT document_order)<>count(*)
        """,
        "node_id_duplicate": """
          SELECT node_id FROM legal_kb.provision_node GROUP BY node_id HAVING count(*)>1
        """,
        "path_index": """
          SELECT document_pk,document_order FROM legal_kb.provision_node WHERE path_index<1
        """,
        "mixed_child_reference": """
          SELECT p.document_pk,p.document_order
          FROM legal_kb.provision_node p
          CROSS JOIN LATERAL jsonb_array_elements(p.mixed_content_jsonb) seg(value)
          LEFT JOIN legal_kb.provision_node c
            ON c.document_pk=p.document_pk AND c.document_order=(seg.value->>'document_order')::int
          WHERE seg.value->>'kind'='child' AND c.document_order IS NULL
        """,
        "mixed_tail_reference": """
          SELECT p.document_pk,p.document_order
          FROM legal_kb.provision_node p
          CROSS JOIN LATERAL jsonb_array_elements(p.mixed_content_jsonb) seg(value)
          LEFT JOIN legal_kb.provision_node c
            ON c.document_pk=p.document_pk AND c.document_order=(seg.value->>'after_document_order')::int
          WHERE seg.value->>'kind'='tail' AND c.document_order IS NULL
        """,
        "node_count": """
          SELECT d.document_id
          FROM legal_kb.law_document d
          LEFT JOIN legal_kb.provision_node n ON n.document_pk=d.document_pk
          GROUP BY d.document_id,d.node_count
          HAVING count(n.document_order)<>d.node_count
        """,
        "attachment_count": """
          SELECT d.document_id
          FROM legal_kb.law_document d
          LEFT JOIN legal_kb.attachment a ON a.document_pk=d.document_pk
          GROUP BY d.document_id,d.attachment_reference_count
          HAVING count(a.attachment_id)<>d.attachment_reference_count
        """,
        "attachment_revision": """
          SELECT a.attachment_id
          FROM legal_kb.attachment a
          JOIN legal_kb.law_document d ON d.document_pk=a.document_pk
          WHERE a.law_revision_id<>d.law_revision_id
        """,
        "search_normalized_text": """
          SELECT document_pk,document_order FROM legal_kb.provision_node
          WHERE text_search_normalized IS NOT NULL
        """,
    }
    counts = {name: _count(conn, sql) for name, sql in zero_queries.items()}
    bad = {name: value for name, value in counts.items() if value}
    if bad:
        raise AssertionError(f"integrity failures: {bad}")
    return counts


def _path_roundtrip(conn, parsed_docs) -> bool:
    for parsed in parsed_docs:
        document_id = parsed.law_document["document_id"]
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.document_order, encode(n.node_id, 'hex'),
                       legal_kb.provision_node_xml_path(n.document_pk, n.document_order)
                FROM legal_kb.provision_node n
                JOIN legal_kb.law_document d ON d.document_pk=n.document_pk
                WHERE d.document_id=%s
                ORDER BY n.document_order
                """,
                (document_id,),
            )
            stored = cur.fetchall()
        expected = [
            (node["document_order"], node["node_id"], node["xml_path"])
            for node in parsed.nodes
        ]
        if stored != expected:
            return False
    return True


def _features(conn) -> dict:
    checks = {
        "articleless": _scalar(
            conn,
            """SELECT count(*)=0 FROM legal_kb.provision_node n
               JOIN legal_kb.law_document d ON d.document_pk=n.document_pk
               WHERE d.law_revision_id=%s AND n.tag_name='Article'""",
            ("503AC0000000004_20210203_000000000000000",),
        ),
        "nonblank_tail": _scalar(
            conn,
            """SELECT count(*)>0 FROM legal_kb.provision_node n
               JOIN legal_kb.law_document d ON d.document_pk=n.document_pk
               CROSS JOIN LATERAL jsonb_array_elements(n.mixed_content_jsonb) seg(value)
               WHERE d.law_revision_id=%s AND seg.value->>'kind'='tail'
                 AND btrim(seg.value->>'value')<>''""",
            ("428AC1000000067_20160603_000000000000000",),
        ),
        "oldnum_oldstyle": _scalar(
            conn,
            """SELECT count(*)>=2 FROM legal_kb.provision_node n
               JOIN legal_kb.law_document d ON d.document_pk=n.document_pk
               WHERE d.law_revision_id=%s AND n.old_num='true' AND n.old_style='false'
                 AND n.attributes_jsonb->>'OldNum'='true'
                 AND n.attributes_jsonb->>'OldStyle'='false'""",
            ("143AC1000000056_19100416_000000000000000",),
        ),
        "attachment_src": _scalar(
            conn,
            """SELECT count(*)=1 FROM legal_kb.attachment
               WHERE law_revision_id=%s
                 AND source_src='./pict/R03F100140190170150160001_101.jpg'
                 AND availability_status='unresolved'""",
            ("503M60000F42001_20211022_000000000000000",),
        ),
    }
    bad = [name for name, value in checks.items() if not value]
    if bad:
        raise AssertionError(f"feature failures: {bad}")
    return {name: bool(value) for name, value in checks.items()}


def run(database_url: str) -> dict:
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    with _connect(database_url) as conn:
        _seed_run(conn)
        parsed_docs = []
        reports = []

        for fixture in manifest["fixtures"]:
            raw = (FIXTURE_DIR / fixture["fixture_file"]).read_bytes()
            if sha256(raw).hexdigest() != fixture["xml_sha256"]:
                raise AssertionError(f"SHA mismatch: {fixture['fixture_file']}")
            if len(raw) != fixture["uncompressed_size"]:
                raise AssertionError(f"size mismatch: {fixture['fixture_file']}")

            source_file_id = f"xml-sha256:{fixture['xml_sha256']}"
            parsed = PARSER.parse_xml_bytes(
                raw,
                law_revision_id=fixture["revision_id"],
                source_file_id=source_file_id,
                ingestion_run_id=RUN_ID,
            )
            if parsed.law_document["parse_status"] != "succeeded":
                raise AssertionError(f"unexpected parse status: {fixture['fixture_file']}")

            _seed_prerequisites(conn, fixture, parsed)
            if not PG_IMPORT.insert_parsed_document(conn, parsed, batch_size=250):
                raise AssertionError("fresh database unexpectedly contained document")
            parsed_docs.append(parsed)
            reports.append(
                {
                    "role": fixture["role"],
                    "revision_id": fixture["revision_id"],
                    "xml_sha256": fixture["xml_sha256"],
                    "document_id": parsed.law_document["document_id"],
                    "node_count": len(parsed.nodes),
                    "attachment_reference_count": len(parsed.attachments),
                }
            )

        integrity = _integrity(conn)
        features = _features(conn)
        path_roundtrip = _path_roundtrip(conn, parsed_docs)
        if not path_roundtrip:
            raise AssertionError("node_id/xml_path reconstruction mismatch")
        idempotent = all(
            not PG_IMPORT.insert_parsed_document(conn, parsed, skip_existing=True)
            for parsed in parsed_docs
        )
        if not idempotent:
            raise AssertionError("skip_existing idempotence failed")

        totals = {
            "law_document_count": int(_scalar(conn, "SELECT count(*) FROM legal_kb.law_document")),
            "provision_node_count": int(_scalar(conn, "SELECT count(*) FROM legal_kb.provision_node")),
            "attachment_count": int(_scalar(conn, "SELECT count(*) FROM legal_kb.attachment")),
            "source_file_member_count": int(_scalar(conn, "SELECT count(*) FROM legal_kb.source_file_member")),
            "xml_parse_issue_count": int(_scalar(conn, "SELECT count(*) FROM legal_kb.xml_parse_issue")),
        }
        if totals["law_document_count"] != 4 or totals["attachment_count"] != 1:
            raise AssertionError(f"unexpected totals: {totals}")

        with conn.cursor() as cur:
            cur.execute(
                """UPDATE legal_kb.ingestion_run
                   SET completed_at=now(),result_status='succeeded'
                   WHERE ingestion_run_id=%s""",
                (RUN_ID,),
            )

        return {
            "schema_version": "1.0",
            "runner": "010_postgres_import_smoke.py",
            "postgresql_target": "16",
            "parser_version": PARSER.PARSER_VERSION,
            "status": "passed",
            "fixtures": reports,
            "totals": totals,
            "zero_issue_counts": integrity,
            "feature_checks": features,
            "node_id_and_xml_path_roundtrip": path_roundtrip,
            "idempotent_skip_existing": idempotent,
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--result", type=Path)
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    result = run(args.database_url)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.result:
        args.result.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
