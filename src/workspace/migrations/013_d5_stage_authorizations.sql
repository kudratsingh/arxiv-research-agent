-- Additional owner approvals append to a frozen scope; never rewrite its base.
CREATE TABLE IF NOT EXISTS workspace_d5_stage_authorizations (
 scope_id TEXT NOT NULL REFERENCES workspace_d5_scopes(scope_id),
 grant_id TEXT NOT NULL,
 authorization_digest TEXT NOT NULL UNIQUE,
 record JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(scope_id,grant_id)
);
