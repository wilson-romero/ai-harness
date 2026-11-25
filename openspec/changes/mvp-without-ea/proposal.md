# Proposal

## Why

El 2026-11-25 Wilson dejó Enterprise Architect en pausa (no lo tiene instalado) y fijó un objetivo intermedio: la **Puerta MVP sin EA**, un flujo completo «requerimiento → memoria del proyecto → Copilot real → revisión HLS → decisión aprobada y guardada en el vault». Todas las piezas existen o están terminándose, pero nadie las ha ejecutado juntas: hoy hay 0 demos y 0 tests que encadenen `hls-review` y `architecture-memory` en una misma sesión (medido el 2026-11-25: `scripts/` en `develop` tiene 4 demos, ninguna con los dos Skills, y `skills/` no existe en `develop`; los dos Skills y `scripts/demo_architecture_skills.py` viven en `feature/architecture-skills-llm`, que los ejecuta por separado). Tampoco se ha medido si las respuestas de Copilot real pasan los pasos `validate` de esos Skills: es la tarea 6.7 de `architecture-skills-llm`, BLOCKED hasta que el proveedor de Copilot esté mergeado.

Puerta **MVP sin EA** de `docs/plan/2026-11-24-ai-harness-cortes.md` (revisión del 2026-11-25), entre el Corte 4 y el Corte 7 en pausa. Riesgo **N2**: es la primera vez que contenido real (un requerimiento, la memoria de trabajo, la respuesta de Copilot) recorre el flujo entero hasta una escritura en el vault. Comprueba de punta a punta **SEC-01** (redacción en lo que se imprime, se envía y se escribe), **SEC-03** (órdenes en el documento, en la memoria o en la respuesta no aprueban ni eligen destino), **SEC-06** (login vencido en mitad del flujo), **SEC-07** (pregunta o escritura interrumpida → `uncertain`, sin repetir), **SEC-12** (la nota escrita es la aprobada) y **SEC-13** (el vault no se copia ni se sincroniza); cada uno ya se prueba por separado en su corte. Se demuestra en **macOS**; Windows es confirmación opcional.

**El repositorio es público y el proyecto es educativo.** La demo automática usa documentos sintéticos y el Mock; la ejecución con Copilot real la hace Wilson en su máquina y aporta solo cifras.

## What Changes

- **Un flujo documentado**, no un Skill nuevo: en una sesión con proyecto, `skill run hls-review` sobre el documento del requerimiento y, con la decisión que Wilson saque de esa revisión, `skill run architecture-memory` en la misma sesión (misma conversación de Copilot), aprobación en terminal y nota nueva en `Decisiones/`. Runbook `docs/runbook/mvp-without-ea.md` para macOS y Windows/PowerShell.
- **Un test de integración** que recorre ese flujo por subprocesos con el Mock guionizado, sobre una copia del vault sintético, con una terminal de aprobación de prueba, y comprueba que la nota escrita aparece después en `memory context` del proyecto.
- **Una demo en Python**, `scripts/demo_mvp_without_ea.py`, que ejecuta los pasos que no necesitan a una persona y escribe como instrucciones los que sí (aprobar).
- **La medición con Copilot real** de la tarea 6.7 de `architecture-skills-llm`, hecha aquí sobre el flujo encadenado y con las mismas reglas (Wilson la ejecuta, solo cifras; si `validation_failed` supera la mitad de las ejecuciones, se reabren las plantillas antes de cerrar la puerta).
- **La demo de la puerta**: con el Mock (PASS exige la demo automática y la aprobación de Wilson) y a mano con Copilot real.

**No entra**, aunque un lector lo asumiría:

- Ningún Skill, efecto, migración, comando ni requisito nuevo. Si la medición con Copilot real obliga a cambiar plantillas o reglas de `validate`, eso se hace en `architecture-skills-llm` (si no está archivado) o en un change propio, no aquí.
- Encadenar los dos Skills en uno solo o pasar la salida de `hls-review` a `architecture-memory` automáticamente (design D1).
- Herramientas MCP (`harness-mcp-server`), Enterprise Architect, `architecture-diagram`, `architecture-impact`.
- Medir la calidad de una revisión o de una decisión: la puerta mide lo que hace el harness con lo que Copilot devuelve, no si el consejo es bueno.
- Lo que solo sirve en producción (criterio del proyecto educativo, Wilson, 2026-11-25): copias del vault o de los datos, ejecución desatendida, varios usuarios.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

Ninguna. Este change no añade conducta: integra, documenta y demuestra capacidades que ya existen. Por eso su `.openspec.yaml` lleva `skip_specs: true` (sin requisitos inventados para pasar la validación). Comprobado el 2026-11-25 sobre `develop` (`86f1079`): `openspec list --specs` devuelve 8 capacidades; las que el flujo usa sin cambiarlas son `session-management`, `llm-provider`, `request-recovery`, `project-context`, `memory-vault`, `memory-search` y `secret-redaction`. `grep -rn -i "hls" openspec/specs/` → 0: las capacidades de los Skills de producto aún no están archivadas.

**Dependencias con changes sin archivar o sin mergear**, que el flujo usa tal como están:

- `skill-engine` (mergeado, sin archivar): `skill-definition`, `skill-execution`, `human-approval`.
- `architecture-skills-llm` (sin mergear): `hls-review`, `architecture-memory`, `decision-notes` y el delta de `memory-vault`.
- `copilot-web-provider` (sin mergear): `copilot-web-provider`, `dedicated-edge-browser`.

Las tareas que necesitan `architecture-skills-llm` o `copilot-web-provider` mergeados están marcadas **BLOCKED** en `tasks.md`.

## Impact

- Código de producto: ninguno.
- Tests: un test de integración nuevo en `tests/integration/` (Mock, subprocesos, copia del vault sintético).
- Documentación: `docs/runbook/mvp-without-ea.md` y un enlace desde `README.md`.
- Script de demo: `scripts/demo_mvp_without_ea.py`.
- Plan: la fila «Puerta MVP sin EA» de `docs/plan/2026-11-24-ai-harness-cortes.md` pasa a su estado final al cerrar.
