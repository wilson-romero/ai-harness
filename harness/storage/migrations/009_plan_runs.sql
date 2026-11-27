-- The plans of code mode (code-mode slice 2, D10). Number 009: 008 is taken by the branch
-- `feature/response-mode`, which touches other tables; the two apply in either order.
--
-- One row per plan read from a `/plan` reply: its hash, the hash of the approval asked for
-- it, the decision and how it was taken, its limits and how it ended. No column can hold the
-- plan, an argument, the question or any text of a result: those are only in the canonical
-- bytes the process keeps in memory, and the arguments of each step reach `tool_calls` only
-- as their keyed hash, as for `mcp call`. Nothing existing changes: `tool_calls` gains two
-- columns that stay NULL for every row of `mcp call`, old or new.

CREATE TABLE plan_runs (
    plan_id          TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions (session_id),
    request_id       TEXT NOT NULL REFERENCES requests (request_id),
    plan_sha256      TEXT NOT NULL CHECK (length(plan_sha256) = 64),
    approval_hash    TEXT NOT NULL CHECK (length(approval_hash) = 64),
    steps            INTEGER NOT NULL CHECK (steps BETWEEN 1 AND 10),
    deadline_s       INTEGER NOT NULL CHECK (deadline_s BETWEEN 1 AND 300),
    shown_max_bytes  INTEGER NOT NULL CHECK (shown_max_bytes > 0),
    approval         TEXT NOT NULL CHECK (approval IN
                     ('pending', 'granted', 'rejected', 'expired', 'undecided', 'consumed')),
    means            TEXT CHECK (means IS NULL OR means IN ('code', 'button')),
    identity         TEXT CHECK (identity IS NULL OR length(identity) <= 64),
    status           TEXT NOT NULL CHECK (status IN
                     ('awaiting_approval', 'not_run', 'running', 'completed', 'failed',
                      'interrupted', 'timeout')),
    -- The step (1 to 10) the plan stopped at when it did not complete.
    stopped_at       INTEGER CHECK (stopped_at IS NULL OR stopped_at BETWEEN 1 AND 10),
    error_code       TEXT CHECK (error_code IS NULL OR error_code IN
                     ('rejected', 'expired', 'undecided', 'approval_not_usable',
                      'plan_altered', 'config_error', 'denied', 'tool_error', 'timeout',
                      'call_failed', 'interrupted', 'deadline', 'abandoned')),
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    decided_at       TEXT,
    started_at       TEXT,
    finished_at      TEXT
);

CREATE INDEX idx_plan_runs_session ON plan_runs (session_id, created_at);
CREATE INDEX idx_plan_runs_status ON plan_runs (status);

-- The plan a call belongs to and its position in it; NULL for `mcp call`.
ALTER TABLE tool_calls ADD COLUMN plan_id TEXT REFERENCES plan_runs (plan_id);
ALTER TABLE tool_calls ADD COLUMN plan_step INTEGER
    CHECK (plan_step IS NULL OR plan_step BETWEEN 1 AND 10);

CREATE INDEX idx_tool_calls_plan ON tool_calls (plan_id, plan_step);
