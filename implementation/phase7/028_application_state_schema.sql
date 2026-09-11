-- Phase 7-5: single-user daily application state
-- This schema stores UI state only. It never replaces Phase 3-6 source truth.
BEGIN;

CREATE SCHEMA IF NOT EXISTS legal_kb;
SET search_path TO legal_kb, public;

CREATE TABLE application_favorite_law (
    workspace_id text NOT NULL DEFAULT 'local',
    law_id text NOT NULL REFERENCES law(law_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, law_id),
    CHECK (workspace_id ~ '^[a-z0-9][a-z0-9._-]{1,63}$')
);

CREATE TABLE application_recent_law (
    workspace_id text NOT NULL DEFAULT 'local',
    law_id text NOT NULL REFERENCES law(law_id) ON DELETE RESTRICT,
    first_viewed_at timestamptz NOT NULL DEFAULT now(),
    last_viewed_at timestamptz NOT NULL DEFAULT now(),
    view_count integer NOT NULL DEFAULT 1 CHECK (view_count > 0),
    last_query_id text,
    PRIMARY KEY (workspace_id, law_id),
    CHECK (workspace_id ~ '^[a-z0-9][a-z0-9._-]{1,63}$'),
    CHECK (last_query_id IS NULL OR last_query_id ~ '^[0-9a-f]{32}$')
);
CREATE TABLE application_search_history (
    query_id text PRIMARY KEY,
    workspace_id text NOT NULL DEFAULT 'local',
    question text NOT NULL,
    requested_as_of_date date,
    effective_as_of_date date NOT NULL,
    law_id text REFERENCES law(law_id) ON DELETE RESTRICT,
    law_title_snapshot text,
    response_status text NOT NULL,
    temporal_status text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (query_id ~ '^[0-9a-f]{32}$'),
    CHECK (workspace_id ~ '^[a-z0-9][a-z0-9._-]{1,63}$'),
    CHECK (char_length(question) BETWEEN 1 AND 4000),
    CHECK (char_length(response_status) BETWEEN 1 AND 64),
    CHECK (temporal_status IS NULL OR char_length(temporal_status) BETWEEN 1 AND 64)
);

CREATE INDEX ix_application_search_history_workspace
    ON application_search_history(workspace_id, created_at DESC);

CREATE TABLE application_saved_theme (
    theme_id text PRIMARY KEY,
    workspace_id text NOT NULL DEFAULT 'local',
    title text NOT NULL,
    question text NOT NULL,
    law_id text REFERENCES law(law_id) ON DELETE RESTRICT,
    as_of_date date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (theme_id ~ '^[0-9a-f]{32}$'),
    CHECK (workspace_id ~ '^[a-z0-9][a-z0-9._-]{1,63}$'),
    CHECK (char_length(title) BETWEEN 1 AND 120),
    CHECK (char_length(question) BETWEEN 1 AND 4000)
);

CREATE INDEX ix_application_saved_theme_workspace
    ON application_saved_theme(workspace_id, updated_at DESC);

COMMENT ON TABLE application_favorite_law IS
  'Phase 7 user preference only; never source truth.';
COMMENT ON TABLE application_recent_law IS
  'Phase 7 navigation history only; never source truth.';
COMMENT ON TABLE application_search_history IS
  'Replayable query inputs and result summary. Evidence/source text is intentionally not duplicated.';
COMMENT ON TABLE application_saved_theme IS
  'Saved query theme for daily use and future Phase 7-6 watch evaluation.';

COMMIT;
