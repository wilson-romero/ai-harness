"""Effects: what an approved step does (skill-engine D13).

The registry is a literal dictionary in code: a `workflow.json` only names a key, it can never
point to a module or a path. Tests inject their own effects through the engine's constructor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from harness.skills.approvals import Proposal

Reconciled = Literal["applied", "absent", "conflict"]


@dataclass(frozen=True)
class Prepared:
    """What an approval would let the effect do. `effect_ref` locates it without content."""

    content: str  # the text to approve, before normalisation
    target: str | None
    effect_ref: str | None


@dataclass(frozen=True)
class EffectContext:
    session_id: str
    run_id: str
    step: str
    skill_name: str


class Effect(Protocol):
    """`prepare` runs once per attempt to apply; `apply` receives only the verified proposal.

    `apply` gets the `Proposal` whose hash was approved and consumed: its `content` and `target`
    are exactly the ones shown and hashed, never a second `prepare` (review 8.3, 2026-11-24).
    `reconcile` answers, after an interruption, whether the content with that SHA-256 is already
    in place (`applied`), not there at all (`absent`) or something else is there (`conflict`).
    """

    scope: str

    def prepare(self, context: EffectContext, validated: str) -> Prepared: ...

    def apply(self, context: EffectContext, proposal: Proposal) -> None: ...

    def reconcile(
        self, context: EffectContext, effect_ref: str | None, content_sha256: str
    ) -> Reconciled: ...


class NoEffect:
    """Approves the validated text itself; consuming the approval lets the run go on."""

    scope = "none"

    def prepare(self, context: EffectContext, validated: str) -> Prepared:
        return Prepared(content=validated, target=None, effect_ref=None)

    def apply(self, context: EffectContext, proposal: Proposal) -> None:
        return None

    def reconcile(
        self, context: EffectContext, effect_ref: str | None, content_sha256: str
    ) -> Reconciled:
        # `applied` is right here only because `apply` changes nothing outside the run: an
        # interrupted step of this effect has nothing that could be applied twice. An effect with
        # a side effect must look at its target and answer `absent` or `conflict` when unsure.
        return "applied"


def default_effects() -> Mapping[str, Effect]:
    return {"none": NoEffect()}
