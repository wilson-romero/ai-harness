"""Strict JSON for untrusted files (skill-engine D3): no duplicate keys, no NaN, bounded."""

import pytest

from harness.core.errors import InvalidInput
from harness.core.strict_json import loads_strict


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
