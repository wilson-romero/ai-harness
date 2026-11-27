"""Strict JSON for untrusted files (skill-engine D3): no duplicate keys, no NaN, bounded."""

import pytest

from harness.core.errors import InvalidInput
from harness.core.strict_json import MAX_DEPTH, StrictJsonError, loads_strict


def test_plain_object():
    assert loads_strict('{"a": [1, "dos", true, null]}', max_bytes=100) == {
        "a": [1, "dos", True, None]
    }


@pytest.mark.parametrize(
    "text, reason",
    [
        ('{"a": 1, "a": 2}', "duplicate key"),
        ('{"a": {"b": 1, "b": 1}}', "duplicate key"),
        ('{"a": NaN}', "NaN"),
        ('{"a": Infinity}', "Infinity"),
        ('{"a": -Infinity}', "Infinity"),
        ('{"a": 1', "not valid JSON"),
        ("", "not valid JSON"),
    ],
)
def test_rejected(text, reason):
    with pytest.raises(InvalidInput, match=reason):
        loads_strict(text, max_bytes=100)


def test_too_large_is_refused_before_parsing():
    with pytest.raises(InvalidInput, match="larger than 10 bytes"):
        loads_strict('{"a": "' + "x" * 20 + '"}', max_bytes=10)


def test_size_is_counted_in_utf8_bytes():
    with pytest.raises(InvalidInput, match="larger than"):
        loads_strict('"' + "€" * 4 + '"', max_bytes=10)  # 6 characters, 14 bytes


def test_deep_nesting_is_refused_without_recursion():
    text = "[" * 100_000 + "]" * 100_000
    with pytest.raises(InvalidInput, match="nested deeper than 32"):
        loads_strict(text, max_bytes=1_000_000)


def test_brackets_inside_strings_do_not_count():
    text = '{"a": "' + "[" * 40 + '\\"["}'
    assert loads_strict(text, max_bytes=200) == {"a": "[" * 40 + '"['}


# -- code-mode 1.1: the kind of each refusal, a tighter depth, and the cases a plan needs ------


@pytest.mark.parametrize(
    "text, kind",
    [
        ('{"a": 1, "a": 2}', "duplicate_key"),
        ('{"a": NaN}', "not_finite"),
        ('{"a": Infinity}', "not_finite"),
        ('{"a": -Infinity}', "not_finite"),
        ('{"a": 1', "not_json"),
        ('{"a": 1} {"b": 2}', "not_json"),  # trailing data
        ('{"a": 1}x', "not_json"),
        ('﻿{"a": 1}', "not_json"),  # a byte order mark is not JSON text
        ('{1: 2}', "not_json"),  # a key that is not a string
        ('{"a": "x\ny"}', "not_json"),  # a raw control character inside a string
        ('{"a": ' + "1" * 5000 + "}", "not_json"),  # past the interpreter's digit limit
        ("[" * 40 + "]" * 40, "too_deep"),
        ('"' + "x" * 200 + '"', "too_large"),
    ],
)
def test_each_refusal_has_its_kind(text, kind):
    with pytest.raises(StrictJsonError) as caught:
        loads_strict(text, max_bytes=100 if kind == "too_large" else 10_000)
    assert caught.value.kind == kind
    assert isinstance(caught.value, InvalidInput)  # callers that catch InvalidInput still do


def test_a_tighter_depth_can_be_asked():
    assert loads_strict('{"a": {"b": 1}}', max_bytes=100, max_depth=2) == {"a": {"b": 1}}
    with pytest.raises(StrictJsonError, match="nested deeper than 2 levels") as caught:
        loads_strict('{"a": {"b": [1]}}', max_bytes=100, max_depth=2)
    assert caught.value.kind == "too_deep"


def test_a_depth_above_the_default_cannot_be_asked():
    with pytest.raises(ValueError):
        loads_strict("{}", max_bytes=100, max_depth=MAX_DEPTH + 1)
