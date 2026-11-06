-- Offline D5 journal. No paid policies/approvals or historical ledgers changed.
CREATE UNIQUE INDEX IF NOT EXISTS workspace_fake_generation_owned ON workspace_fake_generation_jobs(id,owner);
CREATE TABLE IF NOT EXISTS workspace_assistance_wire (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES workspace_fake_generation_jobs(id),
    owner TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('draft','check','repair')),
    request_digest TEXT NOT NULL,
    request JSONB NOT NULL,
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY(job_id,owner) REFERENCES workspace_fake_generation_jobs(id,owner)
);
CREATE INDEX IF NOT EXISTS workspace_assistance_wire_owned ON workspace_assistance_wire(owner,job_id,id);
