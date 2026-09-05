from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
from typing import Any

PHASE5_DIR = Path(__file__).resolve().parent
REPO_ROOT = PHASE5_DIR.parent.parent
MANIFEST = REPO_ROOT / "docs" / "validation" / "xml_snapshot_manifest.public.json"
ARCHIVE_NAMES = tuple(f"all_xml_{i:02d}.zip" for i in range(1, 5))
MIN_POSTGRES_VERSION_NUM = 160000
MIN_FREE_BYTES_FULL_REBUILD = 80 * 1024**3
MIN_FREE_BYTES_BENCHMARK_ONLY = 40 * 1024**3
EXPECTED_PHASE4_DOCUMENTS = 10705
EXPECTED_PHASE4_NODES = 32116330


@dataclass(frozen=True)
class HostReadiness:
    postgres_version: str
    postgres_version_num: int
    free_bytes: int
    archive_count: int
    archive_bytes: int
    law_revision_count: int
    law_document_count: int
    provision_node_count: int
    phase4_full_dataset_present: bool
    recommended_mode: str
    required_free_bytes: int
    disk_ready: bool
    ready: bool


def validate_archives(archive_dir: Path) -> tuple[int, int]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    specs = {part["name"]: part for part in manifest["parts"]}
    total_bytes = 0
    for name in ARCHIVE_NAMES:
        path = archive_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        spec = specs[name]
        size = path.stat().st_size
        if size != int(spec["size_bytes"]):
            raise AssertionError(f"archive size mismatch: {name}: {size} != {spec['size_bytes']}")
        total_bytes += size
    return len(ARCHIVE_NAMES), total_bytes


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def _scalar(conn, sql: str) -> int:
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return int(row[0])


def inspect_database(database_url: str) -> dict[str, Any]:
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW server_version_num")
            version_num = int(cur.fetchone()[0])
            cur.execute("SELECT version()")
            version = str(cur.fetchone()[0])
        if version_num < MIN_POSTGRES_VERSION_NUM:
            raise RuntimeError(f"PostgreSQL 16+ required; server_version_num={version_num}")

        def relation_exists(name: str) -> bool:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s) IS NOT NULL", (name,))
                return bool(cur.fetchone()[0])

        law_revision_count = (
            _scalar(conn, "SELECT count(*) FROM legal_kb.law_revision")
            if relation_exists("legal_kb.law_revision") else 0
        )
        law_document_count = (
            _scalar(conn, "SELECT count(*) FROM legal_kb.law_document")
            if relation_exists("legal_kb.law_document") else 0
        )
        provision_node_count = (
            _scalar(conn, "SELECT count(*) FROM legal_kb.provision_node")
            if relation_exists("legal_kb.provision_node") else 0
        )
    return {
        "postgres_version": version,
        "postgres_version_num": version_num,
        "law_revision_count": law_revision_count,
        "law_document_count": law_document_count,
        "provision_node_count": provision_node_count,
    }


def evaluate(archive_dir: Path, work_dir: Path, database_url: str) -> HostReadiness:
    archive_count, archive_bytes = validate_archives(archive_dir)
    db = inspect_database(database_url)
    work_dir.mkdir(parents=True, exist_ok=True)
    free_bytes = int(shutil.disk_usage(work_dir).free)

    phase4_full = (
        db["law_document_count"] == EXPECTED_PHASE4_DOCUMENTS
        and db["provision_node_count"] == EXPECTED_PHASE4_NODES
    )
    mode = "benchmark-only" if phase4_full else "full-rebuild"
    required = MIN_FREE_BYTES_BENCHMARK_ONLY if phase4_full else MIN_FREE_BYTES_FULL_REBUILD
    disk_ready = free_bytes >= required

    return HostReadiness(
        postgres_version=db["postgres_version"],
        postgres_version_num=db["postgres_version_num"],
        free_bytes=free_bytes,
        archive_count=archive_count,
        archive_bytes=archive_bytes,
        law_revision_count=db["law_revision_count"],
        law_document_count=db["law_document_count"],
        provision_node_count=db["provision_node_count"],
        phase4_full_dataset_present=phase4_full,
        recommended_mode=mode,
        required_free_bytes=required,
        disk_ready=disk_ready,
        ready=disk_ready,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight the host for the Phase 5.2 full-search benchmark")
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("LEGAL_KB_DSN") or os.environ.get("DATABASE_URL"))
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("LEGAL_KB_DSN, DATABASE_URL, or --database-url is required")

    result = asdict(evaluate(args.archive_dir, args.work_dir, args.database_url))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.result:
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(text, encoding="utf-8")
    print(text, end="")
    if not result["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
