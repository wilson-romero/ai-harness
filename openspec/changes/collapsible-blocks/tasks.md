# Tasks

Cada `[x]` lleva su recibo debajo, con fecha y plataforma. Los oráculos se nombran en cada tarea. Todo se ejecutó en macOS 26.2 arm64 con Python 3.14.8 y Textual 8.2.8. Windows no se ha ejecutado: no hay código por plataforma (`tests/unit/test_portability.py`).

Los controles negativos se aplicaron con un guion fuera del repositorio: aplica una mutación, ejecuta la prueba que la tiene que detectar, restaura el fichero y usa `PYTHONDONTWRITEBYTECODE=1` y `-p no:cacheprovider`. El guion está en el *scratchpad* de la sesión de desarrollo y no entra al repositorio. Cada mutación se cita en su tarea como «Mn».

## 1. Rama y premisas

- [x] 1.1 Rama `feature/collapsible-blocks` desde `origin/develop` (`5af28ed`). Hecho: `git log --oneline -1 origin/develop` → `5af28ed`.
  - Recibo (2026-11-27, macOS arm64): `git checkout -B feature/collapsible-blocks origin/develop` → «Switched to a new branch».
- [x] 1.2 Leer en el Textual instalado lo que fija el diseño: atajos de `Input`, el despacho de teclas por la MRO, el foco al pulsar, `border_title`/`border_subtitle`, el anclaje, `scroll_end`, `Content.wrap`, `text-wrap`/`text-overflow` y el widget `Collapsible`. Oráculo: las citas de fichero y línea en `design.md` («Premisas»).
  - Recibo (2026-11-27, macOS arm64): leído en `.venv/lib/python3.14/site-packages/textual/` (`widgets/_input.py`, `message_pump.py`, `app.py`, `screen.py`, `widget.py`, `_compositor.py`, `content.py`, `css/_styles_builder.py`, `widgets/_collapsible.py`). Dos premisas medidas con un programa de prueba: con `nowrap` y `ellipsis`, una línea de 200 caracteres queda en una fila cortada con `…`; y `Widget.region` vale también para un widget fuera de la vista (y negativo o mayor que el panel).

## 2. Corte vertical: plegar una respuesta larga, abrirla, pie verdadero

- [x] 2.1 `harness/shell/blocks.py` (solo biblioteca estándar) y los bloques de `tui.py`: `FoldBlock`, `ForeignBlock` con cabecera y pie en sus bordes, `NoticeBlock`, `Turn` y `SessionLog`. Una respuesta larga llega plegada a su vista previa con `… K more lines · enter/click to expand`; `ctrl+o`, `Esc`+`enter` o un clic en la cabecera la abren. Oráculo: `test_a_short_reply_is_whole_and_a_long_one_folds_with_its_exact_count` (las filas mostradas son exactamente las primeras `preview_lines(alto)` líneas, y el pie dice `total − mostradas`).
  - Recibo (2026-11-27, macOS arm64): pasa; commit `57b101b`. Las 52 pruebas de `test_shell_tui.py` y `test_shell_tui_review.py` pasan sin tocar ninguna aserción.
- [x] 2.2 La vista previa se mide en filas de pantalla (`Content.wrap` al ancho del bloque) y el panel queda anclado a su final (D1, D3). Oráculo: `test_a_folded_reply_of_wrapped_lines_fits_the_pane_as_it_arrives` (el bloque cabe en el panel, su cabecera y su pie se ven, y el pie cuenta las filas no mostradas). Control negativo: M12 (contar cada línea como una fila) y M2 (contar el pie desde el tamaño de la vista previa).
  - Recibo (2026-11-27, macOS arm64): pasa; M12 y M2 → `1 failed` cada una. Fallo real encontrado al capturar la pantalla: con líneas que se parten en dos, 19 líneas de vista previa ocupaban 38 filas y la cabecera de la respuesta nueva quedaba fuera de la vista; y `scroll_end` corría antes de maquetar el bloque recién montado, así que el pie quedaba debajo. Arreglado en `b62d13b`.

## 3. Defaults, turnos, teclas, posición y sesiones

- [x] 3.1 Defaults (D1, D2): respuesta corta entera, larga plegada, metadatos en una línea, alertas enteras, turnos anteriores al penúltimo plegados al enviar, y una elección a mano que se mantiene. Oráculo: `test_older_turns_fold_to_one_line_and_a_manual_choice_sticks`, `test_skill_step_bookkeeping_is_one_line_by_default`, `test_default_folds`. Control negativo: M4 (plegar también lo elegido a mano) y M11 (no plegar nunca los metadatos).
  - Recibo (2026-11-27, macOS arm64): pasan; M4 y M11 → `1 failed` cada una.
- [x] 3.2 Teclas, ratón y paleta (D3): `Esc` para recorrer, flechas, `enter`/`espacio`, `+`/`-`, `home`/`end`; `alt+↑`/`alt+↓` y `ctrl+o` desde la entrada; clic en la cabecera o en el pie; las cinco entradas de la paleta; el pie de la pantalla con los atajos. Oráculo: `test_browsing_moves_and_toggles_and_a_letter_types_again`, `test_a_click_on_the_header_toggles_and_on_the_text_does_nothing`, `test_expand_all_and_collapse_all_from_the_palette_and_the_keys`, `test_the_palette_starts_browsing_and_jumps_to_the_latest`. Control negativo: M5 (recorrer se come todas las teclas), M15 (la letra que termina el recorrido no se escribe) y M6 (cualquier clic abre un bloque ajeno).
  - Recibo (2026-11-27, macOS arm64): pasan; M5, M15 y M6 → `1 failed` cada una.
- [x] 3.3 Posición estable (D3). Oráculo: `test_the_block_being_read_does_not_jump`: al abrir un turno antiguo y su respuesta, sus cabeceras siguen en su fila; lo que llega mientras se recorre no mueve la respuesta; al plegar todo, la línea del turno ocupa la fila de su cabecera, y abrirlo todo sin `_keep_in_place` la mueve, que es el control dentro de la prueba. También `test_opening_the_newest_reply_at_the_end_keeps_its_header`. Control negativo: M3 (abrir sin `_keep_in_place`) y M7 (lo que llega sigue el final aunque se recorran los bloques).
  - Recibo (2026-11-27, macOS arm64): pasan; M3 y M7 → `1 failed` cada una. M3 sobrevivía a la primera versión de la prueba, porque abrir un bloque crece hacia abajo y no mueve su cabecera. Se añadió el caso que sí la mueve: abrir la respuesta más reciente con el panel anclado al final.
- [x] 3.4 Un registro por sesión en memoria (D5). Oráculo: `test_switching_session_shows_that_sessions_blocks` (`/new` muestra un panel nuevo que lo dice y empieza arriba; `/resume` vuelve a los bloques de la primera sesión con la respuesta todavía abierta; dos registros en `session_logs`). Control negativo: M8 (un solo registro) y M16 (sin `min-height` en `#conversation`, el panel anclado se desplaza por encima de su principio: `scroll_y` −9).
  - Recibo (2026-11-27, macOS arm64): pasa; M8 y M16 → `1 failed` cada una. Fallo real encontrado al capturar el README: con menos contenido que panel, el anclaje de Textual ponía un desplazamiento negativo (`_compositor.py:609-619` no lo valida) y dejaba 9 filas vacías arriba. Arreglado en `db01d36`.

## 4. Garantías con su control negativo

- [x] 4.1 El cromo no se puede imitar (D4). Oráculo: `test_a_reply_imitating_the_chrome_cannot_pass_for_it`. La respuesta imita la línea plegada de otro turno y el pie, dentro y fuera del borde. Celda a celda en la pantalla compuesta, solo las palabras del harness llevan el fondo del cromo. También `test_no_style_foreign_text_can_get_has_the_chrome_background` (ningún estilo de `STYLES` tiene fondo) y `test_an_excerpt_is_one_bounded_line` (con separadores, `\r`, `\x85`, ESC, OSC 8, bidireccionales y 10 000 caracteres: una línea de 200 como mucho). Control negativo: M1 (el extracto en `CHROME`), M9 (el extracto sin `terminal_safe`), y `test_negative_control_an_excerpt_in_chrome_is_detected`.
  - Recibo (2026-11-27, macOS arm64): pasan; M1 y M9 → `1 failed` cada una.
- [x] 4.2 El pie dice siempre lo que falta. Oráculo: `test_the_footer_always_says_what_is_hidden_after_line_n`. Una orden en la línea 82 y una primera línea que dice «0 more lines»: el pie cuenta las filas reales y es el único texto de «more lines» sobre el cromo; al abrir, la última línea es la orden. También `test_a_folded_mebibyte_reply_costs_its_preview` (1 MiB: plegada, `truncated` en su título y el aviso del harness visible). Control negativo: M14 (un pie sin número) y `test_negative_control_a_footer_from_the_preview_size_would_lie`.
  - Recibo (2026-11-27, macOS arm64): pasan; M14 → `1 failed`. M14 sobrevivía a la primera versión de la prueba, que comparaba el pie con la misma función que lo genera; ahora se compara también con el texto literal `… N more lines ·`.
- [x] 4.3 Plegar es solo de la pantalla: no envía nada, no quita el foco, y la línea escrita por adelantado no se envía mientras el núcleo trabaja (`_take`). Oráculo: `test_toggling_while_the_core_works_sends_nothing_typed_ahead` (clic, `ctrl+o`, `alt+↑` y `enter` con el proveedor colgado: la línea sigue en la entrada y el proveedor tiene 2 peticiones) y `test_a_reply_arriving_never_takes_the_typing`. El control negativo de `_take` es el de `shell-tui` (`test_lines_typed_in_one_go_send_one_question`), que sigue pasando.
  - Recibo (2026-11-27, macOS arm64): pasan.
- [x] 4.4 La caja de aprobación no se pliega ni se toca. Oráculo: `test_skill_step_bookkeeping_is_one_line_by_default`: con la caja abierta, ningún bloque ni turno está dentro de ella; `ctrl+o` y `Esc` no hacen nada allí y la entrada de la caja conserva el foco. `git diff 5af28ed -- harness/shell/tui.py` no toca `ApprovalScreen`, `CodeInput`, `APPROVAL_RULE_SHOWN` ni `NOT_SEEN`. Las pruebas de la caja de `shell-tui`, entre ellas «la propuesta entera antes del código», pasan sin cambios.
  - Recibo (2026-11-27, macOS arm64): pasan. `git diff 5af28ed -- harness/shell/tui.py | grep -n "ApprovalScreen\|CodeInput\|seen_end\|_watch_scroll"` → sin líneas.
- [x] 4.5 Rendimiento (D6). Oráculo: `test_five_hundred_blocks_stay_responsive_and_folding_touches_one`: 500 bloques en 250 turnos, de los que se pliegan al menos 248; abrir uno reconstruye solo ese (`renders`); plegar y expandir todo terminan en el tiempo de la prueba. También `test_a_folded_mebibyte_reply_costs_its_preview`, con menos de 4 000 caracteres de `Content` plegada. Control negativo: M10 (cada apertura reconstruye todos los bloques).
  - Recibo (2026-11-27, macOS arm64): pasan. La de 500 bloques dura 3,22 s, montaje incluido (`--durations`); M10 → `1 failed`.
- [x] 4.6 Un aviso antes de la respuesta no le quita el título. Oráculo: `test_a_warning_before_the_reply_does_not_take_its_title`. Control negativo: M13 (cualquier llamada consume la etiqueta, el comportamiento anterior).
  - Recibo (2026-11-27, macOS arm64): pasa; M13 → `1 failed`.
- [x] 4.7 Nada en disco y nada por plataforma: `blocks.py` solo importa la biblioteca estándar y no abre ni escribe nada (`test_the_folding_module_is_standard_library_and_writes_nothing`); `test_no_input_history_is_ever_written_to_disk` (de `shell-tui`) sigue pasando sobre `tui.py`; y `tests/unit/test_portability.py` pasa. Las sobrescrituras de capturas, portapapeles y `open_url` no cambian.
  - Recibo (2026-11-27, macOS arm64): pasan.
- [x] 4.8 En una pseudoterminal real (`tests/integration/test_chat_tui_terminal.py::test_a_long_reply_folds_and_opens_at_a_real_terminal`, omitida con motivo donde no hay `pty`): una respuesta del Mock de 64 líneas (`HARNESS_MOCK_RESPONSES`) llega con su pie; `Esc` entra a recorrer y `enter` la abre en su sitio (aparece una fila que la vista previa no mostraba); `ctrl+q` sale con 0, la terminal se restaura y hay una sola petición. Control negativo: sin el `enter`, la prueba falla.
  - Recibo (2026-11-27, macOS arm64): pasa; sin `enter` → `1 failed in 66.23s`.
- [x] 4.9 Todas las mutaciones a la vez. Oráculo: el guion de mutaciones, 16 mutantes (M1-M16) y cero supervivientes.
  - Recibo (2026-11-27, macOS arm64): `survivors: 0` (16 de 16 → `1 failed`).

## 5. Documentación y pruebas existentes

- [x] 5.1 README, «Conversación › Aspecto»: captura de texto rehecha (tras `/new`, el panel de la sesión nueva), un apartado de bloques plegables con su captura (un turno plegado y otro abierto a mano), las teclas y las entradas de la paleta. Oráculo: el README cita `FOOTER` tal como se dibuja en 100 columnas; `scripts/check_public_safety.py` pasa.
  - Recibo (2026-11-27, macOS arm64): capturas con un guion de `Pilot` fuera del repositorio sobre una copia de `tests/fixtures/vault-synthetic`; `public-safety: PASS`.
- [x] 5.2 Ninguna aserción existente cambia. Oráculo: `git diff 5af28ed -- tests/unit/test_shell_tui.py tests/unit/test_shell_tui_review.py tests/unit/test_shell_render.py tests/tui_support.py` vacío. En `tests/integration/test_chat_tui_terminal.py` solo se añaden un `import` y una prueba al final. La prueba de la disposición (`test_the_layout_with_synthetic_content`) sigue buscando `ctrl+p commands` en el pie, que sigue al principio.
  - Recibo (2026-11-27, macOS arm64): el diff de esos ficheros está vacío.
- [x] 5.3 Integrar `develop` con `prompt-economy` (`57c413d`). `git merge` no tuvo conflictos de texto, pero sí uno de conducta: las dos pruebas de `tests/unit/test_shell_tui_prompt_economy.py` leen el bloque de `/context` tal como se dibuja, y ese contexto, más largo que el panel, llega ahora plegado a su vista previa. Cambio en la prueba: un paso más, `ctrl+o`, para abrir el bloque antes de leerlo, como haría la persona. Su aserción («lo que se ve es lo que se envía») no cambia y se cumple con el bloque abierto. Oráculo: las dos pruebas pasan. Control negativo: sin el paso fallan (`2 failed`, la vista previa no incluye las notas de sesión).
  - Recibo (2026-11-27, macOS arm64): sin el paso → `2 failed` en la tanda sin Edge; con el paso → `2 passed`.

## 6. Cierre

- [ ] 6.1 `uv run pytest -q -m "not edge and not copilot"` y después `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y la línea `verify: PASS on <sha>`.
- [ ] 6.2 Al archivar (después de `shell-tui`): convertir «Extracto ajeno en una línea plegada» en MODIFIED del requisito «Texto ajeno contenido e inerte en la pantalla completa» y releer los demás requisitos añadidos contra `openspec/specs/interactive-shell/spec.md`.
- [ ] 6.3 Revisión independiente de la frontera cromo/texto ajeno y de la conducta de las teclas. Pendiente.
- [ ] 6.4 **Demo del corte** (Wilson, macOS, con el Mock y después con Copilot real). Wilson la reproduce sobre el SHA del merge:
  1. Escribir una respuesta larga del Mock y lanzar la conversación (zsh):

     ```zsh
     uv run python -c 'import json; b="\n".join(f"- Punto sintético {n}." for n in range(1,51)); print(json.dumps({"HLS": "## Resumen\nRespuesta sintética.\n\n## Riesgos\n"+b+"\n\n## Alternativas\n- Ninguna."}))' > "${TMPDIR:-/tmp}/mock-largo.json"
     HARNESS_PROVIDER=mock HARNESS_DATA_DIR="$(mktemp -d)" HARNESS_MOCK_RESPONSES="${TMPDIR:-/tmp}/mock-largo.json" uv run python main.py chat
     ```
  2. Preguntar «revisa el HLS» dos veces y una tercera con otra cosa.
  3. Comprobar que la última respuesta llega con su cabecera a la vista y su pie `… N more lines`, y que el primer turno se ve plegado en una línea.
  4. `Esc`, `↑`, `enter`, `+`, `-`, una letra, `ctrl+o`, y un clic en una cabecera y en el texto.
  5. `/new` y `/resume`.
  6. Con Copilot real, una revisión de unas 50 líneas.

  Evidencia: una nota con lo visto (sin contenido corporativo) o un vídeo que no sale del equipo. Estado: **NOT RUN**.
