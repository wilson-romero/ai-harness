# Proposal

## Why

El harness se usa hoy con órdenes sueltas: `uv run python main.py --help` lista 6 subcomandos de primer nivel (`session`, `ask`, `history`, `memory`, `skill`, `mcp`) y 0 modos interactivos (medido el 2026-11-25 sobre `develop` `ee550b6`). Cada orden es un proceso que arranca y termina, y la persona lleva el identificador de sesión de una a otra. Las herramientas que Wilson toma como referencia (Codex, Claude Code, OpenCode) funcionan al revés: se entra una vez y se conversa. Wilson decidió el 2026-11-25 que esta interfaz va antes del endurecimiento y antes de la puerta del MVP, para que la demo sea ya una conversación.

Corte **9 · Interfaz conversacional** (nuevo; se añade a `docs/plan/2026-11-24-ai-harness-cortes.md` en este change, antes de la «Puerta MVP sin EA»). Riesgo **N1**. Toca **SEC-02** (una conversación no ve otra sesión), **SEC-07** (interrumpir una pregunta enviada la deja `uncertain`, sin reenvío), **SEC-12** (la aprobación sigue ligada al hash, ahora dentro de la conversación) y **SEC-15** (límites de entrada). Se demuestra en **macOS**; el diseño usa un único camino de código para macOS y Windows y una ejecución en Windows es confirmación opcional.

## What Changes

- Un modo conversacional: `main.py chat`, y también `main.py` sin argumentos cuando hay una terminal interactiva. Muestra una cabecera con proyecto, proveedor y sesión, y espera líneas.
- Una línea normal es una pregunta en la sesión de la conversación; la respuesta se muestra y se vuelve a esperar.
- Comandos con barra, que nunca se envían al proveedor: `/help`, `/new`, `/sessions`, `/resume`, `/history`, `/memory`, `/context`, `/skill`, `/file`, `/status`, `/exit`.
- La memoria del proyecto de la sesión acompaña a cada pregunta, como en `ask --project`.
- Un Skill lanzado con `/skill` pide su aprobación ahí mismo, con el mecanismo que ya existe.
- Ctrl+C durante una pregunta la interrumpe y la conversación sigue; nada se reenvía.
- Los recursos del proveedor (para Copilot Web, el navegador) duran lo que dura la conversación, no una pregunta.
- La conversación es dueña de su sesión mientras está abierta: una segunda conversación o un `ask` sobre la misma sesión se rechazan.

**No entra**, aunque esas herramientas lo tengan:

- Interfaz de paneles, barra de estado fija, colores o historial con desplazamiento (apariencia: change posterior, que decidirá si se añade una librería de terminal).
- Texto de la respuesta apareciendo poco a poco. Se muestra un aviso de espera y la respuesta completa.
- Que el modelo proponga y ejecute herramientas por su cuenta (bucle de agente): es un experimento posterior.
- Llamar a herramientas MCP desde la conversación (`mcp call` sigue siendo una orden suelta).
- Edición avanzada de la línea, autocompletado e historial de entradas entre ejecuciones.
- Cambios en las órdenes sueltas existentes: siguen funcionando igual y siguen siendo la vía para scripts.

## Capabilities

### New Capabilities

- `interactive-shell`: entrar y salir de una conversación, preguntas y comandos con barra, sesión de la conversación, interrupción de una pregunta, memoria y Skills dentro de la conversación, y salida segura.

### Modified Capabilities

- `llm-provider`: se añade un requisito sobre recursos del proveedor que duran una conversación. No cambia ningún requisito existente (leída entera `openspec/specs/llm-provider/spec.md` el 2026-11-25: sus cinco requisitos describen una pregunta y su resultado, no la vida de los recursos).

`openspec list --specs` (2026-11-25) muestra 8 capacidades; `grep -rn -i "interactiv\|conversaci" openspec/specs` solo encuentra menciones a «terminal interactiva» en textos de aprobación de changes abiertos, ninguna capacidad de conversación.

**Dependencias con changes no archivados.** La aprobación dentro de la conversación usa `human-approval` y `skill-execution` (`skill-engine`, mergeado sin archivar) y los Skills de `architecture-skills-llm`: este change no modifica sus requisitos, los usa. Los recursos con vida de conversación son los que necesita `copilot-web-provider` (rama sin mergear): aquí se especifica el contrato y se prueba con el Mock; mantener Edge abierto se implementa cuando ese change esté mergeado y reabre su decisión D3 (navegador por pregunta), que Wilson confirmó solo como punto de partida.

## Impact

- Código nuevo: `harness/shell/` (bucle, analizador de comandos, terminal inyectable) y la entrada `chat` en `harness/cli.py`. `harness/core/service.py` separa «tomar la sesión» de «preguntar» para que la conversación conserve el bloqueo. `harness/providers/base.py` gana dos operaciones opcionales de apertura y cierre.
- Sin dependencias nuevas: biblioteca estándar y `pydantic`.
- Sin migración: no se guarda nada nuevo.
- Documentación: `README.md`, y el plan de cortes con el Corte 9 y el nuevo orden (interfaz → puerta MVP → apariencia → experimento de agente → endurecimiento).
- Changes afectados: `mvp-without-ea` (su demo manual pasa a hacerse dentro de la conversación), `hardening` (sus guías de uso quedaron aplazadas hasta que exista esta interfaz), `copilot-web-provider` (D3).
