from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
from typing import Any, Iterable
import zipfile

PHASE4_DIR = Path(__file__).resolve().parent
REPO_ROOT = PHASE4_DIR.parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "validation" / "xml_snapshot_manifest.public.json"
REVISION_XML_RE = re.compile(r"^([0-9A-Z]{15}_[0-9]{8}_[0-9A-Z]{15})\.xml$")
UNIT_SEPARATOR = "\x1f"
RUNNER_VERSION = "phase4-full-relational-import-0.1"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class ArchiveSpec:
    name: str
    path: Path
    size_bytes: int
    sha256: str
    xml_count: int


@dataclass(frozen=True)
class XmlMember:
    archive: ArchiveSpec
    member_path: str
    member_ordinal: int
    compressed_size: int
    uncompressed_size: int
    crc32: int
    revision_id: str


def sha256_path(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), sha256(raw).hexdigest()


def archive_specs(manifest: dict[str, Any], archive_dir: Path) -> list[ArchiveSpec]:
    specs = []
    for part in manifest["parts"]:
        specs.append(
            ArchiveSpec(
                name=part["name"],
                path=archive_dir / part["name"],
                size_bytes=int(part["size_bytes"]),
                sha256=part["sha256"].lower(),
                xml_count=int(part["xml_count"]),
            )
        )
    return specs


def validate_archives(specs: Iterable[ArchiveSpec]) -> None:
    for spec in specs:
        if not spec.path.is_file():
            raise FileNotFoundError(spec.path)
        actual_size = spec.path.stat().st_size
        if actual_size != spec.size_bytes:
            raise AssertionError(
                f"archive size mismatch: {spec.name}: expected={spec.size_bytes} actual={actual_size}"
            )
        actual_sha = sha256_path(spec.path)
        if actual_sha != spec.sha256:
            raise AssertionError(
                f"archive SHA-256 mismatch: {spec.name}: expected={spec.sha256} actual={actual_sha}"
            )
        with zipfile.ZipFile(spec.path) as zf:
            xml_count = sum(
                1
                for info in zf.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".xml")
            )
        if xml_count != spec.xml_count:
            raise AssertionError(
                f"archive XML count mismatch: {spec.name}: expected={spec.xml_count} actual={xml_count}"
            )


def iter_xml_members(specs: Iterable[ArchiveSpec]) -> Iterable[XmlMember]:
    for spec in specs:
        with zipfile.ZipFile(spec.path) as zf:
            for ordinal, info in enumerate(zf.infolist(), start=1):
                if info.is_dir() or not info.filename.lower().endswith(".xml"):
                    continue
                basename = PurePosixPath(info.filename).name
                match = REVISION_XML_RE.fullmatch(basename)
                if not match:
                    raise ValueError(f"unrecognized XML member name: {spec.name}:{info.filename}")
                yield XmlMember(
                    archive=spec,
                    member_path=info.filename,
                    member_ordinal=ordinal,
                    compressed_size=info.compress_size,
                    uncompressed_size=info.file_size,
                    crc32=info.CRC,
                    revision_id=match.group(1),
                )


def collect_members(specs: Iterable[ArchiveSpec], expected_total: int) -> list[XmlMember]:
    members = list(iter_xml_members(specs))
    if len(members) != expected_total:
        raise AssertionError(f"XML total mismatch: expected={expected_total} actual={len(members)}")
    revision_ids = [m.revision_id for m in members]
    if len(set(revision_ids)) != len(revision_ids):
        duplicates = sorted({rid for rid in revision_ids if revision_ids.count(rid) > 1})
        raise AssertionError(f"duplicate revision ids: {duplicates[:20]}")
    return members


def archive_source_file_id(archive_sha256: str) -> str:
    return f"archive-sha256:{archive_sha256.lower()}"


def member_source_file_id(archive_sha256: str, member_path: str) -> str:
    token = sha256(
        (archive_sha256.lower() + UNIT_SEPARATOR + member_path).encode("utf-8")
    ).hexdigest()
    return f"zip-member:{token}"


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def _existing_revision_ids(conn, revision_ids: list[str], chunk_size: int = 2000) -> set[str]:
    found: set[str] = set()
    with conn.cursor() as cur:
        for start in range(0, len(revision_ids), chunk_size):
            chunk = revision_ids[start : start + chunk_size]
            cur.execute(
                "SELECT law_revision_id FROM legal_kb.law_revision WHERE law_revision_id = ANY(%s)",
                (chunk,),
            )
            found.update(row[0] for row in cur.fetchall())
    return found


def assert_revision_reconciliation(conn, members: list[XmlMember]) -> None:
    revision_ids = [member.revision_id for member in members]
    found = _existing_revision_ids(conn, revision_ids)
    missing = sorted(set(revision_ids) - found)
    if missing:
        sample = ", ".join(missing[:10])
        raise RuntimeError(
            "LAW_REVISION_NOT_RECONCILED: "
            f"{len(missing)} of {len(revision_ids)} XML revisions are missing from legal_kb.law_revision. "
            f"sample=[{sample}]. Phase 4 must not seed law_revision from XML."
        )


def _captured_at(manifest: dict[str, Any]) -> datetime:
    captured_on = str(manifest["captured_on"])
    return datetime.fromisoformat(captured_on).replace(tzinfo=timezone.utc)


def _insert_ingestion_run(
    conn,
    *,
    run_id: str,
    manifest_sha256: str,
    parser_version: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.ingestion_run (
              ingestion_run_id, started_at, input_manifest_sha256,
              parser_version, result_status
            ) VALUES (%s, now(), %s, %s, 'running')
            ON CONFLICT (ingestion_run_id) DO NOTHING
            """,
            (run_id, manifest_sha256, parser_version),
        )


def _insert_container_source(conn, *, spec: ArchiveSpec, run_id: str, retrieved_at: datetime) -> None:
    source_file_id = archive_source_file_id(spec.sha256)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.source_file (
              source_file_id, source_family, provider_file_id, stored_path,
              retrieved_at, media_type, byte_size, sha256, original_file_name,
              immutable, ingestion_run_id
            ) VALUES (
              %s, 'egov-bulk-zip-snapshot', %s, %s,
              %s, 'application/zip', %s, %s, %s, true, %s
            )
            ON CONFLICT (source_file_id) DO NOTHING
            """,
            (
                source_file_id,
                spec.name,
                f"snapshot-archive://{spec.name}",
                retrieved_at,
                spec.size_bytes,
                spec.sha256,
                spec.name,
                run_id,
            ),
        )


def _insert_member_source(
    conn,
    *,
    member: XmlMember,
    xml_sha256: str,
    run_id: str,
    retrieved_at: datetime,
    pg_import,
    parser,
) -> str:
    source_file_id = member_source_file_id(member.archive.sha256, member.member_path)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO legal_kb.source_file (
              source_file_id, source_family, stored_path, retrieved_at,
              media_type, byte_size, sha256, original_file_name,
              immutable, ingestion_run_id
            ) VALUES (
              %s, 'egov-bulk-xml', %s, %s, 'application/xml',
              %s, %s, %s, true, %s
            )
            ON CONFLICT (source_file_id) DO NOTHING
            """,
            (
                source_file_id,
                f"zip://{member.archive.name}/{member.member_path}",
                retrieved_at,
                member.uncompressed_size,
                xml_sha256,
                PurePosixPath(member.member_path).name,
                run_id,
            ),
        )

    pg_import.insert_source_file_member(
        conn,
        parser.build_source_file_member_row(
            member_source_file_id=source_file_id,
            container_source_file_id=archive_source_file_id(member.archive.sha256),
            member_path=member.member_path,
            member_ordinal=member.member_ordinal,
            compressed_size=member.compressed_size,
            uncompressed_size=member.uncompressed_size,
            crc32=member.crc32,
        ),
    )
    return source_file_id


def _result_template(
    *, run_id: str, manifest_sha256: str, parser_version: str, members: list[XmlMember]
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "runner": "011_full_relational_import.py",
        "runner_version": RUNNER_VERSION,
        "run_id": run_id,
        "input_manifest_sha256": manifest_sha256,
        "parser_version": parser_version,
        "expected_document_count": len(members),
        "status": "running",
        "attempted_document_count": 0,
        "inserted_document_count": 0,
        "skipped_existing_document_count": 0,
        "failed_document_count": 0,
        "inserted_node_count": 0,
        "inserted_attachment_count": 0,
        "parse_issue_count": 0,
        "failures": [],
    }


def _write_result(path: Path | None, result: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(
    *,
    archive_dir: Path,
    manifest_path: Path,
    database_url: str | None,
    result_path: Path | None,
    run_id: str,
    batch_size: int,
    progress_every: int,
    preflight_only: bool,
    max_documents: int | None,
    fail_fast: bool,
) -> dict[str, Any]:
    manifest, manifest_sha256 = load_manifest(manifest_path)
    specs = archive_specs(manifest, archive_dir)
    validate_archives(specs)
    expected_total = int(manifest["totals"]["xml_count"])
    members = collect_members(specs, expected_total)
    if max_documents is not None:
        if max_documents < 1:
            raise ValueError("max_documents must be >= 1")
        members = members[:max_documents]

    if preflight_only and not database_url:
        return {
            "schema_version": "1.0",
            "runner": "011_full_relational_import.py",
            "runner_version": RUNNER_VERSION,
            "status": "preflight-passed",
            "input_manifest_sha256": manifest_sha256,
            "archive_count": len(specs),
            "document_count": len(members),
            "all_archive_hashes_match": True,
            "all_xml_names_parsed": True,
            "revision_ids_unique": True,
            "database_revision_reconciliation_checked": False,
        }

    if not database_url:
        raise RuntimeError("DATABASE_URL or --database-url is required unless --preflight-only is used")

    parser = _load("legal_kb_phase4_xml_parser", PHASE4_DIR / "005_xml_parser.py")
    pg_import = _load("legal_kb_phase4_postgres_import", PHASE4_DIR / "009_postgres_import.py")
    retrieved_at = _captured_at(manifest)
    result = _result_template(
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        parser_version=parser.PARSER_VERSION,
        members=members,
    )
    started = time.monotonic()

    with _connect(database_url) as conn:
        assert_revision_reconciliation(conn, members)
        result["database_revision_reconciliation_checked"] = True
        result["reconciled_revision_count"] = len(members)
        if preflight_only:
            result["status"] = "preflight-passed"
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            _write_result(result_path, result)
            return result

        _insert_ingestion_run(
            conn,
            run_id=run_id,
            manifest_sha256=manifest_sha256,
            parser_version=parser.PARSER_VERSION,
        )
        for spec in specs:
            _insert_container_source(conn, spec=spec, run_id=run_id, retrieved_at=retrieved_at)

        archive_handles: dict[Path, zipfile.ZipFile] = {}
        try:
            for index, member in enumerate(members, start=1):
                result["attempted_document_count"] = index
                try:
                    zf = archive_handles.get(member.archive.path)
                    if zf is None:
                        zf = zipfile.ZipFile(member.archive.path)
                        archive_handles[member.archive.path] = zf
                    raw = zf.read(member.member_path)
                    if len(raw) != member.uncompressed_size:
                        raise AssertionError(
                            f"member size mismatch: {member.archive.name}:{member.member_path}"
                        )
                    xml_sha = sha256(raw).hexdigest()
                    source_file_id = member_source_file_id(member.archive.sha256, member.member_path)
                    parsed = parser.parse_xml_bytes(
                        raw,
                        law_revision_id=member.revision_id,
                        source_file_id=source_file_id,
                        ingestion_run_id=run_id,
                    )
                    with conn.transaction():
                        _insert_member_source(
                            conn,
                            member=member,
                            xml_sha256=xml_sha,
                            run_id=run_id,
                            retrieved_at=retrieved_at,
                            pg_import=pg_import,
                            parser=parser,
                        )
                        inserted = pg_import.insert_parsed_document(
                            conn,
                            parsed,
                            batch_size=batch_size,
                            skip_existing=True,
                            method="copy",
                        )
                    if inserted:
                        result["inserted_document_count"] += 1
                        result["inserted_node_count"] += len(parsed.nodes)
                        result["inserted_attachment_count"] += len(parsed.attachments)
                        result["parse_issue_count"] += len(parsed.issues)
                    else:
                        result["skipped_existing_document_count"] += 1
                except Exception as exc:
                    result["failed_document_count"] += 1
                    failure = {
                        "revision_id": member.revision_id,
                        "archive": member.archive.name,
                        "member_path": member.member_path,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                    result["failures"].append(failure)
                    if fail_fast:
                        result["status"] = "failed"
                        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
                        _write_result(result_path, result)
                        raise

                if progress_every > 0 and (
                    index % progress_every == 0 or index == len(members)
                ):
                    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    _write_result(result_path, result)
                    print(
                        json.dumps(
                            {
                                "progress": f"{index}/{len(members)}",
                                "inserted": result["inserted_document_count"],
                                "skipped": result["skipped_existing_document_count"],
                                "failed": result["failed_document_count"],
                                "nodes": result["inserted_node_count"],
                                "elapsed_seconds": result["elapsed_seconds"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
        finally:
            for zf in archive_handles.values():
                zf.close()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM legal_kb.law_document")
            result["database_law_document_count"] = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM legal_kb.provision_node")
            result["database_provision_node_count"] = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM legal_kb.attachment")
            result["database_attachment_count"] = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM legal_kb.source_file_member")
            result["database_source_file_member_count"] = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM legal_kb.xml_parse_issue")
            result["database_xml_parse_issue_count"] = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT
                  count(*) FILTER (WHERE severity = 'warning'),
                  count(*) FILTER (WHERE severity = 'error')
                FROM legal_kb.xml_parse_issue
                WHERE ingestion_run_id = %s
                """,
                (run_id,),
            )
            warning_issues, error_issues = cur.fetchone()
            result["warning_issue_count"] = int(warning_issues or 0)
            result["error_issue_count"] = int(error_issues or 0)
            final_status = "succeeded" if result["failed_document_count"] == 0 else "partial"
            cur.execute(
                """
                UPDATE legal_kb.ingestion_run
                   SET completed_at=now(), result_status=%s,
                       warnings_count=%s, errors_count=%s
                 WHERE ingestion_run_id=%s
                """,
                (
                    final_status,
                    result["warning_issue_count"],
                    result["error_issue_count"] + result["failed_document_count"],
                    run_id,
                ),
            )

        result["status"] = "succeeded" if result["failed_document_count"] == 0 else "partial"
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _write_result(result_path, result)
        return result


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Import the 10,711-XML snapshot into Phase 4 PostgreSQL tables"
    )
    ap.add_argument("--archive-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--result", type=Path)
    ap.add_argument(
        "--run-id",
        default=f"phase4-full-import-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    ap.add_argument("--batch-size", type=int, default=5000)
    ap.add_argument("--progress-every", type=int, default=100)
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--max-documents", type=int)
    ap.add_argument("--fail-fast", action="store_true")
    args = ap.parse_args()

    result = run(
        archive_dir=args.archive_dir,
        manifest_path=args.manifest,
        database_url=args.database_url,
        result_path=args.result,
        run_id=args.run_id,
        batch_size=args.batch_size,
        progress_every=args.progress_every,
        preflight_only=args.preflight_only,
        max_documents=args.max_documents,
        fail_fast=args.fail_fast,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
