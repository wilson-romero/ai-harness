"""Regressions of the independent review of shell-tui (2026-11-26): each test fails on the code
the review read (e0b930d) and has a negative control in the task receipts."""

from __future__ import annotations

import argparse
import shutil
import threading
import time
import webbrowser

import pytest

from harness.shell import tui as tui_module
from harness.shell.app import FULL_SCREEN_FAILED, run_chat
from harness.shell.tui import (
    CRASHED,
    FullScreenUnavailable,
    HarnessApp,
    TuiTerminal,
    run_full_screen,
)
from tests.conftest import REPO_ROOT
from tests.tui_support import SIZE, Tui
from tests.unit.test_shell_tui import _query

# -- 1: one line per wait (5, one press per box, is in test_shell_tui_buttons.py) ------------


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


# -- 4: nothing writes a file, opens a link or reaches the terminal's clipboard ----------------


# A folder whose path has a backslash before a `U`, as every Windows profile path has (the
# drive, then the Users folder): Textual reads action arguments with `ast.literal_eval`, where `\U` in
# a plain literal is an escape. The path goes in with `repr`, so it is a valid literal on
# every system (Windows 11 run of de089d1). On POSIX the backslashes are part of one name;
# on Windows they separate folders, and the path has `\U` all the same.
@pytest.mark.parametrize("folder", ["", "sub\\Users\\probe"])  # relative on both systems
async def test_no_app_action_writes_opens_or_copies_out(tmp_path, monkeypatch, folder):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / folder if folder else tmp_path
    target.mkdir(parents=True, exist_ok=True)
    assert not folder or "\\U" in str(target)
    opened: list = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: opened.append(a))
    tui = Tui(tmp_path / "datos")
    (tmp_path / "datos").mkdir()
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        written: list[str] = []
        monkeypatch.setattr(tui.app._driver, "write", lambda data: written.append(data))
        reached: list = []
        refused: list = []
        with monkeypatch.context() as patch:  # the action runs, and stops before delivering
            patch.setattr(tui.app, "deliver_screenshot", lambda *a, **k: reached.append(a))
            patch.setattr(tui.app, "_refused", refused.append)
            await tui.app.run_action(f"screenshot('probe.svg', {str(target)!r})")
        assert reached == [] and refused == ["screenshots"]
        tui.app.deliver_screenshot("probe2.svg", str(target))
        tui.app.deliver_text(__import__("io").StringIO("x"), save_directory=str(target),
                             save_filename="probe.txt")
        tui.app.deliver_binary(__import__("io").BytesIO(b"x"), save_directory=str(target),
                               save_filename="probe.bin")
        tui.app.open_url("https://example.invalid/")
        tui.app.action_suspend_process()
        tui.app.copy_to_clipboard("texto")
        with pytest.raises(RuntimeError):
            tui.app.save_screenshot("probe3.svg", str(target))
        await pilot.pause(0.2)
        assert not any("\x1b]52" in data for data in written)
        assert tui.app.clipboard == "texto"
        assert tui.app.is_running
        await tui.send(pilot, "/exit")
    top = target.relative_to(tmp_path).parts[:1]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["datos", *top])
    if folder:
        assert [p for p in target.rglob("*")] == []
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
    assert tui_module.SHOWN_ALL == "The whole proposal has been shown."
