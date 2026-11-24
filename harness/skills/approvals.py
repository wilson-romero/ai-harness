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

from harness.memory.safe_text import safe_text, terminal_safe

PROPOSAL_FORMAT = "ai-harness/approval/1"
HASH_DOMAIN = b"ai-harness/approval/v1\n"
MAX_CONTENT_BYTES = 32 * 1024
CODE_LENGTH = 8
MAX_ATTEMPTS = 3

Decision = Literal["granted", "rejected", "undecided"]


def normalise_content(text: str) -> str:
    """NFC, then the same cleaning and redaction as every vault text (D12 revised)."""
    return safe_text(unicodedata.normalize("NFC", text)).text


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

    def as_dict(self) -> dict:
        data = self.content.encode("utf-8")
        return {
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


def render_for_terminal(proposal: Proposal, approval_hash: str, expires_at: str) -> str:
    """Header, then the full content between two rules. The content is shown as hashed."""
    rule = "-" * 72
    header = [
        "Approval requested",
        f"  skill:    {proposal.skill_name} {proposal.skill_version} ({proposal.skill_sha256})",
        f"  run:      {proposal.run_id}",
        f"  step:     {proposal.step}",
        f"  scope:    {proposal.scope}",
        f"  target:   {terminal_safe(proposal.target) if proposal.target else '-'}",
        f"  bytes:    {proposal.content_bytes}",
        f"  hash:     {approval_hash}",
        f"  expires:  {expires_at} (UTC)",
    ]
    return "\n".join([*header, rule, proposal.content, rule])


def decide(terminal: Terminal, shown: str, approval_hash: str) -> Decision:
    """Show the proposal and ask for the code, at most MAX_ATTEMPTS times."""
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
