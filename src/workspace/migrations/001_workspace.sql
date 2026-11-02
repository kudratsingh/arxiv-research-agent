CREATE TABLE IF NOT EXISTS workspace_profiles (
 owner TEXT PRIMARY KEY CHECK(owner <> ''), revision INTEGER NOT NULL, data JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_history (
 owner TEXT NOT NULL, entity TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
 data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(owner,entity,id,revision)
);
CREATE TABLE IF NOT EXISTS workspace_works (
 work_id TEXT PRIMARY KEY, first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), visibility_owner TEXT
);
CREATE TABLE IF NOT EXISTS workspace_versions (
 version_id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES workspace_works(work_id),
 source_id TEXT NOT NULL, data JSONB NOT NULL, observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workspace_versions_work ON workspace_versions(work_id,observed_at DESC);
CREATE TABLE IF NOT EXISTS workspace_observations (
 source_id TEXT NOT NULL, source_record_id TEXT NOT NULL, content_hash TEXT NOT NULL,
 version_id TEXT NOT NULL REFERENCES workspace_versions(version_id), fetched_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(source_id,source_record_id,content_hash)
);
CREATE TABLE IF NOT EXISTS workspace_reading (
 owner TEXT NOT NULL CHECK(owner <> ''), work_id TEXT NOT NULL REFERENCES workspace_works(work_id),
 revision INTEGER NOT NULL, data JSONB NOT NULL, PRIMARY KEY(owner,work_id)
);
CREATE TABLE IF NOT EXISTS workspace_entries (
 owner TEXT NOT NULL CHECK(owner <> ''), id TEXT NOT NULL, revision INTEGER NOT NULL,
 work_id TEXT NOT NULL REFERENCES workspace_works(work_id),
 version_id TEXT NOT NULL REFERENCES workspace_versions(version_id), data JSONB NOT NULL,
 PRIMARY KEY(owner,id)
);
CREATE TABLE IF NOT EXISTS workspace_sources (
 source_id TEXT PRIMARY KEY, status TEXT NOT NULL, last_success_at TIMESTAMPTZ,
 validators JSONB NOT NULL DEFAULT '{}', receipt JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_ingest_runs (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, receipt JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS workspace_mutations (
 owner TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL,
 response JSONB NOT NULL, PRIMARY KEY(owner,request_id)
);
CREATE TABLE IF NOT EXISTS workspace_editions (
 owner TEXT NOT NULL, id TEXT NOT NULL, data JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(owner,id)
);
CREATE TABLE IF NOT EXISTS workspace_schedules (
 owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, data JSONB NOT NULL, next_check TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS workspace_tasks (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, occurrence_key TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('queued','running','ready','failed','cancelled')),
 due_at TIMESTAMPTZ NOT NULL, lease_owner TEXT, lease_until TIMESTAMPTZ,
 attempts INTEGER NOT NULL DEFAULT 0, reason TEXT,
 UNIQUE(owner,occurrence_key)
);
CREATE TABLE IF NOT EXISTS workspace_delivery_intents (
 owner TEXT NOT NULL, task_id TEXT PRIMARY KEY REFERENCES workspace_tasks(id),
 edition_id TEXT NOT NULL, channel TEXT NOT NULL CHECK(channel='in-app'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
