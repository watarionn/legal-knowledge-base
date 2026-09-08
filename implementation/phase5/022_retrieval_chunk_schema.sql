-- 法令ナレッジベース Phase 5.3a: retrieval chunk provenance layer
-- Target: PostgreSQL 16+
-- Chunks are rebuildable derivative data. Citation truth remains Phase 3/4.

BEGIN;

CREATE TABLE IF NOT EXISTS legal_kb.retrieval_chunk (
    chunk_id text PRIMARY KEY,
    chunking_version text NOT NULL,
    document_pk bigint NOT NULL,
    law_id text NOT NULL,
    law_revision_id text NOT NULL,
    source_xml_sha256 text NOT NULL,

    anchor_document_order integer NOT NULL,
    start_document_order integer NOT NULL,
    end_document_order integer NOT NULL,
    source_document_orders integer[] NOT NULL,

    anchor_node_id bytea NOT NULL CHECK (octet_length(anchor_node_id) = 32),
    start_node_id bytea NOT NULL CHECK (octet_length(start_node_id) = 32),
    end_node_id bytea NOT NULL CHECK (octet_length(end_node_id) = 32),

    anchor_tag_name text,
    anchor_structural_num text,
    anchor_display_label text,
    context_prefix text,
    retrieval_text text NOT NULL,
    retrieval_text_sha256 text NOT NULL,
    char_count integer NOT NULL CHECK (char_count >= 1),
    source_unit_count integer NOT NULL CHECK (source_unit_count >= 1),
    is_oversize boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),

    CHECK (chunk_id ~ '^[0-9a-f]{64}$'),
    CHECK (source_xml_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CHECK (retrieval_text_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (btrim(chunking_version) <> ''),
    CHECK (btrim(retrieval_text) <> ''),
    CHECK (start_document_order <= end_document_order),
    CHECK (cardinality(source_document_orders) = source_unit_count),
    CHECK (source_document_orders[1] = start_document_order),
    CHECK (source_document_orders[array_length(source_document_orders, 1)] = end_document_order),
    CHECK (array_position(source_document_orders, NULL) IS NULL),

    UNIQUE (chunking_version, document_pk, start_document_order, end_document_order),
    FOREIGN KEY (document_pk, law_revision_id)
        REFERENCES legal_kb.law_document(document_pk, law_revision_id)
        ON DELETE CASCADE,
    FOREIGN KEY (law_revision_id)
        REFERENCES legal_kb.law_revision(law_revision_id) ON DELETE RESTRICT,
    FOREIGN KEY (law_id)
        REFERENCES legal_kb.law(law_id) ON DELETE RESTRICT,
    FOREIGN KEY (document_pk, anchor_document_order)
        REFERENCES legal_kb.provision_node(document_pk, document_order)
        ON DELETE CASCADE,
    FOREIGN KEY (document_pk, start_document_order)
        REFERENCES legal_kb.provision_node(document_pk, document_order)
        ON DELETE CASCADE,
    FOREIGN KEY (document_pk, end_document_order)
        REFERENCES legal_kb.provision_node(document_pk, document_order)
        ON DELETE CASCADE
);

COMMENT ON TABLE legal_kb.retrieval_chunk IS
  'Phase 5.3のmodel-independent retrieval chunk。再生成可能な派生層であり、引用正本ではない。';
COMMENT ON COLUMN legal_kb.retrieval_chunk.source_document_orders IS
  'chunkへ寄与したtext-bearing Phase 4 nodeのdocument_orderを順序付きで保持する。';
COMMENT ON COLUMN legal_kb.retrieval_chunk.context_prefix IS
  'embedding/retrieval用の構造ラベル文脈。原文引用には使用しない。';
COMMENT ON COLUMN legal_kb.retrieval_chunk.retrieval_text IS
  'embedding/retrieval用に最小空白正規化して連結した派生本文。引用時はPhase 4 nodeへ戻る。';
COMMENT ON COLUMN legal_kb.retrieval_chunk.is_oversize IS
  '単一source unitがsoft max charactersを超え、node内分割を避けたchunkであることを示す。';

CREATE INDEX IF NOT EXISTS ix_retrieval_chunk_revision
    ON legal_kb.retrieval_chunk(law_revision_id, start_document_order);
CREATE INDEX IF NOT EXISTS ix_retrieval_chunk_law
    ON legal_kb.retrieval_chunk(law_id, law_revision_id, start_document_order);
CREATE INDEX IF NOT EXISTS ix_retrieval_chunk_anchor
    ON legal_kb.retrieval_chunk(anchor_tag_name, anchor_structural_num);

CREATE OR REPLACE FUNCTION legal_kb.retrieval_chunk_provenance(p_chunk_id text)
RETURNS TABLE (
    chunk_id text,
    chunking_version text,
    law_id text,
    law_revision_id text,
    document_pk bigint,
    anchor_document_order integer,
    anchor_xml_path text,
    start_document_order integer,
    start_xml_path text,
    end_document_order integer,
    end_xml_path text,
    source_document_orders integer[],
    source_xml_sha256 text,
    retrieval_text_sha256 text
)
LANGUAGE sql
STABLE
AS $$
SELECT
    c.chunk_id,
    c.chunking_version,
    c.law_id,
    c.law_revision_id,
    c.document_pk,
    c.anchor_document_order,
    legal_kb.provision_node_xml_path(c.document_pk, c.anchor_document_order),
    c.start_document_order,
    legal_kb.provision_node_xml_path(c.document_pk, c.start_document_order),
    c.end_document_order,
    legal_kb.provision_node_xml_path(c.document_pk, c.end_document_order),
    c.source_document_orders,
    c.source_xml_sha256,
    c.retrieval_text_sha256
FROM legal_kb.retrieval_chunk c
WHERE c.chunk_id = p_chunk_id;
$$;

COMMENT ON FUNCTION legal_kb.retrieval_chunk_provenance(text) IS
  'retrieval chunkからrevision、Phase 4 node range、XML path、RAW SHAへ戻るpublic provenance envelope。';

COMMIT;
