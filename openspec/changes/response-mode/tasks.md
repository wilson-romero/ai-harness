# Tasks

Cada `[x]` lleva su recibo debajo: «Recibo (fecha, plataforma)», con el comando y la salida relevante. Los oráculos se nombran en cada tarea. En esta rama no se abre la página real de Copilot, ni el perfil real de Edge, ni `HARNESS_DATA_DIR` real: todo corre contra el Mock y la página sintética local (`tests/fixtures/copilot_ui/app.html`).

## 1. Artefactos y plan

- [x] 1.1 Change creado con `openspec new change response-mode`; proposal, spec `response-mode`, design y tasks. Oráculo: `openspec validate --all --strict --no-interactive` con código 0.
  - Recibo: ver 7.3.
- [x] 1.2 Corte 11 · Modo de respuesta en `docs/plan/2026-11-24-ai-harness-cortes.md` (fila y revisión fechada). Hecho: la fila aparece antes de la Puerta MVP sin EA y la sección «Revisado el 2026-11-27 (Wilson): Corte 11 · Modo de respuesta» al final.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `grep -n "11 · Modo de respuesta" docs/plan/2026-11-24-ai-harness-cortes.md` → la fila y el título de la sección.

## 2. Pruebas primero (rojas)

- [x] 2.1 Pruebas nuevas antes del código: `tests/unit/test_response_mode.py` (servicio, Mock, CLI, migración, configuración, esquema), `tests/unit/test_shell_mode.py` (conversación y panel), `tests/browser/test_copilot_mode.py` (proveedor contra la página sintética), `tests/browser/test_copilot_probe_mode.py` (sonda). Oráculo: fallan antes de la implementación.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8), sobre `aa02081` sin código nuevo: `uv run pytest -q tests/unit/test_response_mode.py tests/unit/test_shell_mode.py` → `2 errors during collection` (no existe `harness.core.response_mode`); `uv run pytest -q -m edge tests/browser/test_copilot_mode.py tests/browser/test_copilot_probe_mode.py` → `13 failed, 5 errors`.

## 3. Registro y servicio (D1, D5, D6, D10)

- [x] 3.1 Migración `008_response_mode.sql` (SQL literal, `CHECK`), `Session.response_mode`, `LLMRequest.mode`, `HistoryEntry.requested_mode/confirmed_mode`. Oráculo: `test_a_database_of_migration_007_opens_unchanged` (una base 001–007 con datos abre igual, sesiones en `auto`, solicitudes antiguas sin modo) y `test_the_new_columns_refuse_an_unknown_mode` (control negativo del `CHECK`); `tests/unit/test_sql_literals.py` en verde.
  - Recibo: ver 7.1 y 6.x.
- [x] 3.2 `SessionService.set_mode` (solo base y auditoría `session.mode`), `check_mode` antes de registrar nada, modo en la solicitud, `on_mode` guardado en su propia transacción, aviso si la página cambió de modo. Oráculo: `test_setting_the_mode_sends_nothing_and_is_audited`, `test_a_mode_the_provider_cannot_set_is_refused_before_anything`, `test_a_fallback_after_the_answer_is_recorded_and_warned` y su control `test_no_fallback_no_warning`.
  - Recibo: ver 7.1.
- [x] 3.3 Plazo de `deep`: `HARNESS_DEEP_REQUEST_TIMEOUT_S` (triple por defecto, nunca menor), vigilante de la CLI con el plazo mayor. Oráculo: `test_deep_waits_longer_than_quick` (misma demora: `completed` en `deep`, `uncertain` en `quick`, sin reenvío), `test_deep_before_sending_is_still_a_timeout`, `test_the_deep_deadline_defaults_to_three_times_and_cannot_be_lower`.
  - Recibo: ver 7.1 y 6.x.
- [x] 3.4 Mock con los tres modos (respuesta con «in mode X» fuera de `auto`, idéntica en `auto` a la de antes). Oráculo: `test_the_mock_receives_each_mode_and_answers_by_it` (3 casos) y la suite previa del Mock sin cambios.
  - Recibo: ver 7.1.
- [x] 3.5 CLI: `ask --mode` (recuerda el modo), `history` con el modo cuando no es `auto` sin cambios, también sin contenido. Oráculo: `test_ask_with_mode_remembers_it`, `test_ask_refuses_an_unknown_mode_before_anything`, `test_history_shows_the_mode_when_it_is_not_plain_auto`, `test_history_without_content_shows_the_mode`.
  - Recibo: ver 7.1.

## 4. Conversación (D9)

- [x] 4.1 `/mode [auto|quick|deep]` (una entrada en la tabla, una línea de ayuda), `/status` con `mode:`, `/history` con el modo, panel lateral con «Mode». Oráculo: `tests/unit/test_shell_mode.py` (7 pruebas, incluida la de pantalla completa) y `tests/unit/test_shell_input.py` con `/mode {}` entre las plantillas hostiles (la guarda `test_every_command_that_takes_arguments_is_covered` falló al añadir el comando y obligó a cubrirlo).
  - Recibo: ver 7.1. Control negativo observado: sin `/mode {}` en `TEMPLATES`, `FAILED tests/unit/test_shell_input.py::test_every_command_that_takes_arguments_is_covered` (`Extra items in the left set: 'mode'`).

- [x] 4.2 Tras integrar `feature/command-completion` (1a37be8): `/mode` es una entrada de la tabla única (`harness/shell/commands.py`, 0 o 1 argumentos, tipo `MODE` con los valores de `ResponseMode`, línea de `/help` escrita desde la tabla) y la entrada de `parser.py` y la línea de `HELP` propias desaparecen. El completado ofrece exactamente `auto`, `quick` y `deep` y nada tras un valor. `/mo` muestra `running: /mode …` antes de ejecutarse; `/m` pasa a ser ambiguo entre `/memory` y `/mode` (regla «principio único o error que nombra los candidatos», aceptado el 2026-11-27); un valor desconocido es un error local; ninguna forma corta convierte una pregunta en `/mode`; la línea «Mode» del panel a 120×40 y 100×30, y `mode:` en `/status` a 80×24, donde el panel se oculta. Oráculo: las pruebas nuevas de `tests/unit/test_shell_mode.py` (13 casos más) y `test_slash_opens_the_commands…` con 12 comandos.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): controles negativos, sin las opciones de modo en `completion.py` → `2 failed`, exit 1; sin el corte tras un valor → `1 failed`, exit 1 (bytes restaurados). `caffeinate -i uv run pytest -q -m "not edge and not copilot"` → `2038 passed, 175 deselected in 343.38s`, exit 0; `caffeinate -i uv run pytest -q -m edge` → `173 passed, 2040 deselected in 1247.54s`, exit 0; `openspec validate --all --strict` → `27 passed, 0 failed`; `check_public_safety.py` → PASS (471 ficheros), exit 0; `check_sec_matrix.py` → PASS (15 filas, 135 pruebas), exit 0.

## 5. Copilot Web (D2, D3, D4, D8)

- [x] 5.1 Esquema `ResponseModeControl` en `ui.json` (opcional) y validación de que el selector no reutiliza el localizador del editor, enviar, parar o conversación nueva. Oráculo: `test_a_selector_that_could_touch_another_control_is_refused` (7 casos que dicen NO y el control que dice SÍ).
  - Recibo: ver 7.1.
- [x] 5.2 Página sintética con selector opcional en dos formas y conductas de fallo; el servidor registra el modo de cada prompt y cada cambio de modo. Hecho: `app.html` (comentario de cabecera con `modes`, `mode_start`, `mode_persist`, `mode_stuck`, `mode_late_ms`, `mode_fallback`, `mode_newchat`) y `tests/copilot_app.py`. Las pruebas de Edge anteriores no cambian (el selector solo aparece con `modes=…`).
  - Recibo: ver 7.2.
- [x] 5.3 Poner y confirmar antes de escribir, fallo limpio, misma conversación; relectura tras la respuesta. Oráculo: `tests/browser/test_copilot_mode.py` (13 pruebas): las dos formas, ya en el modo, aplicado tarde, no confirmable (`failed`, 0 prompts), control ausente de la página, sin medida (rechazo sin registrar ni abrir Edge), `auto` sin medida, `auto` que devuelve la página a automático, `auto` que no bloquea, elegir abre otra conversación (`failed`, la sesión conserva su referencia y no se cierra), vuelta a otro modo registrada y su control.
  - Recibo: ver 7.2 y 6.x.

## 6. Controles negativos (la comprobación sabe decir NO)

Cada mutación se aplicó sobre el árbol de trabajo, se ejecutó solo la prueba nombrada y se restauraron los bytes originales del fichero (comprobado byte a byte). Además, dos guardas previas dijeron NO al añadir el código: `test_every_command_of_d10_and_nothing_else` (tabla de comandos) y `test_provider_types_only_into_the_editor_and_sends_only_with_the_measured_control` (6 acciones en lugar de 3); ambas se revisaron de forma explícita, con fecha y la lista exacta de las tres acciones nuevas del selector (abrir, elegir opción, Escape).

- [x] 6.1 Sin la comprobación de conversación tras poner el modo (`apply_mode`) → falla `test_choosing_a_mode_that_opens_another_conversation_fails_before_typing`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): mutación `if False:` en la comprobación de conversación de `apply_mode` → `1 failed`, exit 1.
- [x] 6.2 Con `quick`/`deep` tratados como `auto` cuando no se confirman → falla `test_a_mode_that_cannot_be_confirmed_fails_before_typing`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): mutación que trata cualquier fallo como el de `auto` (solo aviso) → `1 failed`, exit 1.
- [x] 6.3 Sin la relectura tras la respuesta (`reread_mode`) → falla `test_a_fallback_during_the_answer_is_recorded`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): sin `await self.reread_mode(page)` → `1 failed`, exit 1.
- [x] 6.4 Con el plazo normal también en `deep` → falla `test_deep_waits_longer_than_quick`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `deadline_s = self._timeout_s` también en `deep` → `1 failed`, exit 1.
- [x] 6.5 `check_mode` de Copilot que acepta todo → falla `test_without_the_measured_control_quick_and_deep_are_refused`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `check_mode` que vuelve siempre → `1 failed`, exit 1.
- [x] 6.6 Sonda que acepta el primer localizador sin confirmar los modos → falla `test_a_selector_that_does_not_change_is_not_written`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `if True:` en lugar de exigir todos los modos confirmados → `1 failed`, exit 1.

## 6b. Revisión independiente del 2026-11-27 (sobre 1572b0a)

Cada hallazgo, con su prueba vista en rojo antes del arreglo y una mutación que deshace el arreglo y la vuelve a poner en rojo (bytes restaurados). Rojo previo (2026-11-27, macOS arm64, Python 3.14.8): pruebas unitarias nuevas → `11 failed, 31 passed`; de navegador → `11 failed, 5 passed`. Las 5 que ya pasaban son controles y cobertura de ramas que ya funcionaban: un turno nuevo al elegir, la relectura que falla, URL y turnos cambiados en la sonda, «left as found: yes».

- [x] R1 (MEDIA) Se compara como `guard`: la misma referencia y ningún turno de usuario después del último que había. Un historial que llega encima no bloquea, ni en `deep` ni en `auto`. Oráculo: `test_a_history_that_arrives_while_choosing_does_not_block` (2 casos, `mode_history`) y su control `test_a_new_turn_while_choosing_fails_before_typing` (`mode_append`).
  - Recibo: volver a contar turnos → `2 failed`, exit 1.
- [x] R2 (MEDIA-BAJA) `try/finally` cierra la lista en `read`/`select`, y `close` comprueba el cierre. Con la lista abierta antes de escribir, `failed` en cualquier modo. Oráculo: `test_a_list_that_stays_open_fails_before_typing` (2 casos, `mode_sticky`), `test_a_disabled_option_leaves_no_list_open_under_the_prompt` y `test_two_matching_options_leave_no_list_open`; el servidor recibe `list_open=false`.
  - Recibo: sin la comprobación → `2 failed`; sin el `finally` → `2 failed`, exit 1.
- [x] R3 (BAJA-MEDIA) En la sonda, una forma de leer confirma un modo solo si leía otra cosa justo antes de elegirlo. Oráculo: `test_a_reading_that_cannot_tell_modes_apart_is_not_written` (`mode_label`).
  - Recibo: sin la condición → `1 failed`, exit 1.
- [x] R4 (BAJA) En la página, antes de cualquier clic, ningún elemento visible del botón o de las opciones puede ser, contener o estar dentro del editor ni de los controles de enviar, parar o chat nuevo. Además, cada clic lo comprueba. Oráculo: `test_an_option_that_is_another_control_is_never_clicked` (`exact: false`, que pasa el esquema).
  - Recibo: sin la comprobación → `1 failed`, exit 1.
- [x] R5 (BAJA) El modo confirmado vive en el intento, empieza vacío en cada uno y se informa justo antes de `on_sent`. Oráculo: `test_a_retry_in_a_new_tab_does_not_keep_the_first_confirmation`.
  - Recibo: informar al confirmar, como antes → `1 failed`, exit 1.
- [x] R6 (BAJA) `HARNESS_REQUEST_TIMEOUT_S` y `HARNESS_DEEP_REQUEST_TIMEOUT_S` deben ser finitos y mayores que 0, y ningún número del entorno puede ser `nan`/`inf`. Oráculo: `test_a_deadline_is_a_finite_number_above_zero` (10 casos más el control).
  - Recibo: sin la comprobación → `10 failed`, exit 1.
- [x] R7 (BAJA) `ask --mode` guarda el modo y su auditoría solo después de las comprobaciones que rechazan antes de registrar. Oráculo: `test_ask_with_a_mode_keeps_nothing_when_the_question_is_refused` y su control `…_keeps_it_when_the_question_is_recorded`.
  - Recibo: guardar antes → `1 failed`, exit 1.
- [x] R8 (BAJA) La sonda no escribe sin `ui.json` previo, con un modo de partida no mapeado, si la página no quedó como estaba ni si cambió la URL o los turnos. Si ningún localizador confirma, intenta dejar la página como estaba. Oráculo: `test_an_unknown_starting_mode_is_not_written`, `test_without_a_measurement_the_turns_cannot_be_checked`, `test_a_selector_that_changes_the_conversation_is_not_written[address|turns]`, y «left as found: yes» en la medida buena.
  - Recibo: sin la parada por el modo de partida → `1 failed`; sin la parada por falta de `ui.json` → `1 failed`, exit 1.
- [x] R9 (documentación) Corregidos D2 (sin la promesa de «auto, page's choice», más las dos excepciones), D3, D4, D5, D7, D8, D9 (la tabla única y el completado) y D10, el spec (5 escenarios nuevos) y la propuesta. La regla de `test_browser_code_rules.py` comprueba el ámbito: las dos acciones del selector, solo dentro de `_ModeSelector`, y su docstring dice que la relectura ocurre tras la respuesta.
  - Recibo: una tecla en `_Turn.apply_mode` → `1 failed`, exit 1.
- [x] R10 Lotes, validaciones y comprobaciones tras los arreglos.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `caffeinate -i uv run pytest -q -m "not edge and not copilot"` → `2050 passed, 190 deselected in 346.14s`, exit 0; `caffeinate -i uv run pytest -q -m edge` → `188 passed, 2052 deselected in 1608.93s`, exit 0, sin repeticiones; `openspec validate --all --strict` → `27 passed, 0 failed`; `check_public_safety.py` → PASS (471 ficheros), exit 0; `check_sec_matrix.py` → PASS (15 filas, 135 pruebas), exit 0. `origin/develop` (893694a) ya estaba en HEAD: no hizo falta merge.

## 7. Verificación

- [x] 7.1 Lote sin navegador: `caffeinate -i uv run pytest -q -m "not edge and not copilot"`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): primera pasada `2 failed, 1845 passed` (las dos guardas de 6), exit 1; tras revisarlas, segunda pasada `1 failed, 1846 passed, 175 deselected in 301.51s`, exit 1: `test_shell_tui_buttons.py::test_keys_typed_ahead_of_the_box_cannot_approve` (la caja de aprobación aún no estaba montada al comprobarla; no toca el modo y pasó en la primera pasada); repetido solo, `tests/unit/test_shell_tui_buttons.py` → `17 passed` tres veces seguidas, exit 0. Queda anotado como intermitente de tiempos en máquina compartida, no como regresión de este cambio.
- [x] 7.2 Lote de Edge: `caffeinate -i uv run pytest -q -m edge` (máquina compartida: un fallo de Edge se repite solo).
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `173 passed, 1849 deselected in 1223.29s`, exit 0, sin repeticiones.
- [x] 7.3 `openspec validate --all --strict --no-interactive`, `uv run python scripts/check_public_safety.py`, `uv run python scripts/check_sec_matrix.py`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `Totals: 24 passed, 0 failed`, exit 0; `public-safety: PASS (433 file(s))` y, sobre los 13 ficheros nuevos, `PASS (13 file(s))`, exit 0; `sec-matrix: PASS (15 rows, 135 tests)`, exit 0.
- [x] 7.4 Portabilidad: `tests/unit/test_portability.py` en 7.1 y `git diff origin/develop -- harness scripts | grep -n "sys.platform\|os.name\|msvcrt\|fcntl"` vacío. Banderas de Edge y sandbox sin cambios: `git diff --stat origin/develop -- harness/browser` vacío.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): grep sin coincidencias (exit 1) y `git diff --stat` de `harness/browser` vacío; `tests/unit/test_portability.py` dentro de 7.1.
- [x] 7.5 Documentación: README (comando, opción, variable), runbook (cómo medir el selector y qué guarda; mensajes nuevos en la tabla), `.env.example`.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8): `git diff --stat -- README.md docs .env.example` → 4 ficheros; en el README, el modo de respuesta en Copilot Web, `/mode` en la tabla, `/status` y `HARNESS_DEEP_REQUEST_TIMEOUT_S` en Configuración.

## 8. Medida real y demo del corte

- [ ] 8.1 Medir el selector real con el dueño: `uv run python scripts/copilot_probe.py response-mode` (paso de la sonda; no envía nada). Evidencia: el resumen «paste only this» con `complete: yes`, `response mode: confirmed …`, `URL changed: no`, `turns changed: no`, `left as found: yes`. Estado: **NOT RUN** (lo ejecuta el coordinador con el dueño; esta rama no abre la página real).
- [ ] 8.2 Demo del Corte 11 que reproduce Wilson, con el SHA de la rama mergeada: en `main.py chat` con Copilot, `/mode deep` (el panel dice `deep`, no se abre nada), una pregunta (en Edge se ve el modo profundo antes de que se escriba; `history` dice `mode deep`), `/mode quick` y otra pregunta, `/mode auto` y otra. Evidencia: el log de la terminal (sin texto de Copilot) y `history SESSION_ID`. Estado: **BLOCKED** por 8.1.
