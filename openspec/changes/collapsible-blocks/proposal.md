# Proposal

## Why

Wilson usó la pantalla completa (`shell-tui`) contra Copilot real y el 2026-11-27 dijo: «El bloque es denso de leer. OpenCode, Codex, Claude Code pueden expandir y contraer los bloques para que sea más fácil seguir la conversación». Las cifras:

- Una respuesta real de revisión de un HLS tiene unas **50 líneas** (dato de Wilson, 2026-11-27; el contenido no entra al repo). A eso se suman la línea de contexto del proyecto y los pasos de una Skill.
- En la terminal de las pruebas (110 × 32), el panel de la conversación tiene **27 filas** (medido con `Pilot` el 2026-11-27). Una respuesta de 50 líneas ocupa casi dos pantallas, y cada pregunta nueva la empuja hacia arriba. A los diez turnos, volver a la segunda respuesta exige recorrer unas 500 filas.
- Hoy la pantalla dibuja cada bloque entero. No hay forma de plegar ninguno.

El objetivo: seguir la conversación de un vistazo y abrir solo lo que hace falta, sin tocar el núcleo ni aflojar ninguna garantía de `shell-tui`.

Pertenece al **Corte 9 · Interfaz conversacional**, cuarta entrega (tras `interactive-shell`, `shell-appearance` y `shell-tui`). Riesgo **N1**: no toca datos, proveedores ni la aprobación, pero pone cromo del harness (cabecera, línea plegada, pie de «líneas ocultas») justo al lado del texto ajeno, e incluso con un extracto de ese texto. SEC que cubre: **SEC-15** (el texto ajeno sigue acotado, saneado e inerte, y no puede pasar por cromo) y **SEC-02** (la pantalla muestra los bloques de la sesión tomada). No toca SEC-07 ni SEC-12, y sus pruebas siguen igual. Se demuestra en **macOS**. Windows queda como ejecución opcional: el código no tiene ramas por plataforma.

## What Changes

- **Cada turno es un bloque plegable:** la línea de la persona y todo lo que el harness mostró después (respuesta, avisos, salida de órdenes y de Skills). Plegado, el turno es una línea que construye el harness: quién (`you → mock`, `/history`, `skill demo-echo`), cuántas líneas, el estado (`completed`, `uncertain`, `failed`, `interrupted`, `truncated` o el estado de la ejecución de la Skill) y lo que escribió la persona, tras `› `.
- **Cada bloque de un turno se pliega:** la respuesta del proveedor, el texto ajeno de `/history`, `/context`, `/memory` y de las Skills, y los avisos del harness de más de una línea.
- **Valores por defecto** (D1, D2), para que una conversación larga se lea sin tocar nada:
  - Una respuesta corta se ve entera.
  - Una larga muestra sus primeras filas, tantas como caben en el panel. El pie, en el borde inferior, dice `… 38 more lines · enter/click to expand`.
  - Los metadatos (la línea de contexto con sus omitidos y adjuntos, los pasos de una Skill) quedan en una línea.
  - Los errores, avisos e interrupciones nunca se pliegan solos.
  - Al enviar una línea nueva, los turnos anteriores al penúltimo se pliegan solos. No se pliega ninguno que la persona haya abierto o cerrado a mano, ni el que tiene la selección.
- **Línea plegada de un bloque:** el cromo del harness (`▸ mock · 52 lines`) y, tras `| `, el esquema de títulos de la respuesta (`## Resumen · ## Alternativas`) o su primera línea. Ese extracto sale saneado, en una sola línea, acotado a 200 caracteres y cortado al ancho.
- **Teclado y ratón** (D3). La entrada conserva siempre el foco.
  - Desde la entrada: `alt+↑`/`alt+↓` (o `ctrl+↑`/`ctrl+↓`) eligen bloque y `ctrl+o` abre o cierra el elegido (o la respuesta más reciente).
  - `Esc` entra a recorrer los bloques. Ahí, `↑`/`↓` mueven la selección, `enter`/`espacio` abren o cierran, `+`/`-` expanden o pliegan todo, `home`/`end` van al primero o al último y `Esc` vuelve a escribir. Cualquier otra tecla también vuelve a escribir y se escribe.
  - Con el ratón, un clic en la cabecera o en el pie del bloque lo abre o lo cierra. Un clic en el texto no hace nada.
  - Paleta: «Browse blocks», «Open or close the block», «Expand all blocks», «Collapse all blocks» y «Jump to latest». El pie de la pantalla muestra los atajos.
- **Posición estable** (D3): al abrir o cerrar, la cabecera del bloque sigue en su fila del panel, y lo que llega mientras se lee no mueve el panel.
- **Un registro por sesión, solo en memoria** (D5): `/new`, `/resume` y el selector muestran los bloques de la sesión tomada, con su estado de plegado. Nada de eso se escribe en disco.
- **Arreglo de paso:** un aviso del harness entre la pregunta y la respuesta (una `warning:` de la petición) ya no le quita el título a la respuesta.

**No entra:**

- Plegar la **caja de aprobación**. Ni se toca la caja ni su regla de «el final de la propuesta se ha mostrado»; la rama `feature/approval-buttons` la está cambiando.
- Cambiar el **texto plano** (`--plain`), que sigue imprimiendo todo en orden.
- Recordar el plegado entre ejecuciones o mostrar los turnos de ejecuciones anteriores (para eso está `/history`).
- Buscar dentro de la conversación, copiar un bloque, plegar por secciones de Markdown, o recalcular la vista previa de los bloques ya mostrados cuando cambia el tamaño de la terminal (D1, límite).
- Streaming.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `interactive-shell`, sin archivar, como en `shell-tui`: se **añaden** los requisitos de bloques plegables. Este change **amplía** un requisito de `shell-tui`, «Texto ajeno contenido e inerte en la pantalla completa», que decía que el texto ajeno se muestra *solo* dentro de un bloque con borde. Ahora una línea plegada puede llevar un extracto acotado, de una línea, tras la marca `| ` y con un estilo que el texto ajeno no puede producir. Como `shell-tui` no está archivado, el delta va como requisito añadido («Extracto ajeno en una línea plegada»). Al archivar, después de `shell-tui`, pasa a MODIFIED de aquel requisito (tarea 6.2).
- Comprobado con `grep -rn "pantalla completa\|interactive-shell\|bloque" openspec/specs/` (2026-11-27): nada sobre la pantalla. Las coincidencias de «bloque» son el bloque de contexto de la memoria (`project-context`, `secret-redaction`), que este change no toca. Ninguna capacidad de `openspec/specs/` cambia.

## Impact

- **Código:** `harness/shell/tui.py` (los bloques, los turnos, el registro por sesión, las teclas y la paleta) y `harness/shell/blocks.py` (nuevo, solo biblioteca estándar: qué se pliega, cuánto se ve y qué dice la línea plegada). No cambian `conversation.py`, `render.py`, `terminal.py`, `app.py`, el motor de Skills, los proveedores ni la base de datos.
- **Fuera del código:** `README.md` («Conversación › Aspecto») y este change. Tests: `tests/unit/test_shell_tui_blocks.py` nuevo y una prueba más en `tests/integration/test_chat_tui_terminal.py`. Ninguna aserción existente cambia.
- **Conflicto esperado con `feature/approval-buttons`:** esa rama cambia `ApprovalScreen` y `CodeInput`, y este change no los toca. Los dos cambian `tui.py`: este en los bloques, `PromptInput`, `HarnessApp` (CSS, `show_rows`, `_submit`, `run_entry`, `COMMAND_ENTRIES`) y las constantes del pie. Si aquella rama añade CSS de la caja o entradas a la paleta, el conflicto será de texto en esos mismos bloques y se resuelve a mano.
- Sin migración ni datos nuevos.
