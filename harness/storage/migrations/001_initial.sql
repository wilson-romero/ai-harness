CREATE TABLE sessions (
    session_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    project_id  TEXT,
    provider    TEXT NOT NULL,
    remote_ref  TEXT,
    status      TEXT NOT NULL CHECK (status IN
                ('created', 'active', 'authentication_required', 'uncertain', 'closed')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE requests (
    request_id   TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions (session_id),
    status       TEXT NOT NULL CHECK (status IN
                 ('pending', 'running', 'completed', 'failed', 'timeout',
                  'authentication_required', 'uncertain')),
    error_code   TEXT,
    duration_ms  INTEGER,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    UNIQUE (request_id, session_id)
);

-- The composite foreign key makes a message of another session's request impossible (SEC-02).
CREATE TABLE messages (
    message_id  TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions (session_id),
    request_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (request_id, session_id) REFERENCES requests (request_id, session_id)
);

-- Audit rows never carry prompt or response text.
CREATE TABLE audit_events (
    event_id    TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions (session_id),
    request_id  TEXT REFERENCES requests (request_id),
    event_type  TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    actor       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_sessions_updated ON sessions (updated_at);
CREATE INDEX idx_requests_session ON requests (session_id, started_at);
CREATE INDEX idx_requests_status ON requests (status);
CREATE INDEX idx_messages_session ON messages (session_id, created_at);
CREATE INDEX idx_audit_session ON audit_events (session_id, created_at);
