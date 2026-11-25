"""SEC-01 over a stream: the server's stderr is redacted before its log keeps it (2026-11-25).

`LineRedactor` sees the stream in arbitrary chunks; `StderrLog` writes what it releases under
the log's size cap. Every sample credential is assembled at run time in `tests/conftest.py`.
"""

from __future__ import annotations

import os

import pytest

from harness.mcp import transport
from harness.mcp.transport import StderrLog
from harness.text.redaction import STREAM_HOLD_BYTES, LineRedactor, redact
from tests.conftest import PRIVATE_KEY_SAMPLE, SECRET_SAMPLES

TOKEN = SECRET_SAMPLES["github"]
HEADER, *BODY, FOOTER = PRIVATE_KEY_SAMPLE.splitlines()


def run(redactor: LineRedactor, chunks: list[bytes], finish: bool = True) -> bytes:
    out = b"".join(piece.output for chunk in chunks for piece in redactor.feed(chunk))
    if finish:
        out += b"".join(piece.output for piece in redactor.finish())
    return out


def chunked(data: bytes, size: int) -> list[bytes]:
    return [data[i:i + size] for i in range(0, len(data), size)]


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


@pytest.mark.parametrize("end", [b"\n", b"\r\n", b"\r"], ids=["lf", "crlf", "cr"])
def test_each_line_end_releases_the_line(end):
    redactor = LineRedactor()
    pieces = redactor.feed(b"10% " + TOKEN.encode("ascii") + end + b"x")
    assert b"".join(p.output for p in pieces) == b"10% [REDACTED:github]" + end
    assert redactor.pending == 1


def test_a_final_cr_waits_to_see_whether_a_newline_follows():
    redactor = LineRedactor()
    assert redactor.feed(b"a\r") == []
    assert [p.output for p in redactor.feed(b"\nb\n")] == [b"a\r\n", b"b\n"]


def test_a_progress_bar_with_lone_cr_read_in_4k_chunks_never_shows_the_token():
    """A `\\r` progress bar never ends a line with LF: each update is a line of its own."""
    bar = "".join(f"{n:>3}% {TOKEN}\r" for n in range(2000)).encode("ascii")
    out = run(LineRedactor(), chunked(bar, 4096))
    assert TOKEN.encode("ascii")[8:] not in out
    assert out.count(b"[REDACTED:github]") == 2000


def test_a_private_key_across_lines_and_chunks_is_masked_whole():
    data = f"clave:\n{PRIVATE_KEY_SAMPLE}\nfin\n".encode("ascii")
    expected = b"clave:\n[REDACTED:private-key]\nfin\n"
    for size in (1, 7, 64, len(data)):
        assert run(LineRedactor(), chunked(data, size)) == expected, size


def test_a_key_without_end_masks_what_follows_within_the_bound():
    out = run(LineRedactor(), [f"{HEADER}\n{'K' * 64}\nmas\n".encode("ascii")])
    assert out == b"[REDACTED:private-key]"


def test_a_key_without_end_stops_being_withheld_at_the_bound():
    """A fake BEGIN cannot black out the rest of the log (review of 2026-11-25, finding 3)."""
    redactor = LineRedactor(key_bytes=1000)
    lines = [f"linea {n:04d}\n".encode("ascii") for n in range(200)]  # 11 bytes each
    pieces = [*redactor.feed(f"antes {HEADER} resto\n".encode("ascii")),
              *[p for line in lines for p in redactor.feed(line)], *redactor.finish()]
    out = b"".join(p.output for p in pieces)
    assert out.startswith(b"antes [REDACTED:private-key]")
    assert b"no END line within 1000 bytes of a private key header; logging resumes" in out
    assert b"linea 0090\n" not in out and b"linea 0091\n" in out and out.endswith(b"linea 0199\n")
    assert sum(p.withheld for p in pieces) == 91 * 11  # lines 0..90, the last over the bound


def test_invalid_utf8_passes_unchanged_and_never_raises():
    data = b"\xff\xfe roto \xc3 " + TOKEN.encode("ascii") + b" \xe2\x82\n"
    out = run(LineRedactor(), [data[:5], data[5:]])
    assert out == b"\xff\xfe roto \xc3 [REDACTED:github] \xe2\x82\n"


def test_a_line_without_end_is_cut_and_keeps_its_token_whole():
    """The bound is really reached: 300 bytes against a bound of 256."""
    redactor = LineRedactor(line_bytes=256, hold_bytes=64)
    token = TOKEN.encode("ascii")
    data = b"." * 230 + b" " + token + b" x"
    pieces = [p for chunk in chunked(data, 50) for p in redactor.feed(chunk)]
    assert pieces, "the bound was never reached: the test would prove nothing"
    assert redactor.pending <= 256
    out = b"".join(p.output for p in [*pieces, *redactor.finish()])
    assert out == b"." * 230 + b" [REDACTED:github] x"


@pytest.mark.parametrize("size", [7, 64, 333, 4096])
def test_a_token_never_leaks_at_any_offset_around_the_cut(size):
    """Property: wherever the token falls relative to the cuts, for several chunk sizes, the
    stream gives exactly what `redact` gives on the whole text (finding 1)."""
    redactor_args = {"line_bytes": 1024, "hold_bytes": 128}
    token = TOKEN.encode("ascii")
    for offset in range(700, 1100):
        data = b"." * offset + b" " + token + b" " + b"." * (2600 - offset)
        out = run(LineRedactor(**redactor_args), chunked(data, size))
        assert out == redact(data.decode("ascii")).text.encode("ascii"), (size, offset)


def test_the_review_case_a_70000_byte_chunk_with_the_token_across_the_cut():
    token = TOKEN.encode("ascii")
    cut = 70_000 - STREAM_HOLD_BYTES
    for back in range(1, len(token)):
        start = cut - back  # the token straddles the cut
        data = b"." * (start - 1) + b" " + token + b" " + b"." * (70_000 - start - len(token) - 1)
        assert len(data) == 70_000
        out = run(LineRedactor(), [data], finish=False)
        assert token[4:] not in out and token[:20] not in out, back


def test_a_key_header_across_the_cut_still_withholds_the_body():
    """Finding 2: the header line before the cut, the body only after it."""
    first = ("z" * 60_000 + HEADER + " " * 8182).encode("ascii")
    rest = ("\n" + "\n".join(BODY) + "\n" + FOOTER + "\nfin\n").encode("ascii")
    out = run(LineRedactor(), [first, rest])
    assert BODY[0].encode("ascii") not in out and BODY[1].encode("ascii") not in out
    assert out.endswith(b"[REDACTED:private-key]\nfin\n")


def test_a_stream_that_never_ends_a_line_keeps_memory_bounded():
    redactor = LineRedactor(line_bytes=1024, hold_bytes=128)
    released = 0
    for _ in range(1000):
        released += sum(p.raw for p in redactor.feed(b"E" * 500))
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


def test_the_last_line_without_a_line_end_is_written_at_close(tmp_path):
    assert write_log(tmp_path / "log", [b"a\n", b"sin salto ", TOKEN.encode("ascii")]) == (
        b"a\nsin salto [REDACTED:github]")


def test_the_log_caps_and_counts_what_it_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 100)
    log = write_log(tmp_path / "log", [b"E" * 70 + b"\n", b"F" * 70 + b"\n"])
    kept, marker = log[:100], log[100:]
    assert kept == b"E" * 70 + b"\n" + b"F" * 29
    assert marker == b"\n[ai-harness: 42 more bytes of stderr were dropped]\n"


def test_a_withheld_key_body_is_counted_as_absent_from_the_log(tmp_path):
    body = "\n".join(BODY) + "\n" + FOOTER
    log = write_log(tmp_path / "log", [f"a\n{HEADER}\n{body}\nb\n".encode("ascii")])
    assert log == (b"a\n[REDACTED:private-key]\nb\n"
                   + f"\n[ai-harness: {len(body)} more bytes of stderr were dropped]\n".encode())
