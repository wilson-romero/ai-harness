# Tasks

**Recibos.**
- Cada `[x]` lleva su recibo debajo: «Recibo (fecha, plataforma)», con el comando y la salida relevante.
- La plataforma de todos es macOS arm64 con Python 3.14.8, sobre `bugfix/memory-format-conformance` desde `origin/develop` `e2ce87f`.
- No se leyó ningún vault real ni el directorio de datos del dueño.
- El repositorio público se leyó como datos en el estudio y no se ejecutó nada de él.

## 1. Vault sintético en el formato real (D7)

- [x] 1.1 Tipos y carpetas reales.
  - Tipos: `lesson` en `Lecciones/`, `curated` en `Memoria/`, `reference` en `_index.md`, en los agentes y en el informe del Sueño.
  - El agente pasa a `agents/skills/revisor.md` (con `agent_type`), y se añade `agents/_skills-index.md` (tabla con `[[…\|…]]`).
  - Se añaden `Memoria/preferencias.md`, `proyectos-activos.md`, `perfil.md`, `Memoria/Suenos/2026-11-21.md`, `Memoria-CC/MEMORY-tecnico.md`, `Lecciones/_INDEX.md` y `Decisiones/_INDEX.md`.
  - `MEMORY.md` empieza por `# Memory Index` y apunta a su rama.

  Oráculo: `test_fixture_uses_only_real_note_types` y `test_fixture_has_the_real_layout`.
  - Recibo (2026-11-28): los dos pasan (tarea 4.1).
- [x] 1.2 Notas de la captura con sus campos, secciones y etiquetas:
  - `_project.md` sin `created`, con `project`, `project_slug`, `tags: [claude-code, proyecto]` y sus dos secciones;
  - cinco sesiones con `session_id`, `tags: [claude-code, <slug>]`, objetivo, ficheros, herramientas, último mensaje, aprendizajes, estado de git y metadatos;
  - la nota del día con sus dos secciones;
  - `contexto-reciente.md` con `## YYYY-MM-DD`.

  Las rutas de máquina son `/srv/equipo-sintetico/…`. Oráculo: `test_fixture_capture_notes_have_the_real_fields_and_sections`.
  - Recibo (2026-11-28): pasa (tarea 4.1).
- [x] 1.3 Texto propio, sin copiar nada del repositorio público. Se conservan los canarios (`CANARIO-AGENTE-1180`, `-DAILY-6604`, `-ARCHIVO-5521`, `-MAQUINA-CONTEXTO-4411`, `-MAQUINA-PERSONAS-4410`, `-BETA-*`) y las fechas `updated` de las que dependen los tests de orden. Los `_INDEX.md` llevan un frontmatter normal porque el formato real no los especifica. Oráculo: el control de seguridad pública, más los tests de exclusión de `Memoria/`, `daily/`, `agents/` y `_index` (`test_machine_memory_excluded`, `test_project_filter_includes_curated_notes`).
  - Recibo (2026-11-28): `uv run python scripts/check_public_safety.py` → `public-safety: PASS (507 file(s), 5 denylist term(s))`. Los tests de exclusión pasan sin cambios.
- [x] 1.4 Control negativo de los tests de forma. Los tres tests de 1.1 y 1.2 se ejecutaron contra el vault de `origin/develop`, extraído con `git archive` a un directorio temporal.
  - Recibo (2026-11-28): los tres fallan:
    - `test_fixture_uses_only_real_note_types` (`'_index.md': 'index'`);
    - `test_fixture_has_the_real_layout` (`Memoria/proyectos-activos.md`);
    - `test_fixture_capture_notes_have_the_real_fields_and_sections` (`assert "created" not in fields`).

## 2. Lector y mantenimiento (D1–D6)

- [x] 2.1 Control negativo de todo el lote. Con el código de `harness/memory/` de `origin/develop` (`git checkout` de los tres ficheros; el diff se guardó aparte y se volvió a aplicar con `git apply`, sin `stash`) se ejecutaron `tests/unit/test_memory_format_conformance.py`, `tests/unit/test_memory_paths.py` y `tests/unit/test_notes.py`.
  - Recibo (2026-11-28): `46 failed, 47 passed`. Fallan:
    - los 19 casos de D1, D2, D3, D5, D6 y del vault limpio de `test_memory_format_conformance.py`;
    - los 26 casos de `test_rejected_project_identifiers`;
    - `test_every_fixture_note_is_valid_and_loads`.

    Con el código restaurado, todos pasan (tarea 4.1).
- [x] 2.2 D1, `created` opcional en las tres rutas de la captura (`notes.created_is_optional`; `frontmatter_problem(…, relative)`, que `maintenance.py` llama con `note.relative`). Oráculos:
  - `test_capture_notes_may_leave_created_out` (3 casos);
  - `test_real_capture_notes_are_not_reported`;
  - **control negativo:** `test_every_other_note_still_needs_created`, con una lección, una sesión, `projects/demo-alpha/otra/_project.md`, `Memoria-CC/_index.md` y sin ruta: todos siguen diciendo `created is not YYYY-MM-DD`;
  - `test_a_created_that_is_there_is_still_checked`.
  - Recibo (2026-11-28): pasan. En 2.1 fallaban con el código antiguo.
- [x] 2.3 D2, valor sin comillas con `: ` (`notes._is_quoted`, `_parse_block`). Oráculos:
  - `test_unquoted_colon_space_breaks_the_frontmatter` (3 casos);
  - `test_maintain_reports_the_broken_description` (`Memoria-CC/feedback_rota.md (unsupported)`);
  - **control negativo:** `test_quoted_or_without_space_it_is_fine`. Entre comillas simples o dobles, `https://…` y `12:15:00` siguen siendo válidos.

  Efecto lateral sobre `SKILL.md`: `git grep -n -E "^description: [^\"'].*: " -- skills tests/fixtures` no devuelve nada.
  - Recibo (2026-11-28): pasan. El grep sale con código 1, sin resultados.
- [x] 2.4 D3, el rechazo del proyecto dice el motivo (`paths.slug_problem`, `SLUG_RULE`). La regla no cambia.
  - **Oráculo:** `test_rejected_project_identifiers` (26 casos). Fija el mensaje exacto de cada entrada, más los tres nombres que deriva el original (con espacio, con acento y de 136 caracteres).
  - **Control negativo:** las entradas válidas de `test_accepted_project_identifiers` siguen aceptadas sin cambios.
  - **Sin ignorar en silencio:** `test_real_slug_with_a_space_is_refused_with_its_reason` comprueba el código 1, el motivo y que el texto de la nota no sale, y que `memory search` sin `--project` sí devuelve la nota.
  - Recibo (2026-11-28): pasan. `tests/security/test_vault_confinement.py` pasa sin cambios: comprueba el prefijo `invalid project identifier '<x>'`, que se conserva.
- [x] 2.5 D4, solo el primer nivel de `Memoria-CC/` (`maintenance._in_curated`). Oráculo: `test_orphans_and_duplicates_only_look_at_the_first_level`. La copia en una subcarpeta no da par de duplicados ni huérfana. **Control negativo:** la nota suelta del primer nivel sí sale en `index_orphans`.
  - Recibo (2026-11-28): pasa.
- [x] 2.6 D5, índice relativo a `Memoria-CC/`, comprobado contra los ficheros del recorrido (`maintenance._index_target`, `_index_audit(…, known)`). No usa el disco ni `posixpath`.
  - **Oráculo:** `test_index_entries_are_paths_relative_to_memoria_cc`. Las entradas reales del vault sintético (`../Lecciones/…` y la rama `MEMORY-tecnico.md`), y `./MEMORY.md`, no salen.
  - **Control negativo:** `../Lecciones/2026-11-30-no-existe.md` y `../../fuera-del-vault.md` sí salen, con la ruta resuelta.
  - El guardián del paquete: `test_memory_package_has_no_copy_upload_or_write_path` rechazó la primera versión, que importaba `posixpath`, y se reescribió sin ese módulo.
  - Recibo (2026-11-28): pasa. El guardián dijo NO (`harness/memory/maintenance.py:12: import posixpath`) y pasa con la versión final.
- [x] 2.7 D6, enlace de tabla `[[ruta\|alias]]` (`maintenance._broken_links`). Oráculo: `test_table_escaped_alias_is_not_a_broken_link`. **Control negativo:** el segundo enlace de la tabla, a una nota que no existe, sí sale.
  - Recibo (2026-11-28): pasa.
- [x] 2.8 El vault sintético en el formato real es un vault limpio. Oráculos: `test_the_real_format_fixture_is_a_clean_vault` y `test_clean_vault`, que ya existía.
  - Recibo (2026-11-28): pasan.
- [x] 2.9 Desajuste 8: se deja escrita la conducta de hoy, sin cambiarla, porque es la decisión 2 del dueño. Oráculo: `test_curated_note_without_project_stays_out_of_the_context_today`. La lección con `tags: []` y `CANARIO-LECCION-SIN-PROYECTO-5150` no entra en `memory context demo-alpha`.
  - Recibo (2026-11-28): pasa.
- [x] 2.10 Las propiedades de seguridad del lector no cambian:
  - confinamiento;
  - enlaces simbólicos;
  - límites de bytes;
  - bloque marcado con marcador aleatorio;
  - delimitadores neutralizados;
  - solo lectura salvo la nota de decisión aprobada.

  Oráculo: `uv run pytest -q tests/security` sin cambiar ningún test de esa carpeta.
  - Recibo (2026-11-28): `git diff --stat origin/develop -- tests/security` vacío; la carpeta pasa entera (tarea 4.1).

## 3. Expectativas de tests que cambian por el formato (sin debilitar ninguna)

Cada una cambió porque el test fijaba un dato del vault sintético antiguo, no una conducta. Se anota en el propio test con la fecha 2026-11-28.

- [x] 3.1 `tests/unit/test_memory_context.py::test_note_headers_are_short_and_keep_path_type_and_date`: la cabecera de la lección pasa de `(leccion, …)` a `(lesson, …)`, y el total de 384 a 383 caracteres, porque `lesson` tiene una letra menos. Sigue fijando la lista exacta de cabeceras y el total exacto. El escenario «Cabecera corta sin pérdida» de `openspec/changes/prompt-economy/specs/project-context/spec.md` se actualiza en su sitio, con el mismo nombre y la fecha.
- [x] 3.2 `tests/unit/test_memory_context.py::test_leftover_budget_lengthens_a_truncated_note`: su premisa son sesiones que dejan presupuesto sin usar. Las sesiones reales ocupan unos 1 000 bytes cada una (medido: 1 002–1 013 bytes), así que el test escribe tres sesiones cortas y ya no depende del tamaño del vault sintético. Las aserciones no cambian.
- [x] 3.3 `tests/unit/test_memory_search.py::test_same_query_same_output` (18 → 17 líneas) y `test_result_limit` (15 → 14 omitidos). El `_index.md` real es solo enlaces y ya no lleva la frase «Nota sintética». La comparación byte a byte de las dos ejecuciones no cambia.
- [x] 3.4 `tests/unit/test_notes.py::test_every_fixture_note_is_valid_and_loads`:
  - excluye los índices `Memoria-CC/MEMORY*.md` (antes solo `MEMORY.md`), porque el formato real no les pone frontmatter;
  - comprueba cada nota con su ruta (D1).

  La aserción de que no hay ningún problema no cambia, y el vault sintético tiene más ficheros `.md` que antes (29 frente a 20; contando `Memoria/Archivo/`, que el recorrido ignora).
- [x] 3.5 `tests/integration/test_architecture_memory.py::test_active_obsidian_content_from_the_model_is_written_inert`: comprobaba que ningún `` ``` `` ni `[[` aparecía en **todo** el bloque. Las sesiones y el `_project.md` reales traen bloques de código y enlaces que escribió la captura, no el modelo. Ahora la comprobación es sobre la sección de la nota escrita a partir del texto hostil del modelo, que es lo que el test prueba. Se añade que esa sección aparece una sola vez y contiene `## Decisión` y el texto, para que no pase en vacío.
- [x] 3.6 `tests/unit/test_memory_paths.py::test_rejected_project_identifiers`: cambia la conducta (D3), no el vault sintético. Antes fijaba el mensaje genérico; ahora fija el motivo de cada entrada, más tres entradas nuevas. Es más estricto.
- [x] 3.7 Oráculo de esta sección: `git diff origin/develop -- tests | grep "^-.*assert"`. Cada línea quitada tiene su sustituta en 3.1–3.6, y ninguna desaparece sin una aserción igual o más fuerte.
  - Recibo (2026-11-28): `git diff origin/develop -- tests ':!tests/fixtures' | grep -E "^-.*assert"` devuelve 4 líneas, y cada una tiene su sustituta:
    - `assert forbidden not in context` pasa a `… not in section` (3.5);
    - `== 384` pasa a `== 383` (3.1);
    - `== 18` pasa a `== 17` (3.3);
    - `15 more` pasa a `14 more` (3.3).

    La aserción de `test_rejected_project_identifiers` no aparece porque su primera línea no cambió; su valor esperado ahora incluye el motivo (3.6).

## 4. Puerta y documentación

- [x] 4.1 Suite completa sin Edge ni Copilot. Oráculo: `caffeinate -i uv run pytest -m "not edge and not copilot"`.
  - Recibo (2026-11-28): `2560 passed, 191 deselected in 439.50s`, código 0.
- [x] 4.2 `openspec validate --all --strict --no-interactive`.
  - Recibo (2026-11-28): `Totals: 29 passed, 0 failed (29 items)`.
- [x] 4.3 `uv run python scripts/check_sec_matrix.py`. Comprueba que la matriz no cita ningún id de test que ya no exista, como los casos de `test_rejected_project_identifiers` renombrados.
  - Recibo (2026-11-28): `sec-matrix: PASS (15 rows, 206 tests)`.
- [x] 4.4 Seguridad pública de lo que entra en el commit: `uv run python scripts/check_public_safety.py --staged`.
  - Recibo (2026-11-28): `public-safety: PASS (44 file(s), 5 denylist term(s))`, código 0.
- [x] 4.5 Sin código condicionado por plataforma. Oráculo: `git diff origin/develop -- harness | grep -E "sys\.platform|os\.name|fcntl|msvcrt"` vacío, y `tests/unit/test_portability.py` pasa.
  - Recibo (2026-11-28): el grep sale con código 1, sin resultados. `test_portability.py` pasa en la suite completa (4.1).
- [x] 4.6 README: el párrafo de `memory maintain` describe D1, D2 y D4–D6, y «Qué se lee y qué no» describe la regla del identificador, su motivo y que la búsqueda sin `--project` sigue leyendo esas carpetas. Oráculo: `git grep -n "memory-format-conformance\|it contains a space" README.md`.
  - Recibo (2026-11-28): dos líneas.
- [ ] 4.7 Demo del corte. Wilson reproduce sobre el SHA de esta rama:
  - `uv run python scripts/demo_project_memory.py`;
  - `demo_architecture_skills.py`;
  - `demo_mvp_without_ea.py`;
  - `demo_interactive_shell.py`.

  Cada uno termina con `demo: PASS`. Medir sobre el vault real del dueño sigue NOT RUN y lo hace él en local, sin aportar contenido. Estado: NOT RUN por Wilson.
  - Ejecución previa del agente (2026-11-28, macOS arm64, con el Mock, `</dev/null`):
    - `demo_project_memory`, `demo_architecture_skills` y `demo_mvp_without_ea` → `demo: PASS`, código 0.
    - `demo_interactive_shell` falló en el paso (g) (`demo: FAIL - the pseudo-terminal test failed`, 1 failed, 16 passed) mientras la suite completa corría en paralelo. Los dos ficheros que lanza ese paso, `tests/integration/test_chat_terminal.py` y `test_chat_tui_terminal.py`, pasan en la suite completa (4.1), y la demo, lanzada sola al terminar la suite, dio `demo: PASS`, código 0. Se lee como un fallo de tiempos bajo carga, no del cambio: el único uso del vault sintético en esos tests es completar `demo-a` a `demo-alpha`.
