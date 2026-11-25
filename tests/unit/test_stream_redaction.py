"""SEC-01 over a stream: the server's stderr is redacted before its log keeps it (2026-11-25).

`LineRedactor` sees the stream in arbitrary chunks; `StderrLog` writes what it releases under
the log's size cap. Every sample credential is assembled at run time in `tests/conftest.py`.
"""

from __future__ import annotations

import os

import pytest

from harness.mcp import transport
from harness.mcp.transport import StderrLog
from harness.text.redaction import LineRedactor
from tests.conftest import PRIVATE_KEY_SAMPLE, SECRET_SAMPLES

TOKEN = SECRET_SAMPLES["github"]


def run(redactor: LineRedactor, chunks: list[bytes], finish: bool = True) -> bytes:
    out = b"".join(piece for chunk in chunks for _, piece in redactor.feed(chunk))
    if finish:
        out += b"".join(piece for _, piece in redactor.finish())
    return out


def test_a_token_split_across_two_chunks_is_masked():
    line = f"token {TOKEN} fin\n".encode("ascii")
    cut = line.index(TOKEN.encode("ascii")) + len(TOKEN) // 2
    assert run(LineRedactor(), [line[:cut], line[cut:]]) == b"token [REDACTED:github] fin\n"


def test_every_cut_point_gives_the_same_text():
    line = f"a {TOKEN} b\nc {TOKEN}\n".encode("ascii")
    expected = b"a [REDACTED:github] b\nc [REDACTED:github]\n"
    for cut in range(1, len(line)):
        assert run(LineRedactor(), [line[:cut], line[cut:]]) == expected, cut


def test_nothing_is_released_before_its_line_ends():
    redactor = LineRedactor()
    assert redactor.feed(b"token " + TOKEN[:10].encode("ascii")) == []
    assert redactor.pending > 0


def test_a_private_key_across_lines_and_chunks_is_masked_whole():
    data = f"clave:\n{PRIVATE_KEY_SAMPLE}\nfin\n".encode("ascii")
    expected = b"clave:\n[REDACTED:private-key]\nfin\n"
    for size in (1, 7, 64, len(data)):
        chunks = [data[i:i + size] for i in range(0, len(data), size)]
        assert run(LineRedactor(), chunks) == expected, size


def test_a_key_without_end_masks_the_rest_of_the_stream():
    header = PRIVATE_KEY_SAMPLE.splitlines()[0]
    out = run(LineRedactor(), [f"{header}\n{'K' * 64}\nmas\n".encode("ascii")])
    assert out == b"[REDACTED:private-key]"


def test_invalid_utf8_passes_unchanged_and_never_raises():
    data = b"\xff\xfe roto \xc3 " + TOKEN.encode("ascii") + b" \xe2\x82\n"
    out = run(LineRedactor(), [data[:5], data[5:]])
    assert out == b"\xff\xfe roto \xc3 [REDACTED:github] \xe2\x82\n"


def test_a_line_without_newline_is_bounded_and_keeps_a_token_in_the_hold():
    """The bound: a line past `line_bytes` is released up to its last `hold_bytes`."""
    redactor = LineRedactor(line_bytes=256, hold_bytes=64)
    filler = b"E" * 200
    token = TOKEN.encode("ascii")
    out = b""
    for chunk in (filler, b" " + token[:20], token[20:] + b" x"):
        out += b"".join(piece for _, piece in redactor.feed(chunk))
        assert redactor.pending <= 256
    out += b"".join(piece for _, piece in redactor.finish())
    assert out == filler + b" [REDACTED:github] x"


def test_a_stream_that_never_ends_a_line_keeps_memory_bounded():
    redactor = LineRedactor(line_bytes=1024, hold_bytes=128)
    released = 0
    for _ in range(1000):
        released += sum(raw for raw, _ in redactor.feed(b"E" * 500))
        assert redactor.pending <= 1024
    assert released + redactor.pending == 500_000


def test_the_hold_must_be_smaller_than_the_bound():
    with pytest.raises(ValueError):
        LineRedactor(line_bytes=10, hold_bytes=10)


# -- the log -----------------------------------------------------------------------------------


def write_log(path, chunks: list[bytes]) -> bytes:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
    log = StderrLog(descriptor)
    try:
        for chunk in chunks:
            log.feed(chunk)
        log.close(sum(len(chunk) for chunk in chunks))
    finally:
        os.close(descriptor)
    return path.read_bytes()


def test_the_log_keeps_redacted_text(tmp_path):
    line = f"token {TOKEN}\n".encode("ascii")
    assert write_log(tmp_path / "log", [line[:10], line[10:]]) == b"token [REDACTED:github]\n"


def test_the_log_caps_and_counts_what_it_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 100)
    log = write_log(tmp_path / "log", [b"E" * 70 + b"\n", b"F" * 70 + b"\n"])
    kept, marker = log[:100], log[100:]
    assert kept == b"E" * 70 + b"\n" + b"F" * 29
    assert marker == b"\n[ai-harness: 42 more bytes of stderr were dropped]\n"
