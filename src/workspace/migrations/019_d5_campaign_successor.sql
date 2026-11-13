-- An append-only successor. Prior scopes, responses and both holds are immutable.
CREATE TABLE IF NOT EXISTS workspace_d5_campaign_successors (
 program_id TEXT PRIMARY KEY REFERENCES workspace_evaluation_programs(program_id),
 revision INTEGER NOT NULL CHECK(revision=6),
 extension_id TEXT NOT NULL UNIQUE,
 predecessor_authorization_digest TEXT NOT NULL REFERENCES workspace_d5_campaign_extensions(authorization_digest),
 proposal_digest TEXT NOT NULL,
 authorization_digest TEXT NOT NULL UNIQUE,
 packet_digest TEXT NOT NULL,
 scope_id TEXT NOT NULL UNIQUE,
 record JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS workspace_d5_campaign_successor_revocations (
 extension_id TEXT PRIMARY KEY REFERENCES workspace_d5_campaign_successors(extension_id),
 record JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
