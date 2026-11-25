"""SEC-01: credentials of a known format are masked; prose is left alone (D8).

Every sample credential is assembled at run time in `tests/conftest.py`.
"""

import pytest

from harness.text.redaction import PATTERNS, redact, secret_kinds
from tests.conftest import (
    EXTRA_SECRET_SAMPLES,
    PRIVATE_KEY_SAMPLE,
    SECRET_SAMPLES,
)

ALL_SAMPLES = [
    *SECRET_SAMPLES.items(),
    *EXTRA_SECRET_SAMPLES.items(),
    ("private-key", PRIVATE_KEY_SAMPLE),
]


def test_thirteen_formats():
    assert len(PATTERNS) == 13
    assert {kind for kind, _ in PATTERNS} == {kind for kind, _ in ALL_SAMPLES}


@pytest.mark.parametrize(
    ("kind", "token"), ALL_SAMPLES, ids=[f"{k}-{i}" for i, (k, _) in enumerate(ALL_SAMPLES)]
)
def test_each_format_is_masked(kind, token):
    result = redact(f"antes {token} despues")
    assert result.text == f"antes [REDACTED:{kind}] despues"
    assert result.kinds == (kind,)


def test_private_key_block_masked_as_a_whole():
    result = redact(f"clave:\n{PRIVATE_KEY_SAMPLE}\nfin")
    assert result.text == "clave:\n[REDACTED:private-key]\nfin"
    assert "K" * 64 not in result.text


@pytest.mark.parametrize(
    "text",
    [
        "usamos sk-learn-pipeline para el modelo",
        "sha256 " + "9f" * 32,
        "password: ver gestor",
        "api_key = settings.api_key",
        "token=" + "x" * 30,
        "AKIA corto",
        "ghp_corto",
        "eyJ sin puntos",
    ],
)
def test_lookalike_text_unchanged(text):
    result = redact(text)
    assert result.text == text and result.count == 0


def test_substitution_count():
    text = "uno " + SECRET_SAMPLES["github"] + " dos " + SECRET_SAMPLES["aws"]
    result = redact(text)
    assert result.count == 2
    assert secret_kinds(text) == {"github": 1, "aws": 1}


def test_unknown_format_passes_unchanged():
    # Documented limit: a credential without a known prefix and shape is not detected.
    text = "Server=db;User=app;Pass" + "word=" + "Desconocido-123;"
    assert redact(text).text == text
