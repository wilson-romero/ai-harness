# Design

## Context

Las respuestas del proveedor llegan como texto ya saneado y redactado. El núcleo lo convierte en filas con `foreign_rows` (pantalla completa) o `foreign_lines` (texto plano), y `markdown_styles` les pone color sin quitar ni añadir un carácter (`shell-appearance`). La pantalla completa dibuja cada respuesta en un `ForeignBlock`. `collapsible-blocks` decide al llegar si se ve entera o plegada a su vista previa.

Premisas medidas aquí (2026-11-27, Textual 8.2.8 instalado, macOS 26.2, Terminal.app 466):

- **El núcleo no conoce el ancho del panel.** La pantalla le dice `columns = UNCUT` (10 000) para que no corte filas: Textual las parte dentro de su bloque. Para alinear una tabla hace falta otro dato, el ancho del texto dentro de un bloque ajeno.
- **`App._on_resize` para el evento.** Un `on_resize` en la aplicación no se llama nunca. Lo recibe un widget: una subclase de `VerticalScroll` con `on_resize` sí se entera de cada cambio de tamaño del panel.
- **El ancho del texto de un bloque ajeno** es el del contenido del panel menos `2 + 2 * BLOCK_INSET` columnas (borde y relleno). Medido a 80, 100 y 120 columnas contra la región del `Static` interior: coincide.
- **`scroll_to_widget(top=True)`** coloca la cabecera del bloque en la primera fila del panel, si el contenido deja desplazarse hasta ahí. `release_anchor()` impide que el panel vuelva solo al final mientras tanto.
- **El resaltado azul** de la captura de Wilson es la selección de Textual: `$screen-selection-background`, `$primary` al 50 %, que sobre `#121212` da `#094472`, el color medido en su captura. Doble clic selecciona el widget; triple clic, el contenedor; un clic la quita. Terminal.app exporta `COLORTERM=truecolor` y dibuja bien el color verdadero con el perfil por defecto (captura del 2026-11-27). No acepta OSC 52 (comprobado con `pbpaste`).
- **Seleccionar con la terminal mientras la aplicación pide el ratón:**
  - Terminal.app: arrastrar con `Fn` pulsada, o desactivar «Visualización › Permitir informes del ratón» (`⌘R`). Comprobado en el `MainMenu.nib` de Terminal.app (elemento del menú «View», tecla `r` con `⌘`) y en su `MainMenu.loctable` en español.
  - Windows Terminal: arrastrar con `Mayús` pulsada (documentación de Microsoft, «Selection» de Windows Terminal). No se ha probado en la máquina de Windows.

## Goals / Non-Goals

**Goals:**
- tablas legibles como texto alineado;
- bloques de código separados de la prosa;
- la misma salida con y sin color;
- respuestas enteras al llegar, con su principio a la vista;
- trabajo acotado con texto hostil;
- las dos pruebas inestables, deterministas.

**Non-Goals:**
- volver a alinear al cambiar de tamaño;
- resaltado de sintaxis;
- widgets de Markdown de Textual;
- copiar desde la pantalla;
- cambiar colores.

## Decisions

### D1 · Tablas alineadas como texto, dibujadas por el harness

- **Qué:** `markdown_layout(lines, width)` en `harness/shell/render.py` recorre las líneas de una respuesta.
  - **Qué es una tabla:** una fila de cabecera con `|`, una fila delimitadora con tantas celdas como la cabecera (cada celda `:?-+:?`) y las filas con `|` que siguen hasta una línea en blanco o sin `|`. Se aceptan las tuberías exteriores o no, y `\|` es un `|` dentro de una celda.
  - **Cómo se dibuja:** cada columna mide lo que su celda más ancha, contada con `_char_columns`, la misma función que usa el renderizador (un carácter ancho cuenta 2). Las celdas se separan con ` │ ` y una raya `─┼─` va bajo la cabecera, que se dibuja en negrita. `:--`, `--:` y `:-:` alinean a la izquierda, a la derecha y al centro. Las celdas conservan sus estilos de línea (código, negrita, cursiva) y sus caracteres. Una fila corta se rellena con celdas vacías.
  - **Qué se queda como llegó:** una fila con más celdas que la cabecera, más de 200 filas, más de 16 columnas o una celda de más de 1000 caracteres. La tabla entera se ve como su texto, con el resaltado de siempre.
  - **Caracteres y estilo:** el harness solo añade `│`, `─`, `┼` y espacios, con el estilo `MD_TABLE` (`dim`): sin esquinas y sin fondo.
  - **El ancho:** `HarnessApp._measure` mide el texto de un bloque ajeno al montar y en cada cambio de tamaño del panel (`ConversationPane.on_resize`). `TuiTerminal.layout_columns()` se lo da al núcleo como un entero, y `ConversationDeps.layout` lo pasa a `foreign_rows(..., layout=)`. En texto plano el ancho sale de las columnas de la terminal (`layout_width`).
- **Por qué:**
  - Decisión del dueño.
  - El texto alineado se lee igual con y sin color, en cualquier terminal y en texto plano.
  - El harness controla cada carácter que dibuja. Así sigue cumpliendo SEC-15: una tabla de una respuesta no puede dibujar un recuadro cerrado como los del chrome ni tomar un fondo. Una celda que imita una línea del harness sigue dentro del recuadro ajeno, tras la marca y con el estilo del texto ajeno.
  - Medir con `_char_columns` evita columnas torcidas con caracteres anchos.
  - Los límites acotan el trabajo de una respuesta hostil: cada línea se parte en celdas como mucho dos veces.
- **Alternativas consideradas y rechazadas:**
  - **El widget `Markdown` de Textual:** interpreta enlaces y marcado, que es justo lo que `shell-tui` prohíbe para el texto ajeno, y no existe en texto plano.
  - **`DataTable` o `MarkdownTable`:** widgets con su propio foco, desplazamiento y colores. Habría otro camino para el texto ajeno, con otras reglas de SEC-15, y la salida no sería la del texto plano.
  - **Un recuadro con esquinas (`┌┐└┘`):** se parecería al chrome del harness y una tabla con celdas falsas podría pasar por él.
  - **Medir con `len`:** las columnas se tuercen con CJK o emoji.
- **Impacto:** spec «Tablas de una respuesta alineadas por el harness» y «Tabla que no se alinea»; `tests/unit/test_shell_reply_layout.py`; `tests/unit/test_shell_tui_replies.py` (anchos a 80, 100 y 120 y sin fondo).

### D2 · Una tabla que no cabe se parte dentro de sus columnas

- **Qué:** si la suma de las columnas y separadores pasa del ancho, se quita una columna cada vez a la más ancha que aún pueda estrecharse, hasta que cabe. Ninguna baja de 3 columnas. Una celda más ancha que su columna se parte tras el último espacio que quepa, o en el ancho si no hay espacio. Sus líneas siguen en su columna y una raya separa las filas del cuerpo, para que se vea dónde empieza cada una. Si la tabla no cabe ni con todas las columnas a 3, se queda como llegó.
- **Por qué:** decisión del dueño (partir antes que recortar). Partir no pierde texto: la prueba comprueba que salen todas las palabras, en orden. Estrechar primero la más ancha deja enteras las columnas cortas, que suelen ser las de estado o tipo.
- **Alternativas consideradas y rechazadas:**
  - **Recortar con `…`:** esconde texto ajeno y obliga a abrir otra vista para leerlo.
  - **Desplazamiento horizontal:** no existe en el texto plano y el panel no lo tiene.
  - **Dejar que Textual parta las filas:** es lo que pasaba antes; el resto de una celda cae en la columna del texto.
- **Impacto:** requisito «Tabla partida dentro de sus columnas», escenario «Tabla más ancha que el panel»; `test_a_table_wider_than_the_pane_wraps_its_cells_within_their_columns`, `test_a_table_that_cannot_fit_even_narrowed_is_literal_text`.

### D3 · Bloques de código entre rayas, con su lenguaje

- **Qué:** una valla de apertura (```` ``` ```` o `~~~`) se sustituye por `── etiqueta ───`, y la de cierre por una raya. La etiqueta es la primera palabra de la información de la valla, si es una palabra corta (`[A-Za-z0-9_+#.-]{1,24}`); si no, `code`. La raya mide lo que la línea de código más larga, entre 24 y 80 columnas, y nunca más que el ancho. Las líneas de código no cambian y van en `MD_CODE`. Un bloque sin cierre llega hasta el final de la respuesta y se cierra con una raya. Dentro de un bloque de código, una tabla es código.
- **Por qué:**
  - La raya separa el código de la prosa también sin color.
  - La etiqueta dice el lenguaje sin enseñar la sintaxis de Markdown.
  - Restringir la etiqueta a una palabra corta impide que una respuesta escriba en la raya un texto con forma de chrome (`Approve? ──┼── yes`).
- **Alternativas consideradas y rechazadas:**
  - **Dejar las vallas:** es lo de antes, ruido que no dice nada.
  - **Un fondo para el código:** el texto ajeno no lleva fondo (SEC-15, `tui-spacing` D1).
  - **Resaltado de sintaxis:** otra dependencia y más estilos sobre el texto ajeno, para otro change.
- **Impacto:** escenario «Bloque de código con su lenguaje»; `test_a_code_block_loses_its_fences_and_gets_a_label_and_rules`, `test_the_label_is_a_short_word_of_the_info_string`.

### D4 · El texto plano dibuja lo mismo

- **Qué:** `foreign_lines` (texto plano) y `foreign_rows` (pantalla completa) llaman a `markdown_layout` con el mismo ancho cuando `markdown` está activo. Las filas de la pantalla completa sin color son las del texto plano. Sin Markdown (`/history`, `/memory`, lo que muestra `/context`) no cambia nada.
- **Por qué:**
  - Mantiene el requisito de `shell-appearance` «Respuesta con formato y marca intacta»: lo que se ve con color es, sin color, exactamente el texto plano.
  - Las pruebas y las demos en texto plano ven la misma tabla.
  - Lo que muestra `/context` sigue siendo exactamente lo que se envía.
- **Alternativas consideradas y rechazadas:**
  - **Alinear solo en la pantalla completa:** rompe ese requisito y obliga a mantener dos salidas.
- **Impacto:** escenario «Misma tabla en texto plano»; `test_the_styled_rows_print_what_the_plain_rows_print`, `test_the_plain_conversation_aligns_a_reply_table_without_colour`, y las pruebas de equivalencia de `tests/unit/test_shell_render.py`, que ahora comparan contra `foreign_lines(..., markdown=)`.

### D5 · Una respuesta llega entera, salvo la muy grande

- **Qué:** `default_fold` devuelve `EXPANDED` para una respuesta (`REPLY`) salvo que sus filas sumen más de `ARRIVE_WHOLE_MAX_CHARS = 64_000` caracteres. Entonces devuelve `PREVIEW`, como antes. Lo demás no cambia:
  - el resto del texto ajeno (`FOREIGN`) se pliega si no cabe;
  - los metadatos, plegados;
  - las alertas y `/context`, enteros;
  - los turnos anteriores al penúltimo se pliegan al enviar;
  - `ctrl+o`, `enter` o un clic abren y cierran.

  Como la respuesta llega abierta, el primer `ctrl+o` o `enter` sobre ella la cierra.
- **Por qué:**
  - Decisión del dueño: casi siempre se quiere leer la respuesta entera, y abrirla era un paso más en cada pregunta.
  - El límite conserva la cota de trabajo de `collapsible-blocks` (D6 de ese change, escenario «Respuesta de 1 MiB plegada»). 64 000 caracteres es el doble de lo que construye una vista previa (`PREVIEW_MAX_CHARS`) y bastante más que una respuesta normal de Copilot.
- **Alternativas consideradas y rechazadas:**
  - **Subir el margen de la vista previa:** una respuesta larga seguiría llegando plegada.
  - **Entera sin límite:** una respuesta de 1 MiB construiría todas sus filas al llegar.
  - **Plegar solo en texto plano:** el texto plano nunca plegó.
- **Impacto:** el requisito «Vista previa de una respuesta larga» de `collapsible-blocks` deja de valer para las respuestas. Va como ADDED «Respuesta entera al llegar» y al archivar pasa a MODIFIED (tarea 6.1). Pruebas: `tests/unit/test_shell_tui_replies.py`; en `tests/unit/test_shell_tui_blocks.py`, las que daban por hecha una respuesta plegada ahora la pliegan a mano con `set_fold(Fold.PREVIEW)` o usan texto de `/history`; la prueba de pseudo-terminal pasa a `test_a_long_reply_arrives_whole_and_folds_at_a_real_terminal`.

### D6 · El principio de la respuesta a la vista y lo que queda debajo en el pie

- **Qué:** al llegar una respuesta, si el panel seguía el final (no se recorren los bloques y no se lee más arriba), el panel suelta el ancla y, tras dibujarla:
  - **si cabe con una fila de margen,** vuelve el ancla y se ve el final, como antes;
  - **si es más alta,** su cabecera queda en la primera fila del panel (`scroll_to_widget(top=True)`).

  El pie empieza por `↓ N more rows below` mientras el panel tenga filas debajo de lo que muestra. Se actualiza al moverse el panel (vigilando `scroll_y` y `max_scroll_y`) y desaparece al llegar al final. Si la persona recorría los bloques o leía más arriba, nada se mueve, como manda `collapsible-blocks`. Lo que el harness muestre tras la respuesta tampoco mueve el panel. Enviar una línea lleva al final, como siempre.
- **Por qué:**
  - Una respuesta entera y anclada al final se leería desde su última línea.
  - El pie es del harness (sus palabras y una cuenta), así que no hay texto ajeno en el chrome.
  - Contar filas y no líneas es lo que se puede medir en el panel.
- **Alternativas consideradas y rechazadas:**
  - **Seguir anclado al final:** hay que subir para empezar a leer.
  - **Una marca dentro del bloque:** sería otra línea de chrome junto al texto ajeno y cambiaría la altura del bloque.
  - **Contar líneas de la respuesta:** no dice cuánto hay que bajar si otras cosas siguen debajo.
- **Impacto:** escenarios «Respuesta más alta que el panel» y «Respuesta que cabe»; `test_a_long_reply_arrives_whole_with_its_start_at_the_top_of_the_pane`, `test_reading_to_the_end_clears_the_hint`, `test_a_short_reply_keeps_the_end_in_view_and_shows_no_hint`.

### D7 · README: tablas, respuestas enteras y la selección

- **Qué:**
  - «Conversación › Aspecto» dice cómo se ven las tablas y el código, que las respuestas llegan enteras, qué dice el pie y el límite de 64 000 caracteres.
  - Una entrada «Texto resaltado en azul» dice que es la selección de Textual, que no copia y que un clic la quita.
  - Explica cómo copiar: en Terminal.app, `Fn`+arrastrar o «Permitir informes del ratón» (`⌘R`) y `⌘C`; en Windows Terminal, `Mayús`+arrastrar y `ctrl+shift+c`.
- **Por qué:** el hallazgo C3. El dueño vio el resaltado y lo tomó por un fallo de color. Lo que funciona está comprobado (ver Context), no supuesto.
- **Alternativas consideradas y rechazadas:**
  - **Desactivar la selección de Textual:** quita una ayuda para leer y no arregla la copia.
  - **Copiar con OSC 52:** Terminal.app no lo acepta, y la pantalla no copia al portapapeles (`shell-tui`).
- **Impacto:** tarea 5.1.

### D8 · Las dos pruebas inestables, deterministas sin tocar la protección

- **Qué:**
  - **`test_keys_typed_ahead_of_the_box_cannot_approve`** dependía de que las teclas llegaran antes de 0,5 s, y con la máquina cargada no siempre era así. Ahora abre la caja con `arm_s = 3600`. Envía las teclas y comprueba que la caja no está armada ni pulsada. Después adelanta el reloj de la caja (`opened -= 3600`), la arma con `_arm()` y comprueba que sigue en pantalla y sin pulsar. El orden «teclas antes de armar» ya no depende del reloj.
  - **`test_the_approval_buttons_at_a_real_terminal`** escribía la línea `/skill demo-echo …` y las teclas `\t\r \r\t\r` en una sola escritura. Con 12 a la vez, 1 de 12 se quedó esperando: la línea enviada fue `/skill demo-o-echo` (captura del pseudo-terminal: `error: skill 'demo-o-echo' does not exist`). El Tab es un atajo prioritario de la entrada y completó antes de que la entrada hubiera insertado los últimos caracteres. Ahora envía la línea, espera `working: ctrl+c interrupts` (la línea ya se tomó) y entonces envía las teclas. El Mock tarda 3 s, así que las teclas llegan mientras la Skill redacta, antes de que exista la caja, que es lo que la prueba quiere probar.
- **Por qué:** la protección (botones deshabilitados 0,5 s, Approve solo tras ver el final, la comprobación de armado al pulsar) no cambia. Las pruebas dejan de depender de la carga de la máquina.
- **Alternativas consideradas y rechazadas:**
  - **Más tiempo de armado en el producto:** cambia la protección y no quita la carrera.
  - **Reintentos en la prueba:** esconden el fallo.
- **Impacto:** tarea 4.1. Control negativo: un mutante que quita a la vez las tres capas del armado hace fallar la primera prueba.

## Risks / Trade-offs

- [Una tabla se alinea al ancho del panel cuando llega; al cambiar después el tamaño de la terminal, esa tabla no se vuelve a alinear] → Textual parte sus filas como cualquier texto y no se pierde nada; la siguiente respuesta usa el ancho nuevo. **Límite que no se arregla en este change:** volver a alinear exigiría guardar el texto de cada respuesta y rehacer sus filas en cada cambio de tamaño.
- [Una celda puede imitar una línea del harness] → sigue dentro del recuadro ajeno, tras la marca, con el estilo del texto ajeno y sin fondo (SEC-15). La raya no puede cerrar un recuadro.
- [Un texto hostil hecho de `|` y `---`] → límites de filas, columnas y celda; cada línea se parte como mucho dos veces. Prueba con 1 MiB de cinco formas: acotado.
- [Una respuesta enorme abierta al llegar] → por encima de 64 000 caracteres llega plegada, como antes.
- [El ancho lo lee el hilo del núcleo mientras el hilo de la pantalla lo cambia] → es un entero que se escribe entero; el peor caso es una tabla alineada al ancho anterior.
- [Una tabla dentro de una lista o una cita no se reconoce como tabla] → se queda como llegó, con el resaltado de siempre. **Límite.**
- [Windows Terminal no se ha probado] → la indicación sale de la documentación de Microsoft. La máquina de Windows puede confirmarla (opcional).

## Migration Plan

Nada que migrar: no cambia nada en disco. Para volver atrás basta con revertir la rama.

## Open Questions

(ninguna)
