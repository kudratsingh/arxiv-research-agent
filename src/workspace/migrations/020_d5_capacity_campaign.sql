-- Versioned append-only capacity decisions; predecessor receipts/expiry/holds remain intact.
CREATE TABLE IF NOT EXISTS workspace_d5_capacity_revisions (
 extension_id TEXT PRIMARY KEY,
 program_id TEXT NOT NULL REFERENCES workspace_evaluation_programs(program_id),
 revision INTEGER NOT NULL CHECK(revision=7),
 predecessor_extension_id TEXT NOT NULL REFERENCES workspace_d5_campaign_successors(extension_id),
 predecessor_authorization_digest TEXT NOT NULL REFERENCES workspace_d5_campaign_successors(authorization_digest),
 proposal_digest TEXT NOT NULL,
 authorization_digest TEXT NOT NULL UNIQUE,
 packet_digest TEXT NOT NULL,
 scope_id TEXT NOT NULL UNIQUE,
 record JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 programme_expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CHECK(expires_at<=programme_expires_at)
);
CREATE INDEX IF NOT EXISTS workspace_d5_capacity_revisions_program
 ON workspace_d5_capacity_revisions(program_id,created_at DESC);
CREATE TABLE IF NOT EXISTS workspace_d5_capacity_revision_revocations (
 extension_id TEXT PRIMARY KEY REFERENCES workspace_d5_capacity_revisions(extension_id),
 record JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
