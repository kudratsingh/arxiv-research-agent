-- New externally approved campaign only; no mutation of any prior receipt/hold.
CREATE TABLE IF NOT EXISTS workspace_d5_campaign_extensions (
 program_id TEXT PRIMARY KEY REFERENCES workspace_evaluation_programs(program_id),
 revision INTEGER NOT NULL CHECK(revision=5),
 extension_id TEXT NOT NULL UNIQUE,
 predecessor_authorization_digest TEXT NOT NULL REFERENCES workspace_programme_capacity_amendments(authorization_digest),
 proposal_digest TEXT NOT NULL,
 authorization_digest TEXT NOT NULL UNIQUE,
 packet_digest TEXT NOT NULL,
 scope_id TEXT NOT NULL UNIQUE,
 record JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS workspace_d5_campaign_revocations (
 extension_id TEXT PRIMARY KEY REFERENCES workspace_d5_campaign_extensions(extension_id),
 record JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS workspace_d5_campaign_outcomes (
 scope_id TEXT NOT NULL REFERENCES workspace_d5_scopes(scope_id),
 case_id TEXT NOT NULL,
 job_id TEXT NOT NULL UNIQUE REFERENCES workspace_generation_jobs(id),
 job_digest TEXT NOT NULL,
 record JSONB NOT NULL,
 record_digest TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(scope_id,case_id)
);
