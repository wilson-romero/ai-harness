"""Masking of credentials with a known format (D8, SEC-01).

Formats are matched by provider prefix and exact shape, the same thirteen that
`claude-memory-system` measured against real prose. Generic heuristics (entropy, `key=`) are
deliberately absent: they flag prose. A credential of an unknown format passes unchanged.

Every matcher runs in time linear in the text: a note is untrusted input of up to 1 MiB, and
a pattern that backtracks over it would let a note stall the command. The private key and the
JWT are found by hand for that reason (see `private_key_spans` and `_jwt_spans`).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

Spans = Callable[[str], list[tuple[int, int]]]

_PEM_BEGIN_TEXT = "-----BEGIN "
_PEM_END_TEXT = "-----END "
_PEM_BEGIN = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----")


def private_key_spans(text: str) -> list[tuple[int, int]]:
    """Each PEM private key block, from its BEGIN line to the nearest END line.

    A block without an END line runs to the end of the text: its body cannot be told apart
    from what follows, so all of it is masked.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    while (start := text.find(_PEM_BEGIN_TEXT, pos)) >= 0:
        header = _PEM_BEGIN.match(text, start)
        if header is None:
            pos = start + 1
            continue
        end = None
        candidate = text.find(_PEM_END_TEXT, header.end())
        while candidate >= 0:
            if footer := _PEM_END.match(text, candidate):
                end = footer.end()
                break
            candidate = text.find(_PEM_END_TEXT, candidate + 1)
        if end is None:
            spans.append((start, len(text)))
            break
        spans.append((start, end))
        pos = end
    return spans


_B64 = "A-Za-z0-9_-"
# A run of base64url characters that starts a run and is followed by the JWT's other two
# segments. Possessive quantifiers: the class excludes ".", so giving back never helps.
_JWT_RUN = re.compile(
    rf"(?<![{_B64}])[{_B64}]++(?=\.eyJ[{_B64}]{{10,}}+\.[{_B64}]{{10,}}+)"
)
_JWT_TAIL = re.compile(rf"\.eyJ[{_B64}]{{10,}}+\.[{_B64}]{{10,}}+")
_JWT_HEAD = re.compile(r"\beyJ")


def _jwt_spans(text: str) -> list[tuple[int, int]]:
    """Same matches as `\\beyJ[..]{10,}\\.eyJ[..]{10,}\\.[..]{10,}`, without backtracking.

    The first segment always reaches the end of its run of base64url characters (the next
    character must be the dot), so the leftmost match starts at the first `\\beyJ` of the run
    that leaves at least ten characters before the dot. The run is scanned once.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    while run := _JWT_RUN.search(text, pos):
        run_start, run_end = run.span()
        head = _JWT_HEAD.search(text, run_start, run_end)
        if head is not None and run_end - head.start() >= len("eyJ") + 10:
            tail = _JWT_TAIL.match(text, run_end)
            assert tail is not None  # guaranteed by the lookahead of _JWT_RUN
            spans.append((head.start(), tail.end()))
            pos = tail.end()
        else:
            pos = run_end  # a JWT may still start at the next segment
    return spans


def _regex(pattern: str) -> Spans:
    compiled = re.compile(pattern)
    return lambda text: [match.span() for match in compiled.finditer(text)]


# (kind, matcher). The private key goes first: its body must be masked as a whole.
PATTERNS: tuple[tuple[str, Spans], ...] = (
    ("private-key", private_key_spans),
    ("anthropic", _regex(r"\bsk-ant-[a-z0-9]+-[A-Za-z0-9_-]{20,}")),
    ("openai", _regex(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}")),
    ("openai", _regex(r"\bsk-[A-Za-z0-9]{48}(?![A-Za-z0-9_-])")),
    ("github", _regex(r"\bgh[pousr]_[A-Za-z0-9]{36,255}(?![A-Za-z0-9_])")),
    ("github", _regex(r"\bgithub_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}(?![A-Za-z0-9_])")),
    # The legacy 20-character body and the current routable one, longer and with an optional
    # `.<version>.<suffix>` (security review of 2026-11-27, F-01). Possessive: linear.
    ("gitlab", _regex(r"\bglpat-[A-Za-z0-9_-]{20,300}+(?:\.[A-Za-z0-9]{2}\.[A-Za-z0-9]{1,32})?"
                      r"(?![A-Za-z0-9_-])")),
    ("aws", _regex(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])")),
    ("google", _regex(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    ("slack", _regex(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("digitalocean", _regex(r"\bdo[por]_v1_[a-f0-9]{64}(?![a-f0-9])")),
    ("stripe", _regex(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{24,}(?![A-Za-z0-9])")),
    ("jwt", _jwt_spans),
)


@dataclass(frozen=True)
class Redacted:
    text: str
    kinds: tuple[str, ...]  # one entry per substitution, in pattern order

    @property
    def count(self) -> int:
        return len(self.kinds)


def _redact_once(text: str) -> Redacted:
    """One pass: each pattern in `PATTERNS` order replaces its matches in the text left by the
    patterns before it (the marker a pattern leaves is a boundary for the next ones)."""
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


# A pass that changes nothing ends the loop. Not unbounded: a chain of glued tokens that each
# need the next one masked first would cost one pass per token over the whole text.
REDACT_PASSES = 4


def redact(text: str) -> Redacted:
    """Replace every known credential with `[REDACTED:<kind>]`.

    The pass above is repeated until it finds nothing (at most `REDACT_PASSES` times; revised
    2026-11-25): a credential glued to the end of another one (`dop_v1_<hex>sk-ant-...`) only
    has its boundary once the first is a marker. The first pass is the original function, so
    later passes can only mask more. Not covered: a credential whose start another pattern
    swallowed (an Anthropic or Slack key ending in the header of a JWT leaves the JWT's other
    two segments, which no pattern matches); a hand-made chain of more than four glued
    credentials that each find their boundary only once the next one is a marker (Google API
    keys whose body ends in `-`, then a Slack token): the first ones stay in clear, and nothing
    says so (the single pass of before masked only the last one).
    """
    kinds: list[str] = []
    for _ in range(REDACT_PASSES):
        result = _redact_once(text)
        if not result.kinds:
            break
        text = result.text
        kinds.extend(result.kinds)
    return Redacted(text=text, kinds=tuple(kinds))


def secret_kinds(text: str) -> Counter[str]:
    """Which credential kinds a text contains, without returning any value."""
    return Counter(redact(text).kinds)


# The stream redactor (mcp-gateway D3, revised 2026-11-25 for the fourth time: simplified).
# A line ends at LF, CRLF or a lone CR. A line of at most `STREAM_LINE_BYTES`, its end included,
# goes through `redact` whole; a longer one is never redacted in parts: it is dropped, with a
# marker.
STREAM_LINE_BYTES = 16 * 1024
# A private key block hides at most this many bytes after its BEGIN header (a 16384-bit RSA
# key in PEM is about 13 KiB); past that a marker says so and the next line is handled as usual.
STREAM_KEY_BYTES = 32 * 1024
LONG_LINE_MARKER = "[ai-harness: a line of {size} bytes was dropped: too long to redact]\n"
KEY_BOUND_MARKER = ("[ai-harness: no END line within {limit} bytes of a private key header; "
                    "the rest of this line is dropped]\n")
_LINE_END = re.compile(rb"\r\n|\r|\n")
_PEM_MARK = re.compile(rb"-----(BEGIN|END) (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_MARK_WINDOW = 256  # bytes of a line kept to find a header or footer split across reads


@dataclass(frozen=True)
class Piece:
    """What `LineRedactor` releases: `output` to write, standing for `raw` input bytes, which
    are in the log (as text or as a credential's marker) only if `kept`."""

    raw: int
    output: bytes
    kept: bool


class LineRedactor:
    """`redact` over a byte stream that arrives in arbitrary chunks (mcp-gateway D3, SEC-01).

    A line ends at LF, CRLF or a lone CR; a CR at the end of a read waits for the next byte,
    so a CRLF is one line also when a read splits it. A
    line of at most `line_bytes` (its line end included) is redacted whole; a longer one is dropped
    up to its line end and replaced by one marker: a credential in it is not written, and
    neither is the rest of that line. From a line with a private key's BEGIN header to the line
    with its END, the lines after the header line are dropped; if the END is not within
    `key_bytes` after the header, a marker says so and logging goes on at the next line.

    Only the current line is held (at most `line_bytes`). Whole terminal escape sequences are
    dropped before a line is redacted. Bytes that are not UTF-8 pass unchanged
    (`surrogateescape`). No input makes it raise. Not covered: a credential of a
    format `redact` does not know; a header or footer longer than 256 bytes split across reads;
    a key block longer than `key_bytes`; the unfinished line if `finish` is never called.
    """

    def __init__(self, line_bytes: int = STREAM_LINE_BYTES,
                 key_bytes: int = STREAM_KEY_BYTES) -> None:
        self._line_bytes, self._key_bytes = line_bytes, key_bytes
        self._line = bytearray()  # the current line while it is within the limit
        self._size = 0  # bytes of the current line so far
        self._tail = b""  # its last bytes, to find a header or footer split across reads
        self._in_key = False  # the current line started inside a private key block
        self._open = False  # a private key block is open at this point of the stream
        self._key_seen = 0  # bytes after the BEGIN header of the open block
        self._cr = False  # the line taken so far ends with a CR that may be followed by a LF

    @property
    def pending(self) -> int:
        return len(self._line)

    def feed(self, data: bytes) -> list[Piece]:
        out: list[Piece] = []
        pos = 0
        if self._cr and data:  # the last read ended with a CR: it ends its line either way
            if data[:1] == b"\n":
                self._take(b"\n", out)
                pos = 1
            out.append(self._end_line())
        while pos < len(data):
            end = _LINE_END.search(data, pos)
            stop = end.end() if end else len(data)
            self._take(data[pos:stop], out)
            if end and end.group() == b"\r" and stop == len(data):
                self._cr = True
            elif end:
                out.append(self._end_line())
            pos = stop
        return out

    def finish(self) -> list[Piece]:
        """The stream ended: its last line, even without a line end, is complete."""
        return [self._end_line()] if self._size else []

    def _take(self, part: bytes, out: list[Piece]) -> None:
        self._watch_keys(part, out)
        self._size += len(part)
        if self._in_key or self._size > self._line_bytes:
            self._line.clear()
        else:
            self._line += part

    def _end_line(self) -> Piece:
        size = self._size
        if self._in_key:
            piece = Piece(size, b"", False)
        elif size > self._line_bytes:
            piece = Piece(size, LONG_LINE_MARKER.format(size=size).encode("ascii"), False)
        else:  # the line end stays: a key block without END would otherwise swallow it
            body = bytes(self._line).rstrip(b"\r\n")  # a line holds one line end at most
            end = bytes(self._line[len(body):])
            # Whole escape sequences go first (security review of 2026-11-27, F-02): a
            # credential right after a colour code has no word boundary and would stay in
            # clear. The log keeps the text without them.
            from harness.text.safe_text import drop_escape_sequences  # it imports this module

            clean = drop_escape_sequences(_text(body))
            piece = Piece(size, _encoded(redact(clean).text) + end, True)
        self._line.clear()
        self._size, self._tail, self._in_key, self._cr = 0, b"", self._open, False
        return piece

    def _watch_keys(self, part: bytes, out: list[Piece]) -> None:
        """Follow BEGIN headers and END footers through `part`, counting the bytes after an
        open header; past `key_bytes` the block is abandoned, with a marker."""
        window = self._tail + part
        skip = len(self._tail)
        counted = 0  # bytes of `part` already counted
        search = 0
        while mark := _PEM_MARK.search(window, search):
            search = mark.start() + 1  # every position: a footer may end where a header starts
            if mark.end() <= skip:
                continue  # seen in an earlier part
            at = mark.end() - skip
            self._count(at - counted, out)
            counted = at
            if mark.group(1) == b"BEGIN":
                self._open, self._key_seen = True, 0
            else:
                self._open = False
        self._count(len(part) - counted, out)
        self._tail = window[-_MARK_WINDOW:]

    def _count(self, size: int, out: list[Piece]) -> None:
        if not self._open:
            return
        self._key_seen += size
        if self._key_seen > self._key_bytes:
            self._open = False
            out.append(Piece(0, KEY_BOUND_MARKER.format(limit=self._key_bytes).encode(), False))


def _encoded(text: str) -> bytes:
    return text.encode("utf-8", "surrogateescape")


def _text(data: bytes | bytearray) -> str:
    return bytes(data).decode("utf-8", "surrogateescape")
