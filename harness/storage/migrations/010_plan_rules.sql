-- migrate: foreign keys off
-- Reads allowed by rule (code-mode A2). The first line above makes `migrate` run this file
-- with the foreign keys off and refuse it unless no reference is broken afterwards: SQLite
-- cannot change a CHECK in place, and `tool_calls.plan_id` refers to this table.
--
-- `plan_runs` is rebuilt with the same columns and rows, and:
-- - `means` also takes 'rule': a plan whose steps are all `auto_read` is approved by the
--   local list, without the box; the audit says so;
-- - `entries_sha256`: the hash of the list's entries (server and tool) of every step when
--   the plan was read; the executor computes it again before the first step. NULL for the
--   plans recorded before this migration, which never run again;
-- - `error_code` also takes 'list_changed': the list changed between reading and running.
-- No column holds a plan, an argument, a question or a result.

CREATE TABLE plan_runs_010 (
    plan_id          TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions (session_id),
    request_id       TEXT NOT NULL REFERENCES requests (request_id),
    plan_sha256      TEXT NOT NULL CHECK (length(plan_sha256) = 64),
    approval_hash    TEXT NOT NULL CHECK (length(approval_hash) = 64),
    entries_sha256   TEXT CHECK (entries_sha256 IS NULL OR length(entries_sha256) = 64),
    steps            INTEGER NOT NULL CHECK (steps BETWEEN 1 AND 10),
    deadline_s       INTEGER NOT NULL CHECK (deadline_s BETWEEN 1 AND 300),
    shown_max_bytes  INTEGER NOT NULL CHECK (shown_max_bytes > 0),
    approval         TEXT NOT NULL CHECK (approval IN
                     ('pending', 'granted', 'rejected', 'expired', 'undecided', 'consumed')),
    means            TEXT CHECK (means IS NULL OR means IN ('code', 'button', 'rule')),
    identity         TEXT CHECK (identity IS NULL OR length(identity) <= 64),
    status           TEXT NOT NULL CHECK (status IN
                     ('awaiting_approval', 'not_run', 'running', 'completed', 'failed',
                      'interrupted', 'timeout')),
    stopped_at       INTEGER CHECK (stopped_at IS NULL OR stopped_at BETWEEN 1 AND 10),
    error_code       TEXT CHECK (error_code IS NULL OR error_code IN
                     ('rejected', 'expired', 'undecided', 'approval_not_usable',
                      'plan_altered', 'config_error', 'denied', 'tool_error', 'timeout',
                      'call_failed', 'interrupted', 'deadline', 'abandoned', 'list_changed')),
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    decided_at       TEXT,
    started_at       TEXT,
    finished_at      TEXT
);

INSERT INTO plan_runs_010 (plan_id, session_id, request_id, plan_sha256, approval_hash,
    entries_sha256, steps, deadline_s, shown_max_bytes, approval, means, identity, status,
    stopped_at, error_code, created_at, expires_at, decided_at, started_at, finished_at)
SELECT plan_id, session_id, request_id, plan_sha256, approval_hash, NULL, steps, deadline_s,
    shown_max_bytes, approval, means, identity, status, stopped_at, error_code, created_at,
    expires_at, decided_at, started_at, finished_at
FROM plan_runs;

DROP TABLE plan_runs;
ALTER TABLE plan_runs_010 RENAME TO plan_runs;

CREATE INDEX idx_plan_runs_session ON plan_runs (session_id, created_at);
CREATE INDEX idx_plan_runs_status ON plan_runs (status);
