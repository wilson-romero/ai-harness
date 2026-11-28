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


def test_thirteen_formats_and_the_url_password():
    assert len(PATTERNS) == 14
    assert {kind for kind, _ in PATTERNS} == {kind for kind, _ in ALL_SAMPLES} | {
        "url-credentials"}


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


# Review of d0a65d8, finding 3: a password inside a URL (the `user:password` of
# `scheme://...@host`). Assembled at run time, as the other samples, so that the public-safety
# guard does not take the test for a real credential.
URL_PASSWORD = "S3cret" + "Pass"


def _url(scheme: str, userinfo: str, rest: str) -> str:
    return scheme + "://" + userinfo + "@" + rest


@pytest.mark.parametrize("url", [
    _url("postgres", "admin:" + URL_PASSWORD, "db.example.com:5432/app"),
    _url("https", "deploy:" + URL_PASSWORD, "git.example.com/org/repo.git"),
    _url("redis", ":" + URL_PASSWORD, "cache.example.com:6379/0"),
    _url("amqp+ssl", "user:" + URL_PASSWORD, "mq.example.com"),
])
def test_a_password_in_a_url_is_masked_and_the_rest_is_kept(url):
    result = redact(f"conecta con {url} ya")
    assert URL_PASSWORD not in result.text and result.kinds == ("url-credentials",)
    scheme, rest = url.split("://", 1)
    host = rest.split("@", 1)[1]
    assert result.text == f"conecta con {scheme}://[REDACTED:url-credentials]@{host} ya"


@pytest.mark.parametrize("text", [
    "https://example.com/a:b" + "@c",
    _url("ssh", "git", "host.example.com/repo"),
    "git" + "@github.com:org/repo.git",
    "mailto:a:b" + "@example.com",
    "http://[::1]:8080/path",
    _url("http", "user:", "host.example.com"),
    "see https://example.com:8443/x",
])
def test_url_look_alikes_are_unchanged(text):
    result = redact(text)
    assert result.text == text and result.count == 0


def test_the_url_pattern_is_linear():
    import time

    started = time.monotonic()
    redact("a." * 50_000 + "://" + "b" * 50_000 + ":" + "c" * 50_000)
    redact(("x://y:" + "z" * 20) * 5_000)
    assert time.monotonic() - started < 2
