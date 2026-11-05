-- Immutable trial identity/limits; this is accounting, never permission.
CREATE TABLE IF NOT EXISTS workspace_qualification_trials (
 trial_id TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE,
 limits JSONB NOT NULL, baseline_digest TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
