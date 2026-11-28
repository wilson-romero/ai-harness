"""`/agent` in a conversation (code-mode A3): a plan's results go back to the provider as
data, turn by turn, until a reply without a plan, the cap and its closing turn, a refusal, a
reply that did not complete, a plan the harness stops, or Ctrl+C.

The oracles: the prompts the provider received (exactly N for N turns, in every path), what
the screen showed before each turn, the synthetic server's own `calls.log`, and the rows of
`loop_runs`, `loop_turns`, `plan_runs` and `requests`. Everything is synthetic."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest

from harness.providers.base import ProviderError
from harness.mcp import client
from harness.mcp.audit import args_key
from harness.mcp.client import BASE_ENV_NAMES
from harness.mcp.loop_flow import SEND_FORMAT, SEND_SCOPE
from harness.mcp.plan_run import PLAN_SKILL_NAME
from harness.skills.approvals import Proposal
from harness.providers.mock import MockProvider
from harness.shell.render import FOREIGN_PREFIX
from tests.fixtures.mcp.synthetic_server import CUT_TOKEN, FORGED_NONCE, FORGED_TAIL
from tests.mcp_support import DEFAULT_TOOLS, hang_guard  # noqa: F401
from tests.plan_support import ALPHA, BETA, QUESTION, McpList, plan_reply, rows
from tests.shell_support import CODE, INTERRUPT, ScriptedTerminal, make_conversation

AGENT_LINE = f"/agent {QUESTION}"
AUTO = {**DEFAULT_TOOLS, "get_project_metadata": {**DEFAULT_TOOLS["get_project_metadata"],
                                                   "auto_read": True}}
ON = {"HARNESS_LOOP_PROVIDERS": "mock"}
ECHO = {"id": "e", "server": "synthetic", "tool": "echo_argv", "args": {}}
ERROR = {"id": "x", "server": "synthetic", "tool": "get_project_metadata",
         "args": {"project": "demo-error"}}
FINAL = "Respuesta final sintetica: demo-alpha y demo-beta tienen datos."
SUMMARY = "Resumen sintetico: se leyeron dos proyectos; no queda nada pendiente."
TOKEN = "gh" + "p_" + "S" * 36  # what the synthetic server's demo-error result carries
# What the scripted Mock looks for in each turn's text (the first key found wins, in
# alphabetical order): the closing turn, then the turn number the harness writes.
CLOSING = "turno de cierre, tras"


def turn(k: int) -> str:
    return f"vuelta {k} de"


class LoopMock(MockProvider):
    """The Mock, recording every prompt with its deadline; on a given call (1-based) it can
    hang after sending (an uncertain reply), fail, report its reply read in part, or run a
    hook (Ctrl+C)."""

    def __init__(self, responses: dict, *, synthetic: bool = True, hang: int = 0,
                 fail: int = 0, truncate: int = 0, hook: tuple = (0, None),
                 delay_ms: int = 0) -> None:
        super().__init__(responses=responses, delay_ms=delay_ms)
        self.synthetic_content = synthetic
        self.prompts: list[str] = []
        self.timeouts: list[float] = []
        self.hang, self.fail, self.truncate, self.hook = hang, fail, truncate, hook

    async def ask(self, request, on_sent, *, on_mode=None, events=None) -> str:
        self.prompts.append(request.prompt)
        self.timeouts.append(request.timeout_s)
        number = len(self.prompts)
        self.calls = number - 1  # the Mock's own count, which `super().ask` takes to number
        if number in (self.hook[0], self.hang, self.fail):
            self.calls = number
        if self.hook[0] == number:
            on_sent()
            self.hook[1]()
            await asyncio.sleep(3600)
        if self.hang == number:
            on_sent()
            await asyncio.sleep(3600)
        if self.fail == number:
            on_sent()
            raise ProviderError("the synthetic provider was told to fail")
        text = await super().ask(request, on_sent, on_mode=on_mode)
        if self.truncate == number and events is not None:
            events.truncated()
        return text


@pytest.fixture
def mcp(tmp_path, hang_guard) -> McpList:  # noqa: F811
    return McpList(tmp_path / "mcp", tools=AUTO)


def _run(conn, data_dir, mcp, provider, lines, approvals=(), environ=ON, **options):
    terminal = ScriptedTerminal(list(lines), list(approvals))
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider,
                                           environ=dict(environ), mcp_config=mcp.load,
                                           **options)
    hook = getattr(provider, "hook", (0, None))
    if hook[0] and hook[1] == "interrupt":
        provider.hook = (hook[0], conversation.interrupt)
    asyncio.run(conversation.run())
    return terminal


def _loops(conn) -> list[tuple]:
    return rows(conn, "SELECT status, stop_reason, turns, max_turns, corrections FROM loop_runs "
                      "ORDER BY rowid")


def _turns(conn) -> list[tuple]:
    return rows(conn, "SELECT turn, kind, plan_id IS NOT NULL FROM loop_turns ORDER BY turn")


def _plan_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM plan_runs").fetchone()[0]


def _sent_shown(terminal: ScriptedTerminal) -> list[str]:
    """Each turn's text as the screen showed it, under its harness line, before it went."""
    shown: list[str] = []
    lines = terminal.shown
    for i, line in enumerate(lines):
        if re.match(r"loop \S+: (turn \d+ of \d+|closing turn \(.*\)): sending \d+ characters "
                    r"to mock; exactly this text, nothing else:$", line):
            body = []
            for row in lines[i + 1:]:
                if not row.startswith(FOREIGN_PREFIX.rstrip()):
                    break
                body.append(row[len(FOREIGN_PREFIX):])
            shown.append("\n".join(body))
    return shown


THREE = {turn(1): plan_reply(ALPHA), turn(2): plan_reply(BETA), turn(3): FINAL}


# -- the environment the processes start from ----------------------------------------------------


def test_a_test_s_settings_reach_the_processes_over_a_full_environment(conn, data_dir, mcp,
                                                                       monkeypatch):
    """Windows run of 02b2c09: the tests handed the conversation `{"HARNESS_LOOP_PROVIDERS":
    "mock"}` alone, so the MCP session process and the server started without SYSTEMROOT, PATH
    or TEMP, and on Windows a Python child without them fails at its first socket (WinError
    10106). Through `make_conversation`, as every test and the loop demo build one: each base
    name this process has reaches both, and the test's own setting still applies."""
    sessions: list[dict] = []
    servers: list[dict] = []
    start, build = client._create_platform_compatible_process, client.build_server_env

    async def recording_start(**options):
        sessions.append(dict(options["env"]))
        return await start(**options)

    def recording_build(entry, environ):
        servers.append(build(entry, environ))
        return servers[-1]

    monkeypatch.setattr(client, "_create_platform_compatible_process", recording_start)
    monkeypatch.setattr(client, "build_server_env", recording_build)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): FINAL})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert _loops(conn) == [("completed", "answer", 2, 5, 0)]  # ON applied: the loop ran
    present = {name: os.environ[name] for name in BASE_ENV_NAMES if name in os.environ}
    assert present and sessions and servers
    for what, envs in (("session process", sessions), ("server", servers)):
        for env in envs:
            missing = sorted(name for name in present if env.get(name) != present[name])
            assert not missing, f"the {what} started without {missing}"


# -- the three turns -----------------------------------------------------------------------------


def test_three_turns_two_reads_by_rule_and_an_answer(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE, "/status"])
    assert len(provider.prompts) == provider.calls == 3  # exactly N calls for N turns
    assert terminal.questions == []  # every plan was reads by rule: no box
    assert [line.split()[1] for line in mcp.calls()] == ["get_project_metadata"] * 2
    assert _loops(conn) == [("completed", "answer", 3, 5, 0)]
    assert _turns(conn) == [(1, "question", 0), (2, "results", 1), (3, "results", 1)]
    # Each turn is its own request, recorded with its turn and loop.
    linked = rows(conn, "SELECT t.turn, r.status FROM loop_turns t JOIN requests r "
                        "ON r.request_id = t.request_id ORDER BY t.turn")
    assert linked == [(1, "completed"), (2, "completed"), (3, "completed")]
    assert "Demo Alpha" in provider.prompts[1] and "Demo Beta" in provider.prompts[2]
    assert "Demo Beta" not in provider.prompts[1]
    assert FINAL in terminal.text
    assert re.search(r"loop \S+: completed \(answer\) after 3 send\(s\) to mock", terminal.text)
    assert "loop: completed (answer), 3 send(s)" in terminal.text  # /status


def test_what_is_sent_is_exactly_what_was_shown(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert _sent_shown(terminal) == provider.prompts[1:]
    key = args_key(data_dir)
    for (number, sent, digest) in rows(conn, "SELECT turn, sent_bytes, sent_hmac FROM loop_turns "
                                             "WHERE turn > 1 ORDER BY turn"):
        prompt = provider.prompts[number - 1].encode()
        assert sent == len(prompt)
        assert digest == hmac.new(key, prompt, hashlib.sha256).hexdigest()


def test_every_turn_has_its_own_nonce_and_marker(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    nonces = [re.search(r'"nonce" vale "([0-9a-f]{16})"', p).group(1) for p in provider.prompts]
    markers = [re.search(r"<<<RESULTADOS ([0-9a-f]{16})", p).group(1)
               for p in provider.prompts[1:]]
    assert len(set(nonces + markers)) == 5
    for prompt in provider.prompts[1:]:
        closed = prompt.index("RESULTADOS " + re.search(r"<<<RESULTADOS (\w+)", prompt).group(1)
                              + ">>>")
        assert re.search(r'"nonce" vale "[0-9a-f]{16}"', prompt).start() > closed


def test_a_turn_uses_the_session_s_mode_and_its_deadline(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    _run(conn, data_dir, mcp, provider, ["/mode deep", AGENT_LINE], timeout_s=5,
         deep_timeout_s=7)
    assert [str(mode) for mode in provider.modes] == ["deep"] * 3
    assert provider.timeouts == [7, 7, 7]


def test_mode_never_starts_a_loop(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    _run(conn, data_dir, mcp, provider, ["/mode deep", "/mode", "/status"])
    assert provider.calls == 0 and _loops(conn) == []


# -- the cap and the closing turn ----------------------------------------------------------------


def test_the_cap_then_one_closing_turn_whose_reply_is_never_read(conn, data_dir, mcp):
    always = {turn(1): plan_reply(ALPHA), turn(2): plan_reply(BETA),
              CLOSING: SUMMARY + "\n\n" + plan_reply(ALPHA, nonce="0123456789abcdef")}
    provider = LoopMock(always)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE],
                    environ={**ON, "HARNESS_LOOP_MAX_TURNS": "2"})
    assert provider.calls == 3  # two turns and the closing one
    closing = provider.prompts[2]
    assert closing.startswith("Instrucciones del harness (turno de cierre, tras 2 vueltas")
    assert "Reglas del plan" not in closing and "synthetic.echo_env" not in closing
    assert "Demo Beta" in closing  # the last plan's results
    assert _plan_count(conn) == 2 and len(mcp.calls()) == 2  # the closing plan never ran
    assert _loops(conn) == [("completed", "cap", 3, 2, 0)]
    assert _turns(conn)[-1] == (3, "closing", 1)
    assert SUMMARY in terminal.text
    assert "the closing turn's reply is the summary; it is never read for a plan" in terminal.text


def test_a_cap_of_one_asks_once_and_closes(conn, data_dir, mcp):
    provider = LoopMock({turn(1): plan_reply(ALPHA), CLOSING: SUMMARY})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE],
         environ={**ON, "HARNESS_LOOP_MAX_TURNS": "1"})
    assert provider.calls == 2 and _loops(conn) == [("completed", "cap", 2, 1, 0)]


@pytest.mark.parametrize("raw", ["0", "11", "dos"])
def test_a_wrong_cap_sends_nothing(conn, data_dir, mcp, raw):
    provider = LoopMock(THREE)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE],
                    environ={**ON, "HARNESS_LOOP_MAX_TURNS": raw})
    assert provider.calls == 0 and _loops(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    assert "HARNESS_LOOP_MAX_TURNS must be a whole number from 1 to 10" in terminal.text


# -- refusals ------------------------------------------------------------------------------------


def test_a_refused_plan_s_reason_goes_back_once(conn, data_dir, mcp):
    provider = LoopMock({turn(1): plan_reply(ALPHA, nonce="0000000000000000"),
                         turn(2): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2
    assert "Motivo: nonce_mismatch" in provider.prompts[1]
    assert "RESULTADOS" not in provider.prompts[1]
    assert "plan refused: nonce_mismatch" in terminal.text
    assert _loops(conn) == [("completed", "answer", 2, 5, 1)]
    assert _turns(conn) == [(1, "question", 0), (2, "correction", 0)]
    assert mcp.starts() == 0


def test_a_second_refusal_stops_the_loop(conn, data_dir, mcp):
    wrong = plan_reply(ALPHA, nonce="0000000000000000")
    provider = LoopMock({turn(1): wrong, turn(2): wrong, turn(3): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2 and _loops(conn) == [("stopped", "refused", 2, 5, 1)]
    assert "a second refused plan stops the loop; nothing more is sent" in terminal.text


def test_a_refusal_on_the_last_turn_goes_to_the_closing_turn(conn, data_dir, mcp):
    provider = LoopMock({turn(1): plan_reply(ALPHA, nonce="0000000000000000"),
                         CLOSING: SUMMARY})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE],
         environ={**ON, "HARNESS_LOOP_MAX_TURNS": "1"})
    assert provider.calls == 2 and "Motivo: nonce_mismatch" in provider.prompts[1]
    assert _loops(conn) == [("completed", "cap", 2, 1, 0)]


# -- replies that did not complete ---------------------------------------------------------------


@pytest.mark.parametrize("how, status", [("hang", "uncertain"), ("fail", "failed"),
                                         ("truncate", "completed")])
def test_a_reply_that_did_not_complete_whole_stops_the_loop_unread(conn, data_dir, mcp, how,
                                                                   status):
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): plan_reply(BETA)}, **{how: 2})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE], timeout_s=0.5)
    assert provider.calls == 2  # never resent
    assert _plan_count(conn) == 1 and len(mcp.calls()) == 1  # turn 2's plan never read
    reason = "reply_truncated" if how == "truncate" else "reply_not_completed"
    assert _loops(conn) == [("stopped", reason, 2, 5, 0)]
    assert statuses_of_turns(conn) == ["completed", status]
    assert "the loop stops" in terminal.text


@pytest.mark.parametrize("status", ["uncertain", "failed", "timeout"])
def test_a_reply_not_completed_is_never_read_even_with_a_valid_plan_in_it(conn, data_dir, mcp,
                                                                          monkeypatch, status):
    """Defence in depth: whatever text comes with a reply that did not complete, it is never
    read for a plan (the service gives none today; a provider might)."""
    from harness.core.contracts import RequestStatus
    from harness.core.service import SessionService

    real = SessionService.ask_loop_turn

    async def with_text(self, *args, **kwargs):
        response = await real(self, *args, **kwargs)
        return response.model_copy(update={"status": RequestStatus(status),
                                           "text": plan_reply(BETA)})

    monkeypatch.setattr(SessionService, "ask_loop_turn", with_text)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): plan_reply(BETA)})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2 and _plan_count(conn) == 1 and len(mcp.calls()) == 1
    assert _loops(conn) == [("stopped", "reply_not_completed", 2, 5, 0)]


def statuses_of_turns(conn) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT r.status FROM loop_turns t JOIN requests r ON r.request_id = t.request_id "
        "ORDER BY t.turn")]


# -- what a plan's end does to the loop ----------------------------------------------------------


def test_a_failed_step_goes_back_as_data(conn, data_dir, mcp):
    provider = LoopMock({turn(1): plan_reply(ERROR), turn(2): FINAL})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2
    sent = provider.prompts[1]
    assert "failed (tool_error)" in sent and "fallo sintetico" in sent
    assert TOKEN not in sent and "[REDACTED:github]" in sent and "\x1b" not in sent
    assert _loops(conn) == [("completed", "answer", 2, 5, 0)]


def test_a_plan_that_is_not_by_rule_asks_the_box_every_turn(conn, data_dir, mcp):
    provider = LoopMock({turn(1): plan_reply(ECHO), turn(2): plan_reply(ECHO, BETA),
                         turn(3): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE], approvals=[CODE, CODE])
    assert len(terminal.questions) == 2 and provider.calls == 3
    assert "sent back to mock as data in the next turn of this /agent loop" in terminal.text
    assert _loops(conn) == [("completed", "answer", 3, 5, 0)]
    assert rows(conn, "SELECT means FROM plan_runs ORDER BY rowid") == [("code",), ("code",)]


@pytest.mark.parametrize("answers", [[None], ["n", "reject"]], ids=["undecided", "rejected"])
def test_a_plan_not_approved_stops_the_loop(conn, data_dir, mcp, answers):
    provider = LoopMock({turn(1): plan_reply(ECHO), turn(2): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE], approvals=answers)
    assert provider.calls == 1 and mcp.starts() == 0
    assert _loops(conn) == [("stopped", "not_approved", 1, 5, 0)]
    assert "the plan was not approved; the loop stops and nothing more is sent" in terminal.text


def test_a_plan_the_harness_stops_stops_the_loop(conn, data_dir, mcp, monkeypatch):
    import harness.mcp.plan_flow as flow

    real = flow.execute_plan

    def changed(data_dir_, approved, load, environ, **kwargs):
        mcp.write("ok", tools=AUTO, call=6)  # another call deadline
        return real(data_dir_, approved, load, environ, **kwargs)

    monkeypatch.setattr(flow, "execute_plan", changed)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 1 and mcp.starts() == 0
    assert _loops(conn) == [("stopped", "plan_stopped", 1, 5, 0)]
    assert "the harness stopped the plan (list_changed)" in terminal.text


def test_ctrl_c_during_a_turn_stops_the_loop_and_sends_nothing_more(conn, data_dir, mcp):
    provider = LoopMock(THREE, hook=(2, "interrupt"))
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2
    assert _loops(conn) == [("interrupted", "interrupted", 2, 5, 0)]
    assert statuses_of_turns(conn) == ["completed", "uncertain"]
    assert "is uncertain: the prompt may have reached the provider; it was not resent" \
        in terminal.text


def test_ctrl_c_while_a_step_runs_stops_the_loop(conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "hang", "hang-call", call=60, tools=AUTO)
    provider = LoopMock(THREE)
    terminal = ScriptedTerminal([AGENT_LINE], [])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider,
                                           environ=dict(ON), mcp_config=mcp.load)

    def press_when_called() -> None:
        limit = time.monotonic() + 30
        while not mcp.calls() and time.monotonic() < limit:
            time.sleep(0.05)
        conversation.interrupt()

    threading.Thread(target=press_when_called, daemon=True).start()
    asyncio.run(conversation.run())
    assert provider.calls == 1  # nothing more is sent
    assert mcp.calls() == ["call get_project_metadata"] and mcp.server.stopped()
    assert _loops(conn) == [("interrupted", "interrupted", 1, 5, 0)]
    assert rows(conn, "SELECT status, error_code FROM plan_runs") == [("interrupted",
                                                                       "interrupted")]


def test_ctrl_c_at_the_box_leaves_it_undecided_and_stops_the_loop(conn, data_dir, mcp):
    # Ctrl+C at the code prompt is an undecided approval, as in /plan (T2-9).
    provider = LoopMock({turn(1): plan_reply(ECHO), turn(2): FINAL})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE], approvals=[INTERRUPT])
    assert provider.calls == 1 and mcp.starts() == 0
    assert rows(conn, "SELECT approval FROM plan_runs") == [("undecided",)]
    assert _loops(conn) == [("stopped", "not_approved", 1, 5, 0)]


def test_box_sends_every_plan_of_the_loop_to_the_box(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    terminal = _run(conn, data_dir, mcp, provider, [f"/agent --box {QUESTION}"],
                    approvals=[CODE, CODE])
    assert len(terminal.questions) == 2 and provider.calls == 3
    assert "running plan:" not in terminal.text
    assert rows(conn, "SELECT means FROM plan_runs ORDER BY rowid") == [("code",), ("code",)]
    assert all("--box" not in prompt for prompt in provider.prompts)
    assert rows(conn, "SELECT content FROM messages WHERE role = 'user' ORDER BY rowid")[0] == (
        AGENT_LINE,)


def test_the_panel_follows_each_phase_with_the_loop_s_seconds(conn, data_dir, mcp,
                                                              monkeypatch):
    from harness.shell.conversation import Conversation

    seen: list[str] = []
    real = Conversation._loop_state

    def spy(self, counter: str) -> None:
        seen.append(counter)
        real(self, counter)

    monkeypatch.setattr(Conversation, "_loop_state", spy)
    provider = LoopMock({turn(1): plan_reply(ALPHA, BETA), turn(2): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE, "/status"])
    patterns = [
        r"turn 1 of 5: sending \d+ characters and waiting for the reply \(\d+ s\)",
        r"turn 1 of 5: plan of 2 step\(s\): approval \(\d+ s\)",
        r"turn 1 of 5: running step 1 of 2 \(\d+ s\)",
        r"turn 1 of 5: running step 2 of 2 \(\d+ s\)",
        r"turn 2 of 5: sending \d+ characters and waiting for the reply \(\d+ s\)",
        r"-",
    ]
    assert len(seen) == len(patterns), seen
    assert all(re.fullmatch(p, s) for p, s in zip(patterns, seen, strict=True)), seen
    assert re.search(r"loop: completed \(answer\), 2 send\(s\), done in \d+ s", terminal.text)


# -- hostile results -----------------------------------------------------------------------------


def test_a_hostile_result_stays_inside_its_block(conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "forge", "forge-data", tools=AUTO)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): FINAL})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    sent = provider.prompts[1]
    marker = re.search(r"^<<<RESULTADOS ([0-9a-f]{16})$", sent, re.M).group(1)
    lines = sent.split("\n")
    opened = lines.index(f"<<<RESULTADOS {marker}")
    closed = lines.index(f"RESULTADOS {marker}>>>")
    inside = lines[opened + 1:closed]
    assert all(line.startswith(("| ", "--- ")) for line in inside)
    assert sum(line.startswith("--- ") for line in inside) == 2  # the header, the omission
    assert not any(("<<<" in line or ">>>" in line) for line in inside)
    assert "\x1b" not in sent and "\x07" not in sent
    assert lines.count(f"<<<RESULTADOS {marker}") == 1 and \
        lines.count(f"RESULTADOS {marker}>>>") == 1
    assert [line for line in lines if line.startswith("Instrucciones del harness")] == [lines[0]]
    assert inside[-1].endswith(FORGED_TAIL)  # the tail is kept, the middle cut and marked
    assert "[omitidos por el harness:" in inside[-2] or any("[omitidos" in l for l in inside)
    assert FORGED_NONCE not in "\n".join(lines[closed:])
    assert len(sent) < 28_000
    assert _plan_count(conn) == 1 and len(mcp.calls()) == 1


def test_a_credential_at_the_cut_is_masked_alike_on_screen_and_in_what_is_sent(
        conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "cut", "cut-credential", tools=AUTO)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2
    assert CUT_TOKEN not in provider.prompts[1] and "[REDACTED:github]" in provider.prompts[1]
    assert _sent_shown(terminal) == provider.prompts[1:]  # the screen shows these bytes


def test_a_nonce_injected_by_a_result_is_refused(conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    # The scripted Mock fills its plan with the first nonce it finds in the text it gets:
    # the forged one, inside the result, comes before the turn's own.
    mcp = McpList(tmp_path / "forge", "forge-data", tools=AUTO)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): plan_reply(ALPHA),
                         turn(3): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert f'"nonce": "{FORGED_NONCE}"' in provider.prompts[1]
    assert "plan refused: nonce_mismatch" in terminal.text
    assert provider.calls == 3 and _plan_count(conn) == 1 and len(mcp.calls()) == 1


def test_a_plan_inside_a_result_is_never_the_model_s(conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "forge", "forge-data", tools=AUTO)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): FINAL})
    _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert "set_project_metadata" in provider.prompts[1]  # it was there, as data
    assert _plan_count(conn) == 1
    assert [line.split()[1] for line in mcp.calls()] == ["get_project_metadata"]
    assert _loops(conn) == [("completed", "answer", 2, 5, 0)]


# -- consent -------------------------------------------------------------------------------------


@pytest.mark.parametrize("environ", [{}, {"HARNESS_LOOP_PROVIDERS": "copilot"},
                                     {"HARNESS_LOOP_PROVIDERS": ""}])
def test_without_consent_nothing_leaves_the_machine(conn, data_dir, mcp, environ):
    provider = LoopMock(THREE)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE], environ=environ)
    assert provider.calls == 0 and mcp.starts() == 0 and _loops(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    assert "HARNESS_LOOP_PROVIDERS does not name mock; nothing was sent" in terminal.text


@pytest.mark.parametrize("short", ["/a", "/ag", "/agen"])
def test_agent_is_typed_in_full(conn, data_dir, mcp, short):
    provider = LoopMock(THREE)
    terminal = _run(conn, data_dir, mcp, provider, [f"{short} {QUESTION}"])
    assert provider.calls == 0 and _loops(conn) == []
    assert "running: /agent" not in terminal.text


def test_with_the_loop_allowed_plan_still_sends_nothing_back(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    terminal = _run(conn, data_dir, mcp, provider, [f"/plan {QUESTION} vuelta 1 de"])
    assert provider.calls == 1 and _loops(conn) == []
    assert "the results are only on this screen, nothing was sent to the provider" \
        in terminal.text


def _send_box(terminal: ScriptedTerminal) -> tuple[str, str]:
    """The send approval's loop id and hash, as the box showed them."""
    text = terminal.text
    loop_id = re.search(r"  loop:     (\S+), turn", text).group(1)
    shown = re.search(r"Send approval requested\n(?:.*\n)*?  hash:     ([0-9a-f]{64})", text)
    return loop_id, shown.group(1)


def _send_hash(conn, loop_id: str, text: str) -> str:
    session = conn.execute("SELECT session_id FROM loop_runs").fetchone()[0]
    return Proposal(scope=SEND_SCOPE, session_id=session, run_id=loop_id, step="2",
                    skill_name=PLAN_SKILL_NAME, skill_version=SEND_FORMAT,
                    skill_sha256=hashlib.sha256(text.encode()).hexdigest(), target="mock",
                    content=text).sha256


def test_a_provider_outside_the_machine_asks_once_with_the_exact_text(conn, data_dir, mcp):
    provider = LoopMock(THREE, synthetic=False)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE], approvals=[CODE])
    # One box only, before the first results; the later turn goes without asking again.
    assert len(terminal.questions) == 1 and provider.calls == 3
    assert terminal.text.count("Send approval requested") == 1
    box = terminal.shown.index("Send approval requested")
    first_send = next(i for i, line in enumerate(terminal.shown) if ": sending " in line)
    assert box < first_send
    loop_id, shown_hash = _send_box(terminal)
    assert shown_hash == _send_hash(conn, loop_id, provider.prompts[1])  # bound to what went
    assert _sent_shown(terminal) == provider.prompts[1:]
    assert _loops(conn) == [("completed", "answer", 3, 5, 0)]
    assert rows(conn, "SELECT outcome FROM audit_events WHERE event_type = "
                      "'loop.send_approval'") == [("granted",)]
    # Nothing of what the reads returned, or of the turns, is stored.
    for table, column in [("messages", "content"), ("audit_events", "detail")]:
        for (value,) in conn.execute(f"SELECT {column} FROM {table}"):  # noqa: S608
            assert value is None or ("Demo Alpha" not in value and "RESULTADOS" not in value)


@pytest.mark.parametrize("answers", [[None], ["n", "reject"], [INTERRUPT]],
                         ids=["undecided", "rejected", "ctrl-c"])
def test_a_send_not_approved_sends_nothing_and_stops(conn, data_dir, mcp, answers):
    provider = LoopMock(THREE, synthetic=False)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE], approvals=answers)
    assert provider.calls == 1 and len(provider.prompts) == 1
    assert mcp.calls() == ["call get_project_metadata"]  # the read ran; its result stayed here
    assert _loops(conn) == [("stopped", "send_not_approved", 1, 5, 0)]
    assert "the results were not approved to be sent" in terminal.text
    assert ": sending " not in terminal.text
    assert "this conversation now holds" not in terminal.text


def test_a_send_approved_after_it_expired_sends_nothing(conn, data_dir, mcp):
    times = [datetime(2026, 11, 28, 12, 0, tzinfo=UTC)]

    class Late(ScriptedTerminal):
        def ask(self, question):
            times.append(times[-1] + timedelta(seconds=901))  # the person answers late
            return super().ask(question)

    provider = LoopMock(THREE, synthetic=False)
    terminal = Late([AGENT_LINE], [CODE])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider,
                                           environ=dict(ON), mcp_config=mcp.load,
                                           clock=lambda: times[-1])
    asyncio.run(conversation.run())
    assert provider.calls == 1
    assert _loops(conn) == [("stopped", "send_not_approved", 1, 5, 0)]
    assert "(expired); nothing was sent" in terminal.text


def test_a_code_typed_after_ctrl_c_at_the_send_box_grants_nothing(conn, data_dir, mcp):
    """As at the plan's prompt (T2-9): Ctrl+C while the prompt blocks only marks the task
    cancelled; the code typed after it must not let the results go."""

    class Interrupted(ScriptedTerminal):
        def ask(self, question):
            asyncio.current_task().cancel()  # what asyncio.run's handler does on SIGINT
            return super().ask(question)

    provider = LoopMock(THREE, synthetic=False)
    terminal = Interrupted([AGENT_LINE], [CODE])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider,
                                           environ=dict(ON), mcp_config=mcp.load)
    asyncio.run(conversation.run())
    assert provider.calls == 1
    assert _loops(conn) == [("stopped", "send_not_approved", 1, 5, 0)]


def test_a_send_on_a_terminal_that_is_not_interactive_is_never_approved(conn, data_dir, mcp):
    provider = LoopMock(THREE, synthetic=False)
    terminal = ScriptedTerminal([AGENT_LINE], [CODE], interactive=False)
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider,
                                           environ=dict(ON), mcp_config=mcp.load)
    asyncio.run(conversation.run())
    assert provider.calls == 1 and terminal.questions == []
    assert _loops(conn) == [("stopped", "send_not_approved", 1, 5, 0)]


def test_a_correction_needs_no_send_approval(conn, data_dir, mcp):
    # A refusal's reason is the harness's text about the plan, not what a read returned.
    provider = LoopMock({turn(1): plan_reply({**ALPHA, "server": "otro"}), turn(2): FINAL},
                        synthetic=False)
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2 and terminal.questions == []
    assert "a provider outside this machine" in terminal.text


def test_a_synthetic_provider_gets_no_notice(conn, data_dir, mcp):
    terminal = _run(conn, data_dir, mcp, LoopMock(THREE), [AGENT_LINE])
    assert "a provider outside this machine" not in terminal.text
    assert "Send approval requested" not in terminal.text and terminal.questions == []


def test_the_history_keeps_a_label_of_each_turn_never_the_results(conn, data_dir, mcp):
    provider = LoopMock(THREE)
    _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    stored = [row[0] for row in conn.execute(
        "SELECT content FROM messages WHERE role = 'user' ORDER BY rowid")]
    assert stored[0] == AGENT_LINE
    assert all(re.fullmatch(r"/agent loop \S+: turn \d of 5 \(results\)", s) for s in stored[1:])


# -- after a crash -------------------------------------------------------------------------------


def test_a_loop_left_running_is_marked_interrupted_and_never_resumed(conn, data_dir, mcp):
    provider = LoopMock({turn(1): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, ["/status"])
    session = conn.execute("SELECT session_id FROM sessions").fetchone()[0]
    with conn:
        conn.execute("INSERT INTO loop_runs (loop_id, session_id, provider, max_turns, turns, "
                     "corrections, status, created_at) VALUES (?, ?, 'mock', 5, 2, 0, "
                     "'running', '2026-11-27T00:00:00+00:00')", (str(uuid7()), session))
    # Found when the next conversation opens, before any /agent (review of fa6b6d1, 6).
    terminal = _run(conn, data_dir, mcp, provider, [f"/resume {session}", "/status",
                                                    AGENT_LINE, "/status"])
    assert "loop: running" not in terminal.text
    assert "loop: interrupted (abandoned), 2 send(s)\n" in terminal.text
    assert _loops(conn) == [("interrupted", "abandoned", 2, 5, 0),
                            ("completed", "answer", 1, 5, 0)]
    assert provider.calls == 1
    assert re.search(r"loop: completed \(answer\), 1 send\(s\), done in \d+ s\n"
                     r"memory: 0 note\(s\) in the last question\nattachment: -\n"
                     r"> <end of input>\nend of input: leaving the conversation$", terminal.text)


def test_a_loop_s_rows_reject_what_they_must_not_hold(conn):
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("INSERT INTO loop_runs (loop_id, session_id, provider, max_turns, "
                         "turns, corrections, status, created_at) VALUES "
                         "('x', 'nadie', 'mock', 11, 0, 0, 'running', 'now')")


# -- the full screen -----------------------------------------------------------------------------


async def test_the_side_panel_counts_the_turns(tmp_path, mcp):
    from tests.tui_support import SIZE, Tui

    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    provider = LoopMock(THREE, delay_ms=600)
    tui = Tui(data_dir, provider, environ=dict(ON), mcp_config=mcp.load)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, AGENT_LINE)
        await tui.until(pilot, lambda: "turn 2 of 5" in tui.side())
        assert "Loop" in tui.side()
        await tui.until(pilot, lambda: "turn 3 of 5" in tui.side())
        await tui.until(pilot, lambda: "completed (answer), 3 send(s)" in tui.side())
        harness = "\n".join(tui.blocks("harness"))
        assert harness.count("exactly this text, nothing else:") == 2
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert provider.calls == 3


async def test_the_send_box_on_the_full_screen_approves_with_its_button(tmp_path, mcp):
    from textual.widgets import Button

    from tests.tui_support import SIZE, Tui

    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    provider = LoopMock(THREE, synthetic=False)
    tui = Tui(data_dir, provider, environ=dict(ON), mcp_config=mcp.load)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, AGENT_LINE)
        await tui.approval_box(pilot)
        assert "Send approval requested" in tui.screen()
        assert provider.calls == 1  # nothing more is sent while the box is open
        approve = tui.app.screen.query_one("#approve", Button)
        await pilot.press("end")
        await tui.until(pilot, lambda: not approve.disabled)
        await pilot.press("tab", "enter")
        await tui.until(pilot, lambda: "completed (answer), 3 send(s)" in tui.side())
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert provider.calls == 3


def test_a_loop_left_running_is_marked_interrupted_when_the_conversation_opens(conn, data_dir,
                                                                              mcp):
    _run(conn, data_dir, mcp, LoopMock({turn(1): FINAL}), ["/status"])
    session = conn.execute("SELECT session_id FROM sessions").fetchone()[0]
    with conn:
        conn.execute("INSERT INTO loop_runs (loop_id, session_id, provider, max_turns, turns, "
                     "corrections, status, created_at) VALUES (?, ?, 'mock', 5, 1, 0, "
                     "'running', '2026-11-27T00:00:00+00:00')", (str(uuid7()), session))
    terminal = ScriptedTerminal(["/status"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, LoopMock({}),
                                           environ=dict(ON), mcp_config=mcp.load)
    asyncio.run(conversation.run(session_id=session))
    assert "loop: interrupted (abandoned), 1 send(s)\n" in terminal.text
    assert _loops(conn) == [("interrupted", "abandoned", 1, 5, 0)]


# -- reads by rule need bounded arguments inside a loop (A3-12) ---------------------------------

FREE = {**AUTO, "echo_env": {**AUTO["echo_env"], "auto_read": True}}
ECHO_ENV = {"id": "v", "server": "synthetic", "tool": "echo_env", "args": {"name": "DEMO_X"}}


def test_a_read_by_rule_with_a_free_text_argument_asks_the_box_in_a_loop(conn, data_dir,
                                                                        tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "free", tools=FREE)
    provider = LoopMock({turn(1): plan_reply(ALPHA, ECHO_ENV), turn(2): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE], approvals=[CODE])
    assert len(terminal.questions) == 1 and provider.calls == 2
    assert ("why:      step 2 (synthetic.echo_env) takes free text in argument name; inside "
            "/agent, a read runs by rule only when every argument is bounded, so this whole "
            "plan asks you") in terminal.text
    assert rows(conn, "SELECT means FROM plan_runs") == [("code",)]


def test_control_bounded_reads_by_rule_run_without_the_box_in_a_loop(conn, data_dir, mcp):
    terminal = _run(conn, data_dir, mcp, LoopMock(THREE), [AGENT_LINE])
    assert terminal.questions == []
    assert ("allows by rule (auto_read) and whose every argument is bounded (an enum, a "
            "number, a yes/no or a pattern); no approval is asked") in terminal.text
    assert rows(conn, "SELECT means FROM plan_runs") == [("rule",), ("rule",)]


def test_plan_keeps_the_a2_rule_in_a_clean_session(conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "free", tools=FREE)
    provider = LoopMock({QUESTION: plan_reply(ECHO_ENV)})
    terminal = _run(conn, data_dir, mcp, provider, [f"/plan {QUESTION}"])
    assert terminal.questions == [] and rows(conn, "SELECT means FROM plan_runs") == [("rule",)]


# -- after a loop that sent results (A3-13) ------------------------------------------------------


def test_after_results_were_sent_the_session_says_so_and_plan_needs_bounded_args(
        conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "free", tools=FREE)
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): FINAL,
                         QUESTION: plan_reply(ECHO_ENV)})
    terminal = _run(conn, data_dir, mcp, provider,
                    [AGENT_LINE, "/status", f"/plan {QUESTION}", "/new", f"/plan {QUESTION}"],
                    approvals=[CODE])
    text = terminal.text
    notice = "this conversation now holds what the reads returned"
    assert text.count(f"note: {notice}") == 1  # once, after the loop
    assert f"results: {notice}" in text  # and in /status
    # /plan in that session: the box, saying why; after /new: by rule again.
    assert len(terminal.questions) == 1
    assert "in this session, whose conversation already holds tool results (/new starts a " \
        "clean one), a read runs by rule only when every argument is bounded" in text
    assert rows(conn, "SELECT means FROM plan_runs ORDER BY rowid") == [
        ("rule",), ("code",), ("rule",)]


def test_a_loop_that_sent_no_results_leaves_the_session_clean(conn, data_dir, tmp_path,
                                                              hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "free", tools=FREE)
    provider = LoopMock({turn(1): FINAL, QUESTION: plan_reply(ECHO_ENV)})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE, "/status", f"/plan {QUESTION}"])
    assert "this conversation now holds" not in terminal.text
    assert terminal.questions == [] and rows(conn, "SELECT means FROM plan_runs") == [("rule",)]


# -- a json block without this turn's nonce (A3-15) ----------------------------------------------

EXAMPLE = "Respuesta final sintetica. Ejemplo:\n\n```json\n{\"proyecto\": \"demo-alpha\"}\n```\n"


def test_a_json_block_without_the_turn_s_nonce_is_the_answer_in_a_loop(conn, data_dir, mcp):
    provider = LoopMock({turn(1): plan_reply(ALPHA), turn(2): EXAMPLE})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert provider.calls == 2 and _loops(conn) == [("completed", "answer", 2, 5, 0)]
    assert "plan refused" not in terminal.text and _plan_count(conn) == 1


def test_a_block_with_another_nonce_is_still_refused_in_a_loop(conn, data_dir, mcp):
    stale = plan_reply(BETA, nonce="0123456789abcdef")
    provider = LoopMock({turn(1): stale, turn(2): FINAL})
    terminal = _run(conn, data_dir, mcp, provider, [AGENT_LINE])
    assert "plan refused: nonce_mismatch" in terminal.text and mcp.starts() == 0
    assert _loops(conn) == [("completed", "answer", 2, 5, 1)]  # one correction, then the answer


def test_control_plan_still_refuses_a_block_without_a_nonce(conn, data_dir, mcp):
    provider = LoopMock({QUESTION: EXAMPLE})
    terminal = _run(conn, data_dir, mcp, provider, [f"/plan {QUESTION}"])
    assert "nonce_missing" in terminal.text and mcp.starts() == 0


# -- the loop's tables in their own migration (review of fa6b6d1, 5) ---------------------------


def _database_at(tmp_path, data_dir, version_file: str | None):
    from harness.storage.database import MIGRATIONS_DIR, connect, migrate
    folder = tmp_path / "migrations-old"
    folder.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("0[01][0-9]_*.sql")):
        if int(path.name[:3]) <= 10:
            (folder / path.name).write_text(path.read_text("utf-8"), "utf-8")
    if version_file is not None:  # an earlier build of this branch: 010 carried the loops
        (folder / "010_plan_rules.sql").write_text(version_file, "utf-8")
    conn = connect(data_dir)
    assert migrate(conn, folder) == list(range(1, 11))
    return conn, migrate


def test_a_database_at_the_a2_010_gets_the_loop_tables_from_013(tmp_path):
    data_dir = tmp_path / "d"
    data_dir.mkdir()
    conn, migrate = _database_at(tmp_path, data_dir, None)
    session = "0190a000-0000-7000-8000-000000000001"
    with pytest.raises(sqlite3.OperationalError):  # what the review found: no loop_runs
        conn.execute("SELECT 1 FROM loop_runs").fetchone()
    assert migrate(conn) == [13]
    from harness.mcp.loop_flow import last_loop
    assert last_loop(conn, UUID(session)) == "-"
    conn.close()


def test_a_database_whose_010_held_the_loops_ends_with_the_same_schema(tmp_path):
    from harness.storage.database import MIGRATIONS_DIR
    # An earlier build of this branch: A2's 010 with the loop tables after it, as 013 has them.
    loops = (MIGRATIONS_DIR / "013_loops.sql").read_text("utf-8")
    loops = loops[loops.index("CREATE TABLE loop_runs"):]
    earlier = (MIGRATIONS_DIR / "010_plan_rules.sql").read_text("utf-8") + "\n" + loops
    data_dir = tmp_path / "d"
    data_dir.mkdir()
    conn, migrate = _database_at(tmp_path, data_dir, earlier)
    assert "loop_runs" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert migrate(conn) == [13]
    fresh_dir = tmp_path / "f"
    fresh_dir.mkdir()
    from harness.storage.database import connect
    fresh = connect(fresh_dir)
    migrate(fresh)
    schema = "SELECT name, sql FROM sqlite_master WHERE name LIKE 'loop%' ORDER BY name"
    assert conn.execute(schema).fetchall() == fresh.execute(schema).fetchall()
    conn.close()
    fresh.close()
