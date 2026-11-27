"""The harness's own notice asking the model for short answers (prompt-economy D3).

It is a constant: never built from a note, an input or a reply. It goes first in the text sent
for a plain question (`ask` and the questions of `chat`), outside every data delimiter, and it
is shown by `memory context` and `/context`, so that what is seen is what is sent. Skill LLM
steps never get it: their template decides the shape of their answer.

It is off unless `HARNESS_CONCISE_ANSWERS=on` (owner's decision, 2026-11-27): it costs 55
tokens per question and its effect on Copilot's answers has not been measured yet.
"""

from __future__ import annotations

from collections.abc import Mapping

from harness.core.errors import InvalidInput

CONCISE_ENV = "HARNESS_CONCISE_ANSWERS"
CONCISE_NOTICE = (
    "Responde de forma concisa: empieza por la respuesta, sin preámbulo, sin repetir la "
    "pregunta, sin resumen final y sin ofrecer más ayuda. Usa listas solo si el contenido es "
    "una lista. Si la pregunta pide otra extensión o formato, sigue la pregunta."
)


def answer_notice(env: Mapping[str, str]) -> str | None:
    """The notice when `HARNESS_CONCISE_ANSWERS=on`; None when it is `off`, empty or unset."""
    raw = (env.get(CONCISE_ENV) or "").strip().lower()
    if raw == "on":
        return CONCISE_NOTICE
    if raw in ("", "off"):
        return None
    raise InvalidInput(f"{CONCISE_ENV} must be 'on' or 'off', got {raw!r}")


def with_notice(notice: str | None, text: str) -> str:
    """`text` as sent or shown: the notice first, then a blank line, when there is one."""
    return text if notice is None else f"{notice}\n\n{text}"
