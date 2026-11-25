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
    ("gitlab", _regex(r"\bglpat-[A-Za-z0-9_-]{20}(?![A-Za-z0-9_-])")),
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


def redact(text: str) -> Redacted:
    """Replace every known credential with `[REDACTED:<kind>]`."""
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


def secret_kinds(text: str) -> Counter[str]:
    """Which credential kinds a text contains, without returning any value."""
    return Counter(redact(text).kinds)


# The stream redactor (mcp-gateway D3, revised 2026-11-25 twice). A line longer than
# `STREAM_LINE_BYTES` without its end is released in parts; the cut is never placed inside a
# credential found in the whole pending text, and the last `STREAM_HOLD_BYTES` always wait.
STREAM_LINE_BYTES = 64 * 1024
STREAM_HOLD_BYTES = 8 * 1024
# A private key header without its END line drops what follows for at most this many bytes
# (a 16384-bit RSA key in PEM is about 13 KiB); past it, logging resumes after a marker.
STREAM_KEY_BYTES = 32 * 1024


@dataclass(frozen=True)
class Piece:
    """What `LineRedactor` releases: `output` stands for `raw` input bytes, of which `withheld`
    (the body of a private key block) are in no form in it."""

    raw: int
    output: bytes
    withheld: int = 0


def _line_end(buffer: bytearray, pos: int) -> int:
    """End (exclusive) of the first complete line at or after `pos`, or -1. A line ends with
    LF, CRLF or a lone CR (a progress bar); a CR at the very end waits for the next byte."""
    newline = buffer.find(b"\n", pos)
    cr = buffer.find(b"\r", pos, newline if newline >= 0 else len(buffer))
    if cr < 0:
        return newline + 1 if newline >= 0 else -1
    if cr + 1 == len(buffer):
        return -1
    return cr + 2 if buffer[cr + 1] == 0x0A else cr + 1


def _encoded(text: str) -> bytes:
    return text.encode("utf-8", "surrogateescape")


class LineRedactor:
    """`redact` over a byte stream that arrives in arbitrary chunks (mcp-gateway D3, SEC-01).

    Text is redacted one complete line at a time (LF, CRLF or a lone CR end a line), so a
    credential split across reads is still found; the unfinished tail waits in a buffer. The
    buffer is bounded: when an unfinished line passes `line_bytes`, the credentials are found
    in the whole pending text and the text is released up to a cut that leaves at least
    `hold_bytes` waiting and never falls inside a credential (the cut moves back to the start
    of the credential). So a credential no longer than `hold_bytes` is never split. One that
    starts the buffer and is longer than `line_bytes - hold_bytes` is released whole, as its
    redaction marker, at once.

    A PEM private key spans lines: as in `redact`, a BEGIN header anywhere in a line masks the
    rest of that line, and the following lines are withheld until the END line, for at most
    `key_bytes`; past that, a marker says so and redacted logging resumes. Bytes that are not
    UTF-8 pass through unchanged (`surrogateescape`) and never raise.

    Not covered: a credential longer than `hold_bytes` that straddles a cut; a format that
    `redact` does not know; whatever is still buffered if the process dies before `finish`.
    """

    def __init__(self, line_bytes: int = STREAM_LINE_BYTES,
                 hold_bytes: int = STREAM_HOLD_BYTES, key_bytes: int = STREAM_KEY_BYTES) -> None:
        if not 0 < hold_bytes < line_bytes:
            raise ValueError("the hold must be smaller than the line bound")
        self._line_bytes, self._hold_bytes, self._key_bytes = line_bytes, hold_bytes, key_bytes
        self._pending = bytearray()
        self._scanned = 0  # bytes at the start of `_pending` known to hold no line end
        self._in_key = False  # inside a private key block whose END has not been seen
        self._key_seen = 0  # bytes withheld in the current key block

    @property
    def pending(self) -> int:
        return len(self._pending)

    def feed(self, data: bytes) -> list[Piece]:
        self._pending += data
        out: list[Piece] = []
        start = 0
        while (end := _line_end(self._pending, max(self._scanned, start))) >= 0:
            out.append(self._emit(_text(self._pending[start:end])))
            start = end
        del self._pending[:start]
        self._scanned = max(0, len(self._pending) - 1)  # a final CR is looked at again
        while len(self._pending) > self._line_bytes:
            out.append(self._cut())
        return out

    def finish(self) -> list[Piece]:
        """The stream ended: its last line, even without a line end, is complete."""
        if not self._pending:
            return []
        out = [self._emit(_text(self._pending))]
        self._pending.clear()
        self._scanned = 0
        return out

    def _cut(self) -> Piece:
        text = _text(self._pending)
        cut = len(self._pending) - self._hold_bytes
        while cut > 0 and self._pending[cut] & 0xC0 == 0x80:  # not inside a UTF-8 character
            cut -= 1
        at = len(_text(self._pending[:cut]))
        spans = [span for _, spans_of in PATTERNS for span in spans_of(text)]
        moved = True
        while moved:  # back to the start of any credential the cut would split
            moved = False
            for start, end in spans:
                if start < at < end:
                    at, moved = start, True
        if at == 0:  # a credential starts the buffer and is longer than the bound
            at = max(end for start, end in spans if start == 0)
            moved = True
            while moved:
                moved = False
                for start, end in spans:
                    if start < at < end:
                        at, moved = end, True
        self._pending = bytearray(_encoded(text[at:]))
        self._scanned = max(0, len(self._pending) - 1)
        return self._emit(text[:at])

    def _emit(self, text: str) -> Piece:
        raw = len(_encoded(text))
        withheld = 0
        if self._in_key:
            footer = _PEM_END.search(text)
            if footer is None:
                self._key_seen += raw
                if self._key_seen <= self._key_bytes:
                    return Piece(raw, b"", raw)
                self._in_key = False  # bounded: this part is withheld, what follows is logged
                return Piece(raw, _encoded(
                    f"[ai-harness: no END line within {self._key_bytes} bytes of a private key "
                    "header; logging resumes]\n"), raw)
            withheld = len(_encoded(text[:footer.end()]))
            text = text[footer.end():]
            self._in_key = False
        spans = private_key_spans(text)
        if spans and spans[-1][1] == len(text) and _PEM_END.search(text, spans[-1][0]) is None:
            self._in_key, self._key_seen = True, 0  # its END comes in a later line
        return Piece(raw, _encoded(redact(text).text), withheld)


def _text(data: bytes | bytearray) -> str:
    return bytes(data).decode("utf-8", "surrogateescape")
