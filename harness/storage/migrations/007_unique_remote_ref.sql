-- One remote conversation belongs to one session at most (copilot-web-provider D6, revised
-- 2026-11-26 after an independent review): a session that typed into another session's
-- conversation would mix both contexts and leak one session's questions into the other's
-- answers (SEC-02).
--
-- If two or more sessions already share a reference, nobody can tell whose context the
-- remote conversation holds (all of them may have typed into it), so every session of such
-- a group is unbound, never just the later ones. The next question of each starts a new
-- remote conversation, and the provider says that it does so without the earlier context.
-- Each unbinding is audited; no content and no reference is copied into the audit.
INSERT INTO audit_events (event_id, session_id, request_id, event_type, outcome, actor, created_at)
SELECT 'migration-007-' || session_id, session_id, NULL, 'session.unbound',
       'duplicate_remote_ref', 'migration', strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
FROM sessions
WHERE remote_ref IN (
    SELECT remote_ref FROM sessions WHERE remote_ref IS NOT NULL
    GROUP BY remote_ref HAVING count(*) > 1
);

UPDATE sessions SET remote_ref = NULL
WHERE remote_ref IN (
    SELECT remote_ref FROM sessions WHERE remote_ref IS NOT NULL
    GROUP BY remote_ref HAVING count(*) > 1
);

CREATE UNIQUE INDEX idx_sessions_remote_ref ON sessions (remote_ref) WHERE remote_ref IS NOT NULL;
