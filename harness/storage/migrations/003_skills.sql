-- Skill runs, their steps and human approvals (skill-engine D8). No column holds the content
-- of an input, and `output_text` is filled only when the session's provider is synthetic.

CREATE TABLE skill_runs (
    run_id           TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions (session_id),
    skill_name       TEXT NOT NULL,
    skill_version    TEXT NOT NULL,
    skill_sha256     TEXT NOT NULL CHECK (length(skill_sha256) = 64),
    status           TEXT NOT NULL CHECK (status IN
                     ('pending', 'running', 'awaiting_approval', 'completed', 'failed',
                      'uncertain', 'cancelled')),
    current_step     TEXT,
    -- Canonical JSON {name: {"sha256": ..., "bytes": ...}}: never the content.
    inputs_manifest  TEXT NOT NULL,
    error_code       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    finished_at      TEXT
);

CREATE TABLE skill_steps (
    step_id        TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES skill_runs (run_id),
    step_key       TEXT NOT NULL,
    position       INTEGER NOT NULL CHECK (position >= 0),
    kind           TEXT NOT NULL CHECK (kind IN ('llm', 'validate', 'approval')),
    attempt        INTEGER NOT NULL CHECK (attempt >= 1),
    status         TEXT NOT NULL CHECK (status IN
                   ('pending', 'running', 'awaiting_approval', 'applying', 'completed',
                    'failed', 'uncertain')),
    request_id     TEXT REFERENCES requests (request_id),
    output_sha256  TEXT CHECK (output_sha256 IS NULL OR length(output_sha256) = 64),
    output_bytes   INTEGER CHECK (output_bytes IS NULL OR output_bytes >= 0),
    output_text    TEXT,
    prepared_at    TEXT,
    effect_ref     TEXT,
    error_code     TEXT,
    started_at     TEXT,
    finished_at    TEXT,
    UNIQUE (run_id, step_key, attempt)
);

CREATE TABLE approvals (
    approval_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES skill_runs (run_id),
    step_key       TEXT NOT NULL,
    scope          TEXT NOT NULL,
    proposal_hash  TEXT NOT NULL CHECK (length(proposal_hash) = 64),
    status         TEXT NOT NULL CHECK (status IN
                   ('pending', 'granted', 'rejected', 'expired', 'consumed', 'revoked')),
    identity       TEXT,
    channel        TEXT CHECK (channel IS NULL OR channel IN ('tty')),
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    decided_at     TEXT,
    consumed_at    TEXT
);

-- SQLite, not Python, guarantees one open run per session and one live approval per step.
CREATE UNIQUE INDEX idx_skill_runs_one_open_per_session ON skill_runs (session_id)
    WHERE status IN ('pending', 'running', 'awaiting_approval', 'uncertain');
CREATE UNIQUE INDEX idx_approvals_one_live_per_step ON approvals (run_id, step_key)
    WHERE status IN ('pending', 'granted');
CREATE INDEX idx_skill_runs_status ON skill_runs (status);
CREATE INDEX idx_skill_steps_run ON skill_steps (run_id, position, attempt);

-- Audit rows of a run: which run and a structured detail (step, attempt, hash, limit), never
-- content.
ALTER TABLE audit_events ADD COLUMN run_id TEXT;
ALTER TABLE audit_events ADD COLUMN detail TEXT;
