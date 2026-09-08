-- 法令ナレッジベース Phase 5.3c: revision-scoped chunk retrieval helpers
-- Target: PostgreSQL 16+
-- Ranking is derived. Citation truth remains Phase 3/4 provenance.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_retrieval_chunk_text_trgm
    ON legal_kb.retrieval_chunk USING gin (retrieval_text gin_trgm_ops);

CREATE OR REPLACE FUNCTION legal_kb.retrieval_chunk_lexical_search(
    p_query text,
    p_law_revision_id text,
    p_document_pk bigint,
    p_chunking_config_sha256 text DEFAULT NULL,
    p_limit integer DEFAULT 50
) RETURNS TABLE (
    chunk_id text,
    law_id text,
    law_revision_id text,
    document_pk bigint,
    anchor_document_order integer,
    start_document_order integer,
    end_document_order integer,
    context_prefix text,
    retrieval_text text,
    source_xml_sha256 text,
    retrieval_text_sha256 text,
    score real
)
LANGUAGE sql
STABLE
AS $$WITH q AS (
    SELECT legal_kb.normalize_search_text(p_query) AS value
)
SELECT
    c.chunk_id,
    c.law_id,
    c.law_revision_id,
    c.document_pk,
    c.anchor_document_order,
    c.start_document_order,
    c.end_document_order,
    c.context_prefix,
    c.retrieval_text,
    c.source_xml_sha256,
    c.retrieval_text_sha256,
    similarity(c.retrieval_text, q.value)::real AS score
FROM legal_kb.retrieval_chunk c
CROSS JOIN q
WHERE q.value IS NOT NULL
  AND q.value <> ''
  AND c.law_revision_id = p_law_revision_id
  AND c.document_pk = p_document_pk
  AND (p_chunking_config_sha256 IS NULL OR c.chunking_config_sha256 = p_chunking_config_sha256)
  AND c.retrieval_text LIKE '%' || q.value || '%'
ORDER BY score DESC, c.start_document_order, c.chunk_id
LIMIT greatest(1, least(coalesce(p_limit, 50), 200));
$$;

COMMENT ON FUNCTION legal_kb.retrieval_chunk_lexical_search(text, text, bigint, text, integer) IS
  'strict resolverで確定済みrevision/document内だけをchunk lexical検索する。ranking scoreは法的確信度ではない。';
CREATE OR REPLACE FUNCTION legal_kb.retrieval_chunk_structural_search(
    p_law_revision_id text,
    p_document_pk bigint,
    p_tag_name text DEFAULT NULL,
    p_structural_num text DEFAULT NULL,
    p_display_label text DEFAULT NULL,
    p_chunking_config_sha256 text DEFAULT NULL,
    p_limit integer DEFAULT 100
) RETURNS TABLE (
    chunk_id text,
    law_id text,
    law_revision_id text,
    document_pk bigint,
    anchor_document_order integer,
    start_document_order integer,
    end_document_order integer,
    context_prefix text,
    retrieval_text text,
    source_xml_sha256 text,
    retrieval_text_sha256 text,
    score real
)
LANGUAGE sql
STABLE
AS $$
SELECT
    c.chunk_id,
    c.law_id,
    c.law_revision_id,
    c.document_pk,
    c.anchor_document_order,
    c.start_document_order,
    c.end_document_order,
    c.context_prefix,    c.retrieval_text,
    c.source_xml_sha256,
    c.retrieval_text_sha256,
    1.0::real AS score
FROM legal_kb.retrieval_chunk c
WHERE c.law_revision_id = p_law_revision_id
  AND c.document_pk = p_document_pk
  AND (p_tag_name IS NULL OR c.anchor_tag_name = p_tag_name)
  AND (p_structural_num IS NULL OR c.anchor_structural_num = p_structural_num)
  AND (
      p_display_label IS NULL
      OR c.anchor_display_label LIKE '%' || legal_kb.normalize_search_text(p_display_label) || '%'
  )
  AND (p_chunking_config_sha256 IS NULL OR c.chunking_config_sha256 = p_chunking_config_sha256)
  AND (p_tag_name IS NOT NULL OR p_structural_num IS NOT NULL OR p_display_label IS NOT NULL)
ORDER BY c.start_document_order, c.chunk_id
LIMIT greatest(1, least(coalesce(p_limit, 100), 500));
$$;

COMMENT ON FUNCTION legal_kb.retrieval_chunk_structural_search(text, bigint, text, text, text, text, integer) IS
  'strict resolverで確定済みrevision/document内だけをchunk anchor構造で検索する。';

COMMIT;
