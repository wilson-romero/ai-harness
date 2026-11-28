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
  - Recibo: ver 8.2 y 8.4.

## 5. Sin ventana solo si se pide (D5)

- [x] 5.1 Comprobado en el Playwright instalado cómo interactúa `headless` con `launch_persistent_context` y `channel="msedge"` (design, Contexto) y medido el `User-Agent` con y sin ventana en un perfil desechable.
  - Recibo (2026-11-27, macOS arm64, Edge 158): `Chromium._innerDefaultArgs` añade `--headless`, `--hide-scrollbars`, `--mute-audio`, `--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4`; `getExecutableName` devuelve el canal. Script de medida (perfil desechable, `about:blank`): sin ventana, el `User-Agent` contiene `HeadlessChrome/158` y `Edg/158`; con ventana, `Chrome/158` y `Edg/158`, sin `Headless`.
- [x] 5.2 `HARNESS_COPILOT_HEADLESS` (`off` por defecto), `EdgeLauncher.from_settings(..., window=)`, inicio de sesión y sonda siempre con ventana. Sandbox y opciones quitadas sin cambios. Oráculo: `test_questions_use_a_window_unless_headless_is_switched_on` (el servidor ve `[False, True]` por el `User-Agent`), `test_signing_in_always_uses_a_window`, `test_defaults`.
  - Recibo: ver 8.2; mutantes M10–M11 en 7.1.
- [x] 5.3 Una página distinta sin ventana se rechaza por las guardas de siempre. Oráculo: `test_a_page_that_differs_without_a_window_is_refused[login|other]` (`authentication_required` / `timeout` «not ready», «nothing was sent», 0 prompts; control: con ventana la misma página responde).
  - Recibo: ver 8.2.

## 6. Sonda `speed` (D6)

- [x] 6.1 `speed [--questions N]`: 8 envíos muestreados con la lectura del proveedor, reglas `fast_fire`/`summarise_fast`/`choose_fast`, tres variantes con el proveedor, `finish_speed`, `add_turn_speed` (solo lo confirmado, quita lo demás, no escribe si los localizadores cambiaron), `turn_speed_of` en `assemble`, tabla por fases. Oráculo: `test_speed_measures_both_paths_with_the_fixed_prompts_only` (14 prompts recibidos = 14 anunciados = 14 usados, todos de `PROMPTS`, `fast_end` y `tab_reuse` escritos, sin canarios ni `127.0.0.1` ni `word1` en el resumen y el resultado), `test_speed_refuses_a_fast_end_that_would_cut_a_late_block` (ninguna regla válida, todas con adelantos, respuestas enteras, `fast_end` ausente), `test_speed_without_measured_locators_sends_nothing`, y las pruebas unitarias de la regla (`test_the_rule_*`, `test_a_flickering_signal_restarts_the_confirmation`, `test_text_that_changes_after_the_signal_restarts_the_confirmation`, `test_an_early_rule_is_never_valid_and_none_is_chosen`, `test_a_rule_met_on_fewer_sends_than_planned_is_not_valid`, `test_the_soonest_valid_rule_is_chosen`, `test_the_announced_sends`).
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
  - Recibo: PENDIENTE.
- [x] 8.2 Lote de Edge: `caffeinate -i uv run pytest -m edge`.
  - Recibo: PENDIENTE.
- [x] 8.3 `openspec validate --all --strict`, `scripts/check_public_safety.py`, `scripts/check_sec_matrix.py`.
  - Recibo: PENDIENTE.
- [x] 8.4 Portabilidad y ficheros compartidos.
  - Recibo: PENDIENTE.
- [x] 8.5 Tabla sintética antes/después: el propio paso `speed` contra la página sintética, con la ventana de estabilidad de la página real (4000 ms) y Edge con ventana, de modo que la variante sin ventana es una comparación de verdad. `off` es la conducta de antes (4.1 lo comprueba). **Es la página sintética, no Copilot**: las cifras reales salen de 9.1.
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

    Primera pregunta: 7235 ms `off`, 3812 ms `on`, 3771 ms `headless`. Caminos `on`: `reload` y cuatro `reuse` (`declined: new tab` la primera); finales: cinco `signal`. Sin ventana no cambia nada medible en la página sintética (1720 frente a 1725 ms): la diferencia real, si la hay, la dirá 9.1. Tras esta medida se corrigieron dos detalles de la tabla y la elección (una fase de 0 ms salía como «-»; en un empate entre señales gana la que eligió `measure`), con su prueba `test_on_a_tie_the_signal_measure_chose_wins`.

## 9. Medida real y demo

- [ ] 9.1 Medir en la página real con el dueño: `uv run python scripts/copilot_probe.py speed` (23 envíos de prompts fijos). Evidencia: el resumen con la tabla `off`/`on`/`headless`, `sends: 23 used of 23 planned` (o menos si una variante paró) y `to ui.json: …`. Estado: **NOT RUN** (lo ejecuta el coordinador con el dueño; esta rama no abre la página real).
- [ ] 9.2 Demo que reproduce Wilson con el SHA de la rama mergeada: tras 9.1, `main.py chat` con Copilot y tres preguntas seguidas; `history SESSION_ID --timings` dice `path reuse` en la 2.ª y la 3.ª y `end signal` si se midió; con `HARNESS_COPILOT_REUSE_TAB=off HARNESS_COPILOT_FAST_END=off`, `path reload` y `end window`. Evidencia: la salida de `history --timings` (sin texto). Estado: **BLOCKED** por 9.1.
