-- Original programme policy/authorization/history are never overwritten.
CREATE TABLE IF NOT EXISTS workspace_programme_amendments (
 program_id TEXT NOT NULL REFERENCES workspace_evaluation_programs(program_id),
 revision INTEGER NOT NULL CHECK (revision = 1),
 amendment_id TEXT NOT NULL UNIQUE,
 proposal_digest TEXT NOT NULL,
 authorization_digest TEXT NOT NULL UNIQUE,
 record JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(program_id,revision)
);
CREATE TABLE IF NOT EXISTS workspace_programme_amendment_revocations (
 amendment_id TEXT PRIMARY KEY REFERENCES workspace_programme_amendments(amendment_id),
 record JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
