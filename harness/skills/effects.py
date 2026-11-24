"""Effects: what an approved step does (skill-engine D13).

The registry is a literal dictionary in code: a `workflow.json` only names a key, it can never
point to a module or a path. Tests inject their own effects through the engine's constructor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

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
    scope: str

    def prepare(self, context: EffectContext, validated: str) -> Prepared: ...

    def apply(self, context: EffectContext, content: str, prepared: Prepared) -> None: ...

    def reconcile(self, context: EffectContext, prepared: Prepared) -> Reconciled: ...


class NoEffect:
    """Approves the validated text itself; consuming the approval lets the run go on."""

    scope = "none"

    def prepare(self, context: EffectContext, validated: str) -> Prepared:
        return Prepared(content=validated, target=None, effect_ref=None)

    def apply(self, context: EffectContext, content: str, prepared: Prepared) -> None:
        return None

    def reconcile(self, context: EffectContext, prepared: Prepared) -> Reconciled:
        return "applied"


def default_effects() -> Mapping[str, Effect]:
    return {"none": NoEffect()}
