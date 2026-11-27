"""Deterministic `validate` rules (skill-engine D6)."""

import json

import pytest

from harness.skills.checks import check
from harness.skills.definition import ValidateStep
from tests.conftest import SECRET_SAMPLES


def _step(**rules) -> ValidateStep:
    return ValidateStep.model_validate({"id": "v", "kind": "validate", "of": "x", **rules})


FIELDS = {
    "title": {"type": "string", "single_line": True, "max_length": 20},
    "kind": {"type": "string", "enum": ["decision", "lesson"]},
    "slug": {"type": "string", "format": "slug", "required": False},
    "date": {"type": "string", "format": "date", "required": False},
    "points": {"type": "string_list", "max_items": 2, "max_length": 10},
    "priority": {"type": "integer", "min": 1, "max": 5},
    "urgent": {"type": "boolean", "required": False},
}
GOOD = {"title": "Cola", "kind": "decision", "points": ["a"], "priority": 3}


def _json_step():
    return _step(format="json", fields=FIELDS)


def test_required_heading_missing():
    step = _step(format="markdown", required_headings=["Resumen", "Preguntas pendientes"])
    result = check(step, "## Resumen\nok\n")
    assert not result.ok and result.error_code == "validation_failed:required_headings:Preguntas pendientes"
    assert check(step, "# resumen \n## PREGUNTAS PENDIENTES ##\n").ok


def test_heading_needs_a_space_and_at_most_six_hashes():
    step = _step(format="markdown", required_headings=["Resumen"])
    assert not check(step, "##Resumen").ok
    assert not check(step, "####### Resumen").ok
    assert not check(step, "texto ## Resumen").ok


def test_size_rules_count_utf8_bytes():
    assert check(_step(format="text", max_bytes=4), "€€").error_code == "validation_failed:max_bytes:-"
    assert check(_step(format="text", min_bytes=3), "ab").error_code == "validation_failed:min_bytes:-"
    assert check(_step(format="text", min_bytes=3, max_bytes=6), "€€").ok


def test_valid_json_is_canonical():
    result = check(_json_step(), json.dumps({"priority": 3, "points": ["a"], "kind": "decision",
                                              "title": "Cola"}))
    assert result.ok
    assert result.output == '{"kind":"decision","points":["a"],"priority":3,"title":"Cola"}'


@pytest.mark.parametrize(
    "change, code",
    [
        ({"extra": 1}, "validation_failed:extra_field:extra"),
        ({"title": 5}, "validation_failed:type:title"),
        ({"priority": "3"}, "validation_failed:type:priority"),
        ({"priority": True}, "validation_failed:type:priority"),
        ({"priority": 9}, "validation_failed:max:priority"),
        ({"title": "a\nb"}, "validation_failed:single_line:title"),
        ({"title": "x" * 21}, "validation_failed:max_length:title"),
        ({"kind": "otro"}, "validation_failed:enum:kind"),
        ({"points": ["a", "b", "c"]}, "validation_failed:max_items:points"),
        ({"points": "a"}, "validation_failed:type:points"),
        ({"slug": "No Slug"}, "validation_failed:format:slug"),
        ({"date": "2026-02-30"}, "validation_failed:format:date"),
        ({"date": "26-1-1"}, "validation_failed:format:date"),
        ({"urgent": "si"}, "validation_failed:type:urgent"),
    ],
)
def test_json_with_an_extra_field_or_a_wrong_type(change, code):
    assert check(_json_step(), json.dumps({**GOOD, **change})).error_code == code


def test_missing_required_field():
    data = dict(GOOD)
    del data["kind"]
    assert check(_json_step(), json.dumps(data)).error_code == "validation_failed:missing_field:kind"


@pytest.mark.parametrize("text", ['{"a": 1, "a": 2}', '{"title": NaN}', "[1]", "no json"])
def test_json_with_duplicate_keys_or_nan(text):
    result = check(_json_step(), text)
    assert not result.ok and result.error_code.startswith("validation_failed:json")


def test_json_inside_one_fenced_block():
    text = "Aquí va:\n```json\n" + json.dumps(GOOD) + "\n```\nfin"
    assert check(_json_step(), text).ok


def test_two_json_blocks_are_refused():
    block = "```json\n" + json.dumps(GOOD) + "\n```\n"
    assert check(_json_step(), block + block).error_code == "validation_failed:json_block:-"


def test_same_output_same_result():
    text = "```json\n" + json.dumps({**GOOD, "title": "Café"}) + "\n```"
    first, second = check(_json_step(), text), check(_json_step(), text)
    assert first.output.encode() == second.output.encode()
    assert "Café" in first.output  # NFC


def test_controls_and_credentials_are_cleaned():
    secret = next(iter(SECRET_SAMPLES.values()))
    result = check(_step(format="text"), f"hola\x1b[2J‮ {secret}")
    assert result.ok and "\x1b" not in result.output and "‮" not in result.output
    assert secret not in result.output
    escaped = json.dumps({**GOOD, "title": "a\u001b[2Jb"})
    assert "\x1b" not in check(_json_step(), escaped).output


# -- fenced code blocks (revised 2026-11-26): headings inside code are code ----------------------

F3, F4 = "`" * 3, "`" * 4


def _heads(text, *headings):
    return check(_step(format="markdown", required_headings=list(headings)), text)


def test_a_heading_only_inside_a_fence_is_not_a_heading():
    """The smallest forged structure: the required heading exists only inside a code block."""
    assert _heads(f"{F3}\n## X\n{F3}", "X").error_code == "validation_failed:required_headings:X"
    # Control: the same heading outside the block counts.
    assert _heads(f"## X\n\n{F3}\nx\n{F3}", "X").ok


def test_heading_outside_and_inside_a_fence():
    text = f"## A\n\n{F3}md\n## B\n{F3}\n\n## C"
    assert _heads(text, "A", "C").ok
    assert _heads(text, "A", "B", "C").error_code == "validation_failed:required_headings:B"


def test_an_unterminated_fence_runs_to_the_end():
    """CommonMark: a fence never closed ends with the text, so nothing after it is a heading."""
    text = f"## A\n\n{F3}\ncode\n## B"
    assert _heads(text, "A").ok
    assert _heads(text, "B").error_code == "validation_failed:required_headings:B"


def test_a_shorter_fence_inside_a_longer_one_does_not_close_it():
    text = f"{F4}md\n{F3}\n## Dentro\n{F3}\n{F4}\n\n## Fuera"
    assert _heads(text, "Fuera").ok
    assert not _heads(text, "Dentro").ok
    # A longer closing fence closes a shorter opening one.
    assert _heads(f"{F3}\nx\n{F4}\n\n## Fuera", "Fuera").ok
    # Tildes close only tildes.
    assert not _heads(f"~~~\n{F3}\n## Dentro\n~~~", "Dentro").ok
    assert _heads(f"~~~\nx\n~~~\n## Fuera", "Fuera").ok


def test_indentation_of_fences_and_headings():
    """Up to three spaces still opens a fence or a heading; four or more is indented code."""
    assert not _heads(f"   {F3}\n## Dentro\n   {F3}", "Dentro").ok
    assert _heads("   ## Tres", "Tres").ok
    assert not _heads("    ## Cuatro", "Cuatro").ok
    # A backtick line with a backtick in its info string is not a fence (inline code).
    assert _heads(f"{F3} a`b {F3}\n## Fuera", "Fuera").ok


def test_closing_hashes_and_hash_inside_a_title():
    assert _heads("## Resumen ##", "Resumen").ok
    assert _heads("## C#", "C#").ok  # a `#` without a space before it is part of the title


def test_a_json_block_with_a_longer_fence_is_recognised():
    body = json.dumps(GOOD)
    # The smallest input that failed: a json block fenced with four backticks, after prose.
    assert check(_json_step(), f"Hola\n\n{F4}json\n{body}\n{F4}").ok
    assert check(_json_step(), f"Hola\n\n~~~json\n{body}\n~~~").ok
    assert check(_json_step(), f"Hola\n\n{F3}JSON extra\n{body}\n{F3}").ok
    # Control: the same prose and an unlabelled block is not JSON.
    assert check(_json_step(), f"Hola\n\n{F4}\n{body}\n{F4}").error_code == "validation_failed:json:-"


def test_json_blocks_still_exactly_one_and_closed():
    body = json.dumps(GOOD)
    two = f"{F4}json\n{body}\n{F4}\n\n{F3}json\n{body}\n{F3}"
    assert check(_json_step(), two).error_code == "validation_failed:json_block:-"
    assert check(_json_step(), f"{F3}json\n{body}").error_code == "validation_failed:json_block:-"
    # A json example inside a longer markdown block is code, not a second block.
    inner = f"{F4}md\n{F3}json\n{{}}\n{F3}\n{F4}\n\n{F3}json\n{body}\n{F3}"
    assert check(_json_step(), inner).ok
    # A three-backtick closing line does not close a four-backtick json block.
    assert check(_json_step(), f"{F4}json\n{body}\n{F3}").error_code == "validation_failed:json_block:-"
