# Tasks

## 1. Tablas y bloques de código (D1–D4)

- [x] 1.1 `markdown_layout` en `harness/shell/render.py`: tablas alineadas, partidas dentro de sus columnas si no caben, literales si están mal formadas o pasan los límites; bloques de código entre rayas con su etiqueta. `foreign_lines` y `foreign_rows` la usan con el mismo ancho.
  - Hecho: una respuesta con una tabla se ve alineada en la pantalla completa y en `--plain`, sin las vallas ```` ``` ````.
  - Oráculo: `tests/unit/test_shell_reply_layout.py` (36 pruebas), entre ellas:
    - `test_a_table_is_aligned_by_the_width_of_its_content` (salida exacta);
    - `test_a_table_cannot_draw_a_box_or_take_a_background`;
    - `test_the_styled_rows_print_what_the_plain_rows_print`, a 4 anchos;
    - `test_the_plain_conversation_aligns_a_reply_table_without_colour`;
    - `test_one_mebibyte_of_adversarial_tables_is_bounded`, 5 formas.
  - Las pruebas de equivalencia de `tests/unit/test_shell_render.py` comparan ahora contra `foreign_lines(..., markdown=)`.
  - Recibo (2026-11-27, macOS arm64): sobre `1a49ad2` el fichero no se importa (`markdown_layout` no existe); con el cambio, `36 passed`.
- [x] 1.2 El ancho del panel llega al núcleo: `ConversationPane.on_resize` → `HarnessApp._measure` → `TuiTerminal.layout_columns()` → `ConversationDeps.layout`.
  - Oráculo, en `tests/unit/test_shell_tui_replies.py`:
    - `test_a_table_is_laid_out_to_the_width_of_its_block`, a 80, 100 y 120 columnas;
    - `test_the_width_follows_the_pane`;
    - `test_the_rules_of_a_table_have_no_background`.
  - Recibo: en 6.2.

## 2. Respuestas enteras al llegar (D5, D6)

- [x] 2.1 `default_fold`: una respuesta llega `EXPANDED` salvo que pase de `ARRIVE_WHOLE_MAX_CHARS` (64 000). El panel muestra su principio si no cabe y el pie dice `↓ N more rows below`.
  - Oráculo, en `tests/unit/test_shell_tui_replies.py`:
    - `test_a_long_reply_arrives_whole_with_its_start_at_the_top_of_the_pane`;
    - `test_reading_to_the_end_clears_the_hint`;
    - `test_a_short_reply_keeps_the_end_in_view_and_shows_no_hint`;
    - `test_the_reply_still_folds_by_hand`;
    - `test_older_turns_still_fold_by_themselves`;
    - `test_a_reply_over_the_work_bound_arrives_folded`;
    - `test_default_fold_of_a_reply`.
  - Recibo (2026-11-27): antes de tocar `blocks.py` y `tui.py`, 6 de estas 12 fallaban; con el cambio, `12 passed`.
- [x] 2.2 Pruebas de `collapsible-blocks` que daban por hecha una respuesta plegada al llegar (`tests/unit/test_shell_tui_blocks.py`). Ahora la pliegan a mano (`set_fold(Fold.PREVIEW)`), usan texto de `/history`, que sigue plegándose, o esperan lo nuevo (enter o clic la cierran). Ninguna protección se quita.
  - La prueba de pseudo-terminal pasa a `test_a_long_reply_arrives_whole_and_folds_at_a_real_terminal`: espera `more rows below`, pliega con `Esc`+`enter`, ve `▸ mock · 64 lines` y la abre otra vez.
  - Oráculo: `test_shell_tui_blocks.py` `40 passed`; el fichero de pseudo-terminal en 6.2.

- [x] 2.3 Colocación de una respuesta, tras la revisión del 2026-11-27 sobre `fe808fc`. Allí `test_output_does_not_move_the_pane_while_browsing_at_the_end` falló 4 de 5 veces y pasó 1 (`63 == 77`).
  - Causa: dos cosas.
    - La prueba llenaba el panel con respuestas largas y daba por hecho que quedaba al final. Con D6 queda en el principio de la última.
    - El producto, a veces, decidía antes de la maquetación: la respuesta medía 0 filas, «cabía» y el panel se anclaba a su final. Era la vez que la prueba pasaba. En una sonda de 4 ejecuciones, en 1 todas las alturas eran 0.
  - Arreglo en `tui.py`:
    - solo se coloca la respuesta más nueva (`_arriving`);
    - la decisión espera su altura, como mucho 20 redibujados;
    - enviar una línea o empezar a recorrer los bloques anula la colocación.
  - La prueba ahora llena el panel con respuestas que caben, así que está en su final. Comprueba lo mismo: recorriendo los bloques, una respuesta larga que llega no mueve el panel.
  - Oráculo, en `tests/unit/test_shell_tui_replies.py`:
    - `test_a_reply_not_laid_out_yet_is_not_taken_for_one_that_fits` (determinista: coloca a mano un bloque montado sin maquetar);
    - `test_a_line_sent_before_the_reply_is_placed_goes_to_the_end`;
    - `test_of_replies_that_arrive_together_the_newest_is_shown_from_its_start`.
  - Recibo (2026-11-27, macOS arm64):
    - Con el `tui.py` de `fe808fc`: las dos primeras fallan 5 de 5; la tercera falla 2 de 5; la prueba reescrita pasa 5 de 5, porque su propia comprobación nunca falló.
    - Con el arreglo, las cuatro dan 30 de 30 solas y 12 de 12 en copias a la vez.
    - Las hermanas que leen la geometría del panel tras llegar texto (`test_switching_session_shows_that_sessions_blocks`, `test_the_palette_starts_browsing_and_jumps_to_the_latest`, `test_sending_while_browsing_goes_to_the_end`, `test_the_block_being_read_does_not_jump` y las tres de D6): 12 de 12 en copias a la vez cada una.

## 3. README (D7)

- [x] 3.1 «Conversación › Aspecto»: tablas y bloques de código, respuestas enteras, el pie `↓`, el límite de 64 000 y la entrada «Texto resaltado en azul» (selección de Textual; copiar en Terminal.app y Windows Terminal).
  - Comprobado: «Visualización › Permitir informes del ratón», `⌘R`, leído del `MainMenu.nib` y del `MainMenu.loctable` de Terminal.app 466. `Mayús`+arrastrar en Windows Terminal, de la documentación de Microsoft; sin probar en Windows.

## 4. Pruebas inestables (D8)

- [x] 4.1 `test_keys_typed_ahead_of_the_box_cannot_approve` controla el armado (`arm_s = 3600`, luego `opened -= 3600` y `_arm()`). `test_the_approval_buttons_at_a_real_terminal` envía las teclas cuando la línea ya se tomó, con el Mock a 3 s.
  - Oráculo: 12 copias a la vez de cada una.
  - Recibo (2026-11-27, macOS arm64):
    - Prueba de pseudo-terminal, antes: 2 de 12 fallaron esperando «The whole proposal has been shown». La sonda guardó la pantalla de un fallo: `error: skill 'demo-o-echo' does not exist`.
    - Después: 12 de 12 pasan, en 5,0–5,2 s cada una.
    - Prueba de Pilot, después: 12 de 12 pasan (1,3–1,4 s).
  - Control negativo: el mutante «la caja toma teclas antes de armarse» quita a la vez las tres capas del armado (botones habilitados desde el principio, Approve sin `armed`, sin comprobación al pulsar). Con él, la prueba falla (`1 failed`).

## 5. Controles negativos

- [x] 5.1 Un mutante por regla. Cada uno se aplica solo, con un `PYTHONPYCACHEPREFIX` nuevo, y se restaura después (`scratchpad/drive/mutants_reply.py`, fuera del repo).
  - Oráculo: 14 de 14 fallan.
  - Recibo (2026-11-27):

    | Mutante | Resultado |
    |---|---|
    | Tablas nunca estrechadas | 2 failed |
    | Marcas de alineación ignoradas | 1 failed |
    | `\|` escapado partido | 1 failed |
    | Fila con más celdas aceptada | 2 failed |
    | Sin límite de filas | 1 failed |
    | Tabla que no cabe dibujada igual | 1 failed |
    | Vallas de código mantenidas | 7 failed |
    | Cualquier palabra como etiqueta | 2 failed |
    | Rayas de tabla con fondo | 1 failed |
    | Respuestas largas plegadas al llegar otra vez | 5 failed |
    | El panel siempre al final | 2 failed |
    | Sin aviso de lo que queda debajo | 2 failed |
    | El ancho no se vuelve a medir | 1 failed |
    | La caja toma teclas antes de armarse | 1 failed |

## 6. Verificación

- [ ] 6.1 Al archivar: este delta pasa a MODIFIED sobre «Vista previa de una respuesta larga» (`collapsible-blocks`) y «Respuesta con formato y marca intacta» (`shell-appearance`), después de archivar esos changes.
- [x] 6.2 Las dos tandas, una vez cada una con `caffeinate -i`: `-m "not edge and not copilot"` y `-m edge`. Si falla una de Edge, se repite sola antes de concluir. Después, `openspec validate --all --strict`, `scripts/check_public_safety.py` y `scripts/check_sec_matrix.py`.
  - Oráculo: código 0 en cada una.
  - Recibo (2026-11-27, macOS arm64, sobre `1cd6ba2`):
    - Sin Edge: `1881 passed, 157 deselected` en 321 s, código 0.
    - Edge: `155 passed, 1883 deselected` en 1541 s, código 0.
    - `openspec validate --all --strict`: 25 de 25 válidos, código 0.
    - `scripts/check_sec_matrix.py`: PASS (15 filas, 135 pruebas), código 0.
    - `scripts/check_public_safety.py` sobre los 18 ficheros del change: PASS, código 0.
- [x] 6.3 Sin código por plataforma: `tests/unit/test_portability.py` pasa con los ficheros nuevos.
  - Recibo: está en la tanda sin Edge de 6.2, que pasa entera.
- [x] 6.4 Capturas antes (`1a49ad2`) y después, con Pilot y el Mock: una tabla y un bloque de código a 80×40, 100×40 y 120×40, y una respuesta de 73 líneas al llegar a 100×30. Texto y SVG, fuera del repo; el texto va en el informe del change.

## 7. Demo

- [ ] 7.1 Demo (Wilson, macOS): con el Mock, `main.py chat` y el fragmento de zsh del informe, una respuesta con una tabla y un bloque de código, a 80 y a 120 columnas, y una respuesta larga.
  - Qué comprobar:
    - la tabla alineada y partida a 80;
    - el bloque entre rayas con `python`;
    - la respuesta larga entera con su principio arriba y `↓ N more rows below` en el pie;
    - `ctrl+o` la pliega;
    - `--plain` muestra la misma tabla.
  - Evidencia: el SHA de la rama y una captura.
  - Estado: **NOT RUN**, pendiente de Wilson.
