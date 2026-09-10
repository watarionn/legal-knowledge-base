from __future__ import annotations

from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
_KANJI_TOKEN_RE = re.compile(r"[一-龥々〆ヵヶ]{2,12}")
_SKIP_TOKENS = frozenset({"法律", "法令", "規定", "内容"})
_SMOKE_LAW_TITLE = "Phase7検証法"


def _load(name: str, filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SERVICE = _load("legal_kb_phase7_query_service_postgres_smoke", "002_query_service.py")


def _one(conn, sql: str, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _pick_token(text: str) -> str:
    for match in _KANJI_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token not in _SKIP_TOKENS:
            return token
    compact = "".join(text.split())
    if len(compact) >= 4:
        return compact[:4]
    raise AssertionError("smoke retrieval text has no usable query token")


def run(database_url: str) -> dict:
    import psycopg

    with psycopg.connect(database_url) as conn:
        row = _one(
            conn,
            """
            SELECT c.document_pk, c.law_id, c.law_revision_id,
                   c.chunking_config_sha256, c.retrieval_text,
                   c.source_xml_sha256
            FROM legal_kb.retrieval_chunk c
            ORDER BY c.document_pk, c.start_document_order, c.chunk_id
            LIMIT 1
            """,
        )
        if row is None:
            raise AssertionError("Phase 5 retrieval chunk smoke must run first")
        (
            document_pk,
            law_id,
            revision_id,
            chunk_config,
            retrieval_text,
            source_sha,
        ) = row
        token = _pick_token(str(retrieval_text))

        with conn.cursor() as cur:
            cur.execute("SAVEPOINT phase7_query_service_smoke")
            cur.execute(
                """
                UPDATE legal_kb.law_revision
                SET valid_from=NULL, valid_to_exclusive=NULL
                WHERE law_id=%s AND law_revision_id<>%s
                """,
                (law_id, revision_id),
            )
            cur.execute(
                """
                UPDATE legal_kb.law_revision
                SET valid_from=%s, valid_to_exclusive=NULL,
                    temporal_resolution_quality='confirmed-api',
                    law_title=%s
                WHERE law_revision_id=%s
                """,
                (date(2020, 1, 1), _SMOKE_LAW_TITLE, revision_id),
            )
        try:
            service = SERVICE.QueryService(
                SERVICE.QueryServiceConfig(
                    chunking_config_sha256=str(chunk_config),
                    max_evidence=5,
                )
            )

            request = SERVICE.CONTRACT.parse_query_payload(
                {"question": f"{_SMOKE_LAW_TITLE}を確認したい"},
                default_date=date(2026, 1, 1),
            )
            discovered = service.resolve_law(conn, request)
            if discovered.status != "resolved" or discovered.selected_law_id != str(law_id):
                raise AssertionError(
                    f"law discovery did not resolve smoke law: {discovered.status}"
                )

            response = service.query(
                conn,
                {
                    "question": token,
                    "as_of_date": "2026-01-01",
                    "law_id": str(law_id),
                },
            )
        finally:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT phase7_query_service_smoke")
                cur.execute("RELEASE SAVEPOINT phase7_query_service_smoke")

        if response["status"] != "evidence-only":
            raise AssertionError(f"unexpected Phase 7 query status: {response['status']}")
        if response["law_resolution"]["status"] != "resolved":
            raise AssertionError("explicit law resolution failed")
        temporal = response["temporal_resolution"]
        if temporal["status"] != "resolved":
            raise AssertionError("strict temporal resolution did not resolve smoke revision")
        if temporal["selected_revision_id"] != str(revision_id):
            raise AssertionError("Phase 7 changed the selected revision")
        if temporal["selected_document_pk"] != int(document_pk):
            raise AssertionError("Phase 7 changed the selected document")
        if str(temporal["source_xml_sha256"]).lower() != str(source_sha).lower():
            raise AssertionError("temporal source SHA differs from smoke source")
        retrieval = response["retrieval"]
        if retrieval["status"] != "ok":
            raise AssertionError("Phase 7 retrieval did not return contexts")
        if int(retrieval["channel_counts"]["lexical"]) <= 0:
            raise AssertionError("Phase 7 lexical channel returned no hits")
        evidence = response["evidence"]
        if not evidence:
            raise AssertionError("Phase 7 did not rebuild Evidence Bundle")
        if any(item["citation_truth"] != "phase3-phase4" for item in evidence):
            raise AssertionError("Evidence citation truth changed")
        if any(
            item["law_revision_id"] != str(revision_id)
            or item["source_xml_sha256"].lower() != str(source_sha).lower()
            for item in evidence
        ):
            raise AssertionError("Evidence escaped the selected revision/source SHA")
        if response["answer"]["status"] != "provider-not-configured":
            raise AssertionError("MVP must remain usable without an answer provider")

        return {
            "schema_version": "1.0",
            "runner": "006_query_service_postgres_smoke.py",
            "status": "passed",
            "law_discovery": "resolved",
            "law_id": str(law_id),
            "law_title": _SMOKE_LAW_TITLE,
            "law_revision_id": str(revision_id),
            "document_pk": int(document_pk),
            "query_token": token,
            "chunking_config_sha256": str(chunk_config),
            "retrieval_status": retrieval["status"],
            "lexical_hits": int(retrieval["channel_counts"]["lexical"]),
            "evidence_count": len(evidence),
            "strict_revision_scope": True,
            "provenance_roundtrip": True,
            "answer_provider_required": False,
            "database_url_recorded": False,
        }


def main() -> None:
    database_url = (
        os.environ.get("LEGAL_KB_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("LEGAL_KB_DSN")
    )
    if not database_url:
        raise SystemExit("LEGAL_KB_DATABASE_URL, DATABASE_URL, or LEGAL_KB_DSN is required")
    print(json.dumps(run(database_url), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
