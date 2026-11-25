"""SEC-01 over a stream: the server's stderr is redacted before its log keeps it (2026-11-25).

`LineRedactor` sees the stream in arbitrary chunks; `StderrLog` writes what it releases under
the log's cap. Every sample credential is assembled at run time (here or in
`tests/conftest.py`), so that no versioned file contains one.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import string
import sys
from collections import Counter

import anyio
import pytest

from harness.mcp import transport
from harness.mcp.transport import StderrLog, TransportState, bounded_stdio
from harness.text import redaction
from harness.text.redaction import (
    PATTERNS,
    STREAM_KEY_BYTES,
    STREAM_LINE_BYTES,
    LineRedactor,
    Redacted,
    redact,
)
from tests.conftest import PRIVATE_KEY_SAMPLE, SECRET_SAMPLES

TOKEN = SECRET_SAMPLES["github"]
HEADER, *BODY, FOOTER = PRIVATE_KEY_SAMPLE.splitlines()
ANTHROPIC = "sk-" + "ant-" + "api03-"
SLACK = "xo" + "xb-"
GITLAB = "gl" + "pat-"
DIGITALOCEAN = "do" + "p_v1_"
STRIPE = "sk" + "_live_"
LIMIT = STREAM_LINE_BYTES


def pieces_of(redactor: LineRedactor, chunks: list[bytes], finish: bool = True):
    pieces = [piece for chunk in chunks for piece in redactor.feed(chunk)]
    return pieces + (redactor.finish() if finish else [])


def run(redactor: LineRedactor, chunks: list[bytes], finish: bool = True) -> bytes:
    return b"".join(piece.output for piece in pieces_of(redactor, chunks, finish))


def chunked(data: bytes, size: int) -> list[bytes]:
    return [data[i:i + size] for i in range(0, len(data), size)]


def long_line_marker(size: int) -> bytes:
    return f"[ai-harness: a line of {size} bytes was dropped: too long to redact]\n".encode()


# -- redact: the sequential pass, repeated to a fixed point ---------------------------------------


def develop_redact(text: str) -> Redacted:
    """`redact` as it was before 2026-11-25 (one sequential pass), frozen as the reference."""
    kinds: list[str] = []
    for kind, spans_of in PATTERNS:
        spans = spans_of(text)
        if not spans:
            continue
        parts: list[str] = []
        last = 0
        for start, end in spans:
            parts += [text[last:start], f"[REDACTED:{kind}]"]
            last = end
        parts.append(text[last:])
        text = "".join(parts)
        kinds.extend([kind] * len(spans))
    return Redacted(text=text, kinds=tuple(kinds))


@pytest.mark.parametrize("text", [
    GITLAB + "G" * 20 + PRIVATE_KEY_SAMPLE,
    DIGITALOCEAN + "a" * 64 + STRIPE + "S" * 30,
    GITLAB + "G" * 19 + "-" + ANTHROPIC + "A" * 30,
], ids=["gitlab-pem", "do-stripe", "gitlab-anthropic"])
def test_the_review_cases_of_glued_credentials_are_masked(text):
    """Finding A of the third review: merged spans lost these; the sequential pass masks them
    (the marker one pattern leaves is the boundary the next one needs)."""
    for result in (develop_redact(text), redact(text)):
        assert re.sub(r"\[REDACTED:[a-z-]+\]", "", result.text) == "", result.text


@pytest.mark.parametrize("text,expected", [
    (DIGITALOCEAN + "b" * 64 + ANTHROPIC + "A" * 30,
     "[REDACTED:digitalocean][REDACTED:anthropic]"),
    ("AI" + "za" + "D" * 34 + "-" + SLACK + "1234567890ab",
     "[REDACTED:google][REDACTED:slack]"),
])
def test_a_credential_glued_after_another_is_masked_by_the_second_pass(text, expected):
    assert develop_redact(text).text != expected  # one pass leaves one of them in clear
    assert redact(text).text == expected


@pytest.mark.parametrize("prefix", [ANTHROPIC + "abcdefghij-", SLACK + "abcdefghij-"])
def test_a_jwt_whose_header_another_credential_swallowed_is_a_documented_limit(prefix):
    """Not covered (D3, revised 2026-11-25): the JWT's last two segments stay in clear."""
    jwt_rest = ".ey" + "J" + "Q" * 20 + "." + "S" * 30
    text = prefix + "ey" + "J" + "P" * 20 + jwt_rest
    assert redact(text).text.endswith(jwt_rest)


def test_a_credential_nested_in_a_private_key_block_is_masked_with_it():
    """Finding C of the third review: the block is masked whole, with what it contains."""
    text = f"a {HEADER}\n{TOKEN}\n{'K' * 64}\n{FOOTER} b\n"
    assert redact(text).text == "a [REDACTED:private-key] b\n"
    lines = run(LineRedactor(), [text.encode("ascii")])
    assert TOKEN[8:].encode() not in lines and b"KKKK" not in lines


AN = string.ascii_letters + string.digits
B64 = AN + "_-"


def _random(rng: random.Random, n: int, alphabet: str = AN) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def _credential(rng: random.Random) -> str:
    kind = rng.randrange(12)
    return [
        lambda: ANTHROPIC + _random(rng, rng.randint(20, 60), B64),
        lambda: "sk-" + "proj-" + _random(rng, rng.randint(20, 40), B64),
        lambda: "sk-" + _random(rng, 48),
        lambda: "gh" + "p_" + _random(rng, rng.randint(36, 50)),
        lambda: GITLAB + _random(rng, 20, B64),
        lambda: "AK" + "IA" + _random(rng, 16, string.ascii_uppercase + string.digits),
        lambda: "AI" + "za" + _random(rng, 35, B64),
        lambda: SLACK + _random(rng, rng.randint(10, 40), AN + "-"),
        lambda: DIGITALOCEAN + _random(rng, 64, "0123456789abcdef"),
        lambda: STRIPE + _random(rng, rng.randint(24, 40)),
        lambda: ("ey" + "J" + _random(rng, 12, B64) + ".ey" + "J" + _random(rng, 12, B64) + "."
                 + _random(rng, 12, B64)),
        lambda: f"{HEADER}\n{_random(rng, 64, AN + '+/')}\n{FOOTER}",
    ][kind]()


SEPARATORS = ["", " ", "\n", "_", "-", ".", "/", '"', "=", ":", "\r\n", "é", "x", "A", "0", "]"]


@pytest.mark.parametrize("seed", range(3))
def test_seeded_differential_against_the_single_pass(seed):
    """Item 1 of the third review: whatever one pass masked is still masked, a text with no
    credential is unchanged, and no kind is counted fewer times."""
    rng = random.Random(seed)
    for _ in range(1500):
        secrets = [_credential(rng) for _ in range(rng.randint(1, 4))]
        text = rng.choice(SEPARATORS).join(secrets)
        if rng.random() < 0.3:
            inner, outer = secrets[0], _credential(rng)
            cut = rng.randint(0, len(outer))
            text = outer[:cut] + inner + outer[cut:]
            secrets.append(outer)
        old, new = develop_redact(text), redact(text)
        assert Counter(new.kinds) >= Counter(old.kinds), text
        for secret in secrets:
            for line in secret.splitlines():
                if line not in old.text and len(line) > 12 and not line.startswith("-----"):
                    assert line not in new.text, text
        clean = _random(rng, rng.randint(0, 200), AN + " _-.\n\r/:='é-----BEGIN END")
        if develop_redact(clean).count == 0:
            assert redact(clean).text == clean


# -- lines ----------------------------------------------------------------------------------------


def test_the_bounds_are_the_documented_ones():
    assert (STREAM_LINE_BYTES, STREAM_KEY_BYTES) == (16384, 32768)


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


def test_a_crlf_split_across_reads_gives_the_same_bytes():
    assert run(LineRedactor(), [b"a\r", b"\nb\n"]) == b"a\r\nb\n"


def test_a_progress_bar_with_lone_cr_read_in_4k_chunks_never_shows_the_token():
    bar = "".join(f"{n:>3}% {TOKEN}\r" for n in range(2000)).encode("ascii")
    out = run(LineRedactor(), chunked(bar, 4096))
    assert TOKEN.encode("ascii")[8:] not in out
    assert out.count(b"[REDACTED:github]") == 2000


@pytest.mark.parametrize("size", [1, 7, 4096, LIMIT])
def test_a_line_of_exactly_the_limit_is_redacted_and_one_more_byte_drops_it(size):
    token = TOKEN.encode("ascii")
    exact = token + b"." * (LIMIT - len(token) - 1) + b"\n"
    over = token + b"." * (LIMIT - len(token)) + b"\n"
    assert len(exact) == LIMIT and len(over) == LIMIT + 1
    assert run(LineRedactor(), chunked(exact, size)) == (
        b"[REDACTED:github]" + b"." * (LIMIT - len(token) - 1) + b"\n")
    assert run(LineRedactor(), chunked(over + b"next\n", size)) == (
        long_line_marker(LIMIT + 1) + b"next\n")


def test_a_last_line_without_end_has_the_same_limit():
    assert run(LineRedactor(), [b"x" * LIMIT]) == b"x" * LIMIT
    assert run(LineRedactor(), [b"x" * (LIMIT + 1)]) == long_line_marker(LIMIT + 1)


def test_nothing_of_a_line_over_the_limit_reaches_the_output():
    token = TOKEN.encode("ascii")
    line = b"visible? " + token + b" " + b"Z" * 70_000 + b" " + token + b" end\n"
    for size in (1000, 4096, len(line)):
        redactor = LineRedactor()
        pieces = pieces_of(redactor, chunked(line + b"after\n", size))
        assert b"".join(p.output for p in pieces) == long_line_marker(len(line)) + b"after\n"
        assert redactor.pending == 0


@pytest.mark.parametrize("data", [b"\x80" * 70_000, b"A" + b"\x80" * 70_000,
                                  b"\xc3" + b"\x80" * 70_000], ids=["cont", "ascii", "lead"])
def test_a_burst_of_continuation_bytes_never_raises(data):
    """Second review, finding 1: these made the old cut raise."""
    for size in (len(data), 4096):
        pieces = pieces_of(LineRedactor(), chunked(data, size))
        assert b"".join(p.output for p in pieces) == long_line_marker(len(data))
        assert sum(p.raw for p in pieces) == len(data)


def test_invalid_utf8_passes_unchanged():
    data = b"\xff\xfe roto \xc3 " + TOKEN.encode("ascii") + b" \xe2\x82\n"
    out = run(LineRedactor(), [data[:5], data[5:]])
    assert out == b"\xff\xfe roto \xc3 [REDACTED:github] \xe2\x82\n"


# -- private keys ---------------------------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 7, 64, 10_000])
def test_a_private_key_across_lines_and_chunks_is_masked_whole(size):
    data = f"clave:\n{PRIVATE_KEY_SAMPLE}\nfin\n".encode("ascii")
    assert run(LineRedactor(), chunked(data, size)) == b"clave:\n[REDACTED:private-key]\nfin\n"


def test_a_key_block_on_one_line_masks_only_the_block():
    data = f"a {HEADER} x {FOOTER} b\nc\n".encode("ascii")
    assert run(LineRedactor(), [data]) == b"a [REDACTED:private-key] b\nc\n"


def test_a_footer_that_ends_where_a_header_starts_keeps_the_block_open():
    """Marks are searched at every position, so this one header is not missed."""
    glued = HEADER.replace("-----BEGIN", FOOTER + "BEGIN", 1)  # one "-----" for both
    data = f"{HEADER}\n{'K' * 64}\n{glued}\n{'Z' * 64}\n{FOOTER}\nfin\n".encode("ascii")
    for size in (1, 5, len(data)):
        out = run(LineRedactor(), chunked(data, size))
        assert out == b"[REDACTED:private-key]\nfin\n", size


def block(body: int) -> tuple[bytes, int]:
    """A block whose bytes after its header, to the end of its footer, are `counted`."""
    data = f"{HEADER}\n{'K' * body}\n{FOOTER}\nfin\n".encode("ascii")
    return data, len(f"\n{'K' * body}\n{FOOTER}")


@pytest.mark.parametrize("size", [1, 7, 333, 100_000])
def test_the_key_bound_is_exact_in_bytes_after_the_header(size):
    data, counted = block(1000)
    assert run(LineRedactor(key_bytes=counted), chunked(data, size)) == (
        b"[REDACTED:private-key]\nfin\n")
    assert run(LineRedactor(key_bytes=counted - 1), chunked(data, size)) == (
        b"[REDACTED:private-key]\n[ai-harness: no END line within " + str(counted - 1).encode()
        + b" bytes of a private key header; the rest of this line is dropped]\nfin\n")


def test_a_key_without_end_is_dropped_up_to_the_bound_then_lines_come_back():
    """Finding 2 of the second review: one huge line after BEGIN hides 32 KiB, no more."""
    data = (HEADER + "\n").encode("ascii") + b"S" * (1 << 20) + b"\nvisible\n"
    for chunks in ([data], chunked(data, 65536)):
        pieces = pieces_of(LineRedactor(), chunks)
        out = b"".join(p.output for p in pieces)
        assert out.startswith(b"[REDACTED:private-key]\n[ai-harness: no END line within 32768")
        assert out.endswith(b"the rest of this line is dropped]\nvisible\n")
        assert b"SSSS" not in out


def test_logging_resumes_only_at_a_line_start_after_the_bound():
    """Finding C of the third review: a credential across the bound is never written."""
    data, counted = block(4000)
    token = TOKEN.encode("ascii")
    body = data.index(b"KKKK")
    bound = 100
    cut = body + bound - 1 - 10
    data = data[:cut] + token + data[cut + len(token):]
    out = run(LineRedactor(key_bytes=bound), chunked(data, 7))
    assert token[:6] not in out and token[-10:] not in out and b"KKK" not in out
    assert out.count(b"no END line") == 1  # a header still in the window does not reopen it
    assert out.endswith(b"the rest of this line is dropped]\n" + FOOTER.encode() + b"\nfin\n")


def test_nothing_of_a_key_line_is_held():
    redactor = LineRedactor()
    redactor.feed(f"{HEADER}\n{'K' * 100}".encode("ascii"))
    assert redactor.pending == 0


def test_a_block_closed_by_the_bound_is_not_reopened_by_its_own_header():
    data = f"{HEADER} {'K' * 1000}\nnext\n".encode("ascii")
    out = run(LineRedactor(key_bytes=100), chunked(data, 7))
    assert out == (b"[ai-harness: no END line within 100 bytes of a private key header; the rest "
                   b"of this line is dropped]\n[REDACTED:private-key]\nnext\n")


def test_a_second_key_has_a_bound_of_its_own():
    first, counted = block(64)
    second = f"{HEADER}\n{'Z' * 64}\n{FOOTER}\nfin\n".encode("ascii")
    out = run(LineRedactor(key_bytes=counted), [first + second])
    assert out == b"[REDACTED:private-key]\nfin\n[REDACTED:private-key]\nfin\n"


def test_a_header_split_across_reads_still_opens_the_block():
    data = f"x {HEADER}\n{'K' * 64}\n{FOOTER}\nfin\n".encode("ascii")
    cut = data.index(b"PRIVATE")
    assert run(LineRedactor(), [data[:cut], data[cut:]]) == b"x [REDACTED:private-key]\nfin\n"


def test_a_header_in_a_line_over_the_limit_still_hides_the_body():
    data = (b"z" * 20_000 + f"{HEADER}\n{BODY[0]}\n{FOOTER}\nfin\n".encode("ascii"))
    out = run(LineRedactor(), chunked(data, 4096))
    assert out == long_line_marker(20_000 + len(HEADER) + 1) + b"fin\n"


# -- seeded fuzz ----------------------------------------------------------------------------------


def _line(rng: random.Random, secrets: list[str], long_marks: list[str]) -> str:
    roll = rng.random()
    if roll < 0.08:  # over the limit: nothing of it may reach the output
        mark = "LONG" + _random(rng, 12)
        long_marks.append(mark)
        unit = mark + " " + _credential(rng).replace("\n", " ") + " "
        return unit * (LIMIT // len(unit) + 1)
    parts = []
    for _ in range(rng.randint(0, 4)):
        if rng.random() < 0.4:
            secret = _credential(rng)
            secrets.append(secret)
            parts.append(secret)
        else:
            parts.append(_random(rng, rng.randint(0, 40), AN + "  ..::é€"))
    return rng.choice([" ", ", ", "\t"]).join(parts)


def _chunks(rng: random.Random, data: bytes) -> list[bytes]:
    out, i = [], 0
    mode = rng.choice(["small", "big", "huge"])
    while i < len(data):
        n = rng.randint(1, 9) if mode == "small" else rng.randint(1, 5000) if mode == "big" else (
            rng.randint(1, 70_000))
        out.append(data[i:i + n])
        i += n
    return out


@pytest.mark.parametrize("seed", range(4))
def test_seeded_fuzz_lines_are_redacted_whole_and_long_lines_vanish(seed):
    rng = random.Random(seed)
    for _ in range(25):
        secrets: list[str] = []
        long_marks: list[str] = []
        lines = [_line(rng, secrets, long_marks) for _ in range(rng.randint(1, 30))]
        text = "".join(line + rng.choice(["\n", "\r\n", "\r"]) for line in lines)
        data = text.encode("utf-8")
        redactor = LineRedactor()
        pieces = []
        for chunk in _chunks(rng, data):
            pieces += redactor.feed(chunk)
            assert redactor.pending <= LIMIT
        pieces += redactor.finish()
        assert sum(p.raw for p in pieces) == len(data)
        out = b"".join(p.output for p in pieces)
        assert out == run(LineRedactor(), [data])  # the chunking changes nothing
        flat = out.decode("utf-8", "surrogateescape")
        for mark in long_marks:
            assert mark not in flat
        for secret in secrets:
            for part in secret.splitlines():
                if not part.startswith("-----"):
                    assert part not in flat, part[:12]


@pytest.mark.parametrize("seed", range(4))
def test_seeded_fuzz_arbitrary_bytes_never_raise_and_account_for_every_byte(seed, tmp_path,
                                                                            monkeypatch):
    rng = random.Random(2000 + seed)
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 3000)
    alphabet = [b"\x80", b"\xc3", b"\xe2\x82", b"\xff", b"\r", b"\n", b"a", b".", b" ",
                b"-----BEGIN ", b"-----END ", b"PRIVATE KEY-----", b"ey" + b"J", b"\xf0\x9f"]
    for _ in range(30):
        data = b"".join(rng.choice(alphabet) * rng.randint(1, 300) for _ in range(60))
        redactor = LineRedactor(line_bytes=700, key_bytes=900)
        pieces = []
        for chunk in _chunks(rng, data):
            pieces += redactor.feed(chunk)
            assert redactor.pending <= 700
        pieces += redactor.finish()
        assert sum(p.raw for p in pieces) == len(data)
        path = tmp_path / "log"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                             | getattr(os, "O_BINARY", 0), 0o600)
        log = StderrLog(descriptor)
        try:
            for chunk in _chunks(rng, data):
                log.feed(chunk)
            log.close(len(data))
        finally:
            os.close(descriptor)
        written = path.read_bytes()
        assert b"the stderr log stopped" not in written
        dropped = len(data) - log._kept
        assert 0 <= log._kept <= len(data)
        if dropped:
            assert written.endswith(f"[ai-harness: {dropped} more bytes of stderr were "
                                    "dropped]\n".encode())
        else:
            assert b"more bytes of stderr were dropped]" not in written


# -- the log --------------------------------------------------------------------------------------


def write_log(path, chunks: list[bytes], room: int | None = None) -> bytes:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
    log = StderrLog(descriptor)
    if room is not None:
        log._room = room
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


def test_a_line_that_does_not_fit_ends_the_writing_and_is_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 100)
    log = write_log(tmp_path / "log", [b"E" * 70 + b"\n", b"F" * 70 + b"\n", b"G\n"])
    assert log == b"E" * 70 + b"\n" + b"\n[ai-harness: 73 more bytes of stderr were dropped]\n"


def test_after_the_cap_a_half_read_line_is_dropped_not_written(tmp_path, monkeypatch):
    """Finding B of the third review: close() after the budget wrote the pending line raw."""
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 100)
    token = TOKEN.encode("ascii")
    chunks = [b"E" * 99 + b"\n", b"tok: " + token[:20]]
    log = write_log(tmp_path / "log", chunks)
    assert token[:6] not in log
    # the line that does not fit and the half line after it come in the same read
    other = write_log(tmp_path / "other", [b"E" * 150 + b"\ntok: " + token[:20]])
    assert other == f"\n[ai-harness: {151 + 25} more bytes of stderr were dropped]\n".encode()
    assert log == b"E" * 99 + b"\n" + f"\n[ai-harness: {5 + 20} more bytes of stderr were " \
        "dropped]\n".encode()


def test_after_the_line_budget_a_half_read_line_is_dropped_not_written(tmp_path, monkeypatch):
    """Finding B of the third review, its own input: past the work budget, close() wrote the
    pending half token raw. (The old budget's name is patched too, so the test is a negative
    control on that code.)"""
    monkeypatch.setattr(transport, "STDERR_LOG_LINES", 1, raising=False)
    monkeypatch.setattr(transport, "STDERR_WORK_BYTES", 8, raising=False)
    token = TOKEN.encode("ascii")
    chunks = [b"a\nb\n", b"tok: " + token[:20], token[20:] + b" end\n"]
    log = write_log(tmp_path / "log", chunks)
    assert token[:6] not in log
    assert log == b"\n[ai-harness: " + str(sum(map(len, chunks))).encode() + (
        b" more bytes of stderr were dropped]\n")


def test_a_marker_that_does_not_fit_is_not_cut(tmp_path):
    """Finding 6 of the second review: the marker is longer than the token."""
    log = write_log(tmp_path / "log", [(SLACK + "1234567890\n").encode("ascii")], room=16)
    assert log == b"\n[ai-harness: 16 more bytes of stderr were dropped]\n"


def test_a_dropped_key_block_is_counted_as_absent_from_the_log(tmp_path):
    log = write_log(tmp_path / "log", [f"a\n{PRIVATE_KEY_SAMPLE}\nb\n".encode("ascii")])
    hidden = len(PRIVATE_KEY_SAMPLE) + 1 - len(HEADER) - 1
    assert log == (b"a\n[REDACTED:private-key]\nb\n"
                   + f"\n[ai-harness: {hidden} more bytes of stderr were dropped]\n".encode())


def test_a_long_line_is_counted_as_absent_from_the_log(tmp_path):
    line = b"x" * (LIMIT + 1) + b"\n"
    log = write_log(tmp_path / "log", [line, b"y\n"])
    assert log == (long_line_marker(len(line)) + b"y\n"
                   + f"\n[ai-harness: {len(line)} more bytes of stderr were dropped]\n".encode())


def test_a_failure_inside_the_log_is_marked_and_never_raises(tmp_path, monkeypatch):
    def broken(self, data):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(redaction.LineRedactor, "feed", broken)
    log = write_log(tmp_path / "log", [b"a\n", b"b\n"])
    assert log == (b"\n[ai-harness: the stderr log stopped here (RuntimeError); the rest is "
                   b"counted, not kept]\n\n[ai-harness: 4 more bytes of stderr were dropped]\n")


def test_a_failure_at_close_is_marked_and_writes_nothing_raw(tmp_path, monkeypatch):
    def broken(self):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(redaction.LineRedactor, "finish", broken)
    log = write_log(tmp_path / "log", [b"a\n", b"tok: " + TOKEN.encode("ascii")[:20]])
    assert log == (b"a\n\n[ai-harness: the stderr log stopped here (RuntimeError); the rest is "
                   b"counted, not kept]\n\n[ai-harness: 25 more bytes of stderr were dropped]\n")


def test_a_log_that_cannot_be_written_never_raises():
    """The third review forced a TypeError through the write itself."""
    log = StderrLog("not a descriptor")  # type: ignore[arg-type]
    log.feed(b"a\nb\n")
    log.close(4)


@pytest.mark.parametrize("error", [KeyboardInterrupt, asyncio.CancelledError])
def test_an_interrupt_is_not_swallowed(tmp_path, monkeypatch, error):
    def interrupted(self, data):
        raise error()

    monkeypatch.setattr(redaction.LineRedactor, "feed", interrupted)
    log = StderrLog(os.open(tmp_path / "log", os.O_WRONLY | os.O_CREAT
                            | getattr(os, "O_BINARY", 0), 0o600))
    with pytest.raises(error):
        log.feed(b"a\n")


def test_a_failing_log_does_not_end_the_session(tmp_path, monkeypatch):
    """Through the real transport: the server writes on stderr while the log fails."""
    def broken(self, data):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(redaction.LineRedactor, "feed", broken)
    child = "import sys; sys.stderr.buffer.write(b'x' * 100000); sys.stderr.flush()"
    descriptor = os.open(tmp_path / "log", os.O_WRONLY | os.O_CREAT
                         | getattr(os, "O_BINARY", 0), 0o600)
    state = TransportState(limit=1 << 20)

    async def session() -> None:
        async with bounded_stdio([sys.executable, "-c", child], dict(os.environ), None,
                                 descriptor, state):
            await anyio.sleep(1.0)

    try:
        anyio.run(session)  # raises (an ExceptionGroup) if the stderr reader dies
    finally:
        os.close(descriptor)
    assert state.stderr_bytes == 100_000 and state.fault is None
    assert b"the stderr log stopped here (RuntimeError)" in (tmp_path / "log").read_bytes()
