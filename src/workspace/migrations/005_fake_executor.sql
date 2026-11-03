-- Fake-only local execution; no approval records or billable reservations.
CREATE TABLE IF NOT EXISTS workspace_fake_generation_jobs (
    id TEXT PRIMARY KEY CHECK (id LIKE 'fake-%'),
    owner TEXT NOT NULL CHECK (owner <> ''),
    request_id TEXT NOT NULL,
    lane TEXT NOT NULL DEFAULT 'fake' CHECK (lane = 'fake'),
    kind TEXT NOT NULL CHECK (kind IN ('summary', 'deep_dive')),
    model_id TEXT NOT NULL CHECK (model_id = 'fixture-workspace-v1'),
    fixture_revision TEXT NOT NULL CHECK (fixture_revision = 'workspace-executor-v1'),
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'drafting', 'checking', 'repairing', 'ready', 'ready_partial',
        'cancelled', 'failed', 'interrupted', 'budget_stopped', 'stale'
    )),
    request_digest TEXT NOT NULL,
    request JSONB NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    lease_owner TEXT,
    lease_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner, request_id)
);
CREATE INDEX IF NOT EXISTS workspace_fake_generation_cache
    ON workspace_fake_generation_jobs (owner, request_digest, state);

CREATE TABLE IF NOT EXISTS workspace_fake_generation_reservations (
    job_id TEXT PRIMARY KEY REFERENCES workspace_fake_generation_jobs(id) ON DELETE CASCADE,
    owner TEXT NOT NULL CHECK (owner <> ''),
    max_calls INTEGER NOT NULL CHECK (max_calls BETWEEN 1 AND 4),
    used_calls INTEGER NOT NULL DEFAULT 0 CHECK (used_calls >= 0 AND used_calls <= max_calls),
    max_input_tokens INTEGER NOT NULL CHECK (max_input_tokens > 0),
    max_output_tokens INTEGER NOT NULL CHECK (max_output_tokens > 0),
    workflow_input INTEGER NOT NULL DEFAULT 0 CHECK (workflow_input >= 0),
    workflow_output INTEGER NOT NULL DEFAULT 0 CHECK (workflow_output >= 0),
    checker_input INTEGER NOT NULL DEFAULT 0 CHECK (checker_input >= 0),
    checker_output INTEGER NOT NULL DEFAULT 0 CHECK (checker_output >= 0),
    unknown_input INTEGER NOT NULL DEFAULT 0 CHECK (unknown_input >= 0),
    unknown_output INTEGER NOT NULL DEFAULT 0 CHECK (unknown_output >= 0),
    actual_usd NUMERIC NOT NULL DEFAULT 0 CHECK (actual_usd = 0),
    state TEXT NOT NULL CHECK (state IN ('held', 'settled', 'cancelled', 'uncertain'))
);
