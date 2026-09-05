-- 法令ナレッジベース Phase 4: XML構造DB
-- Target: PostgreSQL
-- Status: proposed detailed-design contract
-- Source of truth: KNW-20260903-001, DEC-20260904-001

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

-- ZIP等のコンテナ原本と、その内部にある個別XML source_fileを結ぶ。
CREATE TABLE source_file_member (
    member_source_file_id text PRIMARY KEY REFERENCES source_file(source_file_id) ON DELETE RESTRICT,
    container_source_file_id text NOT NULL REFERENCES source_file(source_file_id) ON DELETE RESTRICT,
    member_path text NOT NULL,
    member_ordinal integer CHECK (member_ordinal IS NULL OR member_ordinal >= 1),
    compressed_size bigint CHECK (compressed_size IS NULL OR compressed_size >= 0),
    uncompressed_size bigint CHECK (uncompressed_size IS NULL OR uncompressed_size >= 0),
    crc32 text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (container_source_file_id, member_path),
    CHECK (member_source_file_id <> container_source_file_id),
    CHECK (crc32 IS NULL OR crc32 ~ '^[0-9A-Fa-f]{8}$')
);

COMMENT ON TABLE source_file_member IS 'ZIP等の不変原本と内部メンバーsource_fileの包含関係。member_pathは原値を保持する。';

CREATE TABLE law_document (
    document_pk bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    document_id text PRIMARY KEY,
    law_revision_id text NOT NULL REFERENCES law_revision(law_revision_id) ON DELETE RESTRICT,
    source_file_id text NOT NULL REFERENCES source_file(source_file_id) ON DELETE RESTRICT,
    ingestion_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,

    xml_schema_version text,
    xml_decl_encoding text,
    root_tag_name text,
    root_namespace_uri text,
    root_attributes_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_xml_sha256 text NOT NULL,
    parser_version text NOT NULL,

    parse_status text NOT NULL CHECK (
        parse_status IN ('pending', 'succeeded', 'succeeded-with-warnings', 'failed')
    ),
    schema_validation_status text NOT NULL CHECK (
        schema_validation_status IN ('not-checked', 'valid', 'invalid', 'error', 'not-applicable')
    ),
    schema_validation_errors_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb,

    node_count integer CHECK (node_count IS NULL OR node_count >= 0),
    attachment_reference_count integer CHECK (
        attachment_reference_count IS NULL OR attachment_reference_count >= 0
    ),
    parsed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CHECK (parse_status = 'failed' OR root_tag_name IS NOT NULL),
    CHECK (document_id ~ '^[0-9a-f]{64}$'),
    CHECK (source_xml_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CHECK (jsonb_typeof(root_attributes_jsonb) = 'object'),
    CHECK (jsonb_typeof(schema_validation_errors_jsonb) = 'array'),
    UNIQUE (law_revision_id, source_xml_sha256),
    UNIQUE (document_id, law_revision_id),
    UNIQUE (document_pk, law_revision_id)
);

COMMENT ON TABLE law_document IS '個別法令XMLの正規化単位。RAW XMLを置換せず、原本source_fileとSHA-256へ必ず戻れる。';
COMMENT ON COLUMN law_document.document_id IS 'sha256(law_revision_id + unit-separator + source_xml_sha256) の決定的ID。';
COMMENT ON COLUMN law_document.schema_validation_status IS 'XSD非適合でもwell-formed XMLは拒否せずinvalidとして構造化を継続できる。';

CREATE INDEX ix_law_document_revision ON law_document(law_revision_id);
CREATE INDEX ix_law_document_source_file ON law_document(source_file_id);
CREATE INDEX ix_law_document_parse_status ON law_document(parse_status, schema_validation_status);

CREATE TABLE provision_node (
    document_pk bigint NOT NULL REFERENCES law_document(document_pk) ON DELETE CASCADE,
    document_order integer NOT NULL CHECK (document_order >= 1),
    node_id bytea NOT NULL CHECK (octet_length(node_id) = 32),
    parent_document_order integer,

    node_kind text NOT NULL DEFAULT 'element' CHECK (
        node_kind IN ('element', 'comment', 'processing-instruction')
    ),
    ordinal integer NOT NULL CHECK (ordinal >= 1),
    path_index integer NOT NULL CHECK (path_index >= 1),
    depth integer NOT NULL CHECK (depth >= 0),

    tag_name text,
    namespace_uri text,
    qname_original text,
    structural_num text,
    display_label text,
    old_num text,
    old_style text,

    attributes_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    text_original text,
    text_search_normalized text,
    mixed_content_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_line integer CHECK (source_line IS NULL OR source_line >= 1),

    created_at timestamptz NOT NULL DEFAULT now(),

    CHECK (jsonb_typeof(attributes_jsonb) = 'object'),
    CHECK (jsonb_typeof(mixed_content_jsonb) = 'array'),
    CHECK ((node_kind = 'element' AND tag_name IS NOT NULL) OR node_kind <> 'element'),
    PRIMARY KEY (document_pk, document_order),
    UNIQUE (document_pk, parent_document_order, ordinal),
    FOREIGN KEY (document_pk, parent_document_order)
        REFERENCES provision_node(document_pk, document_order)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE provision_node IS 'XML要素を一般化した順序付きツリー。DB内部参照はdocument_pk+document_orderへ正規化し、32Mノード級でも反復hash/pathを複合indexへ重複保存しない。';
COMMENT ON COLUMN provision_node.node_id IS '論理node_idのSHA-256 32-byte値。外部表現はlowercase hex。DB内部の親子参照には使用しない。';
COMMENT ON COLUMN provision_node.parent_document_order IS '同一document内の親ノードdocument_order。NULLはroot。';
COMMENT ON COLUMN provision_node.ordinal IS '親の全子ノード中の1始まり順序。Article等の法的番号ではない。';
COMMENT ON COLUMN provision_node.path_index IS '元XML path segmentの同一expanded-name兄弟内1始まりindex。親情報と組み合わせればxml_pathを損失なく再構成できる。';
COMMENT ON COLUMN provision_node.document_order IS '文書全体のdepth-first document order。document_pkとの組で物理主キー兼引用順となる。';
COMMENT ON COLUMN provision_node.structural_num IS 'Num等の機械構造番号。表示番号とは分離する。';
COMMENT ON COLUMN provision_node.display_label IS 'ArticleTitle等から得る表示ラベル。structural_numの代替ではない。';
COMMENT ON COLUMN provision_node.attributes_jsonb IS '未知属性を含むXML属性原値。OldNum/OldStyleもここに必ず残し、専用列は検索用投影。';
COMMENT ON COLUMN provision_node.text_original IS '必要なtext-bearing nodeだけに保持する無正規化string-value cache。構造コンテナではNULL可。完全な文字順序の正本はmixed_content_jsonbと子ノード。';
COMMENT ON COLUMN provision_node.text_search_normalized IS 'Phase 5検索専用予約列。Phase 4では原則NULLとし、引用根拠に使用しない。';
COMMENT ON COLUMN provision_node.mixed_content_jsonb IS 'leading text / child document_order / tail textを順序付きsegment列として保持する。空白も原値保持する。';

CREATE INDEX ix_provision_node_tag ON provision_node(tag_name);
CREATE INDEX ix_provision_node_structural_num ON provision_node(document_pk, tag_name, structural_num);

CREATE OR REPLACE FUNCTION legal_kb.provision_node_xml_path(
    p_document_pk bigint,
    p_document_order integer
) RETURNS text
LANGUAGE sql
STABLE
AS $$
WITH RECURSIVE chain AS (
    SELECT n.document_pk, n.document_order, n.parent_document_order,
           n.node_kind, n.tag_name, n.namespace_uri, n.path_index, 0 AS level
    FROM legal_kb.provision_node n
    WHERE n.document_pk = p_document_pk
      AND n.document_order = p_document_order

    UNION ALL

    SELECT p.document_pk, p.document_order, p.parent_document_order,
           p.node_kind, p.tag_name, p.namespace_uri, p.path_index, c.level + 1
    FROM chain c
    JOIN legal_kb.provision_node p
      ON p.document_pk = c.document_pk
     AND p.document_order = c.parent_document_order
)
SELECT CASE
         WHEN count(*) = 0 THEN NULL
         ELSE '/' || string_agg(
           CASE
             WHEN node_kind = 'comment' THEN 'comment()[' || path_index || ']'
             WHEN node_kind = 'processing-instruction' THEN
               'processing-instruction()[' || path_index || ']'
             WHEN namespace_uri IS NULL THEN tag_name || '[' || path_index || ']'
             ELSE '{' || namespace_uri || '}' || tag_name || '[' || path_index || ']'
           END,
           '/' ORDER BY level DESC
         )
       END
FROM chain;
$$;

COMMENT ON FUNCTION legal_kb.provision_node_xml_path(bigint, integer) IS
  'document-local compact tree coordinatesからPhase 4 deterministic xml_pathを再構成する。RAW XMLの代替ではない。';

CREATE TABLE attachment (
    attachment_id text PRIMARY KEY,
    document_pk bigint NOT NULL,
    law_revision_id text NOT NULL,
    ref_document_order integer NOT NULL,
    source_file_id text REFERENCES source_file(source_file_id) ON DELETE RESTRICT,

    source_attribute_name text NOT NULL DEFAULT 'src',
    source_src text NOT NULL,
    resolved_locator text,
    media_type text,
    sha256 text,
    byte_size bigint CHECK (byte_size IS NULL OR byte_size >= 0),
    availability_status text NOT NULL CHECK (
        availability_status IN ('unresolved', 'resolved', 'missing', 'fetch-failed', 'external')
    ),
    resolution_detail_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,

    first_seen_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id),
    last_seen_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CHECK (attachment_id ~ '^[0-9a-f]{64}$'),
    CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$'),
    CHECK (jsonb_typeof(resolution_detail_jsonb) = 'object'),
    CHECK (availability_status <> 'resolved' OR source_file_id IS NOT NULL),
    UNIQUE (document_pk, ref_document_order, source_attribute_name, source_src),
    FOREIGN KEY (document_pk, law_revision_id)
        REFERENCES law_document(document_pk, law_revision_id) ON DELETE CASCADE,
    FOREIGN KEY (document_pk, ref_document_order)
        REFERENCES provision_node(document_pk, document_order) ON DELETE CASCADE
);

COMMENT ON TABLE attachment IS 'XMLから参照された図表・画像等。src原値と解決結果を分離し、取得失敗参照も削除しない。';
COMMENT ON COLUMN attachment.source_src IS 'XML属性に記録された相対/絶対参照の原値。解決後locatorで上書きしない。';

CREATE INDEX ix_attachment_revision ON attachment(law_revision_id);
CREATE INDEX ix_attachment_status ON attachment(availability_status);
CREATE INDEX ix_attachment_sha256 ON attachment(sha256) WHERE sha256 IS NOT NULL;

CREATE TABLE xml_parse_issue (
    xml_parse_issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_pk bigint NOT NULL REFERENCES law_document(document_pk) ON DELETE CASCADE,
    node_document_order integer,
    issue_code text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    message text NOT NULL,
    source_line integer CHECK (source_line IS NULL OR source_line >= 1),
    details_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    ingestion_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(details_jsonb) = 'object'),
    FOREIGN KEY (document_pk, node_document_order)
        REFERENCES provision_node(document_pk, document_order)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE xml_parse_issue IS 'XML構造化時の異常・曖昧性。未知要素やXSD invalidそのものを自動的にerror扱いしない。';

CREATE INDEX ix_xml_parse_issue_document ON xml_parse_issue(document_pk, severity);

COMMIT;
