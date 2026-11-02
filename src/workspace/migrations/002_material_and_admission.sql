CREATE TABLE IF NOT EXISTS workspace_material (
 material_id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES workspace_versions(version_id),
 content_hash TEXT NOT NULL, source_scope TEXT NOT NULL, data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_budget_policies (
 owner TEXT PRIMARY KEY CHECK(owner <> ''), approval_id TEXT NOT NULL, data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_generation_jobs (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, approval_id TEXT NOT NULL,
 state TEXT NOT NULL, input_digest TEXT NOT NULL, data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_spend_reservations (
 job_id TEXT PRIMARY KEY REFERENCES workspace_generation_jobs(id), owner TEXT NOT NULL,
 amount NUMERIC NOT NULL CHECK(amount >= 0), day DATE NOT NULL, month DATE NOT NULL,
 workflow NUMERIC NOT NULL DEFAULT 0 CHECK(workflow >= 0),
 judge NUMERIC NOT NULL DEFAULT 0 CHECK(judge >= 0),
 unknown NUMERIC NOT NULL DEFAULT 0 CHECK(unknown >= 0), state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS workspace_reservations_owner_period ON workspace_spend_reservations(owner,day,month);
