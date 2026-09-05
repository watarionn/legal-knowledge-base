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
RUNNER_VERSION = "phase4-full-relational-import-0.2"


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
    return [ArchiveSpec(p["name"], archive_dir / p["name"], int(p["size_bytes"]), p["sha256"].lower(), int(p["xml_count"])) for p in manifest["parts"]]


def validate_archives(specs: Iterable[ArchiveSpec]) -> None:
    for spec in specs:
        if not spec.path.is_file():
            raise FileNotFoundError(spec.path)
        if spec.path.stat().st_size != spec.size_bytes:
            raise AssertionError(f"archive size mismatch: {spec.name}")
        actual = sha256_path(spec.path)
        if actual != spec.sha256:
            raise AssertionError(f"archive SHA-256 mismatch: {spec.name}: expected={spec.sha256} actual={actual}")
        with zipfile.ZipFile(spec.path) as zf:
            count = sum(1 for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(".xml"))
        if count != spec.xml_count:
            raise AssertionError(f"archive XML count mismatch: {spec.name}: expected={spec.xml_count} actual={count}")


def iter_xml_members(specs: Iterable[ArchiveSpec]) -> Iterable[XmlMember]:
    for spec in specs:
        with zipfile.ZipFile(spec.path) as zf:
            for ordinal, info in enumerate(zf.infolist(), 1):
                if info.is_dir() or not info.filename.lower().endswith(".xml"):
                    continue
                match = REVISION_XML_RE.fullmatch(PurePosixPath(info.filename).name)
                if not match:
                    raise ValueError(f"unrecognized XML member name: {spec.name}:{info.filename}")
                yield XmlMember(spec, info.filename, ordinal, info.compress_size, info.file_size, info.CRC, match.group(1))


def collect_members(specs: Iterable[ArchiveSpec], expected_total: int) -> list[XmlMember]:
    members = list(iter_xml_members(specs))
    if len(members) != expected_total:
        raise AssertionError(f"XML total mismatch: expected={expected_total} actual={len(members)}")
    ids = [m.revision_id for m in members]
    if len(ids) != len(set(ids)):
        seen, dup = set(), []
        for rid in ids:
            if rid in seen and rid not in dup:
                dup.append(rid)
            seen.add(rid)
        raise AssertionError(f"duplicate revision ids: {dup[:20]}")
    return members


def archive_source_file_id(archive_sha256: str) -> str:
    return f"archive-sha256:{archive_sha256.lower()}"


def member_source_file_id(archive_sha256: str, member_path: str) -> str:
    return "zip-member:" + sha256((archive_sha256.lower() + UNIT_SEPARATOR + member_path).encode()).hexdigest()


def _connect(database_url: str):
    import psycopg
    conn = psycopg.connect(database_url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit TO off")
    return conn


def _existing_ids(conn, table: str, ids: list[str], chunk_size: int = 2000) -> set[str]:
    found: set[str] = set()
    with conn.cursor() as cur:
        for start in range(0, len(ids), chunk_size):
            cur.execute(f"SELECT law_revision_id FROM legal_kb.{table} WHERE law_revision_id = ANY(%s)", (ids[start:start + chunk_size],))
            found.update(r[0] for r in cur.fetchall())
    return found


def revision_reconciliation(conn, members: list[XmlMember]) -> tuple[set[str], list[str]]:
    ids = [m.revision_id for m in members]
    found = _existing_ids(conn, "law_revision", ids)
    return found, sorted(set(ids) - found)


def existing_imported_revision_ids(conn, revision_ids: list[str]) -> set[str]:
    return _existing_ids(conn, "law_document", revision_ids)


def _captured_at(manifest: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(manifest["captured_on"])).replace(tzinfo=timezone.utc)


def _seed_run(conn, run_id: str, manifest_sha: str, parser_version: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO legal_kb.ingestion_run
          (ingestion_run_id,started_at,input_manifest_sha256,parser_version,result_status)
          VALUES (%s,now(),%s,%s,'running') ON CONFLICT (ingestion_run_id) DO NOTHING""",
          (run_id, manifest_sha, parser_version))


def _seed_archive(conn, spec: ArchiveSpec, run_id: str, retrieved_at: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO legal_kb.source_file
          (source_file_id,source_family,provider_file_id,stored_path,retrieved_at,media_type,byte_size,sha256,original_file_name,immutable,ingestion_run_id)
          VALUES (%s,'egov-bulk-zip-snapshot',%s,%s,%s,'application/zip',%s,%s,%s,true,%s)
          ON CONFLICT (source_file_id) DO NOTHING""",
          (archive_source_file_id(spec.sha256), spec.name, f"snapshot-archive://{spec.name}", retrieved_at, spec.size_bytes, spec.sha256, spec.name, run_id))


def _seed_member(conn, member: XmlMember, xml_sha: str, run_id: str, retrieved_at: datetime, pg_import, parser) -> str:
    sid = member_source_file_id(member.archive.sha256, member.member_path)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO legal_kb.source_file
          (source_file_id,source_family,stored_path,retrieved_at,media_type,byte_size,sha256,original_file_name,immutable,ingestion_run_id)
          VALUES (%s,'egov-bulk-xml',%s,%s,'application/xml',%s,%s,%s,true,%s)
          ON CONFLICT (source_file_id) DO NOTHING""",
          (sid, f"zip://{member.archive.name}/{member.member_path}", retrieved_at, member.uncompressed_size, xml_sha, PurePosixPath(member.member_path).name, run_id))
    pg_import.insert_source_file_member(conn, parser.build_source_file_member_row(
        member_source_file_id=sid, container_source_file_id=archive_source_file_id(member.archive.sha256),
        member_path=member.member_path, member_ordinal=member.member_ordinal,
        compressed_size=member.compressed_size, uncompressed_size=member.uncompressed_size, crc32=member.crc32))
    return sid


def _defer(conn, member: XmlMember, xml_sha: str, source_file_id: str, run_id: str) -> None:
    details = json.dumps({
        "archive": member.archive.name, "archive_sha256": member.archive.sha256,
        "member_path": member.member_path, "source_file_id": source_file_id,
        "source_xml_sha256": xml_sha,
        "reason": "XML snapshot revision is not present in the reconciled Phase 3 API history.",
    }, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute("""SELECT reconciliation_issue_id FROM legal_kb.reconciliation_issue
          WHERE entity_type='law_revision' AND entity_id=%s AND issue_code='LAW_REVISION_NOT_RECONCILED'
            AND resolved_at IS NULL ORDER BY reconciliation_issue_id LIMIT 1""", (member.revision_id,))
        row = cur.fetchone()
        if row:
            cur.execute("""UPDATE legal_kb.reconciliation_issue SET observed_values_jsonb=%s::jsonb,
              last_seen_run_id=%s,updated_at=now() WHERE reconciliation_issue_id=%s""", (details, run_id, row[0]))
        else:
            cur.execute("""INSERT INTO legal_kb.reconciliation_issue
              (entity_type,entity_id,field_name,issue_code,severity,observed_values_jsonb,first_seen_run_id,last_seen_run_id)
              VALUES ('law_revision',%s,'law_revision_id','LAW_REVISION_NOT_RECONCILED','error',%s::jsonb,%s,%s)""",
              (member.revision_id, details, run_id, run_id))


def _write_result(path: Path | None, result: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _result(run_id: str, manifest_sha: str, parser_version: str, total: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0", "runner": "011_full_relational_import.py", "runner_version": RUNNER_VERSION,
        "run_id": run_id, "input_manifest_sha256": manifest_sha, "parser_version": parser_version,
        "expected_document_count": total, "status": "running", "attempted_document_count": 0,
        "inserted_document_count": 0, "skipped_existing_document_count": 0,
        "deferred_unreconciled_document_count": 0, "failed_document_count": 0,
        "inserted_node_count": 0, "inserted_attachment_count": 0, "parse_issue_count": 0, "failures": [],
    }


def _progress(index: int, total: int, result: dict[str, Any], path: Path | None, started: float) -> None:
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    _write_result(path, result)
    print(json.dumps({"progress": f"{index}/{total}", "inserted": result["inserted_document_count"],
        "skipped": result["skipped_existing_document_count"], "deferred": result["deferred_unreconciled_document_count"],
        "failed": result["failed_document_count"], "nodes": result["inserted_node_count"],
        "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False), flush=True)


def run(*, archive_dir: Path, manifest_path: Path, database_url: str | None, result_path: Path | None,
        run_id: str, batch_size: int, progress_every: int, preflight_only: bool,
        max_documents: int | None, fail_fast: bool) -> dict[str, Any]:
    manifest, manifest_sha = load_manifest(manifest_path)
    specs = archive_specs(manifest, archive_dir)
    validate_archives(specs)
    members = collect_members(specs, int(manifest["totals"]["xml_count"]))
    if max_documents is not None:
        if max_documents < 1:
            raise ValueError("max_documents must be >= 1")
        members = members[:max_documents]
    if preflight_only and not database_url:
        return {"schema_version": "1.0", "runner": "011_full_relational_import.py", "runner_version": RUNNER_VERSION,
            "status": "preflight-passed", "input_manifest_sha256": manifest_sha, "archive_count": len(specs),
            "document_count": len(members), "all_archive_hashes_match": True, "all_xml_names_parsed": True,
            "revision_ids_unique": True, "database_revision_reconciliation_checked": False}
    if not database_url:
        raise RuntimeError("DATABASE_URL or --database-url is required unless --preflight-only is used")

    parser = _load("legal_kb_phase4_xml_parser", PHASE4_DIR / "005_xml_parser.py")
    pg_import = _load("legal_kb_phase4_postgres_import", PHASE4_DIR / "009_postgres_import.py")
    result = _result(run_id, manifest_sha, parser.PARSER_VERSION, len(members))
    started, retrieved_at = time.monotonic(), _captured_at(manifest)
    with _connect(database_url) as conn:
        reconciled, missing = revision_reconciliation(conn, members)
        imported = existing_imported_revision_ids(conn, [m.revision_id for m in members])
        result.update({"database_revision_reconciliation_checked": True,
            "already_imported_revision_count_at_start": len(imported), "reconciled_revision_count": len(reconciled),
            "deferred_unreconciled_document_count": len(missing), "unreconciled_revision_ids": missing})
        if preflight_only:
            result["status"] = "preflight-passed" if not missing else "preflight-passed-with-unreconciled"
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            _write_result(result_path, result)
            return result

        _seed_run(conn, run_id, manifest_sha, parser.PARSER_VERSION)
        for spec in specs:
            _seed_archive(conn, spec, run_id, retrieved_at)
        handles: dict[Path, zipfile.ZipFile] = {}
        try:
            for index, member in enumerate(members, 1):
                result["attempted_document_count"] = index
                try:
                    if member.revision_id in reconciled and member.revision_id in imported:
                        result["skipped_existing_document_count"] += 1
                        if progress_every > 0 and (index % progress_every == 0 or index == len(members)):
                            _progress(index, len(members), result, result_path, started)
                        continue
                    zf = handles.get(member.archive.path)
                    if zf is None:
                        zf = zipfile.ZipFile(member.archive.path)
                        handles[member.archive.path] = zf
                    raw = zf.read(member.member_path)
                    if len(raw) != member.uncompressed_size:
                        raise AssertionError(f"member size mismatch: {member.archive.name}:{member.member_path}")
                    xml_sha = sha256(raw).hexdigest()
                    is_reconciled = member.revision_id in reconciled
                    sid = member_source_file_id(member.archive.sha256, member.member_path)
                    parsed = parser.parse_xml_bytes(raw, law_revision_id=member.revision_id, source_file_id=sid,
                                                    ingestion_run_id=run_id) if is_reconciled else None
                    with conn.transaction():
                        sid = _seed_member(conn, member, xml_sha, run_id, retrieved_at, pg_import, parser)
                        if is_reconciled:
                            inserted = pg_import.insert_parsed_document(conn, parsed, batch_size=batch_size,
                                                                       skip_existing=True, method="copy")
                        else:
                            _defer(conn, member, xml_sha, sid, run_id)
                            inserted = False
                    if is_reconciled and inserted:
                        result["inserted_document_count"] += 1
                        result["inserted_node_count"] += len(parsed.nodes)
                        result["inserted_attachment_count"] += len(parsed.attachments)
                        result["parse_issue_count"] += len(parsed.issues)
                    elif is_reconciled:
                        result["skipped_existing_document_count"] += 1
                except Exception as exc:
                    result["failed_document_count"] += 1
                    result["failures"].append({"revision_id": member.revision_id, "archive": member.archive.name,
                        "member_path": member.member_path, "error_type": type(exc).__name__, "message": str(exc)})
                    if fail_fast:
                        result["status"] = "failed"
                        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
                        _write_result(result_path, result)
                        raise
                if progress_every > 0 and (index % progress_every == 0 or index == len(members)):
                    _progress(index, len(members), result, result_path, started)
        finally:
            for zf in handles.values():
                zf.close()

        with conn.cursor() as cur:
            for key, table in (("database_law_document_count", "law_document"),
                ("database_provision_node_count", "provision_node"), ("database_attachment_count", "attachment"),
                ("database_source_file_member_count", "source_file_member"), ("database_xml_parse_issue_count", "xml_parse_issue")):
                cur.execute(f"SELECT count(*) FROM legal_kb.{table}")
                result[key] = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FILTER (WHERE severity='warning'),count(*) FILTER (WHERE severity='error') FROM legal_kb.xml_parse_issue WHERE ingestion_run_id=%s", (run_id,))
            warnings, errors = cur.fetchone()
            result["warning_issue_count"], result["error_issue_count"] = int(warnings or 0), int(errors or 0)
            status = "succeeded" if not result["failed_document_count"] and not missing else "partial"
            cur.execute("UPDATE legal_kb.ingestion_run SET completed_at=now(),result_status=%s,warnings_count=%s,errors_count=%s WHERE ingestion_run_id=%s",
                (status, result["warning_issue_count"], result["error_issue_count"] + result["failed_document_count"] + len(missing), run_id))
        result["status"] = "succeeded" if not result["failed_document_count"] and not missing else "partial"
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _write_result(result_path, result)
        return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Import the 10,711-XML snapshot into Phase 4 PostgreSQL tables")
    ap.add_argument("--archive-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--result", type=Path)
    ap.add_argument("--run-id", default=f"phase4-full-import-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    ap.add_argument("--batch-size", type=int, default=5000)
    ap.add_argument("--progress-every", type=int, default=100)
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--max-documents", type=int)
    ap.add_argument("--fail-fast", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(archive_dir=a.archive_dir, manifest_path=a.manifest, database_url=a.database_url,
        result_path=a.result, run_id=a.run_id, batch_size=a.batch_size, progress_every=a.progress_every,
        preflight_only=a.preflight_only, max_documents=a.max_documents, fail_fast=a.fail_fast), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
