from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PHASE4_DIR = HERE.parent / "phase4"
PHASE5_DIR = HERE.parent / "phase5"
BASE_URL = "https://laws.e-gov.go.jp/api/2"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

PARSER = _load("legal_kb_phase76d_xml_parser", PHASE4_DIR / "005_xml_parser.py")
PG_IMPORT = _load("legal_kb_phase76d_xml_import", PHASE4_DIR / "009_postgres_import.py")
CHUNKS = _load("legal_kb_phase76d_chunk_builder", PHASE5_DIR / "024_retrieval_chunk_builder.py")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_xml(url: str, *, timeout: float, max_retries: int, retry_base_seconds: float) -> tuple[datetime, bytes]:
    attempt = 0
    while True:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/xml", "User-Agent": "legal-kb-watch-refresh/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return utcnow(), response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_HTTP_STATUS or attempt >= max_retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt >= max_retries:
                raise
        time.sleep(retry_base_seconds * (2 ** attempt))
        attempt += 1

def extract_law_xml(response_xml: bytes, expected_revision_id: str) -> bytes:
    root = ET.fromstring(response_xml)
    if root.tag != "law_data_response":
        raise ValueError("unexpected law_data response root")
    revision_id = root.findtext("./revision_info/law_revision_id")
    if revision_id != expected_revision_id:
        raise ValueError("law_data response revision mismatch")
    full_text = root.find("law_full_text")
    if full_text is None:
        raise ValueError("law_data response is missing law_full_text")
    children = [child for child in list(full_text) if child.tag == "Law"]
    if len(children) != 1:
        raise ValueError("law_data response must contain exactly one Law element")
    full_start = response_xml.find(b"<law_full_text")
    full_end = response_xml.find(b"</law_full_text>", full_start)
    law_start = response_xml.find(b"<Law", full_start, full_end)
    law_end_start = response_xml.rfind(b"</Law>", full_start, full_end)
    if min(full_start, full_end, law_start, law_end_start) < 0:
        raise ValueError("law_data response Law bytes could not be located")
    law_xml = response_xml[law_start:law_end_start + len(b"</Law>")]
    parsed_law = ET.fromstring(law_xml)
    if parsed_law.tag != "Law":
        raise ValueError("law_data response Law root is invalid")
    return law_xml


def _chunk_config_sha256() -> str:
    return CHUNKS.chunking_config_sha256(
        CHUNKS.CHUNKING_VERSION, CHUNKS.DEFAULT_MAX_CHARS
    )


def _succeeded_document_pk(conn: Any, revision_id: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT document_pk FROM legal_kb.law_document
               WHERE law_revision_id=%s
                 AND parse_status IN ('succeeded','succeeded-with-warnings')
               ORDER BY document_pk DESC LIMIT 1""",
            (revision_id,),
        )
        row = cur.fetchone()
    return None if row is None else int(row[0])


def _document_has_chunks(conn: Any, document_pk: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM legal_kb.retrieval_chunk
                   WHERE document_pk=%s AND chunking_config_sha256=%s
               )""",
            (document_pk, _chunk_config_sha256()),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def missing_content_revision_ids(conn: Any, law_id: str, run_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT lr.law_revision_id
            FROM legal_kb.law_revision lr
            JOIN legal_kb.ingestion_run first_run
              ON first_run.ingestion_run_id = lr.first_seen_run_id
            WHERE lr.law_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM legal_kb.law_document d
                  WHERE d.law_revision_id = lr.law_revision_id
                    AND d.parse_status IN ('succeeded','succeeded-with-warnings')
                    AND EXISTS (
                        SELECT 1 FROM legal_kb.retrieval_chunk c
                        WHERE c.document_pk = d.document_pk
                          AND c.chunking_config_sha256 = %s
                    )
              )
              AND (
                  lr.first_seen_run_id = %s
                  OR EXISTS (
                      SELECT 1
                      FROM legal_kb.application_law_watch w
                      JOIN legal_kb.ingestion_run base
                        ON base.ingestion_run_id = w.baseline_ingestion_run_id
                      WHERE w.workspace_id = 'local'
                        AND w.enabled = true
                        AND w.law_id = lr.law_id
                        AND (first_run.started_at, first_run.ingestion_run_id)
                            > (base.started_at, base.ingestion_run_id)
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM legal_kb.application_law_watch w
                      WHERE w.workspace_id = 'local'
                        AND w.enabled = true
                        AND w.law_id = lr.law_id
                        AND w.baseline_revision_id = lr.law_revision_id
                  )
              )
            ORDER BY lr.law_revision_id
        """, (law_id, _chunk_config_sha256(), run_id))
        return [str(row[0]) for row in cur.fetchall()]


def _write_raw(path: Path, body: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path)

def _store_source_file(
    conn: Any,
    *,
    source_file_id: str,
    source_family: str,
    source_url: str,
    stored_path: str,
    retrieved_at: datetime,
    body: bytes,
    run_id: str,
) -> None:
    digest = sha256(body).hexdigest()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO legal_kb.source_file
                (source_file_id, source_family, source_url, provider_file_id,
                 stored_path, retrieved_at, media_type, byte_size, sha256,
                 immutable, ingestion_run_id)
            VALUES (%s,%s,%s,%s,%s,%s,'application/xml',%s,%s,true,%s)
            ON CONFLICT (source_file_id) DO UPDATE SET
                stored_path = EXCLUDED.stored_path,
                retrieved_at = EXCLUDED.retrieved_at,
                byte_size = EXCLUDED.byte_size,
                sha256 = EXCLUDED.sha256,
                ingestion_run_id = EXCLUDED.ingestion_run_id
        """, (
            source_file_id, source_family, source_url, source_file_id,
            stored_path, retrieved_at, len(body), digest, run_id,
        ))

def refresh_revision_content(
    conn: Any,
    *,
    revision_id: str,
    run_id: str,
    raw_dir: Path,
    fetcher: Callable[..., tuple[datetime, bytes]] = _fetch_xml,
    parser: Any = PARSER,
    pg_import: Any = PG_IMPORT,
    chunk_builder: Any = CHUNKS,
    base_url: str = BASE_URL,
    timeout: float = 60.0,
    max_retries: int = 5,
    retry_base_seconds: float = 1.0,
) -> dict[str, Any]:
    existing_document_pk = _succeeded_document_pk(conn, revision_id)
    if existing_document_pk is not None:
        if _document_has_chunks(conn, existing_document_pk):
            return {
                'document_imported': False, 'api_fetched': False,
                'document_pk': existing_document_pk, 'chunk_count': 0,
                'already_ready': True,
            }
        chunks = chunk_builder.rebuild_document(conn, existing_document_pk)
        return {
            'document_imported': False, 'api_fetched': False,
            'document_pk': existing_document_pk, 'chunk_count': len(chunks),
            'already_ready': False,
        }
    url = base_url.rstrip('/') + '/law_data/' + urllib.parse.quote(revision_id, safe='')
    url += '?' + urllib.parse.urlencode({
        'response_format': 'xml',
        'law_full_text_format': 'xml',
    })
    retrieved_at, response_xml = fetcher(
        url, timeout=timeout, max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
    )
    law_xml = extract_law_xml(response_xml, revision_id)
    response_sha = sha256(response_xml).hexdigest()
    law_sha = sha256(law_xml).hexdigest()
    response_id = f'{run_id}:law-data:{revision_id}:response:{response_sha}'
    member_id = f'{run_id}:law-data:{revision_id}:law-full-text:{law_sha}'
    base_path = raw_dir / run_id / 'law_data'
    response_path = _write_raw(base_path / f'{revision_id}.{response_sha}.response.xml', response_xml)
    member_path = _write_raw(base_path / f'{revision_id}.{law_sha}.law.xml', law_xml)
    _store_source_file(
        conn, source_file_id=response_id, source_family='api-v2-xml-response',
        source_url=url, stored_path=response_path, retrieved_at=retrieved_at,
        body=response_xml, run_id=run_id,
    )
    _store_source_file(
        conn, source_file_id=member_id, source_family='api-v2-law-xml',
        source_url=url, stored_path=member_path, retrieved_at=retrieved_at,
        body=law_xml, run_id=run_id,
    )
    pg_import.insert_source_file_member(conn, {
        'member_source_file_id': member_id,
        'container_source_file_id': response_id,
        'member_path': 'law_full_text/Law',
        'member_ordinal': 1,
        'compressed_size': None,
        'uncompressed_size': len(law_xml),
        'crc32': None,
    })
    parsed = parser.parse_xml_bytes(
        law_xml,
        law_revision_id=revision_id,
        source_file_id=member_id,
        ingestion_run_id=run_id,
    )
    if parsed.law_document.get('parse_status') == 'failed':
        raise ValueError('law XML parse failed')
    inserted = pg_import.insert_parsed_document(
        conn, parsed, skip_existing=True, method='copy'
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT document_pk FROM legal_kb.law_document WHERE document_id=%s",
            (parsed.law_document['document_id'],),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError('law_document insert could not be resolved')
    document_pk = int(row[0])
    chunks = chunk_builder.rebuild_document(conn, document_pk)
    conn.commit()
    return {
        'document_imported': bool(inserted), 'api_fetched': True,
        'document_pk': document_pk, 'chunk_count': len(chunks),
        'already_ready': False,
    }


def refresh_missing_watch_content(
    conn: Any,
    *,
    law_id: str,
    run_id: str,
    raw_dir: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    revision_ids = missing_content_revision_ids(conn, law_id, run_id)
    imported = 0
    api_fetches = 0
    chunks_generated = 0
    for revision_id in revision_ids:
        item = refresh_revision_content(
            conn, revision_id=revision_id, run_id=run_id,
            raw_dir=raw_dir, **kwargs,
        )
        imported += int(bool(item.get('document_imported')))
        api_fetches += int(bool(item.get('api_fetched')))
        chunks_generated += int(item.get('chunk_count') or 0)
    return {
        'requested_revision_count': len(revision_ids),
        'imported_document_count': imported,
        'api_fetch_count': api_fetches,
        'chunk_count_generated': chunks_generated,
        'revision_ids': revision_ids,
    }
