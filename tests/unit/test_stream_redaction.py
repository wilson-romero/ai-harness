"""SEC-01 over a stream: the server's stderr is redacted before its log keeps it (2026-11-25).

`LineRedactor` sees the stream in arbitrary chunks; `StderrLog` writes what it releases under
the log's budgets. Every sample credential is assembled at run time (here or in
`tests/conftest.py`), so that no versioned file contains one.
"""

from __future__ import annotations

import os
import random
import string
import sys

import anyio
import pytest

from harness.mcp import transport
from harness.mcp.transport import StderrLog, TransportState, bounded_stdio
from harness.text import redaction
from harness.text.redaction import (
    STREAM_HOLD_BYTES,
    STREAM_KEY_BYTES,
    STREAM_LINE_BYTES,
    LineRedactor,
    redact,
)
from tests.conftest import PRIVATE_KEY_SAMPLE, SECRET_SAMPLES

TOKEN = SECRET_SAMPLES["github"]
HEADER, *BODY, FOOTER = PRIVATE_KEY_SAMPLE.splitlines()
ANTHROPIC = "sk-" + "ant-" + "api03-"
SLACK = "xo" + "xb-"


def pieces_of(redactor: LineRedactor, chunks: list[bytes], finish: bool = True):
    pieces = [piece for chunk in chunks for piece in redactor.feed(chunk)]
    return pieces + (redactor.finish() if finish else [])


def run(redactor: LineRedactor, chunks: list[bytes], finish: bool = True) -> bytes:
    return b"".join(piece.output for piece in pieces_of(redactor, chunks, finish))


def chunked(data: bytes, size: int) -> list[bytes]:
    return [data[i:i + size] for i in range(0, len(data), size)]


# -- lines and cuts ------------------------------------------------------------------------------


def test_the_bounds_are_the_documented_ones():
    """Pins the constants the docs state (mutant M10: a hold of half the size)."""
    assert (STREAM_LINE_BYTES, STREAM_HOLD_BYTES, STREAM_KEY_BYTES) == (65536, 8192, 32768)
    redactor = LineRedactor()
    redactor.feed(b"." * (STREAM_LINE_BYTES + 1))
    assert redactor.pending == STREAM_HOLD_BYTES


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
    assert b"".join(p.output for p in redactor.feed(b"\nb\n")) == b"a\r\nb\n"


def test_a_progress_bar_with_lone_cr_read_in_4k_chunks_never_shows_the_token():
    bar = "".join(f"{n:>3}% {TOKEN}\r" for n in range(2000)).encode("ascii")
    out = run(LineRedactor(), chunked(bar, 4096))
    assert TOKEN.encode("ascii")[8:] not in out
    assert out.count(b"[REDACTED:github]") == 2000


def test_a_line_without_end_is_cut_and_keeps_its_token_whole():
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
    """Wherever the token falls relative to the cuts, the stream gives what `redact` gives
    on the whole text (finding 1 of the first review)."""
    token = TOKEN.encode("ascii")
    for offset in range(700, 1100):
        data = b"." * offset + b" " + token + b" " + b"." * (2600 - offset)
        out = run(LineRedactor(line_bytes=1024, hold_bytes=128), chunked(data, size))
        assert out == redact(data.decode("ascii")).text.encode("ascii"), (size, offset)


def test_the_review_case_a_70000_byte_chunk_with_the_token_across_the_cut():
    token = TOKEN.encode("ascii")
    cut = 70_000 - STREAM_HOLD_BYTES
    for back in range(1, len(token)):
        start = cut - back
        data = b"." * (start - 1) + b" " + token + b" " + b"." * (70_000 - start - len(token) - 1)
        out = run(LineRedactor(), [data], finish=False)
        assert token[4:] not in out and token[:20] not in out, back


def test_overlapping_credentials_at_the_cut_are_never_split():
    """Mutant M2: an Anthropic key whose tail is the start of a JWT, across the cut."""
    secret = (ANTHROPIC + "abcdefghij-" + "ey" + "J" + "P" * 40 + ".ey" + "J" + "Q" * 40
              + "." + "S" * 40)
    for offset in range(900, 1000):
        data = ("." * offset + " " + secret + " " + "." * 400).encode("ascii")
        out = run(LineRedactor(line_bytes=1024, hold_bytes=300), chunked(data, 64))
        assert b"PPPP" not in out and b"QQQQ" not in out and b"SSSS" not in out, offset


def test_a_credential_longer_than_the_bound_is_hidden_to_its_end():
    """Finding 3: the rest of an oversized credential is withheld until it ends."""
    data = b"x " + (SLACK + "Q" * 100_000).encode("ascii") + b" end\n"
    pieces = pieces_of(LineRedactor(), chunked(data, 4096))
    out = b"".join(p.output for p in pieces)
    assert out == b"x [REDACTED:slack] end\n"
    assert sum(p.raw for p in pieces) == len(data)


def test_overlapping_credentials_longer_than_the_bound_are_hidden_whole():
    """Mutant M3: the cut is extended over every credential that starts the buffer."""
    secret = ANTHROPIC + "a" * 1500 + "-" + "ey" + "J" + "P" * 800 + ".ey" + "J" + "Q" * 40
    data = (secret + "." + "S" * 40 + " fin\n").encode("ascii")
    out = run(LineRedactor(line_bytes=1024, hold_bytes=128), chunked(data, 100))
    assert out == b"[REDACTED:anthropic] fin\n"


# -- bytes that are not UTF-8 ----------------------------------------------------------------------


@pytest.mark.parametrize("data", [b"\x80" * 70_000, b"A" + b"\x80" * 70_000,
                                  b"\xc3" + b"\x80" * 70_000], ids=["cont", "ascii", "lead"])
def test_a_burst_of_continuation_bytes_never_raises(data):
    """Finding 1 of the second review: the UTF-8 walk-back reached 0 and `max()` raised."""
    for size in (len(data), 4096):
        redactor = LineRedactor()
        pieces = pieces_of(redactor, chunked(data, size))
        assert b"".join(p.output for p in pieces) == data
        assert sum(p.raw for p in pieces) == len(data)


def test_a_cut_never_splits_a_valid_character():
    data = ("é" * 40_000).encode("utf-8")  # two bytes each, no line end
    pieces = pieces_of(LineRedactor(), chunked(data, 999))
    for piece in pieces:
        piece.output.decode("utf-8")  # every piece is valid UTF-8 on its own
    assert b"".join(p.output for p in pieces) == data


def test_a_cut_inside_a_character_moves_back_and_keeps_the_whole_hold():
    """Mutant M7: without the walk-back the hold loses the bytes of a split character."""
    data = ("é" * 33_000 + "a").encode("utf-8")  # the cut falls inside an "é"
    redactor = LineRedactor()
    assert redactor.feed(data)
    assert redactor.pending == STREAM_HOLD_BYTES + 1


def test_invalid_utf8_passes_unchanged():
    data = b"\xff\xfe roto \xc3 " + TOKEN.encode("ascii") + b" \xe2\x82\n"
    out = run(LineRedactor(), [data[:5], data[5:]])
    assert out == b"\xff\xfe roto \xc3 [REDACTED:github] \xe2\x82\n"


# -- private keys ---------------------------------------------------------------------------------


def test_a_private_key_across_lines_and_chunks_is_masked_whole():
    data = f"clave:\n{PRIVATE_KEY_SAMPLE}\nfin\n".encode("ascii")
    expected = b"clave:\n[REDACTED:private-key]\nfin\n"
    for size in (1, 7, 64, len(data)):
        assert run(LineRedactor(), chunked(data, size)) == expected, size


def test_a_key_block_on_one_line_masks_only_the_block():
    data = f"a {HEADER} x {FOOTER} b\n".encode("ascii")
    assert run(LineRedactor(), [data]) == b"a [REDACTED:private-key] b\n"
    assert redact(data.decode("ascii")).text == "a [REDACTED:private-key] b\n"


def test_a_key_without_end_masks_what_follows_within_the_bound():
    out = run(LineRedactor(), [f"{HEADER}\n{'K' * 64}\nmas\n".encode("ascii")])
    assert out == b"[REDACTED:private-key]"


def test_a_key_without_end_is_withheld_for_exactly_the_bound_in_bytes():
    """Finding 2: the bound is in bytes, also for one huge line in one chunk."""
    data = (HEADER + "\n").encode("ascii") + b"S" * (1 << 20) + b"\nvisible\n"
    for chunks in ([data], chunked(data, 65536)):
        pieces = pieces_of(LineRedactor(), chunks)
        out = b"".join(p.output for p in pieces)
        assert sum(p.withheld for p in pieces) == STREAM_KEY_BYTES
        assert out.startswith(b"[REDACTED:private-key][ai-harness: no END line within 32768")
        assert out.endswith(b"\nvisible\n")


def test_the_key_bound_is_inclusive():
    """Mutant M4: a block of exactly `key_bytes` from its header is masked whole."""
    block = f"{HEADER}\n{BODY[0]}\n{FOOTER}"
    data = f"{block}\nfin\n".encode("ascii")
    exact = len(block.encode("ascii"))
    assert run(LineRedactor(key_bytes=exact), [data]) == b"[REDACTED:private-key]\nfin\n"
    assert b"no END line" in run(LineRedactor(key_bytes=exact - 1), [data])


def test_a_second_key_has_a_bound_of_its_own():
    """Mutant M5: the count of hidden bytes starts again at each header."""
    first = f"{HEADER}\n{'K' * 64}\n{FOOTER}\n"
    second = f"{HEADER}\n{'Z' * 64}\n{FOOTER}\n"
    limit = len(first.encode("ascii"))
    out = run(LineRedactor(key_bytes=limit), [(first + second + "fin\n").encode("ascii")])
    assert out == b"[REDACTED:private-key]\n[REDACTED:private-key]\nfin\n"


def test_a_key_without_end_stops_being_withheld_at_the_bound():
    redactor = LineRedactor(key_bytes=1000)
    lines = [f"linea {n:04d}\n".encode("ascii") for n in range(200)]
    pieces = pieces_of(redactor, [f"antes {HEADER} resto\n".encode("ascii"), *lines])
    out = b"".join(p.output for p in pieces)
    assert out.startswith(b"antes [REDACTED:private-key]")
    assert b"no END line within 1000 bytes of a private key header; logging resumes" in out
    assert out.endswith(b"linea 0199\n") and b"linea 0050\n" not in out
    assert sum(p.withheld for p in pieces) == 1000


def test_a_key_header_across_the_cut_still_withholds_the_body():
    first = ("z" * 60_000 + HEADER + " " * 8182).encode("ascii")
    rest = ("\n" + "\n".join(BODY) + "\n" + FOOTER + "\nfin\n").encode("ascii")
    out = run(LineRedactor(), [first, rest])
    assert BODY[0].encode("ascii") not in out and BODY[1].encode("ascii") not in out
    assert out.endswith(b"[REDACTED:private-key]\nfin\n")


# -- redact itself: overlapping formats -----------------------------------------------------------


@pytest.mark.parametrize("prefix,kind", [(ANTHROPIC + "abcdefghij-", "anthropic"),
                                         (SLACK + "abcdefghij-", "slack")])
def test_overlapping_formats_leave_nothing_behind(prefix, kind):
    """Finding 4: replacing one match first left half a JWT that nothing matched."""
    secret = prefix + "ey" + "J" + "P" * 20 + ".ey" + "J" + "Q" * 20 + "." + "S" * 30
    text = f"a {secret} b\n"
    expected = f"a [REDACTED:{kind}] b\n"
    assert redact(text).text == expected and redact(text).kinds == (kind,)
    for size in (1, 5, len(text)):
        assert run(LineRedactor(), chunked(text.encode("ascii"), size)) == expected.encode()


# -- seeded fuzz ----------------------------------------------------------------------------------


ALNUM = string.ascii_letters + string.digits
B64 = ALNUM + "_-"


def _random(rng: random.Random, n: int, alphabet: str = ALNUM) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def _credential(rng: random.Random) -> str:
    kind = rng.randrange(8)
    if kind == 0:
        return ANTHROPIC + _random(rng, rng.randint(20, 120), B64)
    if kind == 1:
        return "gh" + "p_" + _random(rng, rng.randint(36, 80))
    if kind == 2:
        return "AK" + "IA" + _random(rng, 16, string.ascii_uppercase + string.digits)
    if kind == 3:
        return SLACK + _random(rng, rng.randint(10, 120), ALNUM + "-")
    if kind == 4:
        return "sk" + "_live_" + _random(rng, rng.randint(24, 60))
    if kind == 5:
        return ("ey" + "J" + _random(rng, rng.randint(10, 60), B64) + ".ey" + "J"
                + _random(rng, rng.randint(10, 60), B64) + "." + _random(rng, 20, B64))
    if kind == 6:
        body = "\n".join(_random(rng, 64, ALNUM + "+/") for _ in range(rng.randint(1, 6)))
        return f"{HEADER}\n{body}\n{FOOTER}"
    return "AI" + "za" + _random(rng, 35, B64)


def _stream(rng: random.Random, long_lines: bool) -> tuple[bytes, list[str]]:
    parts, secrets = [], []
    for _ in range(rng.randint(1, 30)):
        roll = rng.random()
        if roll < 0.4:
            secret = _credential(rng)
            parts.append(secret)
            secrets.append(secret)
        elif roll < 0.5 and long_lines:
            parts.append(_random(rng, rng.randint(200, 2400), ALNUM + "  ..::é€"))
        else:
            parts.append(_random(rng, rng.randint(0, 40), ALNUM + "  ..::é€"))
        parts.append(rng.choice([" ", "\n", "\r\n", "\r", "\t", ", ", " \x00 "]))
    return "".join(parts).encode("utf-8"), secrets


def _chunks(rng: random.Random, data: bytes) -> list[bytes]:
    out, i = [], 0
    mode = rng.choice(["one", "small", "big"])
    while i < len(data):
        n = 1 if mode == "one" else rng.randint(1, 9) if mode == "small" else rng.randint(1, 5000)
        out.append(data[i:i + n])
        i += n
    return out


@pytest.mark.parametrize("seed", range(4))
def test_seeded_fuzz_short_lines_match_redact_on_the_whole_text(seed):
    """Differential: with lines under the bound, the stream equals `redact` of the whole."""
    rng = random.Random(seed)
    for _ in range(60):
        data, _ = _stream(rng, long_lines=False)
        out = run(LineRedactor(line_bytes=4096, hold_bytes=1024), _chunks(rng, data))
        assert out == redact(data.decode("utf-8")).text.encode("utf-8")


@pytest.mark.parametrize("seed", range(4))
def test_seeded_fuzz_long_lines_never_leak_a_credential_within_the_hold(seed):
    rng = random.Random(1000 + seed)
    for _ in range(40):
        data, secrets = _stream(rng, long_lines=True)
        redactor = LineRedactor(line_bytes=1024, hold_bytes=512, key_bytes=100_000)
        pieces = []
        for chunk in _chunks(rng, data):
            pieces += redactor.feed(chunk)
            assert redactor.pending <= 1024
        pieces += redactor.finish()
        assert sum(p.raw for p in pieces) == len(data)
        flat = b"".join(p.output for p in pieces).decode("utf-8", "surrogateescape")
        flat = flat.replace("\n", "").replace("\r", "")
        for secret in secrets:
            body = secret.replace("\n", "")
            for i in range(0, len(body) - 12, 3):
                window = body[i:i + 12]
                assert "-----" in window or window not in flat, secret[:12]


@pytest.mark.parametrize("seed", range(4))
def test_seeded_fuzz_arbitrary_bytes_never_raise_and_account_for_every_byte(seed, tmp_path,
                                                                            monkeypatch):
    rng = random.Random(2000 + seed)
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 3000)
    alphabet = [b"\x80", b"\xc3", b"\xe2\x82", b"\xff", b"\r", b"\n", b"a", b".", b" ",
                b"-----BEGIN ", b"-----END ", b"PRIVATE KEY-----", b"ey" + b"J", b"\xf0\x9f"]
    for _ in range(30):
        data = b"".join(rng.choice(alphabet) * rng.randint(1, 300) for _ in range(60))
        redactor = LineRedactor(line_bytes=700, hold_bytes=200, key_bytes=900)
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
        assert (dropped == 0) == (b"more bytes of stderr were dropped]" not in written)
        if dropped:
            assert written.endswith(f"[ai-harness: {dropped} more bytes of stderr were "
                                    "dropped]\n".encode())


def test_the_hold_must_be_smaller_than_the_bound():
    with pytest.raises(ValueError):
        LineRedactor(line_bytes=10, hold_bytes=10)


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


def test_the_log_caps_and_counts_what_it_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 100)
    log = write_log(tmp_path / "log", [b"E" * 70 + b"\n", b"F" * 70 + b"\n"])
    kept, marker = log[:100], log[100:]
    assert kept == b"E" * 70 + b"\n" + b"F" * 29
    assert marker == b"\n[ai-harness: 42 more bytes of stderr were dropped]\n"


def test_the_cap_inside_lines_of_one_batch_counts_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "STDERR_KEEP_BYTES", 30)
    log = write_log(tmp_path / "log", [f"a {TOKEN}\nbbbbbbbbbb\ncccc\n".encode("ascii")])
    # 20 bytes of output stand for the 43 of the first line; 10 of the second fit
    assert log.startswith(b"a [REDACTED:github]\nbbbbbbbbbb\n[ai-harness:")
    assert log.endswith(f"[ai-harness: {59 - 53} more bytes of stderr were dropped]\n".encode())


def test_a_marker_cut_by_the_cap_still_gets_its_count_line(tmp_path):
    """Finding 6: the marker is longer than the token; the cap cuts it."""
    log = write_log(tmp_path / "log", [(SLACK + "1234567890\n").encode("ascii")], room=16)
    assert log == b"[REDACTED:slack]\n[ai-harness: 16 more bytes of stderr were dropped]\n"


def test_a_withheld_key_block_is_counted_as_absent_from_the_log(tmp_path):
    log = write_log(tmp_path / "log", [f"a\n{PRIVATE_KEY_SAMPLE}\nb\n".encode("ascii")])
    assert log == (b"a\n[REDACTED:private-key]\nb\n" + f"\n[ai-harness: "
                   f"{len(PRIVATE_KEY_SAMPLE)} more bytes of stderr were dropped]\n".encode())


def test_hostile_key_cycles_cannot_buy_unbounded_work(tmp_path, monkeypatch):
    """Finding 5: withheld text does not reach the cap; the work budget stops it."""
    monkeypatch.setattr(transport, "STDERR_WORK_BYTES", 200_000)
    cycle = (HEADER + "\n").encode("ascii") + b"a\n" * 17_000
    descriptor = os.open(tmp_path / "log", os.O_WRONLY | os.O_CREAT, 0o600)
    log = StderrLog(descriptor)
    fed = []
    real = log._redactor.feed

    def counting(chunk):
        fed.append(len(chunk))
        return real(chunk)

    log._redactor.feed = counting
    try:
        for _ in range(100):
            log.feed(cycle)
        log.close(100 * len(cycle))
    finally:
        os.close(descriptor)
    assert sum(fed) <= 200_000 + len(cycle)


def test_a_failure_inside_the_log_is_marked_and_never_raises(tmp_path, monkeypatch):
    def broken(self, data):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(redaction.LineRedactor, "feed", broken)
    log = write_log(tmp_path / "log", [b"a\n", b"b\n"])
    assert log == (b"\n[ai-harness: the stderr log stopped here (RuntimeError); the rest is "
                   b"counted, not kept]\n\n[ai-harness: 4 more bytes of stderr were dropped]\n")


def test_a_failing_log_does_not_end_the_session(tmp_path, monkeypatch):
    """Through the real transport: the server writes on stderr while the log fails."""
    def broken(self, data):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(redaction.LineRedactor, "feed", broken)
    child = "import sys; sys.stderr.buffer.write(b'x' * 100000); sys.stderr.flush()"
    descriptor = os.open(tmp_path / "log", os.O_WRONLY | os.O_CREAT, 0o600)
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
