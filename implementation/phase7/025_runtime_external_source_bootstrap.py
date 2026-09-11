from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PHASE6_DIR = HERE.parent / "phase6"

DDL_STEPS = (
    ("foundation", PHASE6_DIR / "001_external_source_schema.sql", (
        "external_source_provider", "external_document", "external_document_snapshot",
        "source_relation", "source_relation_assertion",
    )),
    ("parliamentary", PHASE6_DIR / "006_parliamentary_proceedings_schema.sql", (
        "external_document_part", "external_document_part_observation",
    )),
    ("official_gazette", PHASE6_DIR / "013_official_gazette_schema.sql", (
        "official_gazette_issue", "official_gazette_asset",
        "official_gazette_certificate_observation",
    )),
    ("ndl_metadata", PHASE6_DIR / "020_ndl_metadata_schema.sql", (
        "ndl_metadata_observation",
    )),
    ("linkage", PHASE6_DIR / "027_cross_source_linkage_schema.sql", (
        "source_relation_effective_state", "external_relation_retrieval",
    )),
)

BASE_REQUIRED = (
    "ingestion_run", "source_file", "law", "law_revision", "provision_node",
)


def classify_step(existing: set[str], required: tuple[str, ...]) -> str:
    present = set(required).intersection(existing)
    if not present:
        return "empty"
    if present == set(required):
        return "ready"
    return "partial"


def _existing_relations(conn: Any, names: tuple[str, ...]) -> set[str]:
    existing: set[str] = set()
    with conn.cursor() as cur:
        for name in names:
            cur.execute("SELECT to_regclass(%s)", (f"legal_kb.{name}",))
            if cur.fetchone()[0] is not None:
                existing.add(name)
    return existing


def _check_base_prerequisites(conn: Any) -> None:
    missing = [
        name for name in BASE_REQUIRED
        if name not in _existing_relations(conn, (name,))
    ]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regprocedure(%s)",
            ("legal_kb.provision_node_xml_path(bigint,integer)",),
        )
        xml_path_function = cur.fetchone()[0]
    if xml_path_function is None:
        missing.append("provision_node_xml_path(bigint,integer)")
    if missing:
        raise RuntimeError("Phase 3/4 prerequisites missing: " + ", ".join(missing))


def _external_counts(conn: Any) -> dict[str, int]:
    tables = (
        "external_source_provider", "external_document", "external_document_snapshot",
        "source_relation", "source_relation_assertion",
    )
    output: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT count(*) FROM legal_kb.{table}")
            output[table] = int(cur.fetchone()[0])
    return output


def bootstrap(database_url: str) -> dict[str, Any]:
    import psycopg

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "runner": "025_runtime_external_source_bootstrap.py",
        "database_url_recorded": False,
        "steps": [],
        "status": "running",
    }
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            version_num = int(cur.fetchone()[0])
            cur.execute("SELECT version()")
            result["postgresql_version"] = str(cur.fetchone()[0])
        if version_num < 160000:
            raise RuntimeError(f"PostgreSQL 16+ required; server_version_num={version_num}")
        _check_base_prerequisites(conn)
        for name, path, required in DDL_STEPS:
            existing = _existing_relations(conn, required)
            state = classify_step(existing, required)
            if state == "partial":
                missing = [item for item in required if item not in existing]
                raise RuntimeError(
                    f"Phase 6 schema step {name} is partial; missing: {', '.join(missing)}"
                )
            if state == "empty":
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                post = _existing_relations(conn, required)
                if classify_step(post, required) != "ready":
                    raise RuntimeError(f"Phase 6 schema step {name} did not become ready")
                action = "applied"
            else:
                action = "skipped-ready"
            result["steps"].append({
                "name": name,
                "action": action,
                "objects": list(required),
            })

        result["external_counts"] = _external_counts(conn)
        result["status"] = "passed"
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LEGAL_KB_DATABASE_URL") or os.environ.get("DATABASE_URL"),
    )
    parser.add_argument("--result")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("LEGAL_KB_DATABASE_URL, DATABASE_URL, or --database-url is required")
    result = bootstrap(args.database_url)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.result:
        Path(args.result).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
