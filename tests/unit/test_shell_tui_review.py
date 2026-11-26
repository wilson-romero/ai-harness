"""Regressions of the independent review of shell-tui (2026-11-26): each test fails on the code
the review read (e0b930d) and has a negative control in the task receipts."""

from __future__ import annotations

import argparse
import shutil
import threading
import time
import webbrowser

import pytest
from textual.widgets import Input, Static

from harness.shell import tui as tui_module
from harness.shell.app import FULL_SCREEN_FAILED, run_chat
from harness.shell.tui import (
    CRASHED,
    NOT_SEEN,
    ApprovalScreen,
    CodeInput,
    FullScreenUnavailable,
    HarnessApp,
    TuiTerminal,
    run_full_screen,
)
from tests.conftest import REPO_ROOT
from tests.skill_support import ScriptedProvider
from tests.tui_support import SIZE, Tui
from tests.unit.test_shell_tui import _approval, _code, _query, _skill_tui, _type_answer

LONG_ECHO = ("## Resumen\n" + "\n".join(f"Línea {n} del resumen sintético." for n in range(120))
             + "\n\n## Preguntas pendientes\n- Ninguna.")


# -- 1 and 5: one line per wait, one answer per question ---------------------------------------


async def test_lines_typed_in_one_go_send_one_question(tmp_path):
    """The screen handles every Enter of a fast paste before the core's thread runs: only the
    first line may be taken."""
    tui = Tui(tmp_path)
    tui.provider.hang = True
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        taken = [tui.app._submit(line) for line in ("uno", "dos", "/new", "tres")]
        assert taken == [True, False, False, False]
        await tui.until(pilot, lambda: _query(tmp_path, "SELECT status FROM requests")
                        == ["running"])
        await pilot.pause(0.3)
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert tui.provider.calls == 1
    assert len(_query(tmp_path, "SELECT session_id FROM sessions")) == 1  # no /new ran


def test_one_answer_per_question_and_stale_answers_are_dropped():
    terminal = TuiTerminal()
    terminal._arm("ask")
    assert terminal.answer("n") is True
    assert terminal.answer("reject") is False  # the confirmation has not been asked yet
    terminal._answers.put(("answer", "antigua"))  # queued before the next box
    result: list = []
    thread = threading.Thread(target=lambda: result.append(terminal.ask("¿código?")))
    thread.start()
    deadline = time.monotonic() + 5
    while terminal._waiting != "ask" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert terminal.answer("nueva")
    thread.join(5)
    assert result == ["nueva"]


# -- 2: the whole proposal is shown before the code is taken -----------------------------------


async def test_the_code_waits_until_the_end_of_a_long_proposal_is_shown(tmp_path):
    provider = ScriptedProvider({"tarea: demo-echo/draft": LONG_ECHO})
    tui, effect = _skill_tui(tmp_path, provider)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        area = tui.app.screen.query_one("#approval-content")
        await tui.until(pilot, lambda: area.max_scroll_y > 50)
        assert "more line(s) below" in str(tui.app.screen.query_one("#approval-more").render())
        code = _code(tui)
        await _type_answer(tui, pilot, code)
        await tui.until(pilot, lambda: NOT_SEEN in str(
            tui.app.screen.query_one("#approval-message", Static).render()))
        assert isinstance(tui.app.screen, ApprovalScreen) and effect.written() == []
        assert isinstance(tui.app.focused, CodeInput)
        await pilot.press("pagedown")  # scrolls the proposal; the input keeps the focus
        await pilot.pause(0.1)
        assert area.scroll_y > 0 and isinstance(tui.app.focused, CodeInput)
        await pilot.press("end")
        await tui.until(pilot, lambda: "End of the proposal shown" in str(
            tui.app.screen.query_one("#approval-more").render()))
        await _type_answer(tui, pilot, code)
        await tui.until(pilot, lambda: any("is completed" in t for t in tui.blocks("harness")))
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert len(effect.written()) == 1


async def test_n_rejects_without_reading_to_the_end(tmp_path):
    provider = ScriptedProvider({"tarea: demo-echo/draft": LONG_ECHO})
    tui, effect = _skill_tui(tmp_path, provider)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _type_answer(tui, pilot, "n")
        await pilot.pause(0.1)
        await _type_answer(tui, pilot, "reject")
        await tui.until(pilot, lambda: any("is cancelled" in t for t in tui.blocks("harness")))
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["rejected"]


# -- 3: nothing moves text in or out of the approval input -------------------------------------


async def test_ctrl_v_cannot_paste_the_code(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        code = _code(tui)
        tui.app.copy_to_clipboard(code)
        box_input = tui.app.screen.query_one(CodeInput)
        await tui.until(pilot, lambda: tui.app.focused is box_input)
        await pilot.press("ctrl+v")
        assert box_input.value == ""
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(tui.app.screen, ApprovalScreen) and effect.written() == []
        box_input.value = "abc"
        box_input.action_select_all()
        await pilot.press("ctrl+x")
        assert box_input.value == "abc" and tui.app.clipboard == code  # nothing left the box
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        prompt = tui.app.query_one("#prompt", Input)
        await pilot.press("ctrl+v")  # negative control: the ordinary input pastes
        assert prompt.value == code
        prompt.value = ""
        await tui.send(pilot, "/exit")


# -- 4: nothing writes a file, opens a link or reaches the terminal's clipboard ----------------


async def test_no_app_action_writes_opens_or_copies_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a))
    tui = Tui(tmp_path / "datos")
    (tmp_path / "datos").mkdir()
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        written: list[str] = []
        monkeypatch.setattr(tui.app._driver, "write", lambda data: written.append(data))
        reached: list = []
        with monkeypatch.context() as patch:  # the action stops before delivering anything
            patch.setattr(tui.app, "deliver_screenshot", lambda *a, **k: reached.append(a))
            await tui.app.run_action(f"screenshot('probe.svg', '{tmp_path}')")
        assert reached == []
        tui.app.deliver_screenshot("probe2.svg", str(tmp_path))
        tui.app.deliver_text(__import__("io").StringIO("x"), save_directory=str(tmp_path),
                             save_filename="probe.txt")
        tui.app.deliver_binary(__import__("io").BytesIO(b"x"), save_directory=str(tmp_path),
                               save_filename="probe.bin")
        tui.app.open_url("https://example.invalid/")
        tui.app.action_suspend_process()
        tui.app.copy_to_clipboard("texto")
        with pytest.raises(RuntimeError):
            tui.app.save_screenshot("probe3.svg", str(tmp_path))
        await pilot.pause(0.2)
        assert not any("\x1b]52" in data for data in written)
        assert tui.app.clipboard == "texto"
        assert tui.app.is_running
        await tui.send(pilot, "/exit")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["datos"]
    assert opened == []


# -- 6: a crash prints a fixed line, nothing of the screen -------------------------------------


def test_a_crash_shows_a_fixed_message_without_locals():
    app = HarnessApp(TuiTerminal(), lambda: 0)
    try:
        foreign = "SECRETO-AJENO-EN-UNA-VARIABLE"  # noqa: F841 - what show_locals would print
        raise ValueError("fallo")
    except ValueError:
        app._fatal_error()
    assert app._exit_renderables == [CRASHED]
    assert app.return_code == 1
    app2 = HarnessApp(TuiTerminal(), lambda: 0)
    app2.panic("SECRETO-AJENO")
    assert app2._exit_renderables == [CRASHED]


# -- 9: a console the driver cannot start falls back to plain text -----------------------------


def test_a_driver_that_cannot_start_falls_back_to_plain(monkeypatch, tmp_path, capsys):
    def refuse(self, *args, **kwargs):
        raise OSError("no console screen buffer")

    monkeypatch.setattr(HarnessApp, "run", refuse)
    with pytest.raises(FullScreenUnavailable):
        run_full_screen(TuiTerminal(), lambda: 0)
    monkeypatch.setenv("HARNESS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HARNESS_PROVIDER", "mock")
    args = argparse.Namespace(session=None, project=None, name=None, plain=False)
    assert run_chat(args, TuiTerminal()) == 0  # the plain conversation, at end of input
    err = capsys.readouterr()
    assert FULL_SCREEN_FAILED in err.err and "Traceback" not in err.err + err.out
    assert "ai-harness conversation" in err.out


# -- surviving mutants M6 and M9 ---------------------------------------------------------------


async def test_the_panel_drops_the_notes_of_the_session_left(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(REPO_ROOT / "tests" / "fixtures" / "vault-synthetic", vault)
    data = tmp_path / "datos"
    data.mkdir()
    tui = Tui(data, vault=vault)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "/new --project demo-alpha Demo")
        await tui.send(pilot, "pregunta")
        await tui.until(pilot, lambda: "7 note(s)" in tui.side())
        await tui.send(pilot, "/new Otra")
        await tui.ready(pilot)
        await tui.until(pilot, lambda: "Otra" in tui.side())
        assert "0 note(s)" in tui.side() and "_project.md" not in tui.side()
        await tui.send(pilot, "/exit")


async def test_ctrl_q_ends_a_running_question_at_once(tmp_path):
    tui = Tui(tmp_path, timeout_s=120.0)  # the request's own timeout is far away
    tui.provider.hang = True
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "pregunta lenta")
        await tui.until(pilot, lambda: _query(tmp_path, "SELECT status FROM requests")
                        == ["running"])
        started = time.monotonic()
        tui.app.simulate_key("ctrl+q")
        await tui.until(pilot, lambda: not tui.app.is_running)
        assert time.monotonic() - started < 3.0
    assert _query(tmp_path, "SELECT status FROM requests") == ["uncertain"]


def test_the_module_names_one_lock_for_the_waits():
    assert isinstance(TuiTerminal()._state_lock, type(threading.Lock()))
    assert tui_module.APPROVAL_RULE_SHOWN.startswith("The code is taken only")
