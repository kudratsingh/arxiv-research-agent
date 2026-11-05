-- Manual projects/threads reference shared records. No generation authority.
CREATE SEQUENCE workspace_context_activity;
CREATE TABLE workspace_context_preferences (
 owner TEXT PRIMARY KEY CHECK(owner<>''), revision INTEGER NOT NULL CHECK(revision>0), data JSONB NOT NULL
);
CREATE TABLE workspace_projects (
 owner TEXT NOT NULL CHECK(owner<>''), id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), activity_sequence BIGINT NOT NULL DEFAULT nextval('workspace_context_activity'),
 PRIMARY KEY(owner,id)
);
CREATE TABLE workspace_project_sources (
 owner TEXT NOT NULL, project_id TEXT NOT NULL, id TEXT NOT NULL,
 work_id TEXT NOT NULL REFERENCES workspace_works(work_id), version_id TEXT NOT NULL REFERENCES workspace_versions(version_id),
 data JSONB NOT NULL, PRIMARY KEY(owner,project_id,id),
 FOREIGN KEY(owner,project_id) REFERENCES workspace_projects(owner,id)
);
CREATE TABLE workspace_project_entries (
 owner TEXT NOT NULL, project_id TEXT NOT NULL, entry_id TEXT NOT NULL, entry_revision INTEGER NOT NULL,
 PRIMARY KEY(owner,project_id,entry_id,entry_revision),
 FOREIGN KEY(owner,project_id) REFERENCES workspace_projects(owner,id),
 FOREIGN KEY(owner,entry_id) REFERENCES workspace_entries(owner,id)
);
CREATE TABLE workspace_project_artifacts (
 owner TEXT NOT NULL, project_id TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), data JSONB NOT NULL,
 PRIMARY KEY(owner,project_id,id), FOREIGN KEY(owner,project_id) REFERENCES workspace_projects(owner,id)
);
CREATE TABLE workspace_learning_threads (
 owner TEXT NOT NULL CHECK(owner<>''), id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 project_id TEXT, data JSONB NOT NULL, bound_source JSONB,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 activity_sequence BIGINT NOT NULL DEFAULT nextval('workspace_context_activity'), PRIMARY KEY(owner,id),
 FOREIGN KEY(owner,project_id) REFERENCES workspace_projects(owner,id)
);
CREATE TABLE workspace_resume_context (
 owner TEXT NOT NULL, entity TEXT NOT NULL CHECK(entity IN ('entry','reading')), id TEXT NOT NULL,
 revision INTEGER NOT NULL, data JSONB NOT NULL, PRIMARY KEY(owner,entity,id,revision)
);
CREATE TABLE workspace_mode_editions (
 owner TEXT NOT NULL, context_key TEXT NOT NULL, data JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(owner,context_key)
);
