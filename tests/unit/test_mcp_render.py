"""A tool result is untrusted data (mcp-gateway D7, task 4.1): cleaned and redacted, linear."""

from __future__ import annotations

import sys
import time
import unicodedata
import unicodedata

import mcp_types as types

from harness.mcp.render import clean_description, render_error, render_result
from tests.conftest import SECRET_SAMPLES


def text_result(text: str, structured=None, is_error=False) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=structured,
        is_error=is_error,
    )


def test_credential_in_a_text_result_is_masked_and_counted():
    rendered = render_result(text_result("valor " + SECRET_SAMPLES["github"] + " fin"))
    assert "[REDACTED:github]" in rendered.text
    assert SECRET_SAMPLES["github"] not in rendered.text
    assert rendered.redactions == 1


def test_escape_and_bidirectional_characters_are_dropped():
    rendered = render_result(text_result("a\x1b[2J\x1b]0;t\x07b ‮oct‬ ​c"))
    for char in ("\x1b", "\x07", "‮", "‬", "​"):
        assert char not in rendered.text
    assert "ab" in rendered.text and "[2J" not in rendered.text  # whole sequences go
    assert "oct" in rendered.text and "c" in rendered.text  # the rest is data, shown as data


def test_a_colour_code_glued_to_a_credential_does_not_hide_it():
    """Dropping only ESC would leave `[31m` glued to the token, with no word boundary."""
    rendered = render_result(text_result("\x1b[31m" + SECRET_SAMPLES["github"] + "\x1b[0m"))
    assert rendered.text == "[REDACTED:github]"


def test_an_unterminated_osc_sequence_stops_at_the_next_escape():
    rendered = render_result(text_result("a\x1b]0;titulo sin fin\x1b[1mb"))
    assert rendered.text == "ab"


def test_credentials_in_keys_and_nested_values_are_masked():
    aws_hidden = SECRET_SAMPLES["aws"][:10] + "​" + SECRET_SAMPLES["aws"][10:]
    structured = {SECRET_SAMPLES["github"]: "valor", "lista": [{"clave": aws_hidden}]}
    rendered = render_result(text_result("ignored when structured", structured))
    assert "[REDACTED:github]" in rendered.text and "[REDACTED:aws]" in rendered.text
    assert SECRET_SAMPLES["github"] not in rendered.text
    assert SECRET_SAMPLES["aws"] not in rendered.text.replace("​", "")
    assert rendered.redactions == 2
    assert "ignored when structured" not in rendered.text


def test_two_credentials_are_counted_as_two():
    text = SECRET_SAMPLES["github"] + " y " + SECRET_SAMPLES["slack"]
    assert render_result(text_result(text)).redactions == 2


def test_keys_that_clean_to_the_same_text_all_stay_visible():
    structured = {"a": 1, "a​": 2, "a​​": 3}
    rendered = render_result(text_result("", structured))
    assert '"a": 1' in rendered.text and '"a (2)": 2' in rendered.text
    assert '"a (3)": 3' in rendered.text


def test_deep_structures_are_cut_not_crashing():
    value: object = "fondo"
    for _ in range(100):
        value = {"n": value}
    assert "[nested too deep]" in render_result(text_result("", value)).text


def test_non_text_blocks_are_withheld():
    result = types.CallToolResult(content=[
        types.ImageContent(type="image", data="QUJD", mime_type="image/png"),
        types.TextContent(type="text", text="texto"),
    ])
    rendered = render_result(result)
    assert "[image withheld: 4 bytes of base64]" in rendered.text
    assert "QUJD" not in rendered.text and "texto" in rendered.text


def test_an_error_result_is_cleaned_too():
    rendered = render_error(text_result("fallo \x1b[31m" + SECRET_SAMPLES["github"], is_error=True))
    assert "\x1b" not in rendered.text and "[REDACTED:github]" in rendered.text


def test_description_is_cleaned_whole_before_it_is_cut():
    """A token pushed into the first 120 characters by invisible padding is still masked."""
    description = "​" * 5000 + SECRET_SAMPLES["github"] + " resto"
    cleaned = clean_description(description)
    assert len(cleaned) <= 120
    assert "[REDACTED:github]" in cleaned
    assert SECRET_SAMPLES["github"][:12] not in cleaned


# -- linear time on adversarial input of 1 MiB --------------------------------------------------

ONE_MIB = 1024 * 1024
BOUND_S = 5.0  # measured well under 1 s on the reference Mac; the bound only catches quadratics


def _timed(function, *args) -> float:
    started = time.perf_counter()
    function(*args)
    return time.perf_counter() - started


def test_one_mebibyte_of_adversarial_text_is_rendered_in_bounded_time():
    partial = "gh" + "p_" + "A" * 30  # almost a token, many times: every pattern tries each one
    text = ("\x1b[2J​" + partial + " eyJ" + "a" * 9 + ".") * (ONE_MIB // 60)
    assert _timed(render_result, text_result(text[:ONE_MIB])) < BOUND_S


def test_many_colliding_keys_are_rendered_in_bounded_time():
    """25 600 short keys that all clean to `k`: a naive suffix search would be quadratic
    (measured: about 50 s for this many keys on the reference Mac)."""
    invisible = [chr(c) for c in range(0x80, sys.maxunicode + 1)
                 if unicodedata.category(chr(c)) == "Cf"][:160]
    structured = {"k" + a + b: 1 for a in invisible for b in invisible}
    assert len(structured) == 25600
    started = time.perf_counter()
    rendered = render_result(text_result("", structured))
    assert time.perf_counter() - started < BOUND_S
    assert '"k (25600)": 1' in rendered.text


def test_one_mebibyte_description_is_cleaned_in_bounded_time():
    assert _timed(clean_description, ("‮" + "sk-" + "x" * 30) * (ONE_MIB // 34)) < BOUND_S


def test_one_mebibyte_of_broken_escape_sequences_is_cleaned_in_bounded_time():
    text = ("\x1b]" + "t" * 50 + "\x1b[" + "9" * 50) * (ONE_MIB // 104)
    assert _timed(render_result, text_result(text)) < BOUND_S
