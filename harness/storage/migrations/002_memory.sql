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
