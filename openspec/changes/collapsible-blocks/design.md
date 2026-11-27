# Design

## Context

La pantalla completa (`shell-tui`) recibe del núcleo, en orden, llamadas `show_rows(filas, etiqueta)`. Cada `_say` del núcleo es una llamada y cada `_foreign` otra. La pantalla agrupa las filas en un bloque del harness o en uno ajeno con borde (`shell-tui` D3). El núcleo no sabe nada de turnos ni de bloques, y este change no lo cambia: todo lo que aquí se decide vive en la pantalla y sale del estado del harness. Ese estado es la línea que envió la persona, las palabras con que empiezan las líneas del propio harness, el nombre configurado del proveedor y el número de filas.

Premisas leídas el 2026-11-27 en el código instalado de Textual 8.2.8 (`.venv/lib/python3.14/site-packages/textual/`), no de memoria:

- `widgets/_input.py:76-140`: `Input` no liga `escape`, `alt+up`, `alt+down`, `ctrl+up`, `ctrl+down` ni `ctrl+o`. `_input.py:743-754`: inserta las teclas imprimibles en su `_on_key`.
- `message_pump.py:743-760`: un mensaje se despacha a los `_on_<x>` de cada clase de la MRO, de la subclase a la base, hasta que alguna llama a `prevent_default()`. Así `PromptInput._on_key` puede quedarse una tecla antes que `Input._on_key`.
- `app.py:4136-4138` y `4341-4342`: primero los atajos con prioridad (`ctrl+c`, `ctrl+q`, `ctrl+n`, `tab`). Después la tecla va al widget con el foco, y por último sube a los atajos sin prioridad. Si el widget la para (`event.stop()`), los atajos sin prioridad no la ven.
- `screen.py:1933-1939` y `687-705`: al pulsar el ratón, el foco solo cambia si bajo el puntero hay un widget enfocable o un antecesor suyo que lo sea. Ningún bloque ni contenedor del registro lo es.
- `widget.py:256-266`: `border_title` y `border_subtitle` usan un `Content` tal cual (un `str` pasaría por *markup*); `None` los quita.
- `widget.py:800-830` y `_compositor.py:609, 693`: un contenedor con `anchor()` sigue pegado a su final mientras crece, hasta que algo lo desplaza (`scroll_to` llama a `release_anchor` por defecto, `widget.py:2859-2873`). `widget.py:3012-3075`: `scroll_end` espera al siguiente refresco, que puede llegar antes de que se maquete lo recién montado.
- `content.py:992`: `Content.wrap(width)` parte el texto como lo partirá el widget.
- `css/_styles_builder.py:371-412`: `text-wrap: nowrap` y `text-overflow: ellipsis` existen. Una línea así no salta a una segunda fila y se corta con `…` al ancho.
- `widgets/_collapsible.py:17, 44, 56-68, 82-83`: `CollapsibleTitle` es enfocable (`can_focus=True`), liga `enter`, y pasa su `label` por `Content.from_text`, que interpreta un `str` como *markup* (`content.py:234-256`).
- Medido con `Pilot` el 2026-11-27: en 110 × 32 el panel de la conversación tiene 27 filas; en 100 × 30, 25. Un bloque ajeno pierde 4 columnas por el borde y el relleno.

## Goals / Non-Goals

**Goals:** leer una conversación larga sin tocar nada, abrir lo que haga falta con el teclado o el ratón, y no aflojar ninguna garantía de `shell-tui`. Aparte de la extensión del cromo, que se escribe en D4 con su prueba.

**Non-Goals:** plegar la caja de aprobación, cambiar el texto plano, guardar el plegado, mostrar turnos de ejecuciones anteriores, buscar en la conversación.

## Decisions

### D1 · Qué se ve al llegar

- **Qué:**
  - **Vista previa.** Mide `N = max(8, filas del panel − 7)` filas de pantalla. Las 7 son la línea de la persona, los dos bordes y los márgenes. Cada fila de texto se mide con `Content.wrap` al ancho del bloque, así que una línea que se parte en tres cuenta tres.
  - **Respuesta o texto ajeno.** Se ve entero si cabe en `N + 4` filas. Las 4 de gracia evitan plegar un bloque para esconder dos líneas. Si no cabe, se ven las filas enteras que caben en `N`, y nunca más de 32 000 caracteres. El borde inferior dice, en el cromo, `… K more lines · enter/click to expand`. Abierto un bloque que era largo, el pie pasa a `T lines · enter/click to collapse`.
  - **Metadatos.** La línea `context:` es un bloque, y los pasos de una Skill (`skill:`), otro. Seguidas y dentro de un turno, las de un mismo tipo se juntan en un bloque. Con más de una línea, el bloque se pliega a una, que muestra la línea `context:` o el último paso de la Skill.
  - **Lo que fue y no fue con la pregunta.** Las líneas `omitted:` (una nota que no cupo) y `attached:` (el fichero adjunto, que sí se envió) se ven siempre enteras, en su propio bloque. Hasta la revisión independiente del 2026-11-27 iban en el bloque de contexto y se plegaban con él: la pantalla escondía el nombre del fichero enviado y la nota omitida, que `render.py` dibuja como aviso.
  - **Cómo terminó una Skill.** La línea `skill: run … is …` y las líneas `applied:` forman su propio bloque (`RESULT`), siempre entero. Al integrar los botones de aprobación (2026-11-27) se vio que, dentro de los pasos plegados, esa línea se cortaba con `…` al ancho del panel, porque el identificador de la ejecución ocupa 36 caracteres. La persona no veía que la ejecución había terminado.
  - **Lo que muestra `/context`.** Es exactamente lo que se envía, así que llega siempre entero, por largo que sea. El harness lo sabe por la línea del turno (`/context`), no por el texto. Revisión del 2026-11-27.
  - **Alertas.** `error:`, `warning:`, `interrupted:`, `Not confirmed`, `That is not` y `[N more character(s) not shown]` se ven siempre enteras y nunca se juntan con otras.
  - **El resto del harness** (`/help`, `/sessions`…) se pliega como una respuesta.
  - **El recorte de `MAX_SHOWN_CHARS`** marca además la respuesta anterior como `truncated`, en su título.
- **Por qué:** la respuesta más reciente tiene que leerse al llegar: con `N` relativo al panel, su cabecera, su principio y su pie caben en la pantalla (medido en 100 × 30 y 110 × 32). Una respuesta de unas 50 líneas en un panel de 27 filas enseña sus primeras 20 y dice cuántas faltan. Si se contaran líneas y no filas de pantalla, con líneas largas la vista previa doblaría el panel: se vio en la primera captura de este change, 19 líneas en 38 filas. Plegar un error escondería justo lo que hay que ver.
- **Alternativas rechazadas:**
  - Un `N` fijo (20, 30): en una terminal baja la respuesta no cabe, y en una alta se pliega sin necesidad.
  - Plegar por defecto toda respuesta a una línea: obliga a abrir cada respuesta para leerla.
  - Contar líneas en vez de filas de pantalla: con líneas largas, la vista previa se sale del panel.
  - Recalcular `N` al cambiar el tamaño de la terminal: más estado por bloque y saltos al redimensionar.
- **Impacto:** `blocks.py` (`preview_lines`, `folds_by_default`, `rows_in_preview`, `default_fold`, `category`), `tui.py` (`FoldBlock`, `ForeignBlock`, `NoticeBlock`, `HarnessApp._add_rows`, `_height_of`). **Límite que no se arregla:** la vista previa se mide al llegar el bloque; si después cambia el tamaño, el bloque conserva sus filas (el pie sigue diciendo la verdad).

### D2 · Turnos, y cuáles se pliegan solos

- **Qué:**
  - **Qué es un turno.** Empieza cuando la pantalla acepta una línea de la persona (`_submit`, también desde la paleta o un selector) y recoge todo lo que llega hasta la siguiente. Lo mostrado antes de la primera línea es un turno sin línea, el del harness.
  - **Abierto**, el turno es la línea de la persona y sus bloques. **Plegado**, es una línea: `▸ you → mock · 42 lines · completed  › revisa el HLS`.
  - **Quién:** `you → <proveedor>` si hubo respuesta, la orden (`/history`) o `skill NOMBRE`.
  - **Estado**, de las líneas del propio harness, en este orden: `failed` (`error:`), `uncertain`, `interrupted`, el estado de la Skill (`skill: run … is X`), `truncated`, y si nada de eso, `completed` o `done`. Si hubo avisos, se añaden contados: `completed · 1 warning`.
  - **De qué líneas sale el estado.** Solo de los bloques de alertas y de pasos de una Skill, y cada patrón se compara con la línea entera, desde su primer carácter. Antes de la revisión del 2026-11-27, el estado de la Skill se buscaba en cualquier punto de cualquier línea del harness: una nota del vault llamada `notes/x skill: run r1 is approved`, tras `omitted:`, ponía `· approved` en el cromo. La pista de un `ctrl+c` sin nada en curso («interrupted: the conversation is still open; …») no interrumpe nada y no cuenta.
  - **Pliegue automático.** Al empezar un turno nuevo se pliegan los anteriores al penúltimo (`KEEP_OPEN_TURNS = 2`). Se salta el que la persona abrió o cerró a mano, el que tiene un bloque que la persona abrió o cerró, el de la selección y el que tuvo un error, un aviso o una interrupción: un aviso se ve siempre entero, y plegar su turno lo escondería.
  - **Abrir y cerrar.** Un bloque abierto es entero y uno cerrado es una línea. La vista previa es solo el estado de llegada: «abrir» la deja entera. Expandir todo abre turnos y bloques enteros, y plegar todo pliega los turnos. Las dos cuentan como elección de la persona y se mantienen.
- **Por qué:** con diez turnos, el registro plegado cabe en una pantalla y cada línea dice qué fue y cómo acabó. El turno anterior queda abierto porque es el que se compara con la respuesta nueva. Es predecible: el pliegue solo ocurre en un momento, al enviar, cuando la persona mira la entrada y el panel va al final. Nunca ocurre mientras lee. Una elección a mano no se deshace sola.
- **Alternativas rechazadas:**
  - No plegar turnos nunca, como Claude Code, que pliega salidas de herramientas pero no turnos: con respuestas de 50 líneas, volver diez turnos atrás vuelve a ser recorrer cientos de filas.
  - Plegar según lo que está en pantalla: depende del desplazamiento y no se puede predecir.
  - Un ciclo de tres estados (vista previa → entero → plegado): una tecla más que recordar para ganar poco.
  - Sacar el estado del turno del texto de la respuesta: sería leer texto ajeno.
- **Impacto:** `tui.py` (`Turn`, `HarnessApp.start_turn`, `set_all`), `blocks.py` (`turn_state`, `turn_who`, `KEEP_OPEN_TURNS`).

### D3 · Teclas, ratón, foco y desplazamiento

- **Qué:**
  - **Desde la entrada**, con el foco en ella siempre: `alt+↑`/`alt+↓` (y `ctrl+↑`/`ctrl+↓`, por si la terminal no manda `alt`) eligen el bloque anterior o el siguiente. `ctrl+o` abre o cierra el elegido o, sin elección, la respuesta más reciente; es la tecla de Claude Code para ver el detalle.
  - **Recorrer.** `Esc` entra a recorrer los bloques, sin mover el foco: `PromptInput._on_key` se queda `↑`, `↓`, `home`, `end`, `pageup`, `pagedown`, `enter`, `espacio`, `ctrl+o`, `+`, `-` y `Esc` antes que `Input`. Cualquier otra tecla termina el recorrido y sigue su camino: una letra se escribe, `←` mueve el cursor. Mientras se recorre, la entrada tiene un borde de aviso y el texto «browsing the blocks», y el pie de la pantalla cambia a las teclas del recorrido. Cualquier pantalla que se abra encima termina el recorrido: la caja de aprobación, la paleta o un selector. Lo hace `HarnessApp.push_screen`. **Corrección (revisión independiente, 2026-11-27):** este diseño decía que bastaba con perder el foco (`_on_blur`), y es falso. En Textual 8.2.8, `push_screen` no manda `Blur` al widget enfocado de la pantalla que queda debajo. El recorrido seguía con la caja abierta, y al cerrarla, `/status` + `enter` abría o cerraba un bloque en vez de enviar la línea. `_on_blur` queda para cuando el foco pasa a otro widget de la misma pantalla.
  - **Ratón.** El clic en la primera o la última fila de un bloque ajeno (su cabecera en el borde o su pie), en un bloque del harness, en una línea plegada o en la línea de la persona abre o cierra. El clic en el texto ajeno no hace nada. Ningún bloque ni contenedor es enfocable, así que el clic no mueve el foco.
  - **Paleta:** «Browse blocks», «Open or close the block», «Expand all blocks», «Collapse all blocks» y «Jump to latest».
  - **Posición.** Al abrir o cerrar, se anota la fila del panel de la cabecera (el antiguo de la selección o el primero visible, para todo) y, tras el siguiente refresco, se desplaza el panel para devolverla a esa fila (`_keep_in_place`); si estaba por encima del panel, a la fila 0. El panel está anclado a su final (`anchor()`) y sigue lo que llega mientras la persona está al final. Si recorre los bloques o subió a leer, lo que llega no lo mueve. Enviar una línea o cambiar de sesión siempre lleva al final, también mientras se recorre: `_follow(force=True)` mira `force` antes que el recorrido. Antes de la revisión, el orden era el inverso, y `ctrl+n` o una entrada `line:` de la paleta no llevaban al final.
- **Por qué:** el texto que se escribe no se puede perder. Con la entrada siempre enfocada, nada cambia de destino: la línea escrita por adelantado sigue sujeta a `_take`, y `enter` solo envía cuando no se recorre. Un clic en el texto de una respuesta no tiene efecto, como pide `shell-tui` D3. Anclar al final hace lo mismo que hacía `scroll_end`, sin su carrera con el maquetado, que dejaba el final de una respuesta larga fuera de la vista.
- **Alternativas rechazadas:**
  - Dar el foco al registro (un modo con su propio widget enfocable): una pulsación pensada para la entrada acabaría en otro sitio.
  - Atajos `alt+e`/`alt+c` para expandir o plegar todo: en macOS, `alt` escribe caracteres; quedan `+`/`-` al recorrer y la paleta.
  - Que el clic en cualquier parte del bloque lo abra: haría del texto ajeno algo que reacciona al pulsarlo.
  - Conservar el `scroll_end` de siempre: además de la carrera, arrastraba al final a quien estaba leyendo más arriba.
- **Impacto:** `tui.py` (`PromptInput.BINDINGS`, `BROWSE_KEYS`, `_on_key`, `_on_blur`, `HarnessApp.blocks_action`, `toggle_item`, `_keep_in_place`, `_follow`, `push_screen`, `FOOTER`, `BROWSE_FOOTER`, `COMMAND_ENTRIES`). Un cambio de conducta: antes, lo que llegaba siempre arrastraba el panel al final; ahora solo si la persona estaba en él. **Límite:** si el contenido de debajo es más corto que el panel, el desplazamiento no llega y la cabecera queda donde cabe (lo dice el requisito).

### D4 · El cromo junto al texto ajeno

- **Qué:**
  - **Cromo** es el texto del harness: la cabecera (en el borde superior de un bloque ajeno), el pie (en el borde inferior, o tras las filas de un bloque del harness) y la parte de la línea plegada que dice quién, cuántas líneas y el estado. Se dibuja en `CHROME`, negrita sobre el fondo `#3a3f4b`, y es el único estilo con fondo. Ningún estilo de `STYLES`, los únicos que puede recibir un carácter de texto ajeno, tiene fondo. El texto ajeno nunca elige su estilo: lo elige `render.py` sobre texto ya saneado.
  - **Extracto.** En una línea plegada va tras un espacio sin estilo, la marca (`| ` para lo ajeno, `› ` para lo que escribió la persona) y en cursiva. Sale de `one_line`: `terminal_safe` (sin controles, sin caracteres de formato, que incluyen los bidireccionales, y sin separadores de línea), los espacios juntados, y como mucho 200 caracteres con `…`.
  - **Esquema de títulos.** El extracto de una respuesta son sus títulos de Markdown, que `render.markdown_styles` ya distingue (fuera de los bloques de código), unidos con ` · `. Sin títulos, es la primera línea no vacía.
  - **Una sola fila.** Las líneas plegadas son `height: 1`, `text-wrap: nowrap` y `text-overflow: ellipsis`: nunca empiezan una segunda fila con texto ajeno.
  - **Todo se construye como `Content`.** Los títulos y pies son `Content` (`plain`), y nada pasa por *markup*.
- **Por qué:** cabecera, línea plegada y pie son cromo pegado a texto ajeno, y la línea plegada lleva además un trozo de ese texto. El texto ajeno puede escribir los mismos caracteres que el cromo (`▸ you → mock · 3 lines`, `… 38 more lines · enter/click to expand`), pero no puede ponerse el fondo del cromo ni ocupar un borde. Tampoco puede romper la línea plegada: sin separadores, sin `\r` y con un corte de ancho, que deja sin ver lo que el texto colara detrás. El pie cuenta las filas que no se dibujan, así que una respuesta no puede esconder nada diciendo que no hay más.
- **Alternativas rechazadas:**
  - El widget `Collapsible` de Textual: su título es enfocable (le quita el foco a la entrada al pulsarlo), liga `enter` y pasa la etiqueta por `Content.from_text`, que interpreta un `str` como *markup*. Habría que vigilar cada etiqueta.
  - Distinguir el cromo solo por el glifo `▸`: el texto ajeno puede escribirlo.
  - Dejar el extracto fuera de la línea plegada: es lo que permite seguir la conversación de un vistazo.
  - Mostrar el extracto entre comillas: el texto puede cerrarlas.
- **Impacto:** `tui.py` (`CHROME`, `EXCERPT_STYLE`, `TYPED_MARK`, `chrome_line`, los `summary` y `_show` de los bloques, CSS), `blocks.py` (`one_line`, `outline`, `first_line`). Amplía el requisito «Texto ajeno contenido e inerte en la pantalla completa» de `shell-tui`: el texto ajeno ya no está solo dentro de un borde, porque una línea plegada lleva un extracto acotado tras `| `. Spec: «Extracto ajeno en una línea plegada».

### D5 · Un registro por sesión, en memoria

- **Qué:** cada sesión tiene su `SessionLog`, un contenedor con sus turnos, guardado en un diccionario en memoria por el identificador de la sesión. El panel lateral ya se refresca con la sesión tomada cada vez que el núcleo espera una línea (`shell-tui` D4). Si cambia el identificador, la pantalla oculta el registro anterior y muestra el de la sesión nueva. Si la sesión aún no tenía registro, crea uno con una línea que lo dice: «this pane shows what happened in it since the conversation opened; /history lists its stored messages». Lo mostrado antes del primer panel se queda en el registro de la primera sesión. Nada de esto se escribe en disco.
- **Por qué:** SEC-02, por extensión: lo que se ve describe la sesión tomada. La línea `/new` y su respuesta («new session …») se quedan en la sesión donde se escribieron, porque el núcleo las imprime antes de refrescar el panel. El identificador sale del estado del harness y no de las líneas impresas.
- **Alternativas rechazadas:**
  - Un solo registro para todas las sesiones, el de hoy: al volver a una sesión se ven los bloques de otra.
  - Reconstruir el registro de una sesión desde `/history` al volver: sería otro camino de lectura de la base de datos desde la pantalla, que `shell-tui` D4 descarta.
- **Impacto:** `tui.py` (`SessionLog`, `HarnessApp.show_panel`, `_follow_session`, `session_logs`). **Límite:** al reanudar una sesión de otra ejecución, su panel empieza vacío salvo esa línea.

### D6 · Plegar reduce trabajo

- **Qué:**
  - Un bloque guarda sus filas y solo convierte en `Content` lo que se ve: su línea, su vista previa o, si está abierto, todo. Abrir o cerrar reconstruye solo ese bloque (`renders` lo cuenta en las pruebas).
  - Plegar un turno es una clase CSS en su contenedor: sus bloques quedan con `display: none`, sin maquetar ni dibujar.
  - `folds_by_default` y `rows_in_preview` paran en cuanto saben la respuesta: no miden una respuesta de 1 MiB entera.
  - La lógica de plegado (`blocks.py`) es biblioteca estándar y no escribe nada.
- **Por qué:** con 500 bloques, plegar no puede costar un redibujado de todo. Una respuesta de 1 MiB (256 KiB mostrables) plegada cuesta su vista previa: la prueba exige menos de 4 000 caracteres de `Content` en el bloque.
- **Alternativas rechazadas:** construir siempre el `Content` entero y esconderlo con CSS (el coste no baja); virtualizar la lista de bloques (otra capa que Textual no trae y que no hace falta con estas cifras).
- **Impacto:** `tui.py`, `blocks.py`. Pruebas de tiempo acotado: 500 bloques (250 turnos) se montan y se pliegan y expanden todos en 3,2 s (medido el 2026-11-27, macOS arm64).

## Riesgos y límites

- [Una respuesta que imita el cromo] → el cromo es el único estilo con fondo y ocupa bordes o una línea que el texto ajeno no puede romper; la prueba lo mira celda a celda en la pantalla compuesta. Su control negativo: dibujar el extracto en `CHROME` lo detecta.
- [Una respuesta que esconde algo tras la vista previa] → el pie cuenta las filas no dibujadas; prueba con la orden en la última línea y una primera línea que dice «0 more lines».
- [Teclas de recorrer que se coman lo que se escribe] → solo una lista cerrada de teclas no imprimibles más `espacio`, `+` y `-`; cualquier otra tecla vuelve a escribir y se escribe. Perdido a cambio: mientras se recorre, `+`, `-` y `espacio` no se escriben (`Esc` primero).
- [`alt`/`ctrl`+flechas no llegan en algunas terminales (según cómo trate `alt` cada una; en macOS, Mission Control se queda `ctrl+↑` por defecto)] → `Esc` y la paleta funcionan siempre. No se ha probado tecla por tecla en Terminal.app, iTerm2 ni Windows Terminal.
- [Una cabecera que salta al plegar todo cerca del final] → si debajo no hay contenido para desplazar, la cabecera queda donde cabe; está escrito en el requisito y no se arregla.
- [Un modo de recorrer que sobreviva a una pantalla encima, y un `enter` que entonces abra un bloque en vez de enviar] → `push_screen` termina el recorrido para cualquier pantalla, también la caja con botones de `feature/approval-buttons`. Prueba: `test_a_box_or_the_palette_ends_browsing`, con su control (M21).
- [Conflicto con `feature/approval-buttons`] → este change no toca `ApprovalScreen`. Integrada el 2026-11-27 (tasks 6.9): conflictos de texto en `FOOTER`/`ARM_S` y junto a `open_approval`. Las teclas de los bloques no actúan en la caja de botones, y abrirla termina el recorrido.
- [Atributos de Textual que cambien de versión (`anchor`, `Content.wrap`, `text-overflow`)] → Textual sigue fijado exacto (8.2.8); las pruebas de la vista previa medida y de la posición fallan si cambian.
- **Límite:** el número de líneas de un bloque cuenta líneas de texto (y las filas `|+` de una línea de más de 10 000 caracteres), no filas de pantalla. El pie dice «lines» y es exacto en esa unidad.
- **Límite:** el estado de plegado se pierde al salir, por diseño.

## Open Questions

- ¿Quiere Wilson que el pliegue automático de turnos se pueda apagar (una variable o un `/fold off`)? Hoy no existe: «Expand all blocks» lo deshace y se mantiene.
