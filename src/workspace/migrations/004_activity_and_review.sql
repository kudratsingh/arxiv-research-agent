CREATE TABLE IF NOT EXISTS workspace_activity (
 sequence BIGSERIAL PRIMARY KEY, owner TEXT NOT NULL CHECK(owner <> ''),
 kind TEXT NOT NULL CHECK(kind IN ('entry','reading')), entity_id TEXT NOT NULL,
 work_id TEXT NOT NULL REFERENCES workspace_works(work_id),
 version_id TEXT NOT NULL REFERENCES workspace_versions(version_id),
 revision INTEGER NOT NULL, data JSONB NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(owner,kind,entity_id,revision)
);
CREATE INDEX IF NOT EXISTS workspace_activity_owner_sequence ON workspace_activity(owner,sequence DESC);
-- Existing history has timestamps but no monotonic event number. Preserve its
-- recorded order, with stable tie breaks; never resurrect removed QA entries.
INSERT INTO workspace_activity(owner,kind,entity_id,work_id,version_id,revision,data,updated_at)
SELECT h.owner,h.entity,h.id,
 CASE WHEN h.entity='reading' THEN h.id ELSE h.data->>'work_id' END,
 h.data->>'version_id',h.revision,h.data,h.created_at
FROM workspace_history h
WHERE (h.entity='entry' AND EXISTS (
 SELECT 1 FROM workspace_entries e WHERE e.owner=h.owner AND e.id=h.id
)) OR (h.entity='reading' AND EXISTS (
 SELECT 1 FROM workspace_reading r WHERE r.owner=h.owner AND r.work_id=h.id AND r.revision=h.revision
))
ORDER BY h.created_at,h.owner,h.entity,h.id,h.revision
ON CONFLICT(owner,kind,entity_id,revision) DO NOTHING;

CREATE TABLE IF NOT EXISTS workspace_review_packets (
 owner TEXT NOT NULL CHECK(owner <> ''), id TEXT NOT NULL, data JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(owner,id)
);
CREATE TABLE IF NOT EXISTS workspace_usefulness_feedback (
 owner TEXT NOT NULL, packet_id TEXT NOT NULL, work_id TEXT NOT NULL,
 version_id TEXT NOT NULL REFERENCES workspace_versions(version_id),
 revision INTEGER NOT NULL CHECK(revision > 0), data JSONB NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(owner,packet_id,work_id),
 FOREIGN KEY(owner,packet_id) REFERENCES workspace_review_packets(owner,id)
);
