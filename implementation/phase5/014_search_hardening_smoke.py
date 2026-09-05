from __future__ import annotations

import argparse
import os


def _connect(database_url: str):
    import psycopg
    return psycopg.connect(database_url, autocommit=True)


def run(database_url: str) -> dict:
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT legal_kb.escape_like_literal(%s)", (r"a%b_c\\d",))
            escaped = cur.fetchone()[0]
            if escaped != r"a\%b\_c\\\\d":
                raise AssertionError(f"unexpected LIKE escape result: {escaped!r}")

            cur.execute("SELECT legal_kb.rebuild_search_units(NULL)")
            indexed = int(cur.fetchone()[0])
            if indexed <= 0:
                raise AssertionError("search_unit rebuild produced no rows")

            cur.execute(
                """
                SELECT document_pk, document_order, law_revision_id, text_search_normalized
                FROM legal_kb.search_unit
                ORDER BY document_pk, document_order
                LIMIT 1
                """
            )
            document_pk, document_order, revision_id, original_normalized = cur.fetchone()

            literal = "%%%%____"
            try:
                cur.execute(
                    """
                    UPDATE legal_kb.search_unit
                    SET text_search_normalized = text_search_normalized || %s,
                        text_original = text_original || %s
                    WHERE document_pk=%s AND document_order=%s
                    """,
                    (literal, literal, document_pk, document_order),
                )
                cur.execute(
                    "SELECT document_pk, document_order FROM legal_kb.lexical_search(%s, %s, 200)",
                    (literal, revision_id),
                )
                rows = cur.fetchall()
                if rows != [(document_pk, document_order)]:
                    raise AssertionError(f"literal wildcard search mismatch: {rows[:10]!r}")
            finally:
                cur.execute("SELECT legal_kb.rebuild_search_units(%s)", (document_pk,))
                rebuilt = int(cur.fetchone()[0])
                if rebuilt <= 0:
                    raise AssertionError("failed to restore search_unit after literal smoke")

            cur.execute(
                """
                SELECT text_search_normalized
                FROM legal_kb.search_unit
                WHERE document_pk=%s AND document_order=%s
                """,
                (document_pk, document_order),
            )
            restored = cur.fetchone()[0]
            if restored != original_normalized:
                raise AssertionError("search_unit restore mismatch")

    return {
        "indexed_search_units": indexed,
        "escaped_like_literal": escaped,
        "literal_query": literal,
        "literal_hit_document_pk": document_pk,
        "literal_hit_document_order": document_order,
        "restored": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    result = run(args.database_url)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
