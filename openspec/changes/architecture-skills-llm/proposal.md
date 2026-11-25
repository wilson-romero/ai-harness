# Proposal

## Why

Después de `skill-engine` el harness sabe ejecutar y aprobar, pero no tiene ningún Skill de producto (0 carpetas en `skills/`, que no existe sobre `032e989`) y sigue sin poder registrar una decisión: `harness/memory/` tiene 0 caminos de escritura (lo comprueba `tests/security/test_memory_no_writes.py`, en verde el 2026-11-24 dentro de los 258 tests de `032e989`). El Norte del plan termina en «registra la decisión», y `project-memory` dejó esa escritura para este corte (su D9) por dos motivos medidos que siguen en pie: necesita una aprobación, y `Decisiones/` no tiene convención de nombre ni plantilla en `claude-memory-system` (vuelto a medir el 2026-11-24 sobre `92b19ea`: ninguna plantilla ni migración menciona `Decisiones/`; solo aparece como zona del curador en `docs/arquitectura.md` y en la comprobación de escritura de `scripts/memoria-curator.sh`). Revisar un HLS con el contexto del proyecto es, además, el primer uso que no necesita Enterprise Architect.

Corte **4 · Skills sin herramientas** de `docs/plan/2026-11-24-ai-harness-cortes.md`, segunda de sus dos partes. Riesgo **N1**. Completa **SEC-12** con la primera escritura real (la nota que se escribe es byte a byte la aprobada) y ejercita **SEC-14** y **SEC-15** con Skills de producto. Toca además **SEC-01** (redacción en la nota), **SEC-03** (el texto del modelo y de las entradas es dato, nunca aprobación ni destino), **SEC-04** (la escritura confinada a `Decisiones/` del vault), **SEC-07** (escritura interrumpida → `uncertain`, reconciliada sin repetir) y **SEC-13** (el harness sigue sin copiar ni sincronizar el vault). Se demuestra en **macOS**; un único camino de código para macOS y Windows (`pathlib`, `os.replace`, SQLite); Windows es confirmación opcional.

**El repositorio es público.** Las plantillas de los Skills son genéricas; los documentos HLS, las fuentes de decisiones y las respuestas guionizadas de las pruebas son sintéticos. Ningún nombre de empresa, cliente o sistema real.

## What Changes

- Skill `hls-review` en `skills/hls-review/`: con un documento HLS como entrada y el contexto del proyecto de la sesión, pide una revisión de alternativas, restricciones, requisitos no funcionales, supuestos y preguntas pendientes, y comprueba su estructura. La revisión sale por stdout; no escribe nada.
- Skill `architecture-memory` en `skills/architecture-memory/`: con un texto fuente, extrae una decisión como JSON acotado, la valida, prepara la nota, la muestra entera para aprobación y, solo con la aprobación de esos bytes, la escribe en el vault.
- Efecto `vault.save_decision` registrado en el motor: nota en `Decisiones/`, nombre `YYYY-MM-DD-<slug>-<id8>.md`, frontmatter compatible con el vault, identificador de decisión determinista con deduplicación, escritura atómica sin sobrescribir, confinamiento con las reglas de `project-memory`, bloqueo del vault y reconciliación tras una interrupción.
- Respuestas guionizadas y documentos sintéticos para probar los dos Skills con el Mock, y una demo en Python del corte completo.

**No entra**, aunque un lector lo asumiría:

- `architecture-diagram`, `architecture-impact`, Enterprise Architect, MCP y pasos `tool` (cortes 5–7).
- Editar, sustituir, fusionar o borrar una nota existente del vault, incluida una decisión anterior: solo se crea una nota nueva. (Revisado el 2026-11-24: crear `Decisiones/` si no existe **sí** entra, solo en la primera escritura aprobada; decisión de Wilson, D3.)
- Escribir en cualquier otra carpeta del vault (`Memoria/`, `Lecciones/`, `projects/`…), actualizar índices (`_INDEX.md`, `MEMORY.md`) o avisar al curador.
- Guardar la revisión de `hls-review` en un fichero o en el vault.
- Herramienta MCP `memory_save_decision` (Corte 5; reutilizará este efecto).
- Medir la calidad de una revisión o de una decisión extraída por un modelo real: con el Mock solo se prueba lo que hace el harness.

## Capabilities

### New Capabilities

- `hls-review`: qué pide, qué recibe y qué produce el Skill de revisión de HLS, y que no escribe nada.
- `architecture-memory`: flujo del Skill de registro de decisiones (extraer, validar, revisar, persistir), de dónde salen el proyecto y el destino, y qué ocurre ante un duplicado o un rechazo.
- `decision-notes`: formato de la nota de decisión, nombre, identificador y deduplicación, escritura atómica y confinada que solo ocurre con una aprobación de esos bytes, y reconciliación de una escritura interrumpida.

### Modified Capabilities

`memory-vault` (en `openspec/specs/memory-vault/spec.md` desde que `project-memory` se archivó). **Revisado el 2026-11-24:** la primera versión de esta propuesta decía «ninguna», porque `openspec/specs/` estaba vacío; con `session-core` y `project-memory` archivados en `develop` (`f7c590a`), `openspec list --specs` muestra 8 capacidades y el conflicto de abajo se resuelve con un delta MODIFIED en `specs/memory-vault/spec.md`.

**Conflicto con `memory-vault`, resuelto con un delta MODIFIED.** Su requisito «El harness no copia, sincroniza ni modifica el vault» dice que el sistema no copia, sube ni sincroniza el vault y que ningún comando **de memoria** escribe en él. Tras este change el harness **sí** crea notas nuevas en `Decisiones/` (y la carpeta si falta), aunque nunca desde un comando `memory …`. Se trata así:

- `decision-notes` declara en ADDED la única escritura y sus condiciones; `specs/memory-vault/spec.md` copia íntegro el bloque del requisito vigente en MODIFIED y cambia su texto para nombrar esa única escritura; sus dos escenarios no cambian y se añade «Ninguna nota existente cambia tras una decisión».
- La tarea 1.2 recoge el delta y su comprobación tras archivar.
- Dependencia de `skill-engine` (sin archivar; sus capacidades viven en `openspec/changes/skill-engine/specs/` hasta que se archive): este change usa sus capacidades `skill-execution` y `human-approval`; el efecto nuevo se añade a la lista cerrada que `human-approval` define. **Revisado el 2026-11-25 (revisión independiente, 7.7 d):** este change sí amplía el motor (D11: `EffectRefused` en `prepare`, turno exclusivo antes de consumir, `EffectBusy`, excepción inesperada de `apply` → `uncertain`, `Effect.bind`, revocar al terminar, `cancel` que reconcilia, `--input-file` solo con ficheros regulares). Como `skill-engine` está mergeado pero **no archivado**, esos requisitos se llevan editando en esta rama sus specs, que siguen en `openspec/changes/skill-engine/specs/` (`human-approval`: escenario «Excepción inesperada del efecto» y requisito «Rehúses controlados y turno exclusivo del efecto»; `skill-execution`: escenario «Entrada que no es un fichero regular» y el requisito «Cancelar una ejecución» ampliado), en lugar de un delta MODIFIED aquí contra una spec que todavía no existe en `openspec/specs/`. Al archivar `skill-engine` primero, entran con él. Usa también, ya archivadas en `openspec/specs/`, `project-context` (contexto del proyecto en el paso `llm`), `memory-vault` (confinamiento de lectura), `secret-redaction` y `session-management`, sin modificarlas salvo el delta de `memory-vault`.
- Orden de archivo: `skill-engine` y después este change (`session-core` y `project-memory` ya están archivados).

## Impact

- Skills nuevos: `skills/hls-review/` y `skills/architecture-memory/` (`SKILL.md`, `workflow.json`, `templates/*.md`), genéricos y en español.
- Código nuevo: `harness/memory/decisions.py` (identificador, render, escritura confinada y reconciliación) y el efecto `vault.save_decision` en `harness/skills/effects.py`.
- Código modificado: `tests/security/test_memory_no_writes.py` deja de buscar escrituras en **un** fichero nombrado (`harness/memory/decisions.py`) y sigue exigiendo que ningún comando `memory …` cambie la huella del vault; `harness/memory/paths.py` expone la validación de nombre de fichero que ya usa para proyectos.
- Almacenamiento: usa `skill_steps.effect_ref` y `prepared_at` de la `003`. *Revisado el 2026-11-25:* una migración, `005_effect_bindings.sql` (`skill_runs.effect_bindings`), para ligar la ejecución a su vault (hallazgo 3 de la revisión independiente).
- Dependencias: ninguna nueva.
- Configuración: ninguna variable nueva; usa `HARNESS_VAULT_ROOT` y las de `skill-engine`.
- Fixtures: documentos y fuentes sintéticos y respuestas guionizadas en `tests/fixtures/`. `tests/fixtures/vault-synthetic/` **no cambia** (los tests de `project-memory` dependen de su contenido exacto): las notas de duplicado y de conflicto las crea cada test en su copia temporal.
- Documentación: `README.md` (los dos Skills, dónde y cómo se escribe una decisión, qué no hace) y `SECURITY.md` (la única escritura del harness en el vault).
- Script de demo: `scripts/demo_architecture_skills.py`.
