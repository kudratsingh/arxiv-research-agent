-- One cumulative program may span models/stages/principals, without resetting
-- the linked historical trial. Registering a ledger does not grant approval.
CREATE TABLE IF NOT EXISTS workspace_evaluation_programs (
 program_id TEXT PRIMARY KEY,
 parent_trial_id TEXT NOT NULL REFERENCES workspace_qualification_trials(trial_id),
 limits JSONB NOT NULL, baseline JSONB NOT NULL,
 authorization_digest TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS workspace_evaluation_members (
 owner TEXT PRIMARY KEY,
 program_id TEXT NOT NULL REFERENCES workspace_evaluation_programs(program_id)
);
