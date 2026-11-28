-- The work-folder tools (workspace-tools design D7, B1-5). Number 011, kept for this branch:
-- 010 and 013 are code mode's and 012 the speed branch's; `migrate` applies every missing version,
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

-- B2 (design D14, B2-3): the consent to send what the work folder's reads return to a
-- provider whose content is not synthetic, one row per folder and provider. The folder is a
-- keyed hash of its resolved path and identity (`ai-harness/workspace-folder/v1`), never the
-- path; a folder replaced by another one (another identity) has no consent. Off unless a row
-- says `granted`; `/workspace send off` leaves it `revoked`.
CREATE TABLE workspace_consents (
    folder_hmac    TEXT NOT NULL CHECK (length(folder_hmac) = 64),
    provider       TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 64),
    state          TEXT NOT NULL CHECK (state IN ('granted', 'revoked')),
    approval_hash  TEXT CHECK (approval_hash IS NULL OR length(approval_hash) = 64),
    decided_at     TEXT NOT NULL,
    PRIMARY KEY (folder_hmac, provider)
);
