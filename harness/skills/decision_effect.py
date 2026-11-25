"""The `vault.save_decision` effect: the adapter between the skill engine and the decision writer.

It writes nothing itself. `prepare` turns the validated JSON of `architecture-memory` into the
exact note (cleaned and redacted field by field, rendered, normalised again as a whole) and its
target, after the confinement and duplicate checks; `exclusive` is the vault writer's lock, held
by the engine from before the approval is consumed; `apply` hands only the verified proposal to
`harness.memory.decisions.write_decision`; `reconcile` asks the vault, by decision identifier and
SHA-256, whether an interrupted write is in place (architecture-skills-llm D5-D8, D11).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager
from datetime import date, datetime
from pathlib import Path

from harness.core.errors import HarnessError
from harness.memory.config import ensure_data_dir_outside_vault, load_memory_settings
from harness.memory.decisions import (
    DECISIONS_DIR,
    ID_PREFIX,
    DecisionFields,
    DecisionRefused,
    DecisionUncertain,
    Provenance,
    decision_file_name,
    decision_id,
    find_decision_notes,
    inspect_decisions_dir,
    is_decision_id,
    reconcile_decision,
    render_note,
    temp_name_for,
    write_decision,
)
from harness.memory.notes import parse_frontmatter
from harness.memory.paths import resolve_project
from harness.memory.safe_text import safe_line
from harness.skills.approvals import Proposal, normalise_content
from harness.skills.checks import parse_fields
from harness.skills.effects import (
    EffectBusy,
    EffectContext,
    EffectRefused,
    EffectUncertain,
    Prepared,
    Reconciled,
)
from harness.storage.locks import NamedLock

LOCK_NAME = "vault-decisions"
LOCK_WAIT_S = 5.0
REDACTION_MARK = "[REDACTED:"
SOURCE_INPUT = "source"


class DecisionEffect:
    scope = "vault.save_decision"

    def __init__(self, data_dir: Path | None, env: Mapping[str, str] | None = None,
                 lock_wait_s: float = LOCK_WAIT_S) -> None:
        self._data_dir = data_dir
        self._env = env
        self._lock_wait_s = lock_wait_s

    # -- the effect protocol --------------------------------------------------------------------

    def prepare(self, context: EffectContext, validated: str) -> Prepared:
        project = context.project_slug
        if project is None:
            raise EffectRefused("no_project", "a decision needs a session with a project")
        root = self._root()
        try:
            resolve_project(root, project)
        except HarnessError as exc:
            raise EffectRefused("project_not_found", str(exc)) from None
        fields = _fields(validated)
        redactions = sum(text.count(REDACTION_MARK) for text in _texts(fields))
        ident = decision_id(project, fields.title)
        day = _run_day(context.run_created_at)
        name = decision_file_name(day, fields.title, ident)
        source = context.inputs.get(SOURCE_INPUT, {})
        provenance = Provenance(
            skill_name=context.skill_name,
            skill_version=context.skill_version,
            skill_sha256=context.skill_sha256,
            run_id=context.run_id,
            memory_notes=context.memory_notes,
            source_bytes=int(source.get("bytes", 0)),
            source_sha256=str(source.get("sha256", "")),
            redactions=redactions,
        )
        content = normalise_content(render_note(fields, project, day, provenance))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        try:
            folder = inspect_decisions_dir(root)  # never creates the folder
            existing = find_decision_notes(folder, ident) if folder is not None else []
        except DecisionRefused as refused:
            raise EffectRefused(refused.code, str(refused)) from None
        for existing_name, existing_digest in existing:
            # The very note this run would write, already written: the engine is preparing
            # again to reconcile an interrupted step. Anything else is a duplicate (D8).
            if existing_digest != digest:
                where = safe_line(f"{DECISIONS_DIR}/{existing_name}").text
                raise EffectRefused(
                    "duplicate_decision",
                    f"decision {ident} is already recorded in {where}",
                )
        return Prepared(content=content, target=f"{DECISIONS_DIR}/{name}", effect_ref=ident,
                        redactions=redactions)

    def exclusive(self, context: EffectContext) -> AbstractContextManager[None]:
        return self._held()

    def apply(self, context: EffectContext, proposal: Proposal) -> None:
        root = self._root()
        folder, _, name = (proposal.target or "").partition("/")
        frontmatter, _ = parse_frontmatter(proposal.content)
        ident = frontmatter.fields.get("decision_id") if frontmatter.syntax_ok else None
        if (
            folder != DECISIONS_DIR
            or not isinstance(ident, str)
            or not is_decision_id(ident)
            or not name.endswith(f"-{ident[len(ID_PREFIX):][:8]}.md")
            or frontmatter.fields.get("project_slug") != context.project_slug
        ):
            raise EffectRefused("unsafe_target", "the approved note does not match its target")
        try:
            write_decision(root, name, proposal.content.encode("utf-8"),
                           temp_name_for(context.run_id, context.step), ident)
        except DecisionRefused as refused:  # raised only while nothing is published
            raise EffectRefused(refused.code, str(refused)) from None
        except DecisionUncertain as uncertain:  # the note may be published: reconcile decides
            raise EffectUncertain(str(uncertain)) from None

    def reconcile(
        self, context: EffectContext, effect_ref: str | None, content_sha256: str
    ) -> Reconciled:
        if effect_ref is None or not is_decision_id(effect_ref):
            return "conflict"
        root = self._root()
        temp_name = temp_name_for(context.run_id, context.step)
        result = reconcile_decision(root, effect_ref, content_sha256, temp_name)
        if result == "blocked":
            raise EffectRefused(
                "temp_not_removed",
                f"the temporary file {DECISIONS_DIR}/{temp_name} of this step cannot be removed "
                "(another program, such as a sync client or an antivirus, may hold it open); "
                "until it is gone the memory does not read the note. Close that program and run "
                "`skill resume` again",
            )
        assert result in ("applied", "absent", "conflict")
        return result  # type: ignore[return-value]

    # -- helpers --------------------------------------------------------------------------------

    @contextlib.contextmanager
    def _held(self) -> Iterator[None]:
        if self._data_dir is None:
            raise EffectRefused("not_configured", "the decision writer has no data directory")
        lock = NamedLock(self._data_dir, LOCK_NAME)
        if not lock.acquire(self._lock_wait_s):
            raise EffectBusy(
                f"another harness process is writing a decision (waited {self._lock_wait_s:g} s); "
                "the approval is still granted: run `skill resume` again"
            )
        try:
            yield
        finally:
            lock.release()

    def _root(self) -> Path:
        """The real vault root, with the data directory outside it, as for every read."""
        if self._data_dir is None:
            raise EffectRefused("not_configured", "the decision writer has no data directory")
        try:
            settings = load_memory_settings(self._env if self._env is not None else os.environ)
            ensure_data_dir_outside_vault(self._data_dir, settings.vault_root)
        except HarnessError as exc:
            raise EffectRefused("vault_unavailable", str(exc)) from None
        return settings.vault_root


def _fields(validated: str) -> DecisionFields:
    """The validated JSON, each text cleaned and redacted once more as approvable content."""
    data = parse_fields(validated)

    def text(name: str) -> str:
        return normalise_content(str(data.get(name, "")))

    def items(name: str) -> tuple[str, ...]:
        return tuple(normalise_content(str(item)) for item in data.get(name, []) or [])

    return DecisionFields(
        title=text("title"),
        context=text("context"),
        decision=text("decision"),
        alternatives=items("alternatives"),
        consequences=items("consequences"),
        assumptions=items("assumptions"),
    )


def _texts(fields: DecisionFields) -> list[str]:
    return [fields.title, fields.context, fields.decision, *fields.alternatives,
            *fields.consequences, *fields.assumptions]


def _run_day(created_at: str) -> date:
    """The local date the run was created: fixed for the whole run, never in the future."""
    try:
        return datetime.fromisoformat(created_at).astimezone().date()
    except ValueError:
        raise EffectRefused("invalid_run", "the run has no creation time") from None
