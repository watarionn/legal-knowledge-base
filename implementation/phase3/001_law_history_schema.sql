-- 法令ナレッジベース Phase 3: 法令・履歴DB
-- Target: PostgreSQL
-- Status: proposed implementation contract
-- Source of truth: KNW-20260903-001, DEC-20260904-001

BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE TABLE ingestion_run (
    ingestion_run_id text PRIMARY KEY,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    input_manifest_sha256 text,
    parser_version text,
    xsd_sha256 text,
    openapi_sha256 text,
    result_status text NOT NULL CHECK (
        result_status IN ('running', 'succeeded', 'failed', 'partial')
    ),
    warnings_count integer NOT NULL DEFAULT 0 CHECK (warnings_count >= 0),
    errors_count integer NOT NULL DEFAULT 0 CHECK (errors_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE source_file (
    source_file_id text PRIMARY KEY,
    source_family text NOT NULL,
    source_url text,
    provider_file_id text,
    stored_path text,
    retrieved_at timestamptz NOT NULL,
    media_type text,
    byte_size bigint CHECK (byte_size IS NULL OR byte_size >= 0),
    sha256 text,
    original_file_name text,
    immutable boolean NOT NULL DEFAULT true,
    ingestion_run_id text REFERENCES ingestion_run(ingestion_run_id),
    CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-fA-F]{64}$')
);

CREATE TABLE law (
    law_id text PRIMARY KEY,
    law_num text,
    law_type text NOT NULL,
    law_num_era text,
    law_num_year integer CHECK (law_num_year IS NULL OR law_num_year > 0),
    law_num_type text,
    law_num_num text,
    promulgation_date date,
    first_seen_run_id text REFERENCES ingestion_run(ingestion_run_id),
    last_seen_run_id text REFERENCES ingestion_run(ingestion_run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (law_id ~ '^[0-9A-Z]{15}$')
);

COMMENT ON TABLE law IS '法令系列。法令名は改正で変化し得るため保持しない。';
COMMENT ON COLUMN law.law_id IS 'e-Gov法令ID。15文字の機械可読ID。';
COMMENT ON COLUMN law.law_num_num IS 'API原値を損失なく保持するため文字列で保存する。';

CREATE TABLE law_revision (
    law_revision_id text PRIMARY KEY,
    law_id text NOT NULL REFERENCES law(law_id) ON UPDATE RESTRICT ON DELETE RESTRICT,

    -- revision_info source fields
    law_type text NOT NULL,
    law_title text,
    law_title_kana text,
    abbrev text,
    category text,
    updated timestamptz,
    amendment_promulgate_date date,
    amendment_enforcement_date date,
    amendment_enforcement_comment text,
    amendment_scheduled_enforcement_date date,
    amendment_law_id text,
    amendment_law_title text,
    amendment_law_title_kana text,
    amendment_law_num text,
    amendment_type text,
    repeal_status text,
    repeal_date date,
    remain_in_force boolean,
    mission text,
    current_revision_status text,

    -- law_revision_id parsed fields
    revision_id_effective_date date NOT NULL,
    revision_id_amending_law_id text NOT NULL,
    revision_date_kind text NOT NULL DEFAULT 'unknown' CHECK (
        revision_date_kind IN (
            'amendment-enforcement',
            'original-enforcement',
            'data-baseline',
            'unknown'
        )
    ),

    -- derived temporal fields. API source values are never overwritten by these columns.
    revision_sequence integer CHECK (revision_sequence IS NULL OR revision_sequence >= 1),
    valid_from date,
    valid_to_exclusive date,
    temporal_resolution_quality text CHECK (
        temporal_resolution_quality IS NULL OR temporal_resolution_quality IN (
            'confirmed-api',
            'confirmed-revision-id',
            'baseline-boundary',
            'ambiguous',
            'unknown'
        )
    ),

    -- observed API list position. Stored for provenance, not treated as legal ordering by itself.
    api_revision_ordinal integer CHECK (api_revision_ordinal IS NULL OR api_revision_ordinal >= 1),
    first_seen_run_id text REFERENCES ingestion_run(ingestion_run_id),
    last_seen_run_id text REFERENCES ingestion_run(ingestion_run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CHECK (law_revision_id ~ '^[0-9A-Z]{15}_[0-9]{8}_[0-9A-Z]{15}$'),
    CHECK (revision_id_amending_law_id ~ '^[0-9A-Z]{15}$'),
    CHECK (amendment_law_id IS NULL OR amendment_law_id ~ '^[0-9A-Z]{15}$'),
    CHECK (split_part(law_revision_id, '_', 1) = law_id),
    CHECK (split_part(law_revision_id, '_', 3) = revision_id_amending_law_id),
    CHECK (valid_to_exclusive IS NULL OR valid_from IS NULL OR valid_to_exclusive >= valid_from)
);

COMMENT ON TABLE law_revision IS '特定の法令履歴。API原値と派生時点情報を同一列で上書きしない。';
COMMENT ON COLUMN law_revision.amendment_law_id IS '論理的にはlaw_idへの参照だが、外部・未取得法令を許容するため物理FKは張らない。';
COMMENT ON COLUMN law_revision.revision_id_effective_date IS 'law_revision_id中央YYYYMMDDを解析した値。意味はrevision_date_kindで明示する。';
COMMENT ON COLUMN law_revision.api_revision_ordinal IS 'API応答配列内の観測位置。時系列の正本としては使用しない。';

CREATE UNIQUE INDEX ux_law_revision_sequence
    ON law_revision(law_id, revision_sequence)
    WHERE revision_sequence IS NOT NULL;

CREATE INDEX ix_law_revision_law_id
    ON law_revision(law_id);

CREATE INDEX ix_law_revision_temporal
    ON law_revision(law_id, valid_from, valid_to_exclusive);

CREATE INDEX ix_law_revision_current_status
    ON law_revision(current_revision_status);

CREATE INDEX ix_law_revision_amendment_law_id
    ON law_revision(amendment_law_id)
    WHERE amendment_law_id IS NOT NULL;

CREATE INDEX ix_law_revision_updated
    ON law_revision(updated);

CREATE TABLE source_assertion (
    assertion_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type text NOT NULL CHECK (entity_type IN ('law', 'law_revision')),
    entity_id text NOT NULL,
    field_name text NOT NULL,
    source_kind text NOT NULL CHECK (
        source_kind IN (
            'api-v2',
            'bulk-csv',
            'bulk-xml-filename',
            'bulk-xml-root',
            'derived'
        )
    ),
    source_file_id text REFERENCES source_file(source_file_id),
    ingestion_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id),
    source_locator text,
    observed_at timestamptz NOT NULL,
    value_jsonb jsonb,
    selected_as_canonical boolean NOT NULL DEFAULT false,
    selection_reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE source_assertion IS 'CSV・XML・API・派生値の観測事実を別々に保持し、競合値を失わない。';

CREATE INDEX ix_source_assertion_entity
    ON source_assertion(entity_type, entity_id, field_name);

CREATE INDEX ix_source_assertion_run
    ON source_assertion(ingestion_run_id);

CREATE TABLE reconciliation_issue (
    reconciliation_issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type text NOT NULL CHECK (entity_type IN ('law', 'law_revision')),
    entity_id text NOT NULL,
    field_name text,
    issue_code text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    observed_values_jsonb jsonb NOT NULL,
    first_seen_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id),
    last_seen_run_id text NOT NULL REFERENCES ingestion_run(ingestion_run_id),
    resolved_at timestamptz,
    resolution_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE reconciliation_issue IS 'CSV・XML・API間の不一致を上書きせず、検出・解消履歴として保持する。';

CREATE INDEX ix_reconciliation_issue_open
    ON reconciliation_issue(entity_type, entity_id, severity)
    WHERE resolved_at IS NULL;

COMMIT;
