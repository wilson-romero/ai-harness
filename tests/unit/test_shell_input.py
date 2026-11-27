"""Whatever a person types, a command with a bad argument prints an error and the conversation
goes on (review 2026-11-25): no traceback, no exit, nothing sent."""

from __future__ import annotations

import pytest

from harness.shell.parser import COMMANDS
from tests.shell_support import ScriptedTerminal, make_conversation

# Arguments that once escaped as exceptions (`²` to int(), a NUL to os.lstat) and their kin.
HOSTILE = ["²", "٣", "a\x00b", "\udcff", "-1", "0", "9" * 30, "../x", "--x", "=", "a=", "=a",
           "--file", "x" * 5000, "​", "CON", "--project", "\x1b[31m"]
TEMPLATES = ["/new {}", "/new --project {}", "/resume {}", "/memory {}", "/skill {}",
             "/skill demo-echo {}", "/skill demo-echo --file {}", "/skill demo-echo --file text={}",
             "/skill demo-echo text={}", "/file {}", "/mode {}"]


def test_every_command_that_takes_arguments_is_covered():
    taking = {name for name, (least, most) in COMMANDS.items() if most is None or most > 0}
    assert taking == {template.split()[0][1:] for template in TEMPLATES}


@pytest.mark.parametrize("template", TEMPLATES)
async def test_a_bad_argument_prints_an_error_and_the_conversation_goes_on(conn, data_dir, vault,
                                                                           template):
    lines = ["/sessions"]
    for value in HOSTILE:
        quoted = '"' + value.replace('"', "") + '"'
        lines += [template.format(quoted), "/status"]
    lines.append("/exit")
    terminal = ScriptedTerminal(lines)
    conversation, _, provider = make_conversation(conn, data_dir, terminal, vault=vault)
    assert await conversation.run(None, "demo-alpha") == 0
    assert sum(line.startswith("last request:") for line in terminal.shown) == len(HOSTILE)
    assert "leaving the conversation" in terminal.shown
    if not template.startswith("/skill"):
        assert provider.calls == 0


@pytest.mark.parametrize(("line", "said"), [
    ("/resume ²", "/resume takes a number from 1 to"),
    ("/file a\x00b", "cannot be read"),
    ("/skill demo-echo --file text=a\x00b", "cannot be read"),
])
async def test_the_inputs_the_review_found(conn, data_dir, line, said):
    terminal = ScriptedTerminal(["/sessions", line, "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    assert await conversation.run() == 0
    assert any(row.startswith("error:") and said in row for row in terminal.shown)
