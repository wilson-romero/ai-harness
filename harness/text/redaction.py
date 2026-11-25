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


def _groups(text: str, first: int = 0) -> list[tuple[int, int, int]]:
    """Every credential span of every pattern from `PATTERNS[first]` on, found on the
    original text, merged where they overlap: (start, end, index of the first pattern in
    `PATTERNS` order among them)."""
    found = sorted((start, end, order) for order, (_, spans_of) in enumerate(PATTERNS)
                   if order >= first for start, end in spans_of(text))
    groups: list[tuple[int, int, int]] = []
    for start, end, order in found:
        if groups and start < groups[-1][1]:
            last_start, last_end, last_order = groups[-1]
            groups[-1] = (last_start, max(last_end, end), min(last_order, order))
        else:
            groups.append((start, end, order))
    return groups


def redact(text: str) -> Redacted:
    """Replace every known credential with `[REDACTED:<kind>]`.

    All patterns run on the original text and overlapping matches become one substitution
    (revised 2026-11-25): replacing one pattern's match first could leave the rest of an
    overlapping one (half a JWT after an Anthropic key) that no pattern matches any more. The
    kind is that of the first pattern, in `PATTERNS` order, among the overlapping ones.
    """
    groups = _groups(text)
    parts: list[str] = []
    last = 0
    for start, end, order in groups:
        parts += [text[last:start], f"[REDACTED:{PATTERNS[order][0]}]"]
        last = end
    parts.append(text[last:])
    kinds = tuple(PATTERNS[order][0] for order in sorted(order for _, _, order in groups))
    return Redacted(text="".join(parts), kinds=kinds)


def secret_kinds(text: str) -> Counter[str]:
    """Which credential kinds a text contains, without returning any value."""
    return Counter(redact(text).kinds)


# The stream redactor (mcp-gateway D3, revised 2026-11-25 three times). Complete lines are
# redacted in batches; a line longer than `STREAM_LINE_BYTES` without its end is released in
# parts, cut outside every credential found in the whole pending text, and the last
# `STREAM_HOLD_BYTES` always wait.
STREAM_LINE_BYTES = 64 * 1024
STREAM_HOLD_BYTES = 8 * 1024
# A private key block hides at most this many bytes from the start of its header (a 16384-bit
# RSA key in PEM is about 13 KiB); a block whose END comes later is cut there, with a marker.
STREAM_KEY_BYTES = 32 * 1024
KEY_BOUND_MARKER = ("[ai-harness: no END line within {limit} bytes of a private key header; "
                    "logging resumes]\n")
# What can continue a credential released before it ended: the characters of every format
# but the private key.
_NOT_CREDENTIAL = re.compile(rb"[^A-Za-z0-9_.\-]")


@dataclass(frozen=True)
class Piece:
    """What `LineRedactor` releases: `output` stands for `raw` input bytes (`source`), of
    which `withheld` (a private key block, the rest of an oversized credential) are in it at
    most as a marker."""

    raw: int
    output: bytes
    withheld: int = 0
    source: bytes = b""

    def kept_within(self, room: int) -> int:
        """Input bytes represented by the first `room` bytes of `output`. Exact, except when
        the cut falls on a piece with withheld bytes or inside a changed line: those count as
        absent (it can over-count what is missing, never under-count)."""
        if room >= len(self.output):
            return self.raw - self.withheld
        if self.withheld:
            return 0
        sources = self.source.splitlines(keepends=True)
        outputs = self.output.splitlines(keepends=True)
        if len(sources) != len(outputs):
            return 0
        kept, left = 0, room
        for source, output in zip(sources, outputs):
            if len(output) <= left:
                kept, left = kept + len(source), left - len(output)
                continue
            if source == output:
                kept += left
            break
        return kept


def _batch_end(buffer: bytearray, start: int) -> int:
    """End (exclusive) of the last complete line in `buffer`, or -1. A line ends with LF,
    CRLF or a lone CR (a progress bar); a CR at the very end waits for the next byte."""
    last = max(buffer.rfind(b"\n", start), buffer.rfind(b"\r", start))
    if last < 0:
        return -1
    if last + 1 == len(buffer) and buffer[last] == 0x0D:
        last = max(buffer.rfind(b"\n", start, last), buffer.rfind(b"\r", start, last))
        return last + 1 if last >= 0 else -1
    return last + 1


def _char_boundary(data: bytes, cut: int) -> int:
    """`cut`, moved back to the start of the valid UTF-8 character it would split, if any. A
    character has at most four bytes, so it looks back at most three: a longer run of
    continuation bytes is invalid and may be cut anywhere (review of 2026-11-25, finding 1)."""
    for back in range(1, 4):
        lead = cut - back
        if lead < 0:
            return cut
        byte = data[lead]
        if byte & 0xC0 == 0x80:
            continue
        size = 2 if byte >> 5 == 0b110 else 3 if byte >> 4 == 0b1110 else (
            4 if byte >> 3 == 0b11110 else 1)
        if lead + size > cut:
            try:
                data[lead:lead + size].decode("utf-8")
            except UnicodeDecodeError:
                return cut
            return lead
        return cut
    return cut


def _encoded(text: str) -> bytes:
    return text.encode("utf-8", "surrogateescape")


def _text(data: bytes | bytearray) -> str:
    return bytes(data).decode("utf-8", "surrogateescape")


class LineRedactor:
    """`redact` over a byte stream that arrives in arbitrary chunks (mcp-gateway D3, SEC-01).

    Complete lines (ending in LF, CRLF or a lone CR) are redacted as a batch, so a credential
    split across reads is still found; the unfinished tail waits. When it passes `line_bytes`,
    the credentials are found in the whole pending text and it is released up to a cut that
    leaves `hold_bytes` waiting and never falls inside a credential: a credential no longer
    than `hold_bytes` is never split. A credential that starts the pending text and runs past
    the bound is released as its marker, and what continues it (letters, digits, `_`, `-`,
    `.`) is withheld until another character arrives.

    A private key block is replaced by one marker from its BEGIN header to its END line, as
    `redact` does, but hides at most `key_bytes` from the start of the header: past that, a
    marker says so and redacted logging resumes (later only to finish a credential that
    crosses the bound). Bytes that are not UTF-8 pass through unchanged (`surrogateescape`);
    no input makes it raise.

    Not covered: a credential longer than `hold_bytes` that crosses a cut (its start is
    released as text); a private key block longer than `key_bytes`; a format that `redact`
    does not know; whatever is still buffered if the process dies before `finish`.
    """

    def __init__(self, line_bytes: int = STREAM_LINE_BYTES,
                 hold_bytes: int = STREAM_HOLD_BYTES, key_bytes: int = STREAM_KEY_BYTES) -> None:
        if not 0 < hold_bytes < line_bytes:
            raise ValueError("the hold must be smaller than the line bound")
        self._line_bytes, self._hold_bytes, self._key_bytes = line_bytes, hold_bytes, key_bytes
        self._pending = bytearray()
        self._scanned = 0  # bytes at the start of `_pending` known to hold no line end
        self._in_key = False  # inside a private key block whose END has not been seen
        self._key_seen = 0  # bytes of the current key block hidden so far
        self._swallow = False  # inside the rest of a credential already released as a marker

    @property
    def pending(self) -> int:
        return len(self._pending)

    def feed(self, data: bytes) -> list[Piece]:
        out: list[Piece] = []
        if self._swallow and data:
            other = _NOT_CREDENTIAL.search(data)
            taken = other.start() if other else len(data)
            if taken:
                out.append(Piece(taken, b"", taken, bytes(data[:taken])))
            self._swallow = other is None
            data = data[taken:]
        self._pending += data
        end = _batch_end(self._pending, self._scanned)
        if end > 0:
            out.append(self._emit(bytes(self._pending[:end])))
            del self._pending[:end]
        self._scanned = max(0, len(self._pending) - 1)  # a final CR is looked at again
        while len(self._pending) > self._line_bytes:
            out.append(self._cut())
        return out

    def finish(self) -> list[Piece]:
        """The stream ended: its last line, even without a line end, is complete."""
        self._swallow = False
        if not self._pending:
            return []
        out = [self._emit(bytes(self._pending))]
        self._pending.clear()
        self._scanned = 0
        return out

    def _cut(self) -> Piece:
        data = bytes(self._pending)
        text = _text(data)
        at = len(_text(data[:_char_boundary(data, len(data) - self._hold_bytes)]))
        groups = _groups(text)
        for start, end, _ in groups:  # merged spans are disjoint: one pass is enough
            if start < at < end:
                at = start
                break
        if at == 0:  # a credential starts the buffer and runs past the bound
            at = groups[0][1] if groups and groups[0][0] == 0 else max(1, at)
        piece = self._emit(_encoded(text[:at]))
        self._pending = bytearray(_encoded(text[at:]))
        self._scanned = max(0, len(self._pending) - 1)
        if not self._pending and not self._in_key:
            self._swallow = True  # what arrives next may still be that credential
        return piece

    def _emit(self, data: bytes) -> Piece:
        text = _text(data)
        parts: list[str] = []
        withheld = 0
        pos = 0
        while pos < len(text):
            if self._in_key:
                pos, hidden, marker = self._withhold(text, pos)
                withheld += hidden
                parts.append(marker)
                continue
            header = _PEM_BEGIN.search(text, pos)
            if header is None:
                parts.append(redact(text[pos:]).text)
                break
            parts += [redact(text[pos:header.start()]).text, "[REDACTED:private-key]"]
            self._in_key, self._key_seen = True, 0
            pos = header.start()
        return Piece(len(data), _encoded("".join(parts)), withheld, data)

    def _withhold(self, text: str, pos: int) -> tuple[int, int, str]:
        """Hide the key block from `pos`: to its END if that is within the bound, else up to
        the bound. Returns where to go on, the bytes hidden and the marker to write."""
        budget = self._key_bytes - self._key_seen
        footer = _PEM_END.search(text, pos)
        stop = footer.end() if footer else len(text)
        size = len(_encoded(text[pos:stop]))
        if size <= budget:
            self._key_seen += size
            self._in_key = footer is None
            return stop, size, ""
        rest = _encoded(text[pos:])
        at = pos + len(_text(rest[:_char_boundary(rest, max(0, budget))]))
        for start, end, _ in _groups(text, first=1):  # never resume inside a credential
            # (the key's own span, which runs to the end, is not one of them)
            if start < at < end:
                at = end
                break
        self._in_key = False
        return at, len(_encoded(text[pos:at])), KEY_BOUND_MARKER.format(limit=self._key_bytes)
