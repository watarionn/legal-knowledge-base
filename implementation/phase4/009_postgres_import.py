from __future__ import annotations

from typing import Any, Iterable, Sequence

DOCUMENT_COLUMNS = (
    "document_id",
    "law_revision_id",
    "source_file_id",
    "ingestion_run_id",
    "xml_schema_version",
    "xml_decl_encoding",
    "root_tag_name",
    "root_namespace_uri",
    "root_attributes_jsonb",
    "source_xml_sha256",
    "parser_version",
    "parse_status",
    "schema_validation_status",
    "schema_validation_errors_jsonb",
    "node_count",
    "attachment_reference_count",
    "parsed_at",
)

NODE_COLUMNS = (
    "node_id",
    "document_id",
    "parent_node_id",
    "node_kind",
    "ordinal",
    "document_order",
    "depth",
    "tag_name",
    "namespace_uri",
    "qname_original",
    "structural_num",
    "display_label",
    "old_num",
    "old_style",
    "attributes_jsonb",
    "text_original",
    "text_search_normalized",
    "mixed_content_jsonb",
    "xml_path",
    "source_line",
)

ATTACHMENT_COLUMNS = (
    "attachment_id",
    "document_id",
    "law_revision_id",
    "ref_node_id",
    "source_file_id",
    "source_attribute_name",
    "source_src",
    "resolved_locator",
    "media_type",
    "sha256",
    "byte_size",
    "availability_status",
    "resolution_detail_jsonb",
    "first_seen_run_id",
    "last_seen_run_id",
)

ISSUE_COLUMNS = (
    "document_id",
    "node_id",
    "issue_code",
    "severity",
    "message",
    "source_line",
    "details_jsonb",
    "ingestion_run_id",
)

SOURCE_FILE_MEMBER_COLUMNS = (
    "member_source_file_id",
    "container_source_file_id",
    "member_path",
    "member_ordinal",
    "compressed_size",
    "uncompressed_size",
    "crc32",
)

JSONB_COLUMNS = {
    "root_attributes_jsonb",
    "schema_validation_errors_jsonb",
    "attributes_jsonb",
    "mixed_content_jsonb",
    "resolution_detail_jsonb",
    "details_jsonb",
}


def _load_psycopg():
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError(
            "psycopg 3 is required for PostgreSQL import. "
            "Install with `python -m pip install 'psycopg[binary]>=3,<4'`."
        ) from exc
    return psycopg, Jsonb


def _insert_sql(table: str, columns: Sequence[str]) -> str:
    placeholders = ", ".join(["%s"] * len(columns))
    return (
        f"INSERT INTO legal_kb.{table} ({', '.join(columns)}) "
        f"VALUES ({placeholders})"
    )


def _adapt_row(
    row: dict[str, Any],
    columns: Sequence[str],
    Jsonb,
) -> tuple[Any, ...]:
    values: list[Any] = []
    for column in columns:
        value = row.get(column)
        if column in JSONB_COLUMNS:
            value = Jsonb(value)
        values.append(value)
    return tuple(values)


def _batched(rows: Sequence[dict[str, Any]], batch_size: int) -> Iterable[Sequence[dict[str, Any]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    for start in range(0, len(rows), batch_size):
        yield rows[start : start + batch_size]


def document_exists(conn, document_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM legal_kb.law_document WHERE document_id = %s)",
            (document_id,),
        )
        return bool(cur.fetchone()[0])


def insert_source_file_member(conn, row: dict[str, Any]) -> bool:
    """Insert ZIP member provenance once.

    Returns True when inserted and False when the same member_source_file_id already exists.
    The caller remains responsible for creating both referenced source_file rows.
    """

    _, Jsonb = _load_psycopg()
    del Jsonb
    sql = _insert_sql("source_file_member", SOURCE_FILE_MEMBER_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(
            sql + " ON CONFLICT (member_source_file_id) DO NOTHING",
            tuple(row.get(column) for column in SOURCE_FILE_MEMBER_COLUMNS),
        )
        return cur.rowcount == 1


def insert_parsed_document(
    conn,
    parsed,
    *,
    batch_size: int = 1000,
    skip_existing: bool = True,
) -> bool:
    """Persist one ParsedXmlDocument into the Phase 4 relational model.

    The document is inserted before its nodes, then attachments and parse issues.
    Parent-node FKs are DEFERRABLE, but the parser already emits parents before descendants.
    Returns True when inserted. When skip_existing=True, an existing document_id is left intact
    and False is returned.
    """

    _, Jsonb = _load_psycopg()

    document_id = parsed.law_document["document_id"]
    if skip_existing and document_exists(conn, document_id):
        return False

    document_sql = _insert_sql("law_document", DOCUMENT_COLUMNS)
    node_sql = _insert_sql("provision_node", NODE_COLUMNS)
    attachment_sql = _insert_sql("attachment", ATTACHMENT_COLUMNS)
    issue_sql = _insert_sql("xml_parse_issue", ISSUE_COLUMNS)

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                document_sql,
                _adapt_row(parsed.law_document, DOCUMENT_COLUMNS, Jsonb),
            )

            for batch in _batched(parsed.nodes, batch_size):
                cur.executemany(
                    node_sql,
                    [_adapt_row(row, NODE_COLUMNS, Jsonb) for row in batch],
                )

            for batch in _batched(parsed.attachments, batch_size):
                cur.executemany(
                    attachment_sql,
                    [_adapt_row(row, ATTACHMENT_COLUMNS, Jsonb) for row in batch],
                )

            for batch in _batched(parsed.issues, batch_size):
                cur.executemany(
                    issue_sql,
                    [_adapt_row(row, ISSUE_COLUMNS, Jsonb) for row in batch],
                )

    return True
