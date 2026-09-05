-- Phase 5.2 search hardening: treat LIKE metacharacters as literal user text.
-- Target: PostgreSQL 16+

BEGIN;

CREATE OR REPLACE FUNCTION legal_kb.escape_like_literal(p_text text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
SELECT CASE
         WHEN p_text IS NULL THEN NULL
         ELSE replace(
                replace(
                  replace(p_text, E'\\', E'\\\\'),
                  '%', E'\\%'
                ),
                '_', E'\\_'
              )
       END;
$$;

COMMENT ON FUNCTION legal_kb.escape_like_literal(text) IS
  'LIKE検索で利用者入力のbackslash、%、_をwildcardではなくliteralとして扱うためにescapeする。';

CREATE OR REPLACE FUNCTION legal_kb.lexical_search(
    p_query text,
    p_law_revision_id text DEFAULT NULL,
    p_limit integer DEFAULT 20
) RETURNS TABLE (
    law_id text,
    law_revision_id text,
    document_pk bigint,
    document_order integer,
    node_id_hex text,
    xml_path text,
    tag_name text,
    structural_num text,
    display_label text,
    text_original text,
    source_xml_sha256 text,
    score real
)
LANGUAGE sql
STABLE
AS $$
WITH q AS (
    SELECT legal_kb.normalize_search_text(p_query) AS value
), hits AS (
    SELECT
        s.*,
        similarity(s.text_search_normalized, q.value)::real AS score
    FROM legal_kb.search_unit s
    CROSS JOIN q
    WHERE q.value IS NOT NULL
      AND q.value <> ''
      AND (p_law_revision_id IS NULL OR s.law_revision_id = p_law_revision_id)
      AND s.text_search_normalized LIKE
          '%' || legal_kb.escape_like_literal(q.value) || '%'
          ESCAPE E'\\'
    ORDER BY score DESC, s.document_pk, s.document_order
    LIMIT greatest(1, least(coalesce(p_limit, 20), 200))
)
SELECT
    h.law_id,
    h.law_revision_id,
    h.document_pk,
    h.document_order,
    encode(h.node_id, 'hex') AS node_id_hex,
    legal_kb.provision_node_xml_path(h.document_pk, h.document_order) AS xml_path,
    h.tag_name,
    h.structural_num,
    h.display_label,
    h.text_original,
    h.source_xml_sha256,
    h.score
FROM hits h
ORDER BY h.score DESC, h.document_pk, h.document_order;
$$;

COMMENT ON FUNCTION legal_kb.lexical_search(text, text, integer) IS
  '日本語を含むliteral substring lexical search。LIKE metacharacterもliteralとして扱い、revision/node/XML path/RAW SHAを返す。';

CREATE OR REPLACE FUNCTION legal_kb.structural_search(
    p_law_revision_id text,
    p_tag_name text DEFAULT NULL,
    p_structural_num text DEFAULT NULL,
    p_display_label text DEFAULT NULL,
    p_limit integer DEFAULT 100
) RETURNS TABLE (
    law_id text,
    law_revision_id text,
    document_pk bigint,
    document_order integer,
    node_id_hex text,
    xml_path text,
    tag_name text,
    structural_num text,
    display_label text,
    text_original text,
    source_xml_sha256 text
)
LANGUAGE sql
STABLE
AS $$
SELECT
    r.law_id,
    d.law_revision_id,
    n.document_pk,
    n.document_order,
    encode(n.node_id, 'hex') AS node_id_hex,
    legal_kb.provision_node_xml_path(n.document_pk, n.document_order) AS xml_path,
    n.tag_name,
    n.structural_num,
    n.display_label,
    n.text_original,
    d.source_xml_sha256
FROM legal_kb.law_document d
JOIN legal_kb.law_revision r
  ON r.law_revision_id = d.law_revision_id
JOIN legal_kb.provision_node n
  ON n.document_pk = d.document_pk
WHERE d.law_revision_id = p_law_revision_id
  AND d.parse_status IN ('succeeded', 'succeeded-with-warnings')
  AND (p_tag_name IS NULL OR n.tag_name = p_tag_name)
  AND (p_structural_num IS NULL OR n.structural_num = p_structural_num)
  AND (
      p_display_label IS NULL
      OR n.display_label LIKE
         '%' || legal_kb.escape_like_literal(legal_kb.normalize_search_text(p_display_label)) || '%'
         ESCAPE E'\\'
  )
ORDER BY n.document_pk, n.document_order
LIMIT greatest(1, least(coalesce(p_limit, 100), 500));
$$;

COMMENT ON FUNCTION legal_kb.structural_search(text, text, text, text, integer) IS
  'revision固定の構造検索。display_labelのLIKE metacharacterもliteralとして扱い、Phase 4/RAW provenanceへ戻れるhitを返す。';

COMMIT;
