-- 法令ナレッジベース Phase 5.2: lexical / structural search
-- Target: PostgreSQL 16+
-- Search data is derived and disposable. Citation truth remains Phase 3/4 provenance.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION legal_kb.normalize_search_text(p_text text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
SELECT CASE
         WHEN p_text IS NULL THEN NULL
         ELSE regexp_replace(btrim(p_text), '[[:space:]]+', ' ', 'g')
       END;
$$;

COMMENT ON FUNCTION legal_kb.normalize_search_text(text) IS
  '検索専用の最小正規化。Unicode本文の語形や表記を推測変換せず、前後空白と連続空白だけを正規化する。';

CREATE TABLE IF NOT EXISTS legal_kb.search_unit (
    document_pk bigint NOT NULL,
    document_order integer NOT NULL,
    law_id text NOT NULL,
    law_revision_id text NOT NULL,
    node_id bytea NOT NULL CHECK (octet_length(node_id) = 32),
    source_xml_sha256 text NOT NULL,

    tag_name text,
    structural_num text,
    display_label text,
    depth integer NOT NULL CHECK (depth >= 0),

    text_original text NOT NULL,
    text_search_normalized text NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (document_pk, document_order),
    CHECK (source_xml_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CHECK (text_search_normalized <> ''),
    FOREIGN KEY (document_pk, document_order)
        REFERENCES legal_kb.provision_node(document_pk, document_order)
        ON DELETE CASCADE,
    FOREIGN KEY (document_pk, law_revision_id)
        REFERENCES legal_kb.law_document(document_pk, law_revision_id)
        ON DELETE CASCADE,
    FOREIGN KEY (law_revision_id)
        REFERENCES legal_kb.law_revision(law_revision_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (law_id)
        REFERENCES legal_kb.law(law_id)
        ON DELETE RESTRICT
);

COMMENT ON TABLE legal_kb.search_unit IS
  'Phase 4 text-bearing nodeから再生成できる検索専用派生層。本文・引用の正本ではなく、全hitはrevision/node/RAW SHAへbacklinkする。';
COMMENT ON COLUMN legal_kb.search_unit.node_id IS
  'Phase 4 logical node_id。引用・外部参照用の決定的identity。';
COMMENT ON COLUMN legal_kb.search_unit.text_original IS
  '検索hit表示用のPhase 4 cache複製。引用時はdocument/nodeとRAW provenanceを根拠にする。';

CREATE INDEX IF NOT EXISTS ix_search_unit_revision
    ON legal_kb.search_unit(law_revision_id, document_order);
CREATE INDEX IF NOT EXISTS ix_search_unit_law
    ON legal_kb.search_unit(law_id, law_revision_id, document_order);
CREATE INDEX IF NOT EXISTS ix_search_unit_tag_structural
    ON legal_kb.search_unit(tag_name, structural_num);
CREATE INDEX IF NOT EXISTS ix_search_unit_text_trgm
    ON legal_kb.search_unit USING gin (text_search_normalized gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_provision_node_structural_lookup
    ON legal_kb.provision_node(document_pk, tag_name, structural_num, document_order);
CREATE INDEX IF NOT EXISTS ix_provision_node_display_label_trgm
    ON legal_kb.provision_node USING gin (display_label gin_trgm_ops)
    WHERE display_label IS NOT NULL;

CREATE OR REPLACE FUNCTION legal_kb.rebuild_search_units(
    p_document_pk bigint DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_inserted bigint;
BEGIN
    IF p_document_pk IS NULL THEN
        TRUNCATE TABLE legal_kb.search_unit;
    ELSE
        DELETE FROM legal_kb.search_unit s
        WHERE s.document_pk = p_document_pk;
    END IF;

    INSERT INTO legal_kb.search_unit (
        document_pk,
        document_order,
        law_id,
        law_revision_id,
        node_id,
        source_xml_sha256,
        tag_name,
        structural_num,
        display_label,
        depth,
        text_original,
        text_search_normalized
    )
    SELECT
        n.document_pk,
        n.document_order,
        r.law_id,
        d.law_revision_id,
        n.node_id,
        d.source_xml_sha256,
        n.tag_name,
        n.structural_num,
        n.display_label,
        n.depth,
        n.text_original,
        legal_kb.normalize_search_text(n.text_original)
    FROM legal_kb.provision_node n
    JOIN legal_kb.law_document d
      ON d.document_pk = n.document_pk
    JOIN legal_kb.law_revision r
      ON r.law_revision_id = d.law_revision_id
    WHERE (p_document_pk IS NULL OR n.document_pk = p_document_pk)
      AND d.parse_status IN ('succeeded', 'succeeded-with-warnings')
      AND n.text_original IS NOT NULL
      AND legal_kb.normalize_search_text(n.text_original) <> '';

    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    RETURN v_inserted;
END;
$$;

COMMENT ON FUNCTION legal_kb.rebuild_search_units(bigint) IS
  'Phase 4から検索unitを再構築する。NULLで全量、document_pk指定で当該documentのみ。派生層なので再生成可能。';

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
      AND s.text_search_normalized LIKE '%' || q.value || '%'
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
  '日本語を含むliteral substring lexical search。hitごとにrevision、logical node、再構成XML path、RAW SHAを返す。';

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
      OR n.display_label LIKE '%' || legal_kb.normalize_search_text(p_display_label) || '%'
  )
ORDER BY n.document_pk, n.document_order
LIMIT greatest(1, least(coalesce(p_limit, 100), 500));
$$;

COMMENT ON FUNCTION legal_kb.structural_search(text, text, text, text, integer) IS
  'revisionを固定してXML tag/structural_num/display_labelで検索し、Phase 4/RAW provenanceへ戻れるhitを返す。';

COMMIT;
