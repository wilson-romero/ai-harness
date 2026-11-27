# Tasks

## 1. Colores por roles (D1, D6)

- [x] 1.1 `harness/shell/palette.py` con `ROLES`. El CSS declara los roles; `STYLES` y `CHROME` los toman; el marco ajeno pasa a `$foreground-muted`. No queda ningún hexadecimal en `tui.py`.
  - Hecho: `grep -nE "#[0-9a-fA-F]{6}" harness/shell/tui.py` no devuelve nada (antes, 10 coincidencias).
  - Oráculo, en `tests/unit/test_shell_tui_spacing.py`:
    - `test_no_colour_of_the_house_only_theme_variables`;
    - `test_every_colour_role_names_a_theme_variable`;
    - `test_the_roles_resolve_in_a_full_and_in_an_ansi_theme` (`textual-dark` y `ansi-dark`);
    - `test_the_foreign_frame_is_neutral`;
    - y `tests/unit/test_shell_tui_styles.py`, sin cambios.
  - `tests/unit/test_shell_tui_blocks.py`: el ayudante `_chrome_cells` lee el fondo de `CHROME` del tema en lugar de `#3a3f4b`. Ninguna aserción cambia.
  - Recibo (2026-11-27, macOS arm64): en el recibo de 6.1.

## 2. Panel lateral (D2)

- [x] 2.1 Panel oculto por debajo de 100 columnas y de 32 columnas de ancho. `/status` dice `sends: N`, `memory: N note(s) in the last question` y los nombres de las notas.
  - Oráculo:
    - `test_the_side_panel_only_from_100_columns`, a 80×24, 99×30, 100×30 y 120×40;
    - `test_status_says_what_the_side_panel_says`, en texto plano.
  - Recibo: en 6.1.

## 3. Mensajes de la persona (D3)

- [x] 3.1 `.you` con barra `thick $you-bar`, fondo `$you-fill` y una fila encima. En `ansi-dark` la barra sigue dibujada.
  - Oráculo:
    - `test_the_persons_message_has_a_bar_a_fill_and_a_row_before_it`;
    - `test_in_an_ansi_theme_the_bar_still_marks_the_persons_message`.
  - Recibo: en 6.1.

## 4. Columna de texto y huecos (D4, D5)

- [x] 4.1 Borde de 2 columnas y sangría de 1 dentro de la barra o el marco: todo el texto empieza en la columna 4.
  - Huecos de una fila desde 30 filas, salvo encima del primer bloque del panel (`-lead`, y `.turn:first-child > .turn-summary`).
  - Por debajo de 30 filas: sin huecos en las líneas del harness y la entrada en 2 filas, solo con CSS. El pie se ve siempre.
  - Oráculo:
    - `test_text_starts_on_one_column`, a los tres tamaños;
    - `test_vertical_gaps_only_where_the_rows_allow`, a los tres tamaños;
    - `test_the_conversation_keeps_its_rows`, a los tres tamaños;
    - `test_the_app_declares_both_breakpoints`.
  - Filas de conversación visibles (Pilot, dos turnos con el Mock):

    | Tamaño | Antes (`481ad2e`) | Después |
    |---|---|---|
    | 80×24 | 20 | 21 |
    | 100×30 | 26 | 26 |
    | 120×40 | 36 | 36 |

  - Recibo: en 6.1.

## 5. Archivo

- [ ] 5.1 Al archivar, después de `shell-tui`, `collapsible-blocks` y `approval-buttons`: este delta pasa de ADDED a lo que corresponda sobre «Panel lateral de la sesión tomada» (de `shell-tui`) y sobre los requisitos de color del chrome de `collapsible-blocks`.

## 6. Comprobaciones del corte

- [x] 6.1 Pruebas nuevas vistas fallar antes y controles negativos.
  - Oráculo: `tests/unit/test_shell_tui_spacing.py` (24 pruebas) sobre el código de `481ad2e`, y un mutante por regla.
  - Recibo (2026-11-27, macOS arm64):
    - Con `tui.py` y `conversation.py` de `481ad2e`: 21 failed y 5 passed.
      - Las 5 que pasan son guardas de lo que ya era cierto y no debe romperse: `blocks.py` sin hexadecimales, la barra en ANSI y las filas de conversación a los tres tamaños.
      - Los mutantes de abajo las controlan: «sin barra» falla 5 y «huecos a cualquier altura» falla 1.
    - Con el cambio: 26 passed (espaciado y estilos) y 372 passed en todas las pruebas de `shell` y `tui`.
    - Mutantes (`PYTHONPYCACHEPREFIX` nuevo por mutante), 11 de 11 fallan:

      | Mutante | Resultado |
      |---|---|
      | Un hexadecimal en `MD_LINK` | 1 failed |
      | Panel a cualquier ancho | 2 failed |
      | Sin fondo de la persona | 1 failed |
      | Sin barra de la persona | 5 failed |
      | Líneas del harness en otra columna | 3 failed |
      | Entrada en otra columna | 3 failed |
      | Huecos a cualquier altura | 1 failed |
      | Entrada de 3 filas por debajo de 30 | 1 failed |
      | Sin hueco ante las líneas del harness | 2 failed |
      | Marco ajeno en `$secondary` | 1 failed |
      | Sin *breakpoints* | 3 failed |
- [x] 6.2 Las dos tandas, una vez cada una con `caffeinate -i`: `-m "not edge and not copilot"` y `-m edge`. Si falla una de Edge, se repite sola antes de concluir. Después, `openspec validate --all --strict`, `scripts/check_public_safety.py` y `scripts/check_sec_matrix.py`.
  - Oráculo: código 0 en cada una.
  - Recibo (2026-11-27, macOS arm64, sobre `345acfa`): Edge `155 passed, 1835 deselected` en 1253 s, código 0. Sin Edge: `1 failed, 1832 passed`, código 1. La que falló, `test_chat_tui_terminal.py::test_ctrl_c_interrupts_the_question_not_the_screen`, falla también sola, así que no es carga. La prueba espera el texto «is uncertain» en la salida del pseudo-terminal. Con la columna de texto nueva, el panel parte la línea `interrupted: request <id> is uncertain: …` entre «is» y «uncertain». El aviso sí se muestra; la espera ahora busca «uncertain:», que no puede partirse (`437e42c`). Con eso, el fichero da `13 passed`.
  - Tanda sin Edge repetida sobre `437e42c`: `1 failed, 1832 passed`, código 1. Esta vez falló `test_shell_tui_buttons.py::test_keys_typed_ahead_of_the_box_cannot_approve`, una prueba de `approval-buttons` que mide tiempo (el recuadro tarda 0,5 s en armarse). Sola pasa 5 de 5 (`1 passed`, 1,6–2,5 s). La lectura es que, con la máquina cargada, el recuadro ya estaba armado cuando llegaron las teclas. No toca nada de este corte.
  - `openspec validate --all --strict`: 24 de 24 válidos, código 0. `scripts/check_sec_matrix.py`: PASS (15 filas, 135 pruebas), código 0. `scripts/check_public_safety.py` sobre los 13 ficheros del corte: PASS, código 0. `test_portability.py` está en la tanda sin Edge y pasa.
- [x] 6.3 Sin código por plataforma: `tests/unit/test_portability.py` pasa con los ficheros nuevos.
  - Recibo: en 6.2.
- [x] 6.4 Documentación: `README.md` («Conversación › Aspecto»), con la captura nueva a 100×30 y el apartado «Espaciado y colores».

## 7. Demo

- [ ] 7.1 Demo (Wilson, macOS): con el Mock, `main.py chat` a 80×24, 100×30 y 120×40, con el fragmento de zsh del informe del change.
  - Qué comprobar:
    - a 80 columnas no hay panel y `/status` da sus datos;
    - el texto empieza en una sola columna;
    - lo que escribes lleva barra y fondo suave;
    - por debajo de 30 filas no hay filas en blanco entre las líneas del harness;
    - la caja de aprobación sigue igual.
  - Evidencia: el SHA de la rama y una captura.
  - Estado: **NOT RUN**, pendiente de Wilson.
