from __future__ import annotations

from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import sys

PHASE5_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phase5_temporal_resolver", PHASE5_DIR / "003_temporal_resolver.py"
)
RESOLVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RESOLVER
SPEC.loader.exec_module(RESOLVER)

RUN_ID = "phase5-temporal-smoke"
LAW1 = "900AC0000000001"
LAW2 = "900AC0000000002"
LAW3 = "900AC0000000003"
R1A = f"{LAW1}_20200101_000000000000001"
R1B = f"{LAW1}_20210101_000000000000002"
R2A = f"{LAW2}_20220101_000000000000001"
R2B = f"{LAW2}_20220101_000000000000002"
R3A = f"{LAW3}_20200101_000000000000000"


def _seed(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.ingestion_run
              (ingestion_run_id, started_at, result_status)
            VALUES (%s, now(), 'succeeded')
            ON CONFLICT (ingestion_run_id) DO NOTHING
            """,
            (RUN_ID,),
        )

        for law_id in (LAW1, LAW2, LAW3):
            cur.execute(
                """
                INSERT INTO legal_kb.law
                  (law_id, law_type, first_seen_run_id, last_seen_run_id)
                VALUES (%s, 'Act', %s, %s)
                ON CONFLICT (law_id) DO NOTHING
                """,
                (law_id, RUN_ID, RUN_ID),
            )

        revisions = [
            (R1A, LAW1, date(2020, 1, 1), "000000000000001", 1, date(2020, 1, 1), date(2021, 1, 1), "confirmed-api"),
            (R1B, LAW1, date(2021, 1, 1), "000000000000002", 2, date(2021, 1, 1), None, "confirmed-api"),
            (R2A, LAW2, date(2022, 1, 1), "000000000000001", 1, date(2022, 1, 1), None, "ambiguous"),
            (R2B, LAW2, date(2022, 1, 1), "000000000000002", 2, date(2022, 1, 1), None, "ambiguous"),
            (R3A, LAW3, date(2020, 1, 1), "000000000000000", 1, date(2020, 1, 1), None, "ambiguous"),
        ]
        cur.executemany(
            """
            INSERT INTO legal_kb.law_revision (
              law_revision_id, law_id, law_type,
              revision_id_effective_date, revision_id_amending_law_id,
              revision_date_kind, revision_sequence,
              valid_from, valid_to_exclusive, temporal_resolution_quality,
              first_seen_run_id, last_seen_run_id
            ) VALUES (
              %s, %s, 'Act', %s, %s,
              'amendment-enforcement', %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (law_revision_id) DO NOTHING
            """,
            [row + (RUN_ID, RUN_ID) for row in revisions],
        )

        source_file_id = "phase5-temporal-smoke-source"
        cur.execute(
            """
            INSERT INTO legal_kb.source_file (
              source_file_id, source_family, retrieved_at, media_type,
              byte_size, sha256, immutable, ingestion_run_id
            ) VALUES (%s, 'phase5-smoke', now(), 'application/xml', 1, %s, true, %s)
            ON CONFLICT (source_file_id) DO NOTHING
            """,
            (source_file_id, "c" * 64, RUN_ID),
        )
        cur.execute(
            """
            INSERT INTO legal_kb.law_document (
              document_id, law_revision_id, source_file_id, ingestion_run_id,
              root_tag_name, root_attributes_jsonb, source_xml_sha256,
              parser_version, parse_status, schema_validation_status,
              schema_validation_errors_jsonb, node_count, attachment_reference_count,
              parsed_at
            ) VALUES (
              %s, %s, %s, %s,
              'Law', '{}'::jsonb, %s,
              'phase5-smoke', 'succeeded', 'not-checked',
              '[]'::jsonb, 0, 0, now()
            )
            ON CONFLICT (document_id) DO NOTHING
            """,
            ("d" * 64, R1B, source_file_id, RUN_ID, "e" * 64),
        )


def run(database_url: str) -> dict:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as conn:
        _seed(conn)

        before = RESOLVER.resolve_as_of(conn, LAW1, date(2019, 12, 31))
        old = RESOLVER.resolve_as_of(conn, LAW1, date(2020, 6, 1))
        boundary = RESOLVER.resolve_as_of(conn, LAW1, date(2021, 1, 1))
        current = RESOLVER.resolve_as_of(conn, LAW1, date(2021, 6, 1))
        same_day = RESOLVER.resolve_as_of(conn, LAW2, date(2022, 6, 1))
        baseline = RESOLVER.resolve_as_of(conn, LAW3, date(2020, 6, 1))

    checks = {
        "before_first_is_not_found": before.status == "not-found",
        "old_revision_resolves_without_content_fallback": (
            old.status == "resolved"
            and old.selected_revision_id == R1A
            and old.content_status == "missing"
        ),
        "exclusive_boundary_selects_new_revision": (
            boundary.status == "resolved"
            and boundary.selected_revision_id == R1B
        ),
        "current_revision_has_content": (
            current.status == "resolved"
            and current.selected_revision_id == R1B
            and current.content_status == "available"
            and current.selected_document_id == "d" * 64
        ),
        "same_day_candidates_are_ambiguous": (
            same_day.status == "ambiguous"
            and same_day.selected_revision_id is None
            and len(same_day.candidates) == 2
        ),
        "low_quality_single_candidate_is_unresolved": (
            baseline.status == "unresolved"
            and baseline.selected_revision_id is None
        ),
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError(f"Phase 5 temporal smoke failed: {failed}")

    return {
        "schema_version": "1.0",
        "evidence_type": "phase5-temporal-resolution-smoke",
        "status": "passed",
        "checks": checks,
        "examples": {
            "before_first": before.to_dict(),
            "old_missing_content": old.to_dict(),
            "boundary": boundary.to_dict(),
            "current_with_content": current.to_dict(),
            "same_day_ambiguous": same_day.to_dict(),
            "baseline_unresolved": baseline.to_dict(),
        },
    }


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    print(json.dumps(run(database_url), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
