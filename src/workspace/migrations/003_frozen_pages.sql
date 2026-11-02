CREATE TABLE IF NOT EXISTS workspace_pages (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, query_hash TEXT NOT NULL,
 cutoff TEXT NOT NULL, items JSONB NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL DEFAULT (clock_timestamp() + INTERVAL '24 hours')
);
CREATE INDEX IF NOT EXISTS workspace_pages_expiry ON workspace_pages(expires_at);
