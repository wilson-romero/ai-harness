-- MCP tool calls (mcp-gateway D11). One row per `mcp call`, allowed or denied. No column can
-- hold the value of an argument or any text of a result: the free-text columns are limited to
-- fixed vocabularies, and the arguments are kept only as a keyed hash (HMAC-SHA-256 with a
-- random local key under HARNESS_DATA_DIR/keys) and their size. Revised on 2026-11-24, before
-- any merge, after an independent review: `args_hmac` replaces an unsalted `args_sha256`, and
-- the vocabularies gained `annotation_conflict`, `server_error` and `stderr_too_large`.

CREATE TABLE tool_calls (
    call_id         TEXT PRIMARY KEY,
    -- The requested names, cleaned and cut to 64 characters (a name that is not in the
    -- allowlist can contain anything).
    server          TEXT NOT NULL CHECK (length(server) <= 64),
    tool            TEXT NOT NULL CHECK (length(tool) <= 64),
    operation       TEXT CHECK (operation IS NULL OR operation IN ('read', 'write')),
    decision        TEXT NOT NULL CHECK (decision IN ('allowed', 'denied')),
    reason          TEXT NOT NULL CHECK (reason IN
                    ('allowed', 'server_not_allowed', 'args_too_large', 'args_not_json',
                     'args_not_object', 'tool_not_allowed', 'argument_not_allowed',
                     'argument_missing', 'argument_invalid', 'write_requires_approval',
                     'tool_absent', 'schema_mismatch', 'annotation_conflict')),
    args_hmac       TEXT CHECK (args_hmac IS NULL OR length(args_hmac) = 64),
    args_bytes      INTEGER NOT NULL CHECK (args_bytes >= 0),
    status          TEXT NOT NULL CHECK (status IN
                    ('denied', 'running', 'completed', 'failed', 'timeout', 'abandoned')),
    error_code      TEXT CHECK (error_code IS NULL OR error_code IN
                    ('tool_error', 'timeout', 'protocol_error', 'server_exited', 'spawn_failed',
                     'invalid_result', 'result_too_large', 'message_too_large', 'interrupted',
                     'internal_error', 'abandoned', 'server_error', 'stderr_too_large')),
    -- 1: the session's whole process tree (server and anything it started in its group) was
    -- seen to end; 0: something was still alive after the kill; NULL: not known (denied before
    -- starting).
    server_stopped  INTEGER CHECK (server_stopped IS NULL OR server_stopped IN (0, 1)),
    result_bytes    INTEGER CHECK (result_bytes IS NULL OR result_bytes >= 0),
    duration_ms     INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    created_at      TEXT NOT NULL,
    finished_at     TEXT,
    CHECK ((decision = 'denied') = (status = 'denied')),
    CHECK ((decision = 'allowed') = (reason = 'allowed'))
);

CREATE INDEX idx_tool_calls_status ON tool_calls (status, created_at);
