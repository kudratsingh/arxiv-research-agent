-- Operator-recorded scopes; executing a runner cannot authorize itself.
CREATE TABLE IF NOT EXISTS workspace_d5_scopes (
 scope_id TEXT PRIMARY KEY,
 packet_digest TEXT NOT NULL,
 authorization_digest TEXT NOT NULL,
 data JSONB NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('active','revoked','stopped')),
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS workspace_d5_case_runs (
 scope_id TEXT NOT NULL REFERENCES workspace_d5_scopes(scope_id),
 case_id TEXT NOT NULL,
 packet_digest TEXT NOT NULL,
 owner TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES workspace_generation_jobs(id),
 input_digest TEXT NOT NULL,
 PRIMARY KEY(scope_id,case_id),
 UNIQUE(packet_digest,case_id),
 UNIQUE(job_id)
);
CREATE TABLE IF NOT EXISTS workspace_d5_fixture_marker (
 singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
 kind TEXT NOT NULL CHECK(kind='offline_only'),
 data JSONB NOT NULL
);
