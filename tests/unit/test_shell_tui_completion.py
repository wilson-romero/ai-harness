"""The list of completions under the full-screen input (command-completion D2-D4), driven with
Pilot. Each guarantee has a negative control: the check fails without the protection."""

from __future__ import annotations

import threading
import time

from textual.widgets import Input

from harness.shell import tui as tui_module
from harness.shell.completion import Item, Listing
from harness.shell.shortforms import RUNNING
from harness.shell.tui import (
    ApprovalScreen,
    PromptInput,
    SuggestionList,
    _command_word,
    preview_of,
)
from harness.shell.completion import CompletionData
from tests.skill_support import ScriptedProvider, WriteEffect, copy_skills, with_effect
from tests.tui_support import SIZE, Tui

SKILL_LINE = "/skill demo-echo text=texto-sintetico"


def _parts(tui) -> tuple[PromptInput, SuggestionList]:
    return tui.app.query_one(PromptInput), tui.app.query_one(SuggestionList)


def _rows(listing: SuggestionList) -> list[str]:
    return [str(listing.get_option_at_index(i).prompt) for i in range(listing.option_count)]


async def _open(tui, pilot) -> tuple[PromptInput, SuggestionList]:
    await tui.ready(pilot)
    await tui.until(pilot, lambda: tui.app.query_one(PromptInput).data.skills != ())
    return _parts(tui)


def _skills_tui(tmp_path, **options) -> Tui:
    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    return Tui(data_dir, skills_dir=copy_skills(tmp_path), **options)


# -- the list ------------------------------------------------------------------------------------


async def test_slash_opens_the_commands_and_typing_filters_without_losing_a_key(tmp_path):
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press("/")
        assert listing.showing and listing.highlighted is None  # nothing chosen yet
        assert _rows(listing)[0].startswith("/help") and "this list" in _rows(listing)[0]
        assert len(listing.items) == 11
        await pilot.press(*"sk")
        assert prompt.value == "/sk"  # every key typed is in the input, none taken
        assert [i.insert for i in listing.items] == ["/skill "]
        assert prompt.preview == ""  # /sk alone is no command yet
        await pilot.press("tab")
        assert prompt.value == "/skill "
        await tui.until(pilot, lambda: listing.showing)
        assert "demo-echo " in [i.insert for i in listing.items]  # valid skills only
        assert "bad-name " not in [i.insert for i in listing.items]
        assert tui.terminal.waiting_for_line()  # nothing was sent
        prompt.value = ""
        await tui.send(pilot, "/exit")


async def test_arrows_choose_enter_takes_the_chosen_and_never_sends(tmp_path):
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press(*"/s")
        assert [i.insert for i in listing.items][:3] == ["/status", "/sessions", "/skill "]
        await pilot.press("down", "down")
        assert listing.chosen().insert == "/sessions"
        await pilot.press("up")
        assert listing.chosen().insert == "/status"
        await pilot.press("enter")
        assert prompt.value == "/status"
        assert not listing.showing  # the only candidate is what is typed
        assert tui.terminal.waiting_for_line() and tui.blocks("you") == []
        await pilot.press("enter")  # with the list closed, enter sends
        await tui.until(pilot, lambda: any("last request:" in t for t in tui.blocks("harness")))
        await tui.send(pilot, "/exit")


async def test_enter_with_no_row_chosen_sends_what_is_typed(tmp_path):
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press(*"/st")
        assert listing.showing
        await pilot.press("enter")
        await tui.until(pilot, lambda: any(RUNNING + "/status" in t
                                           for t in tui.blocks("harness")))
        assert tui.blocks("you")[-1].strip().endswith("/st")
        await tui.send(pilot, "/exit")


async def test_esc_closes_the_list_first_then_starts_browsing(tmp_path):
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press("/")
        assert listing.showing
        await pilot.press("escape")
        assert not listing.showing and not prompt.browsing and prompt.value == "/"
        await pilot.press("escape")
        assert prompt.browsing
        await pilot.press("escape")
        prompt.value = ""
        await tui.send(pilot, "/exit")


async def test_up_and_down_recall_the_history_when_the_list_is_closed(tmp_path):
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await tui.send(pilot, "/help")
        await tui.send(pilot, "/status")
        await tui.ready(pilot)
        await pilot.press("up")
        assert prompt.value == "/status" and not listing.showing  # a recall opens nothing
        await pilot.press("up")
        assert prompt.value == "/help"
        await pilot.press("down", "down")
        assert prompt.value == ""
        await pilot.press("/", "down")
        assert prompt.value == "/" and listing.chosen().insert == "/help"  # the list's own
        await pilot.press("escape")
        prompt.value = ""
        await tui.send(pilot, "/exit")


async def test_the_preview_shows_the_full_command_before_enter(tmp_path, vault):
    tui = _skills_tui(tmp_path, vault=vault)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await tui.until(pilot, lambda: prompt.data.projects == ("demo-alpha", "demo-beta"))
        await pilot.press(*"/new demo-a", "tab")
        assert prompt.value == "/new demo-alpha "
        assert prompt.preview == RUNNING + "/new --project demo-alpha"
        await pilot.pause(0.05)
        assert RUNNING + "/new --project demo-alpha" in tui.screen()  # on its lower border
        await pilot.press("enter")
        await tui.until(pilot, lambda: "demo-alpha" in tui.side())
        assert any(RUNNING + "/new --project demo-alpha" in t for t in tui.blocks("harness"))
        await tui.send(pilot, "/exit")


async def test_paths_complete_folders_first_and_tab_takes_the_only_one(tmp_path, monkeypatch):
    work = tmp_path / "trabajo"
    (work / "entradas").mkdir(parents=True)
    (work / "entradas" / "fuente.md").write_text("contenido sintético", encoding="utf-8")
    (work / "entradas" / "fuentes").mkdir()
    monkeypatch.chdir(work)
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press(*"/file ent", "tab")
        await tui.until(pilot, lambda: prompt.value == "/file entradas/")
        await tui.until(pilot, lambda: listing.showing)
        assert [i.insert for i in listing.items] == ["entradas/fuentes/", "entradas/fuente.md"]
        await pilot.press(*"fuente.")
        await pilot.press("tab")
        await tui.until(pilot, lambda: prompt.value == "/file entradas/fuente.md")
        assert tui.terminal.waiting_for_line()
        await pilot.press("enter")
        await tui.until(pilot, lambda: any("attached fuente.md" in t
                                           for t in tui.blocks("harness")))
        await tui.send(pilot, "/exit")


# -- guarantees --------------------------------------------------------------------------------


HOSTILE_NAMES = ["[bold]negrita.md", "[@click=app.quit]x.md", "error:falso.md",
                 "Approval_requested.md", "\x1b[31mrojo.md", "linea\nnueva.md"]


async def test_a_hostile_name_is_drawn_and_inserted_literally(tmp_path, monkeypatch):
    work = tmp_path / "trabajo"
    work.mkdir()
    made = []
    for name in HOSTILE_NAMES:
        try:
            (work / name).write_text("x", encoding="utf-8")
            made.append(name)
        except OSError:
            pass
    monkeypatch.chdir(work)
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press(*"/file ")
        await tui.until(pilot, lambda: listing.showing)
        offered = [i.insert for i in listing.items]
        assert "[bold]negrita.md" in offered and "[@click=app.quit]x.md" in offered
        assert not [name for name in offered if "\x1b" in name or "\n" in name]
        for index, item in enumerate(listing.items):  # drawn as typed: no style from the name
            prompt_content = listing.get_option_at_index(index).prompt
            assert str(prompt_content).startswith(item.insert)
            assert all(str(span.style) in ("", "dim") for span in prompt_content.spans)
        await pilot.pause(0.05)
        assert "[bold]negrita.md" in tui.screen()  # the composed screen: the characters
        index = offered.index("[@click=app.quit]x.md")
        for _ in range(index + 1):
            await pilot.press("down")
        await pilot.press("enter")
        assert prompt.value == "/file [@click=app.quit]x.md"  # its own characters, nothing more
        assert tui.app.is_running and tui.terminal.waiting_for_line()
        prompt.value = ""
        await tui.send(pilot, "/exit")
    assert tui.provider.calls == 0


def test_negative_control_a_row_parsed_as_markup_would_style_the_name():
    from textual.content import Content

    assert Content.from_markup("[bold]negrita.md").spans  # the payload is live
    assert str(Content.from_markup("[bold]negrita.md")) == "negrita.md"


async def test_listing_runs_off_the_screen_thread_and_a_stale_answer_is_dropped(tmp_path,
                                                                                monkeypatch):
    release = threading.Event()
    calls: list[str] = []

    def slow(word: str, **kwargs) -> Listing:  # noqa: ANN003
        calls.append(word)
        if word == "a":
            release.wait(10)  # a folder that takes long: the first request
            return Listing((Item("a-viejo.md", "file", "file"),))
        return Listing((Item(word + "-nuevo.md", "file", "file"),))

    monkeypatch.setattr(tui_module, "list_folder", slow)
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        started = time.monotonic()
        await pilot.press(*"/file a")
        await pilot.press(*"bc")  # typed while the first listing still runs
        assert time.monotonic() - started < 5.0  # the first listing alone takes 10 s
        assert prompt.value == "/file abc"
        await tui.until(pilot, lambda: listing.showing)
        assert [i.insert for i in listing.items] == ["abc-nuevo.md"]
        release.set()
        await pilot.pause(0.3)
        assert [i.insert for i in listing.items] == ["abc-nuevo.md"]  # the old one never shows
        await pilot.press("escape")
        prompt.value = ""
        await tui.send(pilot, "/exit")


async def test_completing_never_sends_or_runs(tmp_path):
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press(*"/ex", "tab")
        assert prompt.value == "/exit"
        await pilot.press(*"/", "tab", "tab", "down", "tab")
        await pilot.pause(0.2)
        assert tui.app.is_running and tui.terminal.waiting_for_line()
        assert tui.blocks("you") == []
        prompt.value = ""
        await tui.send(pilot, "/exit")
    assert tui.provider.calls == 0


def _approval_tui(tmp_path) -> tuple[Tui, WriteEffect]:
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", "test.write")
    effect = WriteEffect(tmp_path / "efecto")
    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    return Tui(data_dir, ScriptedProvider(), skills_dir=root,
               effects={"test.write": effect}), effect


async def test_the_list_never_opens_over_the_approval_box_and_its_keys_do_nothing(tmp_path):
    tui, effect = _approval_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press("/")
        assert listing.showing
        await tui.send(pilot, SKILL_LINE)
        await tui.until(pilot, lambda: isinstance(tui.app.screen, ApprovalScreen))
        assert not listing.showing  # the box closed it
        box = tui.app.screen
        focused = tui.app.focused
        # Tab and enter are the box's own keys (approval-buttons D2); these are the list's.
        await pilot.press("/", "down", "up", "escape")
        await pilot.pause(0.1)
        assert not listing.showing and tui.app.screen is box and not box.pressed
        assert tui.app.focused is focused
        prompt.refresh_suggestions()  # asked directly while the box is up: nothing
        prompt._listed(prompt._generation, Listing((Item("x.md"),)))  # a late listing too
        assert not listing.showing
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert effect.written() == []


async def test_ctrl_n_and_the_palette_work_with_the_list_open(tmp_path):
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        first = tui.conversation._session.session_id
        await pilot.press("/")
        await pilot.press("ctrl+p")
        await pilot.pause(0.2)
        assert not listing.showing  # the palette is a screen over the input
        await pilot.press("escape")
        await pilot.pause(0.1)
        prompt.value = ""
        await pilot.press("/")
        await tui.until(pilot, lambda: listing.showing)
        await pilot.press("ctrl+n")
        await tui.until(pilot, lambda: tui.conversation._session.session_id != first)
        await pilot.pause(0.1)
        # What was typed stays, and so does its list: ctrl+n does not touch the input.
        assert prompt.value == "/" and listing.showing
        prompt.value = ""
        await tui.send(pilot, "/exit")


def test_a_cut_name_of_context_is_still_context_for_the_blocks():
    assert _command_word("/con") == "/context"
    assert _command_word("/context") == "/context"
    assert _command_word("/c") == "/context"  # /c is unique too
    assert _command_word("/s x") == "/s"  # ambiguous: left as typed
    assert _command_word("hola") == "hola" and _command_word(None) is None


def test_the_preview_is_clean_and_bounded():
    data = CompletionData(projects=("demo-alpha",))
    assert preview_of("/new demo-alpha", data) == RUNNING + "/new --project demo-alpha"
    assert preview_of("/new --project demo-alpha", data) == ""
    assert preview_of("hola /new demo-alpha", data) == ""
    long_line = preview_of('/sk x "' + "a\x1b[31m" * 400 + '"', data)
    assert len(long_line) <= tui_module.PREVIEW_MAX and "\x1b" not in long_line


async def test_programmatic_values_open_no_list(tmp_path):
    """The palette's insert opens the list on purpose; a value set by the program does not."""
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        prompt.value = "/s"
        await pilot.pause(0.1)
        assert not listing.showing
        prompt.value = ""
        await tui.send(pilot, "/exit")
    assert isinstance(prompt, Input)


async def test_keys_written_in_one_go_still_open_the_list(tmp_path):
    """A terminal delivers a burst of keys before the first `Changed` is handled (found at a
    real terminal, task 4.8): the list follows the last of them."""
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        for char in "/st":  # three edits in one step of the screen's loop
            prompt.insert_text_at_cursor(char)
        await pilot.pause(0.1)
        assert prompt.value == "/st"
        assert listing.showing and listing.items[0].insert == "/status"
        await pilot.press("escape")
        prompt.value = ""
        await tui.send(pilot, "/exit")


async def test_tab_after_keys_not_yet_seen_by_the_list_completes_what_is_typed(tmp_path):
    """Tab behind keys of the same write (task 4.8): the list on the screen is for older text,
    so Tab computes it again for the text typed, never takes the stale top row."""
    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press(*"/skill ")
        await tui.until(pilot, lambda: listing.showing)
        assert listing.items[0].insert == "demo-echo "  # the stale top row
        for char in "demo-j":
            prompt.insert_text_at_cursor(char)  # no Changed handled yet
        prompt.action_complete()
        assert prompt.value == "/skill demo-json "
        await pilot.press("escape")
        prompt.value = ""
        await tui.send(pilot, "/exit")


# -- independent review (2026-11-27): a stuck listing, a stale Enter --------------------------

EXIT_SCRIPT = r"""
import asyncio, sys, threading, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from harness.shell import tui as tui_module
from harness.shell.completion import Listing
stuck = threading.Event()
def blocked(word, **kwargs):
    stuck.wait(30)  # a dead network folder
    return Listing()
tui_module.list_folder = blocked
from tests.tui_support import SIZE, Tui

async def main():
    tui = Tui(Path(sys.argv[2]))
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        await pilot.press(*"/file a")
        await pilot.pause(0.3)
        await tui.send(pilot, "/exit")
    print("closed", flush=True)

started = time.monotonic()
asyncio.run(main())
print(f"exit {time.monotonic() - started:.2f}", flush=True)
"""


def test_leaving_does_not_wait_for_a_stuck_folder_listing(tmp_path):
    """A listing blocked on a dead folder must not hold the exit: `asyncio.run` waits for the
    threads of its default executor, where Textual's thread workers run (measured 8.87 s with
    a listing of 8 s before the fix)."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    started = time.monotonic()
    done = subprocess.run([sys.executable, "-c", EXIT_SCRIPT, str(repo), str(data_dir)],
                          capture_output=True, text=True, timeout=60, cwd=tmp_path)
    took = time.monotonic() - started
    assert "closed" in done.stdout, done.stderr[-2000:]
    assert took < 20, f"the exit waited {took:.1f} s for the listing (it blocks 30 s)"


async def test_keys_with_a_stuck_listing_keep_typing_and_bound_the_threads(tmp_path,
                                                                           monkeypatch):
    stuck = threading.Event()
    started: list[str] = []

    def blocked(word: str, **kwargs) -> Listing:  # noqa: ANN003
        started.append(word)
        stuck.wait(30)
        return Listing()

    monkeypatch.setattr(tui_module, "list_folder", blocked)
    tui = _skills_tui(tmp_path)
    try:
        async with tui.app.run_test(size=SIZE) as pilot:
            prompt, listing = await _open(tui, pilot)
            before = threading.active_count()
            await pilot.press(*"/file ", *"abcdefghijklmnopqrst")
            await pilot.pause(0.3)
            assert prompt.value == "/file abcdefghijklmnopqrst"  # every key typed
            live = threading.active_count() - before
            assert live <= tui_module.MAX_LISTERS, f"{live} threads for 21 keys"
            assert len(started) <= tui_module.MAX_LISTERS
            stuck.set()  # the folder answers: the newest request is the one listed
            await tui.until(pilot, lambda: started[-1:] == ["abcdefghijklmnopqrst"])
            prompt.value = ""
            await tui.send(pilot, "/exit")
    finally:
        stuck.set()


async def test_enter_after_keys_the_list_has_not_seen_sends_what_is_typed(tmp_path):
    """`e` and Enter in one write after choosing `/status`: Enter must not take the row the
    list chose for `/s`, which would drop the `e` (same class as the Tab of task 4.8)."""
    from textual.events import Key

    tui = _skills_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        prompt, listing = await _open(tui, pilot)
        await pilot.press("/", "s")
        await tui.until(pilot, lambda: listing.showing)
        await pilot.press("down")
        assert listing.chosen() is not None and listing.chosen().insert.startswith("/status")
        prompt.insert_text_at_cursor("e")  # its Changed not handled yet
        event = Key("enter", "\r")
        await prompt._on_key(event)
        assert prompt.value == "/se"  # the e is kept; Enter goes on to send it as typed
        assert not event._no_default_action and not listing.showing
        prompt.value = ""
        await tui.send(pilot, "/exit")
