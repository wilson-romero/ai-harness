# Tasks

Cada `[x]` lleva su recibo debajo: «Recibo (fecha, plataforma)», con el comando y la salida relevante. Los oráculos se nombran en cada tarea. En esta rama no se envía nada a Copilot real ni se abre ningún navegador.

## 1. Estudio y plan

- [ ] 1.1 Guardar el estudio en `docs/estudios/2026-11-26-formato-compacto-para-copilot.md`, sin rutas de la máquina ni nombres, con cada afirmación marcada como medida, citada o inferida, y el punto de `innerText` y los `##` marcado como inferencia que se verifica aparte. Oráculo: `uv run python scripts/check_public_safety.py <fichero>` → PASS, y `grep -n "scratchpad\|/Users\|/private" <fichero>` sin resultados.
- [ ] 1.2 Añadir el Corte 10 · Economía del prompt al plan de cortes en una revisión fechada. Hecho: la fila y la sección aparecen en `docs/plan/2026-11-24-ai-harness-cortes.md`.
- [ ] 1.3 `openspec validate --all --strict --no-interactive` con código 0.

## 2. JSON de `extract` en una sola línea (D1)

- [ ] 2.1 Cambiar la regla de formato de `skills/architecture-memory/templates/extract.md`. Oráculo: `test_the_extract_prompt_asks_for_minified_json_on_one_line`. Control negativo: con la plantilla de `develop` ese test falla.
- [ ] 2.2 Fixture `tests/fixtures/mvp/decision-mock-min.json` y test de que la forma minificada, la de sangría y el bloque cercado único dan la misma salida validada (mismo `output_sha256` del paso `check`). Oráculo: `test_minified_indented_or_fenced_reply_prepares_the_same_note` (3 casos) y `test_the_minified_fixture_is_the_indented_one_on_one_line`. Sin cambio en `strict_json.py` ni `checks.py`: `git diff --stat origin/develop -- harness/core/strict_json.py harness/skills/checks.py` vacío.
- [ ] 2.3 Hash del Skill: anotar el antiguo y el nuevo y buscar todo vector que lo fije. Oráculo: `grep -rlE "[0-9a-f]{64}" tests scripts docs openspec/changes skills` y la lista de lo que sale, en el recibo.

## 3. Cabeceras de nota cortas (D2)

- [ ] 3.1 `header_path` y la cabecera nueva en `harness/memory/context.py`. Oráculo: `test_note_headers_are_short_and_keep_path_type_and_date` (las siete cabeceras exactas, 384 caracteres, y la ruta reconstruida igual a la procedencia). Control negativo: con la cabecera de `develop`, los tests de contexto y de endurecimiento fallan.
- [ ] 3.2 Revisión de los tests que fijaban `--- nota:` (fechada el 2026-11-26), sin debilitar aserciones: ayudas `header_paths`/`note_header`/`vault_path` en `tests/conftest.py`, y las aserciones negativas que con la forma nueva pasarían siempre, reescritas. Oráculo: `grep -rn "nota:" tests` solo devuelve la línea hostil antigua de `test_decisions.py`, que se conserva junto a la nueva.
- [ ] 3.3 Las propiedades anti-falsificación siguen: `tests/security/test_memory_hardening.py` (incluido el nombre de fichero con salto de línea que imita la cabecera nueva) y `tests/security/test_note_instructions.py` pasan; `decisions._escape_line` escapa una línea que imita la cabecera nueva (`test_model_text_cannot_open_sections_forge_frontmatter_or_delimiters`).
- [ ] 3.4 Demos y documentación: `scripts/demo_project_memory.py`, `scripts/demo_mvp_without_ea.py`, README y runbook con la cabecera nueva. Oráculo: cada `scripts/demo_*.py` (no los lanza `verify.sh`) termina con `demo: PASS` y `grep -rn "\-\-\- nota:" README.md docs/runbook scripts` vacío.
- [ ] 3.5 Medir antes y después con el método del estudio y dejar la tabla en `design.md`. Oráculo: la tabla de «Medidas antes y después».

## 4. Aviso de respuesta concisa (D3)

- [ ] 4.1 `harness/core/answer_style.py`, `Settings.answer_notice` y `HARNESS_CONCISE_ANSWERS` (on por defecto, off, otro valor = error). Oráculo: `tests/unit/test_answer_style.py` (configuración y longitud medida). `HARNESS_VARS` limpia la variable.
- [ ] 4.2 El aviso va primero en `ask` y `ask_taken` y nunca en `ask_with_lock_held`. Oráculo: `test_a_plain_question_carries_it_first_and_does_not_store_it`, `test_a_skill_step_never_carries_it`, `test_a_note_cannot_switch_it_off_or_change_it`. Controles negativos: sin `with_notice` en `_ask_locked` fallan los de envío; con el aviso también en `ask_with_lock_held` falla el de Skills.
- [ ] 4.3 Visible: `memory context` y `/context` lo muestran, también sin proyecto. Oráculo: `test_what_is_seen_is_what_is_sent` (CLI), `test_context_shows_the_block_of_memory_context` y `test_a_question_carries_the_notice_first_and_context_shows_it` (conversación), `test_without_project_the_notice_still_goes_and_context_says_so`.
- [ ] 4.4 README (tabla de configuración y sección de memoria) y `.env.example`. Hecho: la variable aparece en los dos con su valor por defecto y su coste medido.

## 5. Memoria por deltas (D4) — implementación pendiente del merge de `copilot-web-provider`

- [ ] 5.1 Migración: `requests.context_mode`, `context_reason`, `context_fingerprint`, `remote_ref_sha256`; `request_context.sent_sha256`, `in_message`. Oráculo: test de migración sobre una base de la versión anterior y `SELECT` de las columnas; un `CHECK` rechaza un modo desconocido (control negativo: insertar `'otro'` falla).
- [ ] 5.2 Atributo del proveedor «conserva la conversación» (Mock: no). Oráculo: con el Mock, dos preguntas seguidas envían dos bloques completos con motivo `no_memory_provider`.
- [ ] 5.3 Cálculo de la base y de los modos en `_ask_locked`. Oráculo: escenarios «Segunda pregunta sin cambios en la misma conversación» y «Nota nueva entre dos preguntas» con un proveedor de prueba que conserva la conversación. Control negativo: ignorar el estado de las solicitudes intermedias y ver fallar «Vuelta al bloque completo» con una `uncertain`.
- [ ] 5.4 Un test por motivo de vuelta: `first`, `new_conversation`, `closed`, `unknown_delivery` (uncertain, failed, timeout), `no_memory_provider`, `fingerprint` (proveedor, límite, versión de formato, redacciones), `changed_note` (editada, borrada, omitida), `skill_step`, `forced`, `refresh`. Oráculo: `SELECT context_mode, context_reason FROM requests` en cada caso.
- [ ] 5.5 `/context` con modo, motivo y texto exacto; `/context --full`; `ask --full-memory`; `HARNESS_MEMORY_DELTAS`. Oráculo: escenario «Lo que se ve es lo que se envía con deltas» y «Reenvío completo forzado».
- [ ] 5.6 Nada de contenido en SQLite. Oráculo: escenario «Sin contenido en la base de datos» con un canario.
- [ ] 5.7 README y runbook: cuándo se envía la memoria entera y cómo forzarlo.
- [ ] 5.8 Comprobación de portabilidad: `tests/unit/test_portability.py` pasa y `grep -rn "sys.platform\|os.name" harness/memory harness/core` no añade nada.

## 6. Mediciones con Copilot real (NOT RUN en esta rama)

- [ ] 6.1 Efecto del aviso conciso: las tres preguntas sintéticas de `tests/fixtures/mvp/requerimiento-*.md`, en conversaciones nuevas, con `HARNESS_CONCISE_ANSWERS=on` y `off`, tres veces cada una; registrar caracteres de la respuesta y tokens `o200k_base`, y si empieza con preámbulo o termina con ofrecimiento. Oráculo: tabla con la mediana por caso frente al coste de 55 tokens. Solo datos sintéticos; Wilson lo ejecuta en local y aporta la cifra.
- [ ] 6.2 Obediencia de «minificado en una sola línea»: diez ejecuciones de `architecture-memory` sobre la fuente sintética; contar respuestas en una línea y tokens. Oráculo: n/10 y tokens medianos frente a 157/186.
- [ ] 6.3 Deltas (cuando exista 5.x): ¿el modelo usa una nota enviada tres y ocho preguntas antes? Pregunta sintética cuya respuesta solo está en una nota. Oráculo: acierto por distancia, que fija K de `refresh`.

## 7. Verificación y demo

- [ ] 7.1 Sin código condicionado por plataforma. Oráculo: `uv run pytest -q tests/unit/test_portability.py` y `git diff origin/develop -- harness | grep -n "sys.platform\|os.name\|fcntl\|msvcrt"` vacío.
- [ ] 7.2 `bash scripts/verify.sh` una vez, con su log; código 0 y la línea `verify: PASS on <sha>`.
- [ ] 7.3 Demo del corte (Wilson, macOS, con el Mock): `uv run python main.py memory context demo-alpha` sobre una copia del vault sintético muestra el aviso conciso, el aviso de memoria y las cabeceras `--- _project (project, …)`, `--- sessions/…`; con `HARNESS_CONCISE_ANSWERS=off` el aviso desaparece; `uv run python scripts/demo_project_memory.py` y `uv run python scripts/demo_mvp_without_ea.py` terminan con `demo: PASS`. Evidencia: la salida pegada aquí con el SHA. Estado: NOT RUN.
