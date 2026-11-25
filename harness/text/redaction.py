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


# A line longer than this, still without its newline, is cut before it is complete; the last
# `STREAM_HOLD_BYTES` stay buffered, so a credential up to that long is never split by the cut.
STREAM_LINE_BYTES = 64 * 1024
STREAM_HOLD_BYTES = 8 * 1024


class LineRedactor:
    """`redact` over a byte stream that arrives in arbitrary chunks (mcp-gateway D4, SEC-01).

    A credential can straddle two chunks, so text is redacted one complete line at a time; the
    unfinished tail stays buffered. The buffer is bounded: a line that passes
    `STREAM_LINE_BYTES` without a newline is redacted and released up to its last
    `STREAM_HOLD_BYTES`, which stay for the next chunk. Only a credential longer than that
    hold, in a line longer than the bound, can be split by the cut (documented limit).

    A PEM private key spans lines: from a BEGIN line without its END, every following line is
    dropped until the END line, as `redact` masks the block as a whole. Bytes that are not
    UTF-8 pass through unchanged (`surrogateescape`) and never raise.

    `feed` and `finish` return `(raw_bytes, output)` pairs: how many input bytes each output
    stands for, so that a writer with a size cap can say how much of the input it kept.
    """

    def __init__(self, line_bytes: int = STREAM_LINE_BYTES,
                 hold_bytes: int = STREAM_HOLD_BYTES) -> None:
        if not 0 < hold_bytes < line_bytes:
            raise ValueError("the hold must be smaller than the line bound")
        self._line_bytes, self._hold_bytes = line_bytes, hold_bytes
        self._pending = bytearray()
        self._scanned = 0  # bytes at the start of `_pending` known to hold no newline
        self._in_key = False  # inside a private key block whose END has not been seen

    @property
    def pending(self) -> int:
        return len(self._pending)

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._pending += data
        out: list[tuple[int, bytes]] = []
        start = 0
        while (newline := self._pending.find(b"\n", max(self._scanned, start))) >= 0:
            out.append(self._emit(bytes(self._pending[start:newline + 1])))
            start = self._scanned = newline + 1
        del self._pending[:start]
        self._scanned = len(self._pending)
        if len(self._pending) > self._line_bytes:
            cut = len(self._pending) - self._hold_bytes
            out.append(self._emit(bytes(self._pending[:cut])))
            del self._pending[:cut]
            self._scanned = len(self._pending)
        return out

    def finish(self) -> list[tuple[int, bytes]]:
        """The stream ended: its last line, even without a newline, is complete."""
        if not self._pending:
            return []
        out = [self._emit(bytes(self._pending))]
        self._pending.clear()
        self._scanned = 0
        return out

    def _emit(self, raw: bytes) -> tuple[int, bytes]:
        text = raw.decode("utf-8", "surrogateescape")
        if self._in_key:
            footer = _PEM_END.search(text)
            if footer is None:
                return len(raw), b""  # the body of a key already masked
            text = text[footer.end():]
            self._in_key = False
        spans = private_key_spans(text)
        if spans and spans[-1][1] == len(text) and _PEM_END.search(text, spans[-1][0]) is None:
            self._in_key = True  # its END comes in a later line
        return len(raw), redact(text).text.encode("utf-8", "surrogateescape")
