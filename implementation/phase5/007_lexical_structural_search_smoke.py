from __future__ import annotations

import argparse
import os


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url, autocommit=True)


def run(database_url: str) -> dict:
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT legal_kb.rebuild_search_units(NULL)")
            indexed = int(cur.fetchone()[0])
            if indexed <= 0:
                raise AssertionError("search_unit rebuild produced no rows")

            cur.execute(
                """
                SELECT count(*)
                FROM legal_kb.search_unit s
                JOIN legal_kb.law_document d ON d.document_pk=s.document_pk
                JOIN legal_kb.provision_node n
                  ON n.document_pk=s.document_pk AND n.document_order=s.document_order
                WHERE s.law_revision_id<>d.law_revision_id
                   OR s.source_xml_sha256<>d.source_xml_sha256
                   OR s.node_id<>n.node_id
                   OR s.text_original<>n.text_original
                """
            )
            backlink_mismatch = int(cur.fetchone()[0])
            if backlink_mismatch:
                raise AssertionError(f"search backlink mismatch: {backlink_mismatch}")

            cur.execute(
                """
                SELECT text_search_normalized, law_revision_id
                FROM legal_kb.search_unit
                ORDER BY document_pk, document_order
                LIMIT 1
                """
            )
            sample_text, revision_id = cur.fetchone()
            query = sample_text[: min(len(sample_text), 12)]
            if not query:
                raise AssertionError("empty sample lexical query")

            cur.execute(
                "SELECT * FROM legal_kb.lexical_search(%s, %s, 10)",
                (query, revision_id),
            )
            lexical_rows = cur.fetchall()
            if not lexical_rows:
                raise AssertionError("lexical search returned no rows")
            lexical_names = [column.name for column in cur.description]
            lexical = dict(zip(lexical_names, lexical_rows[0]))
            for key in ("law_revision_id", "node_id_hex", "xml_path", "source_xml_sha256"):
                if not lexical.get(key):
                    raise AssertionError(f"lexical hit missing provenance field: {key}")

            cur.execute(
                """
                SELECT tag_name, structural_num
                FROM legal_kb.provision_node n
                JOIN legal_kb.law_document d ON d.document_pk=n.document_pk
                WHERE d.law_revision_id=%s AND n.tag_name IS NOT NULL
                ORDER BY n.document_order
                LIMIT 1
                """,
                (revision_id,),
            )
            tag_name, structural_num = cur.fetchone()
            cur.execute(
                "SELECT * FROM legal_kb.structural_search(%s, %s, %s, NULL, 10)",
                (revision_id, tag_name, structural_num),
            )
            structural_rows = cur.fetchall()
            if not structural_rows:
                raise AssertionError("structural search returned no rows")
            structural_names = [column.name for column in cur.description]
            structural = dict(zip(structural_names, structural_rows[0]))
            for key in ("law_revision_id", "node_id_hex", "xml_path", "source_xml_sha256"):
                if not structural.get(key):
                    raise AssertionError(f"structural hit missing provenance field: {key}")

            cur.execute(
                """
                SELECT count(*)
                FROM legal_kb.search_unit
                WHERE text_search_normalized IS NULL OR text_search_normalized=''
                """
            )
            empty_normalized = int(cur.fetchone()[0])
            if empty_normalized:
                raise AssertionError(f"empty normalized search rows: {empty_normalized}")

    return {
        "indexed_search_units": indexed,
        "backlink_mismatch": backlink_mismatch,
        "lexical_query": query,
        "lexical_hit_revision": lexical["law_revision_id"],
        "lexical_hit_path": lexical["xml_path"],
        "structural_hit_revision": structural["law_revision_id"],
        "structural_hit_path": structural["xml_path"],
        "empty_normalized": empty_normalized,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = ap.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    result = run(args.database_url)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
