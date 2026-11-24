"""What architecture-skills-llm adds to the engine for effects with real side effects (D11)."""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

from harness.skills.definition import FieldSpec, ValidateStep
from harness.skills.checks import check
from harness.skills.effects import EffectBusy, EffectContext, EffectRefused, NoEffect, Prepared
from harness.memory.context import build_context
from tests.conftest import VAULT_FIXTURE
from tests.skill_support import (
    ApprovingTerminal,
    FakeTerminal,
    ScriptedProvider,
    WriteEffect,
    build,
    copy_skills,
    with_effect,
)


def _run(engine, session, name="demo-echo", **inputs):
    return asyncio.run(engine.run(name, str(session.session_id), inputs or {"text": "hola"}))


def _resume(engine, run_id, **inputs):
    return asyncio.run(engine.resume(run_id, inputs or {"text": "hola"}, None))


def _one(conn, sql, *params):
    return conn.execute(sql, params).fetchone()


class RefusingAtPrepare(NoEffect):
    scope = "test.refuse"

    def prepare(self, context, validated):
        raise EffectRefused("duplicate_decision", "already recorded in Decisiones/x.md")


class Recording(WriteEffect):
    """Keeps every context it is given and a redaction count to show."""

    def __init__(self, folder, redactions=0):
        super().__init__(folder)
        self.contexts: list[EffectContext] = []
        self.redactions = redactions

    def prepare(self, context, validated):
        self.contexts.append(context)
        prepared = super().prepare(context, validated)
        return Prepared(prepared.content, prepared.target, prepared.effect_ref,
                        redactions=self.redactions)


class Busy(WriteEffect):
    """Its exclusive section is taken by someone else until `free` is set."""

    def __init__(self, folder):
        super().__init__(folder)
        self.free = False

    def exclusive(self, context):
        if not self.free:
            raise EffectBusy("the vault writer is busy in another process")
        return contextlib.nullcontext()


class RefusingAtApply(WriteEffect):
    def apply(self, context, proposal):
        raise EffectRefused("conflict", "Decisiones/x.md already exists")


def _engine(conn, data_dir, tmp_path, effect, terminal, **kwargs):
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", effect.scope)
    return build(conn, data_dir, root=root, terminal=terminal, effects={effect.scope: effect},
                 **kwargs)


def test_a_refusal_in_prepare_fails_the_run_before_any_approval(conn, data_dir, tmp_path):
    terminal = ApprovingTerminal()
    engine, sessions, _ = _engine(conn, data_dir, tmp_path, RefusingAtPrepare(), terminal)
    outcome = _run(engine, sessions.create_session("Demo"))
    assert outcome.status == "failed"
    assert "already recorded in Decisiones/x.md" in outcome.message
    assert tuple(_one(conn, "SELECT status, error_code FROM skill_runs")) == (
        "failed", "duplicate_decision")
    assert _one(conn, "SELECT count(*) FROM approvals")[0] == 0
    assert terminal.shown == []


def test_a_busy_effect_keeps_the_approval_granted_and_consumes_nothing(conn, data_dir, tmp_path):
    effect = Busy(tmp_path / "salida")
    engine, sessions, _ = _engine(conn, data_dir, tmp_path, effect, ApprovingTerminal())
    with pytest.raises(EffectBusy):
        _run(engine, sessions.create_session("Demo"))
    assert tuple(_one(conn, "SELECT status FROM approvals")) == ("granted",)
    run_id, status = _one(conn, "SELECT run_id, status FROM skill_runs")
    assert status == "awaiting_approval" and effect.written() == []
    effect.free = True
    outcome = _resume(engine, run_id)
    assert outcome.status == "completed" and len(effect.written()) == 1
    assert tuple(_one(conn, "SELECT status FROM approvals")) == ("consumed",)


def test_a_refusal_in_apply_fails_the_step_with_its_code(conn, data_dir, tmp_path):
    effect = RefusingAtApply(tmp_path / "salida")
    engine, sessions, _ = _engine(conn, data_dir, tmp_path, effect, ApprovingTerminal())
    outcome = _run(engine, sessions.create_session("Demo"))
    assert outcome.status == "failed" and "already exists" in outcome.message
    assert tuple(_one(conn, "SELECT status, error_code FROM skill_steps WHERE kind = 'approval'")
                 ) == ("failed", "conflict")
    assert tuple(_one(conn, "SELECT status FROM approvals")) == ("consumed",)


def test_redactions_are_shown_in_the_approval_header(conn, data_dir, tmp_path):
    terminal = ApprovingTerminal()
    effect = Recording(tmp_path / "salida", redactions=1)
    engine, sessions, _ = _engine(conn, data_dir, tmp_path, effect, terminal)
    _run(engine, sessions.create_session("Demo"))
    assert "  redacted: 1 credential(s) redacted" in terminal.shown[0].splitlines()


def test_applied_targets_are_reported_and_audited(conn, data_dir, tmp_path):
    effect = Recording(tmp_path / "salida")
    engine, sessions, _ = _engine(conn, data_dir, tmp_path, effect, ApprovingTerminal())
    outcome = _run(engine, sessions.create_session("Demo"))
    assert outcome.status == "completed"
    assert outcome.applied == ("salida/salida.md",)
    events = [r[0] for r in conn.execute(
        "SELECT event_type FROM audit_events WHERE event_type LIKE 'approval.%' "
        "OR event_type = 'effect.applied' ORDER BY rowid")]
    assert events == ["approval.requested", "approval.granted", "approval.consumed",
                      "effect.applied"]


def test_the_effect_context_carries_what_the_note_needs(conn, data_dir, tmp_path):
    root = copy_skills(tmp_path)
    path = root / "demo-json" / "workflow.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["steps"] = data["steps"][:2] + [
        {"id": "save", "kind": "approval", "of": "fields", "effect": "test.write"}]
    data["output"] = "save"
    path.write_text(json.dumps(data), encoding="utf-8")
    effect = Recording(tmp_path / "salida")
    answer = json.dumps({"title": "Cola gestionada", "kind": "decision", "points": ["uno"],
                         "priority": 2})
    engine, sessions, _ = build(
        conn, data_dir, root=root, terminal=FakeTerminal(interactive=False),
        effects={"test.write": effect},
        provider=ScriptedProvider({"tarea: demo-json/extract": answer}),
        project_context=lambda project: build_context(VAULT_FIXTURE, project, 16_000),
    )
    session = sessions.create_session("Demo", "demo-alpha")
    outcome = _run(engine, session, name="demo-json", source="fuente sintética")
    assert outcome.status == "awaiting_approval"
    context = effect.contexts[-1]
    run = _one(conn, "SELECT run_id, created_at, skill_version, skill_sha256 FROM skill_runs")
    assert context.project_slug == "demo-alpha"
    assert (context.run_id, context.run_created_at, context.skill_version,
            context.skill_sha256) == tuple(run)
    assert set(context.inputs) == {"source"} and context.inputs["source"]["bytes"] == len(
        "fuente sintética".encode())
    expected = conn.execute(
        "SELECT DISTINCT note_path, sha256 FROM request_context ORDER BY note_path").fetchall()
    assert context.memory_notes == tuple(tuple(r) for r in expected) and expected


@pytest.mark.parametrize("value, ok", [("x" * 7, False), ("x" * 8, True), ("x" * 120, True),
                                       ("x" * 121, False)])
def test_string_min_length(value, ok):
    step = ValidateStep(id="check", kind="validate", of="x", format="json", fields={
        "title": FieldSpec(type="string", min_length=8, max_length=120)})
    result = check(step, json.dumps({"title": value}))
    assert result.ok is ok
    if not ok:
        assert result.error_code in ("validation_failed:min_length:title",
                                     "validation_failed:max_length:title")
