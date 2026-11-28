-- The loops of code mode (A3): `/agent`, a question whose plans' results go back to the
-- model as data, turn by turn. Its own migration, so that the history is linear whatever a
-- database applied before (review of `fa6b6d1`, finding 5): 010 is A2's alone, 011 belongs
-- to `feature/workspace-tools` and 012 is kept for the speed branch, so this is 013.
-- A database of this branch's earlier builds may hold these tables from a 010 that carried
-- them; they are dropped and made again (loops are bookkeeping, never resumed, and no
-- released database had them), so every database ends with the same schema.
--
-- Enough to tell, after a crash, which loop was in flight and that it was interrupted: a
-- loop is never resumed. No column holds a question, a plan, a result or a reply: of what
-- each turn sent, only its size and a keyed hash.
--
-- `loop_runs`: one row per loop. `turns` is the last turn recorded; `corrections` the
-- refused plans whose reason went back (one at most). `stop_reason` is a word of a closed
-- list. A row left `running` by a process that is gone becomes `interrupted` (`abandoned`)
-- when a conversation opens or a loop starts.
-- `loop_turns`: one row per question sent, written in the transaction that records the
-- request, with the turn number, its kind and the plan whose results it carried.

DROP TABLE IF EXISTS loop_turns;
DROP TABLE IF EXISTS loop_runs;

CREATE TABLE loop_runs (
    loop_id      TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions (session_id),
    provider     TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
    max_turns    INTEGER NOT NULL CHECK (max_turns BETWEEN 1 AND 10),
    turns        INTEGER NOT NULL CHECK (turns BETWEEN 0 AND 11),
    corrections  INTEGER NOT NULL CHECK (corrections BETWEEN 0 AND 1),
    status       TEXT NOT NULL CHECK (status IN
                 ('running', 'completed', 'stopped', 'interrupted')),
    stop_reason  TEXT CHECK (stop_reason IS NULL OR stop_reason IN
                 ('answer', 'cap', 'refused', 'not_approved', 'plan_stopped',
                  'reply_not_completed', 'reply_truncated', 'turn_too_large',
                  'turn_not_clean', 'send_not_approved', 'error', 'interrupted',
                  'abandoned')),
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);

CREATE INDEX idx_loop_runs_session ON loop_runs (session_id, created_at);
CREATE INDEX idx_loop_runs_status ON loop_runs (status);

CREATE TABLE loop_turns (
    loop_id     TEXT NOT NULL REFERENCES loop_runs (loop_id),
    turn        INTEGER NOT NULL CHECK (turn BETWEEN 1 AND 11),
    request_id  TEXT NOT NULL UNIQUE REFERENCES requests (request_id),
    kind        TEXT NOT NULL CHECK (kind IN ('question', 'results', 'correction', 'closing')),
    plan_id     TEXT REFERENCES plan_runs (plan_id),
    sent_bytes  INTEGER NOT NULL CHECK (sent_bytes >= 0),
    sent_hmac   TEXT NOT NULL CHECK (length(sent_hmac) = 64),
    created_at  TEXT NOT NULL,
    PRIMARY KEY (loop_id, turn)
);
