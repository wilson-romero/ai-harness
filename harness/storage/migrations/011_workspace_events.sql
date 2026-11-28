-- The work-folder tools (workspace-tools design D7, B1-5). Number 011: 009 is on `develop` and
-- 010 is taken by the branch `feature/code-mode-loop`; `migrate` applies every missing version,
-- so the gap does not matter and the two apply in either order.
--
-- Every call of a work-folder tool leaves its `tool_calls` row (server `workspace`) with the
-- nearest existing reason, and here the exact code of the outcome. The relative path is kept
-- only as a keyed hash (HMAC-SHA-256 with the `mcp-args.key` key and the domain
-- `ai-harness/workspace-path/v1`): no column can hold a path, a name or any text of a file.
-- Nothing existing changes.

CREATE TABLE workspace_events (
    call_id     TEXT PRIMARY KEY REFERENCES tool_calls (call_id),
    code        TEXT NOT NULL CHECK (code IN
                ('ok', 'not_absolute', 'root_not_found', 'link', 'not_a_directory',
                 'harness_repo', 'data_dir', 'vault', 'code_run_root', 'home',
                 'filesystem_root', 'workspace_changed', 'empty_path', 'path_too_long',
                 'absolute', 'backslash', 'colon', 'forbidden_character',
                 'invisible_character', 'not_nfc', 'empty_component', 'dot_component',
                 'component_too_long', 'trailing_dot_or_space', 'reserved_name', 'not_found',
                 'name_not_exact', 'not_regular', 'hard_link', 'changed', 'outside_root',
                 'unreadable', 'denied_component', 'denied_name', 'credential_in_file',
                 'binary', 'too_large', 'offset_out_of_range')),
    path_hmac   TEXT CHECK (path_hmac IS NULL OR length(path_hmac) = 64),
    created_at  TEXT NOT NULL
);
