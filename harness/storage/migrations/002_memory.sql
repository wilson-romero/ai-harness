-- One row: the profile and the resolved vault root this data directory is bound to (D2).
CREATE TABLE memory_binding (
    binding_id  INTEGER PRIMARY KEY CHECK (binding_id = 1),
    profile     TEXT NOT NULL CHECK (profile IN ('work', 'personal')),
    vault_root  TEXT NOT NULL CHECK (length(vault_root) > 0),
    created_at  TEXT NOT NULL
);

-- Provenance of the memory sent with a request: which notes, in which version. Never their
-- text (D7).
CREATE TABLE request_context (
    request_id  TEXT NOT NULL REFERENCES requests (request_id),
    note_path   TEXT NOT NULL,
    sha256      TEXT NOT NULL CHECK (length(sha256) = 64),
    bytes       INTEGER NOT NULL CHECK (bytes >= 0),
    truncated   INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    PRIMARY KEY (request_id, note_path)
);
