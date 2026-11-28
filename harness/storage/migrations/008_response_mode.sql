-- The response mode (change response-mode, design D5).
--
-- A session remembers the mode a person chose; every existing session starts in `auto`, which
-- is what it always was: the provider's page chose. A request records the mode it asked for
-- and the mode the provider confirmed on its page (which may differ: the page can fall back
-- during the answer). Requests from before this migration have neither: NULL, shown as nothing.
ALTER TABLE sessions ADD COLUMN response_mode TEXT NOT NULL DEFAULT 'auto'
    CHECK (response_mode IN ('auto', 'quick', 'deep'));

ALTER TABLE requests ADD COLUMN requested_mode TEXT
    CHECK (requested_mode IN ('auto', 'quick', 'deep'));

ALTER TABLE requests ADD COLUMN confirmed_mode TEXT
    CHECK (confirmed_mode IN ('auto', 'quick', 'deep'));
