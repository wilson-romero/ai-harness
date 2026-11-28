"""What a `/plan` question sends before the question (code-mode slice 2, D8, D15).

The harness's own instructions: the grammar of a plan of version 1, an example with the nonce
of this question, and the catalogue of the tools a plan may call. Everything in it is a
constant of this module or comes from the local allowlist the person writes: never a server's
description, a note, a file or a reply. It goes first in the text sent, before the memory
block and the attachment, outside every data delimiter, and `/context` shows it.

The catalogue has one line per `read` tool of the allowlist, ordered by server and tool, each
argument with its declared type and limits and the person's own `description` when the entry
has one. Write tools are never offered: a plan of version 1 cannot use them. The catalogue is
bounded (`MAX_CATALOGUE_TOOLS`, `MAX_CATALOGUE_CHARS`); one that does not fit is refused
before anything is recorded or sent, and so is a question whose whole text does not fit the
provider's own limit (its `check`, as for any question).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from harness.core.errors import UsageError
from harness.mcp.config import (
    BooleanArgument,
    EnumArgument,
    IntegerArgument,
    LoadedConfig,
    StringArgument,
    ToolEntry,
)
from harness.mcp.plan import MAX_STEPS, NONCE_PATTERN, PLAN_FORMAT
from harness.text.safe_text import terminal_safe

MAX_CATALOGUE_TOOLS = 64
MAX_CATALOGUE_CHARS = 8_000
# What `/context` shows in place of the nonce: each `/plan` question gets its own.
NONCE_SHOWN = "<nonce de cada pregunta /plan>"

PLAN_INSTRUCTIONS = """\
Instrucciones del harness para esta pregunta (no son datos):
Si para responder necesitas leer datos con las herramientas del catálogo, responde SOLO con un \
plan de lecturas; el harness lo valida, una persona lo aprueba y el harness lo ejecuta. Tú no \
verás el resultado. Si no necesitas ninguna herramienta, responde con texto normal, sin ningún \
bloque json.
Reglas del plan ({format}):
1. Un único bloque de código cercado con la etiqueta json, fuera de citas y de listas.
2. Un objeto JSON con exactamente tres campos: "format", "nonce" y "steps".
3. "format" vale "{format}".
4. "nonce" vale "{nonce}". Escríbelo solo en ese campo: no lo repitas en ningún otro sitio de \
la respuesta.
5. "steps" es una lista de 1 a {max_steps} pasos, que se ejecutan en orden; el primero que falla \
detiene el plan.
6. Cada paso tiene "id" (minúsculas, cifras o _, empieza por una letra, hasta 16 caracteres, \
distinto en cada paso), "server", "tool" y "args" (un objeto); ningún otro campo.
7. Solo herramientas del catálogo, con los argumentos, tipos y límites que dice el catálogo.
8. Cada argumento es un valor literal: sin referencias a otros pasos, sin expresiones ni \
plantillas.
9. Ninguna cadena lleva saltos de línea, caracteres invisibles ni credenciales.
Ejemplo de la forma (con nombres de relleno):
```json
{{"format": "{format}", "nonce": "{nonce}", "steps": [{{"id": "a", "server": "SERVIDOR", \
"tool": "HERRAMIENTA", "args": {{"ARGUMENTO": "VALOR"}}}}]}}
```
Catálogo (servidor.herramienta(argumentos): qué lee):
{catalogue}"""


@dataclass(frozen=True)
class Catalogue:
    lines: tuple[str, ...]
    servers: int  # servers with at least one read tool
    write_tools: int  # declared write tools, left out

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class PlanUnavailable(UsageError):
    """`/plan` cannot ask: no read tool, or a catalogue over its bounds. Nothing was sent."""


def tool_line(server: str, name: str, tool: ToolEntry) -> str:
    """One line of the catalogue, from the allowlist only."""
    arguments = ", ".join(_argument(arg, tool.arguments[arg]) for arg in sorted(tool.arguments))
    line = f"{server}.{name}({arguments})"
    if tool.description is not None:
        line += f": {tool.description}"
    return terminal_safe(line)


def _argument(name: str, spec: object) -> str:
    need = "required" if getattr(spec, "required", False) else "optional"
    if isinstance(spec, StringArgument):
        pattern = f", pattern {spec.pattern}" if spec.pattern is not None else ""
        return f"{name}: string, max {spec.max_length}{pattern}, {need}"
    if isinstance(spec, IntegerArgument):
        return f"{name}: integer, {spec.minimum} to {spec.maximum}, {need}"
    if isinstance(spec, BooleanArgument):
        return f"{name}: boolean, {need}"
    if isinstance(spec, EnumArgument):
        return f"{name}: one of {json.dumps(spec.values, ensure_ascii=False)}, {need}"
    return f"{name}: unknown, {need}"  # never: the allowlist has four kinds


def build_catalogue(config: LoadedConfig) -> Catalogue:
    """The read tools of the allowlist, one line each. Raises PlanUnavailable when there is
    none or when the catalogue is over its bounds: nothing has been recorded or sent."""
    lines: list[str] = []
    servers = 0
    writes = 0
    for server in sorted(config.servers):
        tools = config.servers[server].tools
        reads = [name for name in sorted(tools) if tools[name].operation == "read"]
        writes += len(tools) - len(reads)
        servers += bool(reads)
        lines += [tool_line(server, name, tools[name]) for name in reads]
    if not lines:
        raise PlanUnavailable("/plan needs at least one read tool in the MCP list "
                              "(HARNESS_MCP_CONFIG); nothing was sent")
    if len(lines) > MAX_CATALOGUE_TOOLS:
        raise PlanUnavailable(f"the MCP list has {len(lines)} read tools; a plan's catalogue "
                              f"takes at most {MAX_CATALOGUE_TOOLS}; nothing was sent")
    size = len("\n".join(lines))
    if size > MAX_CATALOGUE_CHARS:
        raise PlanUnavailable(f"the catalogue of read tools has {size} characters; the limit "
                              f"is {MAX_CATALOGUE_CHARS}; nothing was sent")
    return Catalogue(tuple(lines), servers, writes)


def plan_instructions(nonce: str, catalogue: Catalogue) -> str:
    """The harness's block for one `/plan` question, with its nonce (D15)."""
    if not re.fullmatch(NONCE_PATTERN, nonce):
        raise ValueError("the nonce must be 16 lowercase hexadecimal characters")
    return _fill(nonce, catalogue)


def shown_instructions(catalogue: Catalogue) -> str:
    """What `/context` shows: the same block, with the place of the nonce named."""
    return _fill(NONCE_SHOWN, catalogue)


def _fill(nonce: str, catalogue: Catalogue) -> str:
    return PLAN_INSTRUCTIONS.format(format=PLAN_FORMAT, nonce=nonce, max_steps=MAX_STEPS,
                                    catalogue=catalogue.text)
