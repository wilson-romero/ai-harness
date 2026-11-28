"""The work folder of a conversation and the consent to send its content (workspace-tools B2).

- The folder is chosen with `/workspace <path>` and lives in the conversation's memory only:
  it is never written to the database (a path is the person's content, design D7), so a new
  run of `chat`, or `/resume` of another session, starts without one (design B2-1).
- While it is set, `with_workspace` adds the internal server `workspace` (`server.TOOLS`) to
  the policy view every `/plan` and `/agent` reads; without it the tools do not exist.
- The consent (D14, B2-3) is per folder and per provider: a row of `workspace_consents` keyed
  by `server.folder_hmac`, never the path. It is off by default, given only through the box
  (`approvals.decide` on a `Proposal` of its own scope) and revocable. A synthetic provider
  (the Mock) needs none: its content never leaves the machine.
"""

from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from harness.mcp.config import LoadedConfig
from harness.mcp.plan_run import PlanReport
from harness.skills.approvals import Proposal
from harness.storage import repositories as repo
from harness.storage.database import transaction, utc_now
from harness.text.safe_text import terminal_safe
from harness.workspace.audit import SERVER
from harness.workspace.paths import Root
from harness.workspace.root import check_root
from harness.workspace.server import Folder, WorkspaceServer, folder_hmac

CONSENT_SCOPE = "workspace-tools.send-consent"
CONSENT_FORMAT = "ai-harness/workspace-consent/1"
CONSENT_BUTTON_QUESTION = ("Approve lets the loops of /agent send what reads of this folder "
                           "return to this provider, until /workspace send off; Reject sends "
                           "nothing.")
NO_CONSENT = "not sent: no consent for this folder"


def choose(raw: str, *, data_dir: Path, environ: Mapping[str, str],
           vault: Path | None = None) -> Root:
    """`check_root` with the conversation's own vault protected too, when it has one."""
    if vault is not None and not (environ.get("HARNESS_VAULT_ROOT") or "").strip():
        environ = {**environ, "HARNESS_VAULT_ROOT": str(vault)}
    return check_root(raw, data_dir=data_dir, environ=environ)


def with_workspace(config: LoadedConfig, folder: Folder | None, key: bytes) -> LoadedConfig:
    """The policy view of a question: the local list, plus the work folder when one is set."""
    if folder is None:
        return config
    return dataclasses.replace(config, internal={SERVER: WorkspaceServer(folder, key)})


def content_steps(report: PlanReport | None) -> list[int]:
    """The positions of the steps whose result holds text of the work folder: a completed
    `workspace` call. A refusal holds only the harness's reason."""
    if report is None:
        return []
    return [r.position for r in report.steps if r.server == SERVER and r.status == "completed"]


def consent_proposal(root: Root, key: bytes, provider: str, session_id: UUID) -> Proposal:
    """What the box shows and binds for the consent: the folder (shown to the person only),
    its keyed hash and the provider."""
    folder = folder_hmac(key, root)
    content = "\n".join([
        f"file contents of {terminal_safe(str(root.path))} will be sent to {provider}",
        "  when: in the turns of /agent that carry what reads of this folder returned, each "
        "one shown before it goes (and the first one of each loop asked again)",
        "  never: .env files, key files, .git, files with a known credential, or anything "
        "outside this folder",
        f"  folder: {folder[:16]} (a keyed hash; the path itself is never stored)",
        "  until: /workspace send off, or another folder",
    ])
    return Proposal(scope=CONSENT_SCOPE, session_id=str(session_id), run_id=folder,
                    step=provider, skill_name=SERVER, skill_version=CONSENT_FORMAT,
                    skill_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    target=provider, content=content)


def has_consent(conn: sqlite3.Connection, key: bytes, root: Root, provider: str) -> bool:
    row = conn.execute("SELECT state FROM workspace_consents WHERE folder_hmac = ? AND "
                       "provider = ?", (folder_hmac(key, root), provider[:64])).fetchone()
    return row is not None and row[0] == "granted"


def record_consent(conn: sqlite3.Connection, key: bytes, root: Root, provider: str, *,
                   state: str, session_id: UUID, approval_hash: str | None = None,
                   means: str | None = None) -> None:
    """Grant (`granted`), revoke (`revoked`) or audit an answer that grants nothing
    (`rejected`, `undecided`, `expired`: the row, if any, is left as it was)."""
    folder = folder_hmac(key, root)
    with transaction(conn):
        if state in ("granted", "revoked"):
            conn.execute(
                "INSERT INTO workspace_consents (folder_hmac, provider, state, approval_hash, "
                "decided_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT (folder_hmac, provider) DO "
                "UPDATE SET state = excluded.state, approval_hash = excluded.approval_hash, "
                "decided_at = excluded.decided_at",
                (folder, provider[:64], state, approval_hash, utc_now()))
        repo.insert_audit(conn, event_type="workspace.send_consent", outcome=state, actor="cli",
                          session_id=session_id,
                          detail=f"folder={folder[:16]};means={means or '-'}"
                                 + (f";hash={approval_hash[:16]}" if approval_hash else ""))
