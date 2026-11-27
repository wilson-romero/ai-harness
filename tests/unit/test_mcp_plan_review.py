"""The four findings of the independent review of `feature/code-mode` @ 38683ac (tasks 2.6-2.9).

1. A number out of float range raised instead of refusing; `read_plan` must always answer.
2. A string the approval display would change (U+2028, a newline, a tab) was accepted.
3. The nonce could appear in a second, unfenced copy of a plan the person would see rendered.
4. The limits were not pinned with literal numbers at their boundaries.
"""

from __future__ import annotations

import json
import random

import pytest

from harness.mcp.plan import (
    MAX_PLAN_BYTES,
    MAX_PLAN_DEPTH,
    MAX_REPLY_CHARS,
    MAX_STEPS,
    REFUSAL_REASONS,
    NoPlan,
    Plan,
    Refusal,
    read_plan,
    read_plan_reply,
    string_refusal,
)
from harness.skills.approvals import normalise_content
from harness.text.safe_text import safe_foreign_line, terminal_safe
from tests.unit.test_mcp_plan import CONFIG, NONCE, TWO_READS, fenced, plan, reply, step


def read(text: str):
    return read_plan(text, nonce=NONCE, config=CONFIG)


def reason(text: str) -> str:
    result = read(text)
    assert isinstance(result, Refusal), result
    return result.reason


def with_args(raw_args: str, tool: str = "get_project_metadata") -> str:
    """A one-step plan whose `args` object is written as given, unparsed."""
    return fenced('{"format":"ai-harness/plan/1","nonce":"%s","steps":[{"id":"a",'
                  '"server":"synthetic","tool":"%s","args":%s}]}' % (NONCE, tool, raw_args))


# -- finding 1: numbers out of range, and never an exception -------------------------------------


@pytest.mark.parametrize("raw_args", [
    '{"project":1e400}',
    '{"project":-1e400}',
    '{"undeclared":1e400}',
    '{"project":"demo-alpha","limit":1E+999}',
])
def test_a_number_out_of_range_is_refused_as_not_finite(raw_args):
    assert reason(with_args(raw_args)) == "not_finite"


def test_a_raw_lone_surrogate_in_the_block_is_refused():
    body = json.dumps(plan(step("a", "echo_env", name="X"))).replace('"X"', '"\ud800"')
    assert reason(fenced(body)) == "invisible_character"


def test_a_raw_lone_surrogate_in_the_prose_does_not_stop_reading():
    assert isinstance(read("Note \ud800 here.\n\n" + fenced(json.dumps(TWO_READS))), Plan)


HOSTILE = ["1e400", "-1e400", "NaN", "Infinity", "\ud800", "\\ud800", "\u2028", "\x00", "\ufeff",
           "\r", "\n", "\n> ", "```", "```json\n", "~~~", "{", "}", "[", "]", '"', ",", ":",
           NONCE, "$ref", "9" * 5000, "\\u0000", "null", "true", "{}", "[]", "\t", "\u202e",
           '"args"', '"steps"', '"nonce"', "-", "0", "1.0", "\\", "<!--", "-->"]


def test_reading_never_raises_on_hostile_text():
    """Fuzz-style guard: seeded mutations of a valid reply. The answer is always a Reading."""
    rng = random.Random(38683)
    base = reply(TWO_READS)
    for _ in range(3000):
        text = base
        for _ in range(rng.randint(1, 6)):
            at = rng.randrange(len(text) + 1)
            choice = rng.random()
            if choice < 0.6:
                text = text[:at] + rng.choice(HOSTILE) + text[at:]
            elif choice < 0.8:
                text = text[:at] + text[at + rng.randint(1, 20):]
            else:
                end = min(len(text), at + rng.randint(1, 40))
                text = text[:end] + text[at:end] + text[end:]
        result = read(text)
        assert isinstance(result, (Plan, Refusal, NoPlan))
        if isinstance(result, Refusal):
            assert result.reason in REFUSAL_REASONS


def test_a_reply_object_with_hostile_text_never_raises():
    from tests.unit.test_mcp_plan import response  # the same reply builder
    from harness.core.contracts import RequestStatus

    built = response(RequestStatus.COMPLETED).model_copy(update={"text": with_args(
        '{"project":1e400}')})
    assert read_plan_reply(built, nonce=NONCE, config=CONFIG).reason == "not_finite"


# -- finding 2: what is accepted is shown unchanged -----------------------------------------------


@pytest.mark.parametrize("value", ["a\u2028b", "a\u2029b", "a\nb", "a\tb", "a\x85b", "a\x1bb"])
def test_a_string_the_display_would_change_is_refused(value):
    assert reason(reply(plan(step("a", "echo_env", name=value)))) == "invisible_character"


def test_a_key_the_display_would_change_is_refused():
    body = plan({"id": "a", "server": "synthetic", "tool": "echo_env",
                 "args": {"na\u2028me": "x"}})
    assert reason(reply(body)) == "invisible_character"


def test_an_invisible_character_is_reported_before_the_other_text_reasons():
    """The documented order (module docstring, step 4): invisible, then NFC, then credential."""
    assert string_refusal("e\u0301\u200b") == "invisible_character"
    assert string_refusal("e\u0301") == "not_nfc"


def _code_points():
    yield from range(0x10000)
    yield from range(0x10000, 0x110000, 97)
    yield 0x10FFFF


def test_every_accepted_character_is_shown_unchanged():
    """All of the BMP and a sample of the astral planes: accepted by D5 => unchanged by the
    three display paths (the approval content, one terminal line, a foreign line)."""
    shown_differently = []
    for code in _code_points():
        text = "a" + chr(code) + "b"
        if string_refusal(text) is not None:
            continue
        if (normalise_content(text) != text or terminal_safe(text) != text
                or safe_foreign_line(text).text != text):
            shown_differently.append(f"U+{code:04X}")
    assert shown_differently == []


# -- finding 3: the nonce appears once, inside the chosen block -----------------------------------

REAL = fenced(json.dumps(TWO_READS))
PLAN_B = json.dumps(plan(step("z", "env_names")))


@pytest.mark.parametrize("case, text, expected", [
    ("a quoted second plan", "> ```json\n> " + PLAN_B + "\n> ```\n\n" + REAL, "nonce_elsewhere"),
    ("an HTML comment on one line", "<!-- " + PLAN_B + " -->\n\n" + REAL, "nonce_elsewhere"),
    ("a fenced block inside an HTML comment",
     "<!--\n```json\n" + PLAN_B + "\n```\n-->\n\n" + REAL, "too_many_blocks"),
    ("a details element", "<details><summary>more</summary>\n\n" + PLAN_B +
     "\n\n</details>\n\n" + REAL, "nonce_elsewhere"),
    ("a list item", "- first: " + PLAN_B + "\n\n" + REAL, "nonce_elsewhere"),
    ("a fenced block in a list item", "1. Plan:\n\n   ```json\n   " + PLAN_B + "\n   ```\n\n"
     + REAL, "too_many_blocks"),
    ("the nonce in the prose", "Nonce " + NONCE + ".\n\n" + REAL, "nonce_elsewhere"),
    ("the nonce after the block", REAL + "\n\n(" + NONCE + ")", "nonce_elsewhere"),
    ("the nonce twice inside the block", reply(plan(step("a", "echo_env", name=NONCE))),
     "nonce_elsewhere"),
], ids=lambda value: value if isinstance(value, str) and len(value) < 40 else None)
def test_the_nonce_appears_once_inside_the_chosen_block(case, text, expected):
    assert reason(text) == expected


# -- finding 4: the limits, as literal numbers, at their boundaries -------------------------------


def test_the_limits_are_the_documented_numbers():
    assert (MAX_PLAN_BYTES, MAX_PLAN_DEPTH, MAX_STEPS, MAX_REPLY_CHARS) == (
        16 * 1024, 6, 10, 200_000)


def test_depth_six_is_read_and_seven_is_refused():
    # plan 1, steps 2, step 3, args 4, then the value's own levels
    assert reason(with_args('{"name":[[]]}', "echo_env")) == "argument_invalid"  # depth 6
    assert reason(with_args('{"name":[[[]]]}', "echo_env")) == "plan_too_deep"  # depth 7


def test_ten_steps_are_read_and_eleven_are_refused():
    ten = plan(*[step(f"s{i}", project="demo-alpha") for i in range(10)])
    assert isinstance(read(reply(ten)), Plan)
    eleven = plan(*[step(f"s{i}", project="demo-alpha") for i in range(11)])
    assert reason(reply(eleven)) == "too_many_steps"


def _body_of(size: int) -> str:
    body = json.dumps(TWO_READS)
    return body + " " * (size - len(body.encode("utf-8")))


def test_a_plan_of_16384_bytes_is_read_and_16385_is_refused():
    assert len(_body_of(16384).encode("utf-8")) == 16384
    assert isinstance(read(fenced(_body_of(16384))), Plan)
    assert reason(fenced(_body_of(16385))) == "plan_too_large"


def test_a_reply_of_200000_characters_is_read_and_200001_is_refused():
    block = fenced(json.dumps(TWO_READS)) + "\n"
    exact = block + "x" * (200_000 - len(block))
    assert len(exact) == 200_000
    assert isinstance(read(exact), Plan)
    assert reason(exact + "x") == "reply_too_large"


@pytest.mark.parametrize("found", ["xx" + NONCE, NONCE + "xx", NONCE[:-1], NONCE.upper(),
                                   " " + NONCE])
def test_a_nonce_that_only_contains_or_resembles_the_expected_one_is_a_mismatch(found):
    assert reason(reply(plan(nonce=found))) == "nonce_mismatch"


def test_lone_carriage_returns_are_read_as_line_ends():
    assert isinstance(read(reply(TWO_READS).replace("\n", "\r")), Plan)
