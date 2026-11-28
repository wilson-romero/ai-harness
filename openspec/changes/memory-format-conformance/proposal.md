# Proposal

## Why

El estudio `docs/estudios/2026-11-28-segunda-memoria-como-claude-memory-system.md` (§2.3) comparó el 2026-11-28 el vault sintético y el lector de memoria del harness con el formato real de `claude-memory-system` en el commit `92b19ea` (licencia MIT). Encontró 15 desajustes. Esta rama corrige los que no necesitan una decisión del dueño, porque los hechos no son ambiguos y hoy dan resultados falsos.

- **El vault sintético no tiene el formato real.** Medido sobre `origin/develop` `e2ce87f`:
  - 4 de los 9 valores de `type` que usa no existen en el formato real: `leccion`, `memoria`, `index` y `agent`. `decision` es el tipo propio del harness. Además, el agente estaba fuera de `agents/skills/`;
  - le faltan 9 ficheros que la estructura real sí tiene: `preferencias.md`, `proyectos-activos.md`, `perfil.md`, `Suenos/`, `MEMORY-<tema>.md`, los dos `_INDEX.md`, `agents/_skills-index.md` y `agents/skills/`;
  - las notas de proyecto, de sesión y del día no llevan las secciones ni las etiquetas que escribe la captura.

  Un test que pasa con el vault sintético no dice nada del vault real.
- **`memory maintain --dry-run` informa de cosas falsas sobre un vault real.** Comprobado con notas sintéticas en el formato real:
  - **(5)** cada `projects/<slug>/_project.md`, `_index.md` y `agents/_skills-index.md` sale en `invalid_frontmatter`, porque la captura los reescribe sin `created`;
  - **(12)** cada entrada `../Lecciones/x.md` de un índice sale en `index_dangling`;
  - **(14)** una nota en una subcarpeta de `Memoria-CC/` cuenta como huérfana y como posible duplicado, aunque el original solo mira el primer nivel;
  - **(nuevo, D6)** un enlace de tabla `[[agents/skills/x\|x]]` sale en `broken_links`.
- **(13)** Un `description:` sin comillas que lleva `: ` dentro se acepta, aunque no es YAML válido y Obsidian no lo lee.
- **(7)** Una carpeta de proyecto con espacios, acentos o más de 128 caracteres se rechaza con el mismo mensaje que `../../etc`. El mensaje no dice por qué.

**Corte.** Corrección del **Corte 3 · Memoria** (`project-memory`, archivado y publicado en `v0.1.0`). Este change es nuevo y no se añade a uno abierto, porque cambia la conducta de dos capacidades vigentes: `memory-maintenance` y `memory-vault`. Riesgo **N1**: solo lectura, no se escribe nada nuevo. Toca **SEC-03** y **SEC-04**:
- SEC-03: las notas nuevas del vault sintético traen bloques de código y `[[enlaces]]` reales, y siguen siendo datos marcados.
- SEC-04: la ruta de un índice se resuelve como texto y nunca sale del vault.

Se demuestra en **macOS**. Es el mismo código para Windows, y una ejecución allí es una confirmación opcional.

## What Changes

1. **Vault sintético en el formato real** (`tests/fixtures/vault-synthetic/`). El texto es sintético y propio. No se copia texto ni plantillas del repositorio público (la decisión 4 del estudio, sobre la licencia, sigue abierta). Cambia:
   - los tipos `lesson`, `curated` y `reference`;
   - `agents/skills/<tipo>.md` más `agents/_skills-index.md`;
   - `_project.md`, las sesiones y la nota del día con sus secciones y etiquetas;
   - `contexto-reciente.md` con secciones `## YYYY-MM-DD`;
   - los ficheros que faltaban.
2. **`created` opcional** solo en las tres rutas que la captura reescribe (D1).
3. **Un valor sin comillas con `: ` invalida el frontmatter** (D2).
4. **El rechazo de un proyecto dice el motivo** (D3). La regla no se relaja.
5. **Huérfanas y duplicados: solo el primer nivel de `Memoria-CC/`** (D4).
6. **Las entradas de un índice son rutas relativas a `Memoria-CC/`** y se comprueban contra los ficheros del vault (D5).
7. **Un enlace de tabla `[[ruta\|alias]]`** se lee sin la `\` (D6).

**No entra**, aunque un lector lo asumiría:

- **Desajuste 8**: qué notas globales sin proyecto entran en `memory context`. Es la decisión 2 del dueño. Un test deja escrita la conducta de hoy (design, «Riesgos»).
- `machine:` en las notas que escribe el harness, el formato de la nota de decisión, `/remember` y cualquier escritura nueva.
- Relajar la regla del identificador para aceptar espacios, acentos o nombres largos (D3).
- El formato de los `_INDEX.md`. El repositorio público no lo especifica, así que el vault sintético les da un frontmatter normal y una lista de enlaces, sin presentarlo como el real.
- La lista de autocompletado de `harness/shell/conversation.py`, que omite en silencio las carpetas con nombre no válido. `harness/shell/` está fuera de esta rama porque otra sesión trabaja en él. Escribir el nombre da el rechazo con su motivo.

## Capabilities

### Modified Capabilities

- `memory-maintenance`: se añaden dos requisitos.
  - «Índices de Memoria-CC con el formato real» cubre la entrada relativa a `Memoria-CC/` y el primer nivel.
  - «Frontmatter y enlaces con el formato real» cubre las notas de la captura sin `created`, el valor con `: `, el enlace de tabla y el vault sintético limpio.

  «Hallazgos del informe» no cambia: sus categorías son las mismas, y lo que cambia es cómo se lee el formato real. Se añaden requisitos en vez de modificarlo porque el texto de un requisito no puede pasar de 500 caracteres en modo estricto.
- `memory-vault`: cambia «Identificador de proyecto validado». El mensaje dice el motivo y se añade el escenario del nombre con espacio. Los escenarios existentes siguen ciertos.

Comprobado el 2026-11-28 con `git grep -n "created\|Memoria-CC\|identificador" openspec/specs`. No cambian:
- `project-context`, `memory-search` y `secret-redaction`;
- `decision-notes`, del change `architecture-skills-llm`. Su escritor no lee `created` de otra nota.

El escenario «Cabecera corta sin pérdida» del change `prompt-economy`, aún sin archivar, decía `leccion` y 384 caracteres. Era una cifra del vault sintético. Se actualiza en su sitio, con el mismo nombre y la fecha, a `lesson` y 383.

## Impact

- Código: `harness/memory/paths.py` (`slug_problem`, `SLUG_RULE`), `harness/memory/notes.py` (`_is_quoted`, `created_is_optional`, `frontmatter_problem(…, relative)`) y `harness/memory/maintenance.py`.
- **Efecto lateral:** `harness/skills/definition.py` usa el mismo `parse_frontmatter`. Un `SKILL.md` cuyo `description:` lleve `: ` sin comillas pasa a ser inválido. Ningún Skill del repositorio lo tiene, y la suite completa pasa.
- Tests:
  - uno nuevo, `tests/unit/test_memory_format_conformance.py`;
  - `tests/unit/test_memory_paths.py` es más estricto: fija el motivo de cada entrada;
  - seis expectativas del vault sintético cambian por el formato, una por una en `tasks.md`.
- Documentación: `README.md` (mantenimiento e identificador de proyecto).
- Sin dependencias nuevas ni migraciones. No toca `harness/providers/`, `harness/mcp/` ni `harness/shell/`.
