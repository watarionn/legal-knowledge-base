-- Phase 7-6a: deterministic law watch application state
-- This schema records watch state only. It never replaces Phase 3-5 source truth.
BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE TABLE application_law_watch (
    watch_id text PRIMARY KEY,
    workspace_id text NOT NULL DEFAULT 'local',
    theme_id text REFERENCES application_saved_theme(theme_id) ON DELETE SET NULL,
    law_id text NOT NULL REFERENCES law(law_id) ON DELETE RESTRICT,
    baseline_revision_id text REFERENCES law_revision(law_revision_id) ON DELETE RESTRICT,
    baseline_ingestion_run_id text REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    enabled boolean NOT NULL DEFAULT true,
    last_evaluated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (watch_id ~ '^[0-9a-f]{32}$'),
    CHECK (workspace_id ~ '^[a-z0-9][a-z0-9._-]{1,63}$')
);

CREATE INDEX ix_application_law_watch_workspace
    ON application_law_watch(workspace_id, updated_at DESC);
CREATE TABLE application_law_watch_event (
    event_id text PRIMARY KEY,
    watch_id text NOT NULL REFERENCES application_law_watch(watch_id) ON DELETE CASCADE,
    event_type text NOT NULL CHECK (
        event_type IN ('effective-change', 'observed-change', 'scheduled-change')
    ),
    from_revision_id text REFERENCES law_revision(law_revision_id) ON DELETE RESTRICT,
    to_revision_id text REFERENCES law_revision(law_revision_id) ON DELETE RESTRICT,
    detected_at timestamptz NOT NULL DEFAULT now(),
    effective_date date,
    source_ingestion_run_id text REFERENCES ingestion_run(ingestion_run_id) ON DELETE RESTRICT,
    temporal_status text NOT NULL,
    acknowledged_at timestamptz,
    CHECK (event_id ~ '^[0-9a-f]{32}$'),
    CHECK (char_length(temporal_status) BETWEEN 1 AND 64)
);

CREATE UNIQUE INDEX ux_application_law_watch_event_identity
    ON application_law_watch_event (
        watch_id,
        event_type,
        COALESCE(from_revision_id, ''),
        COALESCE(to_revision_id, ''),
        COALESCE(source_ingestion_run_id, '')
    );
CREATE INDEX ix_application_law_watch_event_watch
    ON application_law_watch_event(watch_id, detected_at DESC);

COMMENT ON TABLE application_law_watch IS
  'Phase 7-6 application watch state only; never legal source truth.';
COMMENT ON TABLE application_law_watch_event IS
  'Deterministic change-detection record; source law data remains in Phase 3-5.';

COMMIT;
