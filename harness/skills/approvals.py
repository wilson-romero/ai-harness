"""Human approval: what is signed, how it is shown and how a person grants it (skill-engine D12).

The proposal is a small object whose content is represented by its SHA-256; its hash is the
SHA-256 of a fixed prefix plus canonical JSON. A person grants it only at an interactive
terminal, by typing the first 8 characters of the hash shown next to the full content. Nothing
here reads a model output as a decision: the only input that can grant is the terminal's.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import sys
import unicodedata
from dataclasses import dataclass
from typing import Literal, Protocol

from harness.memory.redaction import redact
from harness.memory.safe_text import strip_controls, terminal_safe

PROPOSAL_FORMAT = "ai-harness/approval/1"
HASH_DOMAIN = b"ai-harness/approval/v1\n"
MAX_CONTENT_BYTES = 32 * 1024
CODE_LENGTH = 8
MAX_ATTEMPTS = 3

Decision = Literal["granted", "rejected", "undecided"]


# Invisible code points (review 8.5, 2026-11-24). Derived with `unicodedata` only, no data file:
# every code point whose general category is control (Cc), format (Cf), surrogate (Cs), private
# use (Co) or unassigned (Cn), plus the Default_Ignorable_Code_Point and Variation_Selector code
# points that those categories miss (Unicode PropList: Other_Default_Ignorable_Code_Point and
# Variation_Selector), listed literally. `\n` is the one exception: it ends lines.
INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
INVISIBLE_RANGES = (
    (0x034F, 0x034F),  # combining grapheme joiner
    (0x115F, 0x1160),  # Hangul choseong and jungseong fillers
    (0x17B4, 0x17B5),  # Khmer inherent vowels
    (0x180B, 0x180D),  # Mongolian free variation selectors
    (0x180F, 0x180F),  # Mongolian free variation selector four
    (0x3164, 0x3164),  # Hangul filler
    (0xFE00, 0xFE0F),  # variation selectors (U+FE0F: emoji presentation)
    (0xFFA0, 0xFFA0),  # halfwidth Hangul filler
    (0xE0100, 0xE01EF),  # variation selectors supplement
)


def is_invisible(char: str) -> bool:
    if char == "\n":
        return False
    code = ord(char)
    if any(first <= code <= last for first, last in INVISIBLE_RANGES):
        return True
    return unicodedata.category(char) in INVISIBLE_CATEGORIES


def _escape_invisible(text: str) -> str:
    return "".join(f"<U+{ord(c):04X}>" if is_invisible(c) else c for c in text)


def normalise_content(text: str) -> str:
    """What an approval shows, hashes and applies (D12, revised 8.5 on 2026-11-24).

    NFC; then the cleaning of every vault text (`strip_controls`: controls and format characters
    go, a tab becomes a space); then every other invisible character is written as `<U+XXXX>`,
    so that the person sees it (an emoji with U+FE0F shows as `❤<U+FE0F>`). Redaction runs last,
    and also on the text without those characters, so that one of them placed inside a
    credential cannot keep it from being redacted.
    """
    cleaned = strip_controls(unicodedata.normalize("NFC", text))
    without = redact("".join(c for c in cleaned if not is_invisible(c)))
    if without.kinds:
        cleaned = without.text
    return redact(_escape_invisible(cleaned)).text


def valid_target(target: str) -> bool:
    """A target is shown, hashed and applied as one string: NFC, nothing invisible (8.4)."""
    return (
        bool(target)
        and unicodedata.normalize("NFC", target) == target
        and target == terminal_safe(target)
        and not any(is_invisible(c) or c == "\n" for c in target)
    )


@dataclass(frozen=True)
class Proposal:
    scope: str
    session_id: str
    run_id: str
    step: str
    skill_name: str
    skill_version: str
    skill_sha256: str
    target: str | None
    content: str  # already normalised
    # Where `target` lives (the decision effect: the resolved vault root). Shown and hashed, so
    # that an approval for one vault cannot be applied to another (2026-11-25); never stored.
    destination: str | None = None

    def as_dict(self) -> dict:
        data = self.content.encode("utf-8")
        extra = {"destination": self.destination} if self.destination is not None else {}
        return {
            **extra,
            "format": PROPOSAL_FORMAT,
            "scope": self.scope,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "step": self.step,
            "skill": {
                "name": self.skill_name,
                "version": self.skill_version,
                "sha256": self.skill_sha256,
            },
            "target": self.target,
            "content": {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
        }

    @property
    def content_bytes(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def sha256(self) -> str:
        return proposal_hash(self.as_dict())


def proposal_hash(proposal: dict) -> str:
    canonical = json.dumps(proposal, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(HASH_DOMAIN + canonical.encode("utf-8")).hexdigest()


class Terminal(Protocol):
    """Where a person sees a proposal and answers. Tests inject a fake one."""

    def is_interactive(self) -> bool: ...

    def show(self, text: str) -> None: ...

    def ask(self, question: str) -> str | None:  # None: end of input
        ...

    def identity(self) -> str: ...


class TtyTerminal:
    """The only object that reads stdin to decide an approval."""

    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()

    def show(self, text: str) -> None:
        print(text, flush=True)

    def ask(self, question: str) -> str | None:
        try:
            return input(question)
        except EOFError:
            return None

    def identity(self) -> str:
        return getpass.getuser()


def render_for_terminal(proposal: Proposal, approval_hash: str, expires_at: str,
                        redactions: int = 0) -> str:
    """Header, then the full content between two rules. The content is shown as hashed."""
    rule = "-" * 72
    header = [
        "Approval requested",
        f"  skill:    {proposal.skill_name} {proposal.skill_version} ({proposal.skill_sha256})",
        f"  run:      {proposal.run_id}",
        f"  step:     {proposal.step}",
        f"  scope:    {proposal.scope}",
        *([f"  vault:    {proposal.destination}"] if proposal.destination is not None else []),
        f"  target:   {proposal.target if proposal.target is not None else '-'}",
        f"  bytes:    {proposal.content_bytes}",
        *([f"  redacted: {redactions} credential(s) redacted"] if redactions else []),
        f"  hash:     {approval_hash}",
        f"  expires:  {expires_at} (UTC)",
    ]
    return "\n".join([*header, rule, proposal.content, rule])


def decide(terminal: Terminal, shown: str, approval_hash: str) -> Decision:
    """Show the proposal and ask for the code, at most MAX_ATTEMPTS times.

    The question blocks the session (its lock is held) until the person answers or closes the
    input; there is no timer, because a bounded wait would need platform code or a thread that
    outlives the command. The caller checks the expiry after the answer (review 8.8).
    """
    terminal.show(shown)
    code = approval_hash[:CODE_LENGTH]
    question = f"Type the first {CODE_LENGTH} characters of the hash to approve, or n to reject: "
    for _ in range(MAX_ATTEMPTS):
        answer = terminal.ask(question)
        if answer is None:
            return "undecided"
        answer = answer.strip().lower()
        if answer == "n":
            return "rejected"
        if answer == code:
            return "granted"
        terminal.show("That is not the start of the hash shown above.")
    return "undecided"
