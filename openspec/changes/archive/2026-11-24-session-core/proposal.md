# Proposal

## Why

El repositorio tiene 0 líneas de código de producto y 1 test (medido el 2026-11-24 con `git status` y `uv run pytest` sobre el árbol del Corte 0). Todo lo que viene después —Copilot Web, memoria, Skills, Enterprise Architect— necesita un lugar donde vivan las sesiones, las solicitudes y su estado, y una interfaz de proveedor contra la que programar. Sin eso el Corte 2 (Copilot real) no tiene dónde enchufarse.

Corte **1 · Esqueleto** de `docs/plan/2026-11-24-ai-harness-cortes.md`. Riesgo **N1**. Cubre **SEC-02** (cruce de sesiones), **SEC-07** (timeout tras envío → `uncertain`, sin duplicación) y **SEC-08** (reinicio con recuperación verificada). Se demuestra en **macOS y Windows**.

## What Changes

- CLI ejecutable con `uv run python main.py`: `session create`, `session list`, `ask`, `history`.
- Sesiones persistentes en SQLite local, con migraciones numeradas y repetibles.
- Contratos tipados de sesión, solicitud y respuesta, con sus estados.
- Interfaz de proveedor LLM y un proveedor Mock determinista, sin red, que también reproduce fallo, timeout y envío incierto.
- Recuperación al arrancar: una solicitud que quedó a medias pasa a `uncertain` y nunca se reenvía sola.
- Bloqueo por sesión: dos procesos no pueden preguntar a la vez en la misma sesión.
- Auditoría de eventos sin prompts ni respuestas.

**No entra**, aunque el plan maestro lo nombre junto a F01:

- Policy Engine, aprobaciones y `tool_calls` (§17 del plan maestro los mezcla con F01; nacen en los cortes 4 y 5).
- Copilot Web y cualquier uso de navegador (Corte 2).
- Tablas `skill_runs`, `skill_steps`, `approvals`, `memory_jobs`: cada una llega con la migración de su corte.
- MCP en cualquier sentido.
- Persistir contenido real de conversaciones: en este corte solo existe contenido sintético del Mock.
- Cerrar, renombrar o borrar sesiones desde la CLI.

## Capabilities

### New Capabilities

- `session-management`: crear y listar sesiones, consultar su historial, aislamiento entre sesiones, persistencia local y auditoría sin contenido.
- `llm-provider`: contrato de pregunta y respuesta con un proveedor seleccionable por configuración, estados de resultado y el proveedor Mock determinista.
- `request-recovery`: qué ocurre con una solicitud interrumpida, la garantía de no reenvío y la exclusión de dos preguntas simultáneas en una sesión.

### Modified Capabilities

Ninguna. `openspec/specs/` solo contiene `.gitkeep` (comprobado con `ls openspec/specs` el 2026-11-24): no hay capacidad vigente que modificar.

## Impact

- Código nuevo: `main.py`, `harness/core/`, `harness/storage/` (con `migrations/001_*.sql`), `harness/providers/`, `tests/unit/`, `tests/security/`.
- Dependencias: ninguna nueva. Se usan `pydantic` (ya instalada) y la biblioteca estándar (`sqlite3`, `argparse`, `asyncio`, `uuid`).
- Configuración: se leen `HARNESS_DATA_DIR` y `HARNESS_PROVIDER`; se añaden variables del Mock solo para pruebas y demo.
- Documentación: `README.md` con instalación y los comandos de la CLI.
- Los cortes 2 a 8 dependen de los contratos y del esquema que fija este change.
