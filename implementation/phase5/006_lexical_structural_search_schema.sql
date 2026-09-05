-- 法令ナレッジベース Phase 5.2: lexical / structural search
-- Target: PostgreSQL 16+
-- Search text is a rebuildable derivative. Phase 4 normalized infoset / RAW XML remain citation truth.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS legal_kb.search_index_build (
    build_id text PRIMARY KEY,
    index_version text NOT NULL,
    builder_version text NOT NULL,
    normalization_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    document_count integer NOT NULL DEFAULT 0 CHECK (document_count >= 0),
    search_unit_count bigint NOT NULL DEFAULT 0 CHECK (search_unit_count >= 0),
    searchable_sentence_count bigint NOT NULL DEFAULT 0 CHECK (searchable_sentence_count >= 0),
    uncovered_sentence_count bigint NOT NULL DEFAULT 0 CHECK (uncovered_sentence_count >= 0),
    detail_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (jsonb_typeof(detail_jsonb) = 'object')
);

COMMENT ON TABLE legal_kb.search_index_build IS
  'Phase 5.2検索派生層の再構築run。検索indexはRAW/Phase 4から再生成可能で、引用正本ではない。';

CREATE TABLE IF NOT EXISTS legal_kb.search_unit (
    search_unit_id text PRIMARY KEY CHECK (search_unit_id ~ '^[0-9a-f]{64}$'),
    build_id text NOT NULL REFERENCES legal_kb.search_index_build(build_id) ON DELETE RESTRICT,
    law_id text NOT NULL REFERENCES legal_kb.law(law_id) ON DELETE RESTRICT,
    law_revision_id text NOT NULL REFERENCES legal_kb.law_revision(law_revision_id) ON DELETE RESTRICT,
    document_pk bigint NOT NULL,
    source_document_order integer NOT NULL CHECK (source_document_order >= 1),
    anchor_document_order integer NOT NULL CHECK (anchor_document_order >= 1),
    unit_kind text NOT NULL CHECK (unit_kind IN ('sentence', 'table-row', 'direct-text')),
    anchor_tag_name text,
    anchor_structural_num text,
    anchor_display_label text,
    hierarchy_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb,
    search_text_cache text NOT NULL,
    search_text_normalized text NOT NULL,
    context_text_cache text NOT NULL DEFAULT '',
    context_text_normalized text NOT NULL DEFAULT '',
    source_xml_sha256 text NOT NULL CHECK (source_xml_sha256 ~ '^[0-9a-fA-F]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(hierarchy_jsonb) = 'array'),
    CHECK (search_text_normalized <> ''),
    UNIQUE (document_pk, unit_kind, source_document_order),
    FOREIGN KEY (document_pk, law_revision_id)
      REFERENCES legal_kb.law_document(document_pk, law_revision_id) ON DELETE CASCADE,
    FOREIGN KEY (document_pk, source_document_order)
      REFERENCES legal_kb.provision_node(document_pk, document_order) ON DELETE CASCADE,
    FOREIGN KEY (document_pk, anchor_document_order)
      REFERENCES legal_kb.provision_node(document_pk, document_order) ON DELETE CASCADE
);

COMMENT ON TABLE legal_kb.search_unit IS
  'revision-aware lexical/structural search unit。search/cache列は派生値であり、引用時はsource_document_orderからPhase 4原文を再構成する。';
COMMENT ON COLUMN legal_kb.search_unit.search_text_cache IS
  '検索unit構築時のPhase 4 string-value cache。引用正本ではなく、原文再構成との整合検証用。';
COMMENT ON COLUMN legal_kb.search_unit.hierarchy_jsonb IS
  'Part/Chapter/Article/Paragraph/Item等の祖先構造context。検索filter/表示用でidentityの代替ではない。';

CREATE TABLE IF NOT EXISTS legal_kb.search_document_state (
    document_pk bigint PRIMARY KEY REFERENCES legal_kb.law_document(document_pk) ON DELETE CASCADE,
    build_id text NOT NULL REFERENCES legal_kb.search_index_build(build_id) ON DELETE RESTRICT,
    index_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    search_unit_count integer NOT NULL DEFAULT 0 CHECK (search_unit_count >= 0),
    searchable_sentence_count integer NOT NULL DEFAULT 0 CHECK (searchable_sentence_count >= 0),
    covered_sentence_count integer NOT NULL DEFAULT 0 CHECK (covered_sentence_count >= 0),
    uncovered_sentence_count integer NOT NULL DEFAULT 0 CHECK (uncovered_sentence_count >= 0),
    built_at timestamptz NOT NULL DEFAULT now(),
    detail_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (jsonb_typeof(detail_jsonb) = 'object'),
    CHECK (covered_sentence_count + uncovered_sentence_count = searchable_sentence_count)
);

CREATE INDEX IF NOT EXISTS ix_search_unit_revision
  ON legal_kb.search_unit(law_revision_id, document_pk, source_document_order);
CREATE INDEX IF NOT EXISTS ix_search_unit_structure
  ON legal_kb.search_unit(law_revision_id, anchor_tag_name, anchor_structural_num, unit_kind);
CREATE INDEX IF NOT EXISTS ix_search_unit_text_trgm
  ON legal_kb.search_unit USING gin (search_text_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_search_unit_context_trgm
  ON legal_kb.search_unit USING gin (context_text_normalized gin_trgm_ops);

CREATE OR REPLACE FUNCTION legal_kb.provision_node_string_value(
    p_document_pk bigint,
    p_document_order integer
) RETURNS text
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_kind text;
    v_text text;
    v_mixed jsonb;
    v_segment jsonb;
    v_segment_kind text;
    v_child_order integer;
    v_child_kind text;
    v_result text := '';
BEGIN
    SELECT n.node_kind, n.text_original, n.mixed_content_jsonb
      INTO v_kind, v_text, v_mixed
    FROM legal_kb.provision_node n
    WHERE n.document_pk = p_document_pk
      AND n.document_order = p_document_order;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF v_kind <> 'element' THEN
        RETURN coalesce(v_text, '');
    END IF;

    IF v_mixed IS NULL OR jsonb_array_length(v_mixed) = 0 THEN
        RETURN coalesce(v_text, '');
    END IF;

    FOR v_segment IN SELECT value FROM jsonb_array_elements(v_mixed)
    LOOP
        v_segment_kind := v_segment->>'kind';
        IF v_segment_kind IN ('text', 'tail') THEN
            v_result := v_result || coalesce(v_segment->>'value', '');
        ELSIF v_segment_kind = 'child' THEN
            v_child_order := (v_segment->>'document_order')::integer;
            SELECT n.node_kind INTO v_child_kind
            FROM legal_kb.provision_node n
            WHERE n.document_pk = p_document_pk
              AND n.document_order = v_child_order;
            IF v_child_kind = 'element' THEN
                v_result := v_result || coalesce(
                    legal_kb.provision_node_string_value(p_document_pk, v_child_order),
                    ''
                );
            END IF;
        END IF;
    END LOOP;

    RETURN v_result;
END;
$$;

COMMENT ON FUNCTION legal_kb.provision_node_string_value(bigint, integer) IS
  'Phase 4 mixed-content treeからelement string-valueを原順序で再構成する。検索cacheではなく引用原文取得に使う。';

CREATE OR REPLACE FUNCTION legal_kb.search_revision_units_normalized(
    p_law_revision_id text,
    p_query_normalized text,
    p_limit integer DEFAULT 20,
    p_anchor_tag_name text DEFAULT NULL,
    p_structural_num text DEFAULT NULL,
    p_unit_kind text DEFAULT NULL
) RETURNS TABLE (
    search_unit_id text,
    law_id text,
    law_revision_id text,
    document_pk bigint,
    document_id text,
    source_xml_sha256 text,
    source_document_order integer,
    anchor_document_order integer,
    unit_kind text,
    anchor_tag_name text,
    anchor_structural_num text,
    anchor_display_label text,
    hierarchy_jsonb jsonb,
    reconstructed_xml_path text,
    body_match boolean,
    context_match boolean,
    rank_score real
)
LANGUAGE sql
STABLE
AS $$
SELECT
    u.search_unit_id,
    u.law_id,
    u.law_revision_id,
    u.document_pk,
    d.document_id,
    u.source_xml_sha256,
    u.source_document_order,
    u.anchor_document_order,
    u.unit_kind,
    u.anchor_tag_name,
    u.anchor_structural_num,
    u.anchor_display_label,
    u.hierarchy_jsonb,
    legal_kb.provision_node_xml_path(u.document_pk, u.source_document_order),
    (u.search_text_normalized LIKE '%' || p_query_normalized || '%') AS body_match,
    (u.context_text_normalized LIKE '%' || p_query_normalized || '%') AS context_match,
    (
      CASE WHEN u.search_text_normalized LIKE '%' || p_query_normalized || '%' THEN 2.0 ELSE 0.0 END
      + CASE WHEN u.context_text_normalized LIKE '%' || p_query_normalized || '%' THEN 0.75 ELSE 0.0 END
      + greatest(
          similarity(u.search_text_normalized, p_query_normalized),
          similarity(u.context_text_normalized, p_query_normalized) * 0.5
        )
    )::real AS rank_score
FROM legal_kb.search_unit u
JOIN legal_kb.law_document d
  ON d.document_pk = u.document_pk
WHERE u.law_revision_id = p_law_revision_id
  AND p_query_normalized IS NOT NULL
  AND p_query_normalized <> ''
  AND (
      u.search_text_normalized LIKE '%' || p_query_normalized || '%'
      OR u.context_text_normalized LIKE '%' || p_query_normalized || '%'
      OR u.search_text_normalized % p_query_normalized
      OR u.context_text_normalized % p_query_normalized
  )
  AND (p_anchor_tag_name IS NULL OR u.anchor_tag_name = p_anchor_tag_name)
  AND (p_structural_num IS NULL OR u.anchor_structural_num = p_structural_num)
  AND (p_unit_kind IS NULL OR u.unit_kind = p_unit_kind)
ORDER BY
    (u.search_text_normalized LIKE '%' || p_query_normalized || '%') DESC,
    (u.context_text_normalized LIKE '%' || p_query_normalized || '%') DESC,
    rank_score DESC,
    u.document_pk,
    u.source_document_order,
    u.search_unit_id
LIMIT greatest(1, least(coalesce(p_limit, 20), 200));
$$;

COMMENT ON FUNCTION legal_kb.search_revision_units_normalized(text, text, integer, text, text, text) IS
  '1 revisionに固定したstrict lexical/structural search。p_query_normalizedはPhase 5.2 normalization contract適用済み文字列を渡す。';

COMMIT;
