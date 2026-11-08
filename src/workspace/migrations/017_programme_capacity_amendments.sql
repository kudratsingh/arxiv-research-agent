-- Capacity only. Preserve the original programme and all three predecessor receipts.
CREATE TABLE IF NOT EXISTS workspace_programme_capacity_amendments (
 program_id TEXT PRIMARY KEY REFERENCES workspace_evaluation_programs(program_id),
 revision INTEGER NOT NULL CHECK(revision=4),
 amendment_id TEXT NOT NULL UNIQUE,
 predecessor_authorization_digest TEXT NOT NULL REFERENCES workspace_programme_third_amendments(authorization_digest),
 proposal_digest TEXT NOT NULL,
 authorization_digest TEXT NOT NULL UNIQUE,
 record JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS workspace_programme_capacity_revocations (
 amendment_id TEXT PRIMARY KEY REFERENCES workspace_programme_capacity_amendments(amendment_id),
 record JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
