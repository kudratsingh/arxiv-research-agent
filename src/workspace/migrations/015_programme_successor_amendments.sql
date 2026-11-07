-- Preserve the original20->21 receipt verbatim. A separately approved successor
-- can add only job22, never money/contacts or time beyond the predecessor expiry.
CREATE TABLE IF NOT EXISTS workspace_programme_successor_amendments (
 program_id TEXT PRIMARY KEY REFERENCES workspace_evaluation_programs(program_id),
 revision INTEGER NOT NULL CHECK(revision=2),
 amendment_id TEXT NOT NULL UNIQUE,
 predecessor_authorization_digest TEXT NOT NULL REFERENCES workspace_programme_amendments(authorization_digest),
 proposal_digest TEXT NOT NULL,
 authorization_digest TEXT NOT NULL UNIQUE,
 record JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS workspace_programme_successor_revocations (
 amendment_id TEXT PRIMARY KEY REFERENCES workspace_programme_successor_amendments(amendment_id),
 record JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
