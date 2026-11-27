# Proposal

## Why

Wilson lee las respuestas en la pantalla completa y le cuestan dos cosas. Medido el 2026-11-27 con Pilot y el Mock sobre `1a49ad2` (capturas de texto en el informe del change):

- **Tablas.** Una tabla de Markdown llega como sus caracteres: `| Componente | Capa | Estado |`, la fila `|:-----------|:----:|-------:|` y filas que no se alinean. A 80 columnas, una fila de 3 celdas con una celda larga se parte por la mitad de esa celda y su resto (`filas | Dominio | en revisión |`) empieza en la columna del texto.
- **Bloques de código.** Las líneas ```` ```python ```` y ```` ``` ```` se ven tal cual. No hay nada que separe el código de la prosa salvo el color.
- **Respuestas largas plegadas al llegar.** Una respuesta de 73 líneas a 100×30 llega plegada a 17 líneas de contenido, con el pie `… 54 more lines · enter/click to expand`. Para leerla hay que abrirla: `Esc` y `enter`, `ctrl+o` o un clic. Desde `collapsible-blocks` es así para toda respuesta que no cabe en el panel con 4 filas de margen.

Wilson decidió el 2026-11-27:

1. **Tablas como texto alineado** dibujado por el harness, no con un widget de Textual. Si no caben, las celdas se parten dentro de su columna.
2. **Las respuestas llegan enteras.** Plegar a mano sigue igual y los turnos antiguos se siguen plegando solos.
3. **El resaltado azul** que vio sobre el texto era la selección de Textual (lo confirmó: había seleccionado el texto antes de la captura). No hay cambio de colores; solo una línea en el README.

Pertenece al **Corte 9 · Interfaz conversacional**, tras `tui-spacing`. Riesgo **N1**: no cambia qué se envía, qué se escribe ni qué se aprueba, pero el harness pasa a dibujar caracteres dentro del texto ajeno. SEC que cubre:

- **SEC-15:** el texto ajeno no puede tomar el aspecto del chrome. Lo que el harness añade a una tabla o a un bloque de código son solo `│`, `─`, `┼` y espacios, atenuados, sin esquinas (no se puede cerrar un recuadro) y sin fondo. El texto de las celdas sigue saneado y sin interpretar.

Se demuestra en **macOS**. Windows es una comprobación opcional en la máquina de pruebas, no una puerta.

## What Changes

- **Tablas (D1, D2):** una tabla GFM de una respuesta se dibuja como texto alineado:
  - columnas del ancho de su contenido, medido con el ancho que usa el renderizador (los caracteres anchos cuentan dos);
  - una raya `─┼─` bajo la cabecera, que va en negrita;
  - las marcas `:--`, `:-:` y `--:`;
  - los estilos de línea de las celdas (código, negrita, cursiva);
  - si no cabe en el panel, se estrecha primero la columna más ancha y las celdas se parten dentro de su columna, con una raya entre filas;
  - se queda como llegó si ni así cabe, si está mal formada o si pasa de 200 filas, 16 columnas o 1000 caracteres por celda.
- **Bloques de código (D3):** las líneas de la valla se sustituyen por una raya con el lenguaje (`── python ───`) y una raya de cierre. El código no cambia.
- **Texto plano (D4):** `--plain` hace lo mismo sin color. Las filas de la pantalla completa sin color siguen siendo exactamente las del texto plano.
- **Respuestas enteras al llegar (D5):** una respuesta se ve entera salvo que pase de 64 000 caracteres, que llega plegada como antes. El resto del texto ajeno (`/history`, `/memory`) y las reglas de los turnos antiguos no cambian.
- **El principio a la vista (D6):** si la respuesta es más alta que el panel, el panel se coloca en su principio y el pie dice `↓ N more rows below` hasta llegar al final.
- **README (D7):** tablas, bloques, respuestas enteras, y cómo seleccionar y copiar en Terminal.app y Windows Terminal.
- **Dos pruebas inestables** de `approval-buttons`, deterministas ahora sin tocar la protección:
  - `test_keys_typed_ahead_of_the_box_cannot_approve`;
  - `test_the_approval_buttons_at_a_real_terminal`.

**No entra:**
- volver a alinear una tabla al cambiar el tamaño de la terminal (se alinea al ancho del panel cuando llega);
- tablas o código fuera de las respuestas del proveedor;
- resaltado de sintaxis del código;
- los widgets `Markdown`, `MarkdownTable` o `DataTable` de Textual;
- cambiar el sistema de colores;
- copiar al portapapeles desde la pantalla;
- `/run` (propuesta `code-run`) y `/mode` (`feature/response-mode`): el panel lateral y la caja de aprobación siguen pudiendo tomar una línea más.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `interactive-shell`: delta sobre los changes `shell-appearance`, `collapsible-blocks` y `tui-spacing`, sin archivar. Un `ls openspec/specs/` del 2026-11-27 confirma que `interactive-shell` aún no está en las specs vigentes (solo `llm-provider`, `memory-*`, `project-context`, `request-recovery`, `secret-redaction` y `session-management`). El delta va como ADDED y se convierte al archivar (tarea 6.1).

## Impact

- **Código:**
  - `harness/shell/render.py`: `markdown_layout`, `layout_width`, `MD_TABLE`, y el parámetro `layout` de `foreign_lines` y `foreign_rows`;
  - `harness/shell/blocks.py`: `ARRIVE_WHOLE_MAX_CHARS` y `default_fold`;
  - `harness/shell/tui.py`: `ConversationPane`, `_show_start`, `_show_below`, `below_hint`, `foreign_width`, `TuiTerminal.layout_columns`;
  - `harness/shell/conversation.py` y `harness/shell/app.py`: el ancho de la tabla llega al núcleo.
- **Pruebas:**
  - `tests/unit/test_shell_reply_layout.py` y `tests/unit/test_shell_tui_replies.py`, nuevos;
  - `tests/unit/test_shell_tui_blocks.py`: las pruebas que daban por hecho una respuesta plegada al llegar la pliegan a mano o usan otro texto ajeno;
  - `tests/unit/test_shell_render.py`, `tests/unit/test_shell_tui_buttons.py`, `tests/integration/test_chat_tui_terminal.py`.
- **Documentación:** `README.md` («Conversación › Aspecto»).
- **Dependencias:** ninguna nueva.
