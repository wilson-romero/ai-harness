# Tasks

Cada `[x]` lleva su recibo debajo: «Recibo (fecha, plataforma)», con el comando y la salida relevante. Los oráculos se nombran en cada tarea. En esta rama no se abre la página real de Copilot, ni el perfil real de Edge, ni `HARNESS_DATA_DIR` real: todo corre contra la página sintética local (`tests/fixtures/copilot_ui/app.html`, servida por `tests/copilot_app.py`, que cuenta cada prompt y cada carga de página) y perfiles desechables.

Nota de honestidad sobre el orden: las pruebas se escribieron después del código (no hubo una pasada roja antes de implementar). Cada garantía se vio fallar con su **mutante** (grupo 7): el código se rompe a propósito en el punto que la garantía protege, la prueba falla, y el fichero se restaura.

## 1. Tiempos por fases (D1)

- [x] 1.1 `harness/providers/copilot_timings.py`: `TurnTimings`, fases y palabras de listas cerradas, `record` (añade una línea JSON, recorta a 1000 al pasar de 512 KB, nunca falla la pregunta) y `read_for` (valida cada línea). Oráculo: `test_every_question_records_its_phases_and_no_text` (dos preguntas → dos líneas con las fases de la recarga, `settle` ≥ 2000 ms, sin canarios del prompt ni de la respuesta ni `127.0.0.1`), `test_timings_of_another_provider_or_a_tampered_file_are_not_shown` (control negativo: tres líneas manipuladas y una no JSON se descartan), `test_timings_are_appended_and_trimmed`, `test_a_timings_file_that_cannot_be_written_never_fails_the_question`.
  - Recibo: ver 8.1 y 8.2.
- [x] 1.2 `history SESSION_ID --timings` y el aviso con `HARNESS_COPILOT_TIMINGS=on`. Oráculo: `test_history_shows_the_timings_of_each_question` (sin la variable no hay aviso; con ella, `warning: timings (s): answered, path reload, end window`; `history --timings` dos líneas; control: sin `--timings` no aparece «timings»).
  - Recibo: ver 8.2.
- [x] 1.3 `provider.last_timings` para la barra de progreso de otra rama. Oráculo: el mismo `request_id` que la última línea del fichero (`test_every_question_records_its_phases_and_no_text`).
  - Recibo: ver 8.2.

## 2. Pestaña de confianza (D2)

- [x] 2.1 `_TabMemory`, `reuse_refusal` (ocho condiciones, cada una con su palabra), `remember`, solo primer intento y navegador retenido; `guard`, modo, posición de la respuesta, identificador tras enviar y `on_sent` sin cambios. Oráculo: `test_a_trusted_tab_is_asked_again_without_reloading` (tres preguntas: `page_hits == 1`, `prompt_count == 3`, prompts en orden en la conversación de la sesión, sin fases de recarga en la 2.ª y 3.ª y con `guard`).
  - Recibo: ver 8.2.
- [x] 2.2 Las guardas rechazan. Oráculos y su control: `test_reuse_refuses_a_tab_moved_to_another_address` (`address`, recarga y sigue), `test_reuse_refuses_a_tab_another_session_used` (`new tab`, `no conversation`, `other session`; cada conversación con solo sus prompts), `test_reuse_refuses_a_page_that_signed_out` (`page state` → `authentication_required`, 1 prompt), `test_reuse_refuses_a_conversation_deleted_elsewhere` (`address` → `failed` «Create a new session», 1 prompt), `test_reuse_refuses_a_tab_with_a_turn_added_elsewhere` (`turns` → recarga con el aviso «1 more turn(s)»), `test_reuse_refuses_a_tab_idle_too_long` (`idle`), `test_on_the_reused_tab_the_mode_is_set_and_confirmed_before_typing` (el prompt llega en `quick` con la lista cerrada). El control positivo de todas es 2.1.
  - Recibo: ver 8.2; mutantes M1–M4 en 7.1.
- [x] 2.3 Página sintética con `live=1` (la pestaña sigue `/api/live/<id>`: sesión cerrada, conversación borrada, turnos añadidos) y servidor con `forget`/`add_elsewhere`. Oráculo: las pruebas de 2.2 que la usan.
  - Recibo: ver 8.2.

## 3. Fin por señal positiva (D3)

- [x] 3.1 `FastEnd` en `ui.json` (señal estructural con su control medido, 300 ≤ `confirm_ms` ≤ 2000, `sends` ≥ 1). Oráculo: `test_a_fast_end_outside_its_bounds_is_refused` (5 casos), `test_a_fast_end_needs_the_control_it_watches`, `test_a_measurement_without_the_new_entries_is_still_accepted`.
  - Recibo: ver 8.1.
- [x] 3.2 `await_reply`: señal vista ocupada, libre sin interrupción, texto sin cambios durante la ventana corta; la condición de siempre en la misma vuelta. Oráculos, todos con igualdad del texto completo (`make_reply(prompt)`, más el bloque tardío): `test_a_reply_ends_on_its_signal_before_the_window` (control: sin la regla, `end window`, ≥ 2,5 s más), `test_a_pause_while_the_reply_is_still_busy_does_not_end_it` (pausa 1,5 s), `test_a_signal_that_flickers_does_not_end_the_reply` (pausa 2 s con parpadeo de 300 ms), `test_a_signal_that_never_shows_leaves_the_window_to_decide` (`nostop`), `test_a_reply_that_streams_slowly_is_returned_whole` (6 trozos cada 0,8 s), `test_a_block_appended_after_the_signal_is_waited_for` (6 trozos tras la señal), `test_without_the_fast_end_a_late_block_is_kept_by_the_window`, `test_both_optimisations_together_keep_every_answer_whole`.
  - Recibo: ver 8.2; mutantes M5–M7 en 7.1.
- [x] 3.3 Variantes de la página sintética: `steps`, `flicker_ms`, `nostop`, `late_block_ms`/`late_chunks`. Oráculo: las pruebas de 3.2.
  - Recibo: ver 8.2.

## 4. Interruptores y sin medida (D4)

- [x] 4.1 `HARNESS_COPILOT_REUSE_TAB`, `HARNESS_COPILOT_FAST_END`, `HARNESS_COPILOT_TIMINGS` (`on`/`off`) y `speed_for`. Oráculo: `test_without_the_measurement_every_question_reloads_and_waits_the_window` (tres preguntas, `reload`/`window`, 3 cargas, 3 prompts), `test_each_switch_turns_its_optimisation_off` (2 casos), `test_each_switch_turns_off_only_its_own_optimisation`, `test_without_the_measurement_both_optimisations_stay_off`, `test_a_switch_takes_only_on_or_off` (control negativo: `maybe`, `1`).
  - Recibo: ver 8.1, 8.2; mutante M8 en 7.1.
- [x] 4.2 Las pruebas anteriores del proveedor, la conversación, la sonda y el modo pasan con sus aserciones sin cambiar (truncado, sugerencias excluidas, lenguaje de bloques de código, `authentication_required`, plazo de `deep`, `timeout` frente a `uncertain`). Oráculo: `git diff origin/develop -- tests/browser/test_copilot_provider.py tests/browser/test_copilot_conversation.py tests/browser/test_copilot_mode.py tests/browser/test_copilot_probe.py tests/browser/test_copilot_probe_mode.py` vacío y el lote de Edge en verde.
  - Recibo: `git diff --stat origin/develop` de esos cinco ficheros vacío; ver 8.2.

## 5. Sin ventana solo si se pide (D5)

- [x] 5.1 Comprobado en el Playwright instalado cómo interactúa `headless` con `launch_persistent_context` y `channel="msedge"` (design, Contexto) y medido el `User-Agent` con y sin ventana en un perfil desechable.
  - Recibo (2026-11-27, macOS arm64, Edge 158): `Chromium._innerDefaultArgs` añade `--headless`, `--hide-scrollbars`, `--mute-audio`, `--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4`; `getExecutableName` devuelve el canal. Script de medida (perfil desechable, `about:blank`): sin ventana, el `User-Agent` contiene `HeadlessChrome/158` y `Edg/158`; con ventana, `Chrome/158` y `Edg/158`, sin `Headless`.
- [x] 5.2 `HARNESS_COPILOT_HEADLESS` (`off` por defecto), `EdgeLauncher.from_settings(..., window=)`, inicio de sesión y sonda siempre con ventana. Sandbox y opciones quitadas sin cambios. Oráculo: `test_questions_use_a_window_unless_headless_is_switched_on` (el servidor ve `[False, True]` por el `User-Agent`), `test_signing_in_always_uses_a_window`, `test_defaults`.
  - Recibo: ver 8.2; mutantes M10–M11 en 7.1.
- [x] 5.3 Una página distinta sin ventana se rechaza por las guardas de siempre. Oráculo: `test_a_page_that_differs_without_a_window_is_refused[login|other]` (`authentication_required` / `timeout` «not ready», «nothing was sent», 0 prompts; control: con ventana la misma página responde).
  - Recibo: ver 8.2.

## 6. Sonda `speed` (D6)

- [x] 6.1 `speed [--questions N]`: 8 envíos muestreados (12, más 2 en `deep`, tras la revisión: 9.2) con la lectura del proveedor, reglas `fast_fire`/`summarise_fast`/`choose_fast`, tres variantes con el proveedor, `finish_speed`, `add_turn_speed` (solo lo confirmado, quita lo demás, no escribe si los localizadores cambiaron), `turn_speed_of` en `assemble`, tabla por fases. Oráculo: `test_speed_measures_both_paths_with_the_fixed_prompts_only` (14 prompts recibidos = 14 anunciados = 14 usados, todos de `PROMPTS`, `fast_end` y `tab_reuse` escritos, sin canarios ni `127.0.0.1` ni `word1` en el resumen y el resultado), `test_speed_refuses_a_fast_end_that_would_cut_a_late_block` (ninguna regla válida, todas con adelantos, respuestas enteras, `fast_end` ausente), `test_speed_without_measured_locators_sends_nothing`, y las pruebas unitarias de la regla (`test_the_rule_*`, `test_a_flickering_signal_restarts_the_confirmation`, `test_text_that_changes_after_the_signal_restarts_the_confirmation`, `test_an_early_rule_is_never_valid_and_none_is_chosen`, `test_a_rule_met_on_fewer_sends_than_planned_is_not_valid`, `test_the_soonest_valid_rule_is_chosen`, `test_the_announced_sends`).
  - Recibo: ver 8.1, 8.2; mutante M9 en 7.1.
- [x] 6.2 Variante sin ventana: «not usable» en lugar de un tiempo. Oráculo: `test_headless_that_behaves_differently_is_reported_not_usable[login|other]` (con ventana de verdad: variantes `off`/`on` enteras, `headless: not usable (AuthenticationRequired|ProviderTimeout)`, 0 envíos sin ventana, 12 prompts en total, `n/a` en la fila `total`).
  - Recibo: ver 8.2; mutante M12 en 7.1.
- [x] 6.3 Runbook (`docs/runbook/copilot.md`, «Velocidad de cada pregunta») y `.env.example` con las cuatro variables.
  - Recibo: `git diff --stat origin/develop -- docs/runbook/copilot.md .env.example`.

## 7. Controles negativos

- [x] 7.1 Mutantes (script de la sesión, fuera del repo: aplica el cambio, corre el oráculo, restaura el fichero; después `grep` confirma el original).
  - Recibo (2026-11-27/28, macOS arm64, Python 3.14.8, Edge 158):

    | Mutante | Cambio | Oráculo | Resultado |
    |---|---|---|---|
    | M1 | `reuse_refusal` confía en cualquier pestaña ya usada | `test_reuse_refuses_a_tab_moved_to_another_address` | `1 failed`, exit 1 |
    | M2 | sin límite de inactividad | `test_reuse_refuses_a_tab_idle_too_long` | `1 failed`, exit 1 |
    | M3 | sin la comparación del número de turnos | `test_reuse_refuses_a_tab_with_a_turn_added_elsewhere` | **sobrevive** (`1 passed`): la comprobación de los elementos del último turno da el mismo `turns`; las dos se solapan |
    | M3b | sin ninguna de las dos comprobaciones de turnos | la misma | `1 failed`, exit 1 |
    | M4 | sin `classify` en la pestaña | `test_reuse_refuses_a_page_that_signed_out` | `1 failed`, exit 1 |
    | M5 | fin rápido sin haber visto la página ocupada | `test_a_signal_that_never_shows_leaves_the_window_to_decide` | `1 failed`, exit 1 (respuesta cortada) |
    | M6 | un parpadeo no reinicia la confirmación | `test_a_signal_that_flickers_does_not_end_the_reply` | `1 failed`, exit 1 |
    | M7 | fin rápido sin mirar el texto | `test_a_block_appended_after_the_signal_is_waited_for` | `1 failed`, exit 1 |
    | M8 | reutilizar sin la medida `tab_reuse` | `test_without_the_measurement_every_question_reloads_and_waits_the_window` | `1 failed`, exit 1 |
    | M9 | la regla de la sonda no mira los cambios del texto | `test_text_that_changes_after_the_signal_restarts_the_confirmation` (M9u) | `1 failed`, exit 1; la prueba de la sonda con bloque tardío **no** lo mata (el bloque llega después de las dos ventanas y la regla ya era temprana) |
    | M9b | la sonda nunca cuenta un adelanto | `test_speed_refuses_a_fast_end_that_would_cut_a_late_block` | `1 failed`, exit 1 |
    | M10 | el inicio de sesión sigue `HARNESS_COPILOT_HEADLESS` | `test_signing_in_always_uses_a_window` | `1 failed`, exit 1 |
    | M11 | `HARNESS_COPILOT_HEADLESS` ignorada | `test_questions_use_a_window_unless_headless_is_switched_on` | `1 failed`, exit 1 |
    | M12 | sin ventana siempre «usable» | `test_headless_that_behaves_differently_is_reported_not_usable` | `2 failed`, exit 1 |

    No hay mutante para «la guarda sigue en la pestaña reutilizada»: con `reuse_refusal` intacta, quitar `guard` del camino rápido no cambia ninguna prueba (las ocho condiciones ya la cubren). Se mantiene como defensa en profundidad; M1 muestra que, si la confianza falla, es `guard` quien impide escribir en otra conversación (la pregunta falla en vez de responder).

## 8. Verificación

- [x] 8.1 Lote sin navegador: `caffeinate -i uv run pytest -m "not edge and not copilot"`.
  - Recibo (2026-11-28, macOS arm64, Python 3.14.8, sobre `a5ddcf7` mezclado con `origin/develop` `d5f7864`): `2392 passed, 223 deselected in 400.12s`, exit 0, sin repeticiones.
  - Recibo tras la revisión (2026-11-28, `9b92756`): `2641 passed, 244 deselected in 439.23s`, exit 0, sin repeticiones.
  - Recibo tras windows-parity-3 (2026-11-28, `ec18009` mezclado con `develop` `02b2c09`, con la prueba de 8.6 y el reinicio de `gave_up`): `2654 passed, 247 deselected in 473.49s`, exit 0, sin repeticiones.
- [x] 8.2 Lote de Edge: `caffeinate -i uv run pytest -m edge`.
  - Recibo (mismo árbol, Edge 158): `221 passed, 2394 deselected in 2091.89s`, exit 0, sin repeticiones.
  - Recibo tras la revisión (2026-11-28, `9b92756` = `a9d9594` mezclado con `origin/develop` `cc39fb7`, Edge 158): `242 passed, 2643 deselected in 3064.07s`, exit 0, sin repeticiones.
  - Recibo tras windows-parity-3 (mismo árbol, Edge 158): `245 passed, 2656 deselected in 3950.59s`, exit 0, sin repeticiones.
- [x] 8.3 `openspec validate --all --strict`, `scripts/check_public_safety.py`, `scripts/check_sec_matrix.py`.
  - Recibo (mismo árbol): `Totals: 29 passed, 0 failed`, exit 0; `public-safety: PASS (507 file(s))`, exit 0 (control negativo: el pre-commit rechazó una primera versión de esta tarea porque `158` seguido de tres `.0` parece una IP; se reescribió); `sec-matrix: PASS (15 rows, 177 tests)`, exit 0, con las pruebas nuevas en SEC-02, SEC-06 y SEC-07.
  - Recibo tras la revisión (2026-11-28, `9b92756`): `Totals: 30 passed, 0 failed (30 items)`, exit 0; `public-safety: PASS (532 file(s), 5 denylist term(s))`, exit 0; `sec-matrix: PASS (15 rows, 216 tests)`, exit 0 (SEC-07 con las pruebas de la pausa entre fases y del bloque tardío; conflicto con `develop` en esa fila resuelto juntando las dos listas).
  - Recibo tras windows-parity-3 (mismo árbol): `Totals: 30 passed, 0 failed (30 items)`, exit 0; `public-safety: PASS (533 file(s), 5 denylist term(s))`, exit 0; `sec-matrix: PASS (15 rows, 216 tests)`, exit 0.
- [x] 8.4 Portabilidad y ficheros compartidos. Oráculo: `git diff origin/develop -- harness scripts | grep -c "sys.platform\|os.name\|msvcrt\|fcntl"` → 0; `git diff --stat origin/develop -- harness/core harness/mcp harness/shell harness/storage` vacío (ni `service.py`, ni `plan*.py`, ni `conversation.py`, ni migración). Compartidos tocados, solo añadidos: `harness/cli.py` (argumento `--timings` de `history`, la llamada a `_history` partida en dos líneas, y un parámetro con sus líneas en `_history`/`_history_without_content`); `harness/browser/edge.py` (`from_settings` con `window=`); `harness/browser/login.py` (una línea, `window=True`); `docs/security/sec-matrix.md` (15 líneas añadidas en tres filas, sin cambiar estados). Banderas de Edge: solo las que Playwright añade al pedir `headless` (design D5) y solo con `HARNESS_COPILOT_HEADLESS=on`; sandbox y `DROPPED_DEFAULT_ARGS` sin cambios.
  - Recibo (mismo árbol): grep → `0`; `git diff --stat` de esas carpetas vacío; `tests/unit/test_portability.py` dentro de 8.1.
  - Recibo tras la revisión (`9b92756`): grep → `0`; `git diff --stat origin/develop` de esas carpetas vacío. La revisión no toca más compartidos: `harness/storage/private.py` solo se importa. `provider.last_timings` es atributo público y estable para el bucle del agente de `develop` (comentado en el código y en D1; `test_last_timings_is_a_stable_public_attribute`).
- [x] 8.5 Tabla sintética antes/después: el propio paso `speed` contra la página sintética, con la ventana de estabilidad de la página real (4000 ms) y Edge con ventana, de modo que la variante sin ventana es una comparación de verdad. `off` es la conducta de antes (4.1 lo comprueba). **Es la página sintética, no Copilot**: las cifras reales salen de 10.1; la tabla tras la revisión, en 9.8.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8, Edge 158.0.4370.45; script de la sesión fuera del repo que arranca `SyntheticCopilot`, escribe el `ui.json` sintético con `stability_window_ms: 4000` y llama a `copilot_probe.main(["speed", "--questions", "5"])`): `complete: yes`, `sends: 23 used of 23 planned`, el servidor recibió 23 prompts, 1 de 9 cargas sin ventana. Las 8 reglas válidas (8/8, 0 adelantos; retraso medio 561 ms con 500 ms, 1064 ms con 1000 ms). Mediana de las preguntas 2..5, en ms:

    | fase | off | on | headless |
    |---|---|---|---|
    | reuse_check | - | 10 | 6 |
    | navigate | 8 | - | - |
    | ready | 22 | - | - |
    | settle | 2030 | - | - |
    | guard | 4 | 3 | 2 |
    | type | 7 | 8 | 6 |
    | reply_start | 109 | 110 | 109 |
    | reply_end | 5050 | 1576 | 1564 |
    | total | **7268** | **1725** | **1720** |

    Primera pregunta: 7235 ms `off`, 3812 ms `on`, 3771 ms `headless`. Caminos `on`: `reload` y cuatro `reuse` (`declined: new tab` la primera); finales: cinco `signal`. Sin ventana no cambia nada medible en la página sintética (1720 frente a 1725 ms): la diferencia real, si la hay, la dirá 10.1. Tras esta medida se corrigieron dos detalles de la tabla y la elección (una fase de 0 ms salía como «-»; en un empate entre señales gana la que eligió `measure`), con su prueba `test_on_a_tie_the_signal_measure_chose_wins`.

- [x] 8.6 Mezclar `bugfix/windows-parity-3` (en `develop` `02b2c09`) y conservar su diagnóstico también en el camino rápido. Mezcla `ec18009`: `copilot_web.py`, `base.py`, `service.py` y `test_copilot_provider.py` sin conflicto; solo `docs/security/sec-matrix.md` (filas SEC-02, SEC-06 y SEC-07), resuelto con las pruebas y los controles negativos de las dos ramas y la línea **Windows** de `develop`, más la nota de que las pruebas de este change son posteriores a la ejecución en Windows (NOT RUN allí). Comprobado sobre el árbol mezclado:
  - Una pestaña retenida que no se reutiliza cae a la recarga, que pasa por `wait_ready`, y una página que entonces no llega a estar lista da el mismo detalle estructural. Oráculo nuevo: `test_a_declined_tab_that_reloads_into_a_page_never_ready_says_what_it_showed` (declinada por `idle`, la recarga recibe una página sin el chat: `timeout`, `not ready in time`, `ended by HARNESS_COPILOT_READY_TIMEOUT_S`, `user turns`, `nothing was sent`, un solo prompt). Pasó a la primera (el comportamiento viene de la mezcla); control negativo R20 (sin `not_ready_seen` en el mensaje): `1 failed`, exit 1.
  - La regla del contexto de la cancelación (`cancel.__context__ = turn.gave_up` si no se envió) está en `_ask`, alrededor de los dos caminos (recarga y conversación retenida, también la reutilizada), así que vale en ambos.
  - Ni la comprobación posterior al fin rápido ni la grabación de tiempos interfieren: la comprobación solo corre después de enviar (la regla mira `not turn.sent`), y la grabación, en el `finally` de `ask`, captura solo `Exception`, así que una `CancelledError` sigue saliendo con su `__context__` intacto (lo que se captura allí es otra excepción, nueva). `gave_up` se pone a `None` al empezar cada intento en `run`: hoy ningún reintento sigue a un `ProviderTimeout` (solo se reintenta una pestaña perdida antes de escribir), así que es defensa.
  - Recibos de los lotes y comprobaciones: 8.1–8.3, «tras windows-parity-3».

## 9. Revisión independiente de `7cc187f` (2026-11-28)

Cada arreglo con su prueba vista **fallar primero** contra el código de `7cc187f` (los tres ficheros de código devueltos a `HEAD` con `git checkout HEAD --`, las pruebas nuevas y el esquema `modes` ya puestos; después restaurados desde una copia), y sus mutantes. macOS arm64, Python 3.14.8, Edge 158.

- [x] 9.1 **Alta: el fin rápido cortaba una respuesta en una pausa entre fases** (D7). Oráculo: `test_an_idle_gap_between_two_phases_does_not_cut_the_reply[700|800]`, `test_a_late_block_after_an_idle_moment_is_kept`, `test_a_signal_element_removed_and_created_again_does_not_cut_the_reply`, `test_an_instant_reply_whose_signal_never_turns_busy_ends_by_the_window`, `test_a_signal_already_busy_before_sending_does_not_count`, `test_the_fast_end_acts_only_in_the_modes_it_was_measured_in`; cada una afirma el texto **entero** y `prompt_count == 1` (`ask_once` lo comprueba en todas las de una pregunta). Fixtures nuevas de la página sintética: `recreate=1` (el botón de parar se quita y vuelve como elemento nuevo) y `stale_stop=1` (visible antes de enviar).
  - Recibo rojo (sobre `7cc187f`): `9 failed, 6 passed, 27 deselected in 223.33s`; los cuatro cortes con `assert 'ZZ-CANARY-RE...rd3 word4 wor' == 'ZZ-CANARY-RE...d12 ZQX-END-1'` (la mitad del texto), el bloque tardío sin `ZZ-LATE-BLOCK-END`, la señal ya ocupada y el modo `deep` con `assert 'signal' == 'window'`. La instantánea pasaba ya (la regla antigua decide; queda como control).
  - Recibo verde: `15 passed, 27 deselected in 238.40s`; los tres ficheros completos `104 passed` salvo los cinco que esta revisión cambió a propósito (ver 9.6).
  - Coste de la comprobación (9.5): `recheck` 553 ms de mediana en la página sintética, cuyo identificador llega a la vez que la respuesta; en la real lo cubre la espera del identificador.
- [x] 9.2 **Sonda** (D7, puntos 3 y 4): «ocupado» solo con la respuesta en la página; temprana si la señal vuelve a ocupada después de dispararse o si la lectura 5 s después difiere; prompts fijos nuevos (`SPEED_PROMPTS`: largo por fases, y búsqueda con citas); dos envíos en `deep` si el modo está medido y `modes` en `fast_end`; anuncio y Enter antes de enviar; `--rounds`, `--skip-headless` y el mínimo en la ayuda; un fin temprano del proveedor en la variante encendida impide escribir. Oráculo: unitarias `test_busy_seen_before_the_reply_exists_does_not_count`, `test_busy_again_after_the_rule_fired_is_early`, `test_a_late_read_that_differs_makes_the_rule_early`, `test_the_planned_sends_and_the_smallest_run`, `test_finish_speed_refuses_a_rule_the_provider_found_early[0-True|1-False]`; de navegador `test_speed_without_the_persons_enter_sends_nothing`, `test_speed_refuses_a_fast_end_on_a_page_that_pauses_between_phases` (500 ms temprana 12/12; 1000 ms, más larga que la pausa, válida: control), `test_speed_refuses_a_fast_end_that_a_late_read_contradicts` (bloque a 5 s, tras el muestreo), `test_speed_with_deep_measured_sends_two_in_deep_and_records_the_modes` (6 + 2 + 2·2 = 10 envíos, el servidor recibe los dos en `deep`), `test_the_smallest_run_is_stated_in_the_help`.
  - Recibo rojo: las unitarias de la sonda, `14 failed, 38 passed` junto con las de 9.3 y 9.4 (antes de tocar código).
  - Recibo verde: `tests/browser/test_copilot_speed_probe.py` `10 passed`; las unitarias `57 passed`.
- [x] 9.3 **Media: un fichero de tiempos corrupto convertía una pregunta enviada en `failed`** (D9). Oráculo: unitarias `test_a_corrupt_timings_file_never_raises` (y que el recorte siguió leyendo con reemplazo), `test_a_directory_in_place_of_the_timings_file_never_raises`, `test_an_unwritable_timings_directory_never_raises`, `test_recording_never_raises_whatever_goes_wrong`; de navegador `test_a_corrupt_timings_file_does_not_change_the_answer`, `test_a_directory_in_place_of_the_timings_file_does_not_change_the_answer`, `test_a_recording_that_raises_does_not_change_the_answer`.
  - Recibo rojo: `test_a_corrupt_timings_file_does_not_change_the_answer` con `RequestStatus.FAILED … 'utf-8' codec can't decode byte 0xff in position 0`, el error que describe la revisión.
  - Recibo verde: en los lotes de 8.1 y 8.2.
- [x] 9.4 **Bajas: permisos (0700/0600, también la copia recortada) y líneas manipuladas en `history --timings`** (D9). Oráculo: `test_the_timings_file_and_its_folder_are_owner_only`, `test_a_line_with_a_bad_field_is_skipped` (14 casos: `"total_ms":"abc"`, negativos, enormes, `True`, tipos cambiados, escapes de terminal, campos de más), `test_control_a_good_line_is_read`, `test_a_deeply_nested_line_is_skipped`, `test_nesting_beyond_the_parser_is_skipped`, `test_an_overlong_line_is_skipped`.
  - Recibo rojo: dentro de los `14 failed` de 9.2 (permisos `0o644`, la línea anidada).
- [x] 9.5 **Baja: la pestaña reutilizada** (D8). Elegido: documentar el límite y dejar `HARNESS_COPILOT_REUSE_TAB` **apagada por defecto**. Lo que la pestaña reutilizada no ve, dicho igual en el README, el runbook y D2: una conversación borrada en otro sitio que la pestaña sigue mostrando (la pregunta se envía; sin la página de «no encontrada» no hay `closed`) y un aviso de sesión caducada sin el indicador medido (`uncertain` en lugar de `authentication_required`). El README ya no dice sin matiz «si ya no existe, no envía nada». Oráculo: `test_defaults`, `test_tab_reuse_measured_but_not_switched_on_stays_off`, `test_reuse_is_off_unless_switched_on`, `test_a_switch_takes_only_on_or_off`.
  - Recibo rojo: `test_reuse_is_off_unless_switched_on` con `['reload', 'reuse'] == ['reload', 'reload']`; `test_defaults` con `(True, True, False, False)`.
- [x] 9.6 **Huecos de prueba.** Tras una pregunta `uncertain`, `failed` o cancelada, la siguiente recarga en una pestaña nueva (`test_after_an_uncertain_question_the_next_one_reloads`, que ahora responde la primera para que haya memoria; `…_failed_…`, `…_cancelled_…`); `prompt_count == 1` en todas las de una pregunta con fin rápido (`ask_once`); el límite de 120 s en su borde con el reloj del proveedor (`test_the_idle_bound_at_its_edge[119.0-reuse|121.0-reload]`, la hora de la memoria movida 119 y 121 s atrás). Pasaban ya con `7cc187f`: son cobertura, y sus mutantes (9.7) muestran que vigilan. Cambiadas a propósito por esta revisión: el valor por defecto de la pestaña (`test_a_switch_takes_only_on_or_off`) y las cifras de la sonda (`18` envíos con `--questions 2`, `fast_end.sends == 12`).
- [x] 9.7 Mutantes de la revisión (`mutants2.py` de la sesión, fuera del repo; aplica, corre el oráculo y restaura; `git status` al final sin más cambios que los de la rama):

    | Mutante | Cambio | Resultado |
    |---|---|---|
    | R1 | sin la comprobación tras un fin rápido | `3 failed`, exit 1 |
    | R2 | la comprobación no mira la señal | `3 failed`, exit 1 |
    | R3 | la comprobación no mira el texto | `1 failed`, exit 1 |
    | R4 | la comprobación no espera lo que queda de la ventana corta | `3 failed`, exit 1 |
    | R5 | tras un fin temprano la regla rápida vuelve a actuar | **sobrevive** (`3 passed`): cada nuevo disparo pasa otra vez por la comprobación, así que el texto sigue entero; apagarla es prudencia, no la garantía |
    | R6 | «ocupado» cuenta antes de que exista la respuesta | `1 failed`, exit 1 |
    | R7 | el fin rápido en todos los modos | `1 failed`, exit 1 |
    | R8 | `record` solo captura `OSError` | `1 failed, 1 passed`, exit 1 |
    | R8b | sin la captura alrededor de la grabación en `ask` | `1 failed`, exit 1 |
    | R8c | el recorte lee sin `errors="replace"` | `1 failed`, exit 1 |
    | R9 / R9b | la carpeta y el fichero / la copia recortada con permisos por defecto | `1 failed` / `1 failed`, exit 1 |
    | R10 | una línea leída sin validar tipos | `14 failed`, exit 1 |
    | R11 | sin capturar `RecursionError` | `1 failed, 1 passed`, exit 1 (con la cota de longitud subida en la prueba; con ella puesta no se llega a anidar tanto) |
    | R11b | sin cota de longitud de línea | `1 failed`, exit 1 |
    | R12 | la pestaña encendida por defecto | `2 failed`, exit 1 |
    | R13 | una pregunta sin respuesta conserva la memoria de la pestaña | **sobrevive** (`3 passed`): la marca `untrusted` de antes abre una pestaña nueva y la memoria ya no coincide (`new tab`); las dos defensas se solapan |
    | R13b | las dos defensas quitadas | `3 failed`, exit 1 |
    | R14 | el límite de inactividad doblado | `1 failed, 1 passed`, exit 1 (121 s reutiliza) |
    | R15 | la sonda no mira la vuelta a ocupado | `1 failed, 1 passed`, exit 1 |
    | R16 | la sonda no mira la lectura de 5 s | `2 failed`, exit 1 |
    | R17 | la sonda cuenta «ocupado» antes de la respuesta | `1 failed`, exit 1 |
    | R18 | la sonda envía sin Enter | `1 failed`, exit 1 |
    | R19 | la sonda escribe una regla que el proveedor vio temprana | `1 failed, 1 passed`, exit 1 |

- [x] 9.8 Tabla sintética antes/después de la revisión (mismo método que 8.5: `speed --questions 5` con ventana, ventana de estabilidad de 4000 ms; la sonda recibe el Enter por la entrada estándar). **Es la página sintética, no Copilot.**
  - Recibo (2026-11-28): `complete: yes`, `sends: 27 used of 27 planned`, el servidor recibió 27, 1 de 9 cargas sin ventana, `early endings in the questions: 0`, `reply changed after it settled: 0`; las 8 reglas válidas (12/12, 0 tempranas); elegida `stop_hidden + 500 ms`. Mediana de las preguntas 2..5, en ms:

    | fase | off (antes y ahora) | on `7cc187f` | on ahora | headless `7cc187f` | headless ahora |
    |---|---|---|---|---|---|
    | settle | 2030 / 2038 | - | - | - | - |
    | reply_end | 5050 / 4980 | 1576 | 1612 | 1564 | 1604 |
    | recheck | - | - | 553 | - | 552 |
    | total | **7268 / 7234** | **1725** | **2341** | **1720** | **2328** |

    Primera pregunta: 7293 `off`, 4435 `on`, 4401 `headless` (antes 7235 / 3812 / 3771). La comprobación cuesta en la página sintética lo que queda de la ventana corta (≈ 550 ms), porque su identificador está antes de que acabe la respuesta; en la real la espera del identificador ya la cubre (D7). Página de la revisión (`pause_ms=2000&flicker_ms=800`): ver 9.9.
- [x] 9.9 Página de la revisión con la sonda (`pause_ms=2000&flicker_ms=800`, mismo método). Oráculo: la regla `stop_hidden + 500` no es válida y todas las respuestas llegan enteras.
  - Recibo (2026-11-28): `complete: yes`, `sends: 27 used of 27 planned`, el servidor recibió 27; `stop_hidden+500 ms: not valid (met 12/12, early 12)`; las otras 7 válidas (la de 1000 ms dura más que la pausa); elegida `aria_busy + 500 ms`; 15/15 respuestas enteras, `early endings: 0`. Total (mediana 2..5): `off` 9242 ms, `on` 4335 ms, `headless` 4341 ms; `recheck` 551 ms. En `7cc187f` la misma página, con `stop_hidden + 500` escrito, cortaba la pregunta a 65 de 122 caracteres (revisión); ahora esa regla ni se escribe y, si estuviera escrita, la comprobación la devuelve a la espera (9.1).

## 10. Medida real y demo

- [ ] 10.1 Medir en la página real con el dueño: `uv run python scripts/copilot_probe.py speed` (27 envíos de prompts fijos, 29 si `deep` está medido; la sonda los anuncia y espera Enter; mínimo que aún escribe las reglas: `--rounds 1 --questions 2 --skip-headless`, 10 o 12). Evidencia: el resumen con la tabla `off`/`on`/`headless`, `sends: 27 used of 27 planned`, `early endings in the questions: 0`, la línea de la lectura de 5 s (o menos si una variante paró) y `to ui.json: …`. Estado: **NOT RUN** (lo ejecuta el coordinador con el dueño; esta rama no abre la página real).
- [ ] 10.2 Demo que reproduce Wilson con el SHA de la rama mergeada: tras 10.1 y con `HARNESS_COPILOT_REUSE_TAB=on` (apagada por defecto, D8), `main.py chat` con Copilot y tres preguntas seguidas; `history SESSION_ID --timings` dice `path reuse` en la 2.ª y la 3.ª y `end signal` si se midió; con `HARNESS_COPILOT_REUSE_TAB=off HARNESS_COPILOT_FAST_END=off`, `path reload` y `end window`. Evidencia: la salida de `history --timings` (sin texto). Estado: **BLOCKED** por 10.1.
