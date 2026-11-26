# Design

## Context

`develop` (`c39b93f`): la conversación de `interactive-shell` (D1–D10) lee con `input()` en un hilo auxiliar (`ConsoleTerminal`), imprime texto plano y marca el texto ajeno con `| ` en cada fila, cortada por debajo del ancho de la terminal (D9). Ctrl+C lo recibe un manejador propio instalado con `signal.signal` antes de `asyncio.run` (D6), que cancela la pregunta o interrumpe la espera (D7). La aprobación es la del motor, con la confirmación `reject` tras `n` (D8). La motivación y el alcance están en `proposal.md`.

Premisas medidas el 2026-11-26 (macOS arm64, Python 3.14.8; recibos en `tasks.md`):

- La flecha arriba en la conversación de hoy llega como una línea `^[[A` que se toma por pregunta (tarea 1.2).
- `prompt_toolkit` 3.0.53 se instala en Python 3.14 con `uv add` y su única dependencia es `wcwidth` 0.9.5 (tarea 1.1). Wheel de 392 288 bytes; `wcwidth` tiene wheel `py3-none-any` además de los nativos.
- `rich` 15.0.0 depende de `markdown-it-py` (→ `mdurl`) y `pygments` (wheel de 1 250 147 bytes); 4 paquetes para el lado de salida (PyPI, consultado el 2026-11-26).

Premisas leídas en el código fuente de `prompt_toolkit` 3.0.53 instalado (context7 no estaba disponible en esta sesión; el código es la versión exacta que se fija):

- `Application.run_async(handle_sigint=True)` instala con `loop.add_signal_handler(SIGINT, …)` su propio manejador mientras dura el indicador y luego restaura el anterior (`application/application.py`, `set_handle_sigint` y `_restore_sigint_from_ctypes`); en Windows y fuera del hilo principal lo desactiva solo (líneas 649–654).
- En modo crudo, POSIX quita `ISIG` (`input/vt100.py`, `_patch_lflag`) y Windows quita `ENABLE_PROCESSED_INPUT` (`input/win32.py`, `_patch`): Ctrl+C llega como la tecla `c-c`, cuyo atajo por defecto termina el indicador con `KeyboardInterrupt` (`shortcuts/prompt.py`, línea 844); Ctrl+D en línea vacía, con `EOFError`.
- `c-j` (`\n`) equivale a Intro (`key_binding/bindings/basic.py`, `_newline2`); un pegado delimitado inserta sus saltos de línea en el búfer en lugar de enviarlo (`_paste`).
- `Vt100_Output.write` sustituye cada ESC por `?` (`output/vt100.py`, línea 523); la pantalla muestra los caracteres de control como `^X` (`layout/screen.py`, `display_mappings`).
- `PromptSession` trae desactivados por defecto el indicador de sistema (`M-!` ejecuta una orden), suspender y abrir en editor (`shortcuts/prompt.py`, líneas 393–395).
- `PromptSession.prompt(in_thread=True)` ejecuta el indicador en un hilo con su propio bucle y bloquea al llamante, con `handle_sigint=False` forzado (`Application.run`, líneas 930–945).
- `rich.markdown.Markdown` tiene `hyperlinks=True` por defecto y convierte los enlaces y las imágenes en hiperenlaces OSC 8 (`rich/markdown.py` 15.0.0, `ImageItem`, `link_open`); reescribe el texto (quita marcas, cambia viñetas, reajusta el ancho).

## Goals / Non-Goals

**Goals:**

- El aspecto de la maqueta de Wilson: barra de estado, respuesta con Markdown, indicador con segundos, edición, historial y completado.
- Ninguna garantía de `interactive-shell` se debilita: marca del texto ajeno, aprobación, Ctrl+C, sesión.
- El camino plano de hoy, intacto, como respaldo y como camino de los tests y las demos.
- Mismo código en macOS y Windows.

**Non-Goals:**

- Pantalla completa, paneles, streaming, historial en disco, contador de envíos.

## Decisions

### D1 · Una sola librería: `prompt_toolkit`

- **Qué:** se añade `prompt_toolkit==3.0.53` (fijada exacta en `pyproject.toml`, con `uv.lock` actualizado). Cubre la entrada (edición, historial, completado, barra inferior, `prompt_async` dentro del bucle de `asyncio`) y la salida con estilos (`print_formatted_text` con clases de estilo, que en Windows usa la API de consola cuando no hay secuencias VT). El resaltado del subconjunto de Markdown se escribe aquí, con la biblioteca estándar (D3).
- **Por qué:** la entrada es lo que no se puede hacer sin librería de forma portable: `readline` no existe en Windows (D2 de `interactive-shell`) y la conversación no puede tener ramas por plataforma. De las candidatas, solo `prompt_toolkit` la cubre; y su salida con estilos basta para colorear filas que ya corta y marca el harness. Comparación (2026-11-26):

  | | `prompt_toolkit` 3.0.53 | `rich` 15.0.0 |
  |---|---|---|
  | Edición, historial, completado | sí (`PromptSession`) | no (`Prompt.ask` usa `input()`) |
  | `asyncio` | nativo (`prompt_async`) | no aplica |
  | Markdown | no | sí, pero reescribe el texto y emite OSC 8 por defecto |
  | Indicador con tiempo | barra inferior o escribir la línea | `Status` (un hilo que repinta) |
  | Dependencias | `wcwidth` | `markdown-it-py`, `mdurl`, `pygments` |
  | Licencia | BSD-3-Clause | MIT (+ BSD de `pygments`) |
  | Windows | conhost (API Win32) y Windows Terminal (VT) | conhost en modo «legacy» y VT |
  | Sin terminal | `PlainTextOutput` | desactiva colores |
  | Mantenimiento | 3.0.53 publicada el 2026-07-26; base de IPython y ptpython | 15.0.0 publicada el 2026-04-12 |

- **Alternativas rechazadas:**
  - `rich` sola: no edita la línea, que es la mitad del encargo; su Markdown reescribe el texto ajeno después de sanearlo (viñetas, títulos sin `#`, saltos propios) y por defecto convierte enlaces e imágenes en OSC 8, justo lo que no puede llegar a la terminal; desactivarlo exige conocer cada elemento que añada una versión futura.
  - `prompt_toolkit` y `rich` juntas: dos librerías donde Wilson pidió una, cuatro paquetes más, y dos dueños de la terminal (el `Status` de `rich` repinta desde un hilo mientras `prompt_toolkit` puede tener el modo crudo).
  - Textual: es pantalla completa, que Wilson descartó.
  - Biblioteca estándar con secuencias ANSI propias: sin edición en Windows y sin colores en la consola clásica (conhost sin VT).
- **Impacto:** `pyproject.toml`, `uv.lock`; `harness/shell/styled.py` es el único módulo que importa `prompt_toolkit` (el camino plano no lo importa). Riesgo de cadena de suministro en «Risks».

### D2 · La marca del texto ajeno no cambia: `| ` en cada fila, también con colores

- **Qué:** el texto ajeno se imprime en las mismas filas que hoy: saneado y acotado primero, luego cortado por debajo del ancho con `| ` o `|+` al principio de cada fila. En la terminal con estilo, esa marca va en gris (estilo `gutter`) y el resto en el color del texto; las líneas del harness van en cian (amarillo los avisos, rojo los errores) y nunca empiezan por `|`. La entrada de la persona va tras `> ` en verde. El estilo de una fila del harness sale de sus propias primeras palabras; el de una fila ajena nunca puede ser uno del harness (`foreign_rows` solo produce `gutter`, `foreign` y `md.*`).
- **Por qué:** es la marca que ya pasó la revisión independiente de `interactive-shell` (D9) y es la única que aguanta sin colores, al copiar el texto y en una terminal tonta. El color es una pista más, nunca la frontera.
- **Alternativas rechazadas:**
  - La sangría de dos espacios de la maqueta: las líneas del harness también la usan (`  skill resume …`, la cabecera del aviso de aprobación), así que dejaría de distinguir.
  - Un carácter de caja (`│`) como marca: en una consola sin la fuente adecuada se ve como `?`, y cambiaría la regla que comprueban los tests y la revisión.
  - Distinguir solo por color: desaparece con `NO_COLOR`, al redirigir y al copiar (ya rechazado en D9 de `interactive-shell`).
- **Impacto:** spec (Respuesta con formato y marca intacta). Las funciones de filas pasan de `conversation.py` a `render.py` sin cambiar (se reexportan con los mismos nombres: ningún test cambia de import).

### D3 · Markdown: un subconjunto que solo colorea, sobre el texto ya saneado

- **Qué:** `markdown_styles` decide el estilo de cada carácter de cada línea, después de `safe_foreign_text` y antes de cortar en filas; nunca quita ni añade un carácter. Subconjunto: bloque de código con ``` o ~~~ (lo cierra solo una valla del mismo tipo; dentro no se interpreta nada), título ATX (`#`–`######` y espacio), regla, elemento de lista (`-`, `*`, `+`, `1.`, `1)`), cita (`>`), y en línea `código`, **negrita**, *cursiva* y `[texto](url)`. Todo lo demás es texto: `_cursiva_` (marcaría nombres con guion bajo), tablas, HTML, imágenes, enlaces automáticos. Un enlace o una imagen se colorean como texto y no se siguen ni se convierten en hiperenlace. Se aplica a respuestas del proveedor, a `/history` y a la salida de un Skill; `/memory` y `/context` siguen sin formato.
- **Por qué:** «el texto de las filas con estilo es exactamente el de las filas planas» es una propiedad que se comprueba (test con 300 textos aleatorios y los hostiles) y de la que se siguen las demás: el corte a lo ancho y la marca son los de hoy, lo que se copia es lo que dijo el proveedor, y sin colores se ve lo mismo que en el camino plano. La maqueta de Wilson mantiene `## Resumen` y `- ` visibles. Cada patrón en línea empieza por su carácter de apertura y su cuerpo no puede contenerlo, así que un intento fallido termina en la siguiente apertura: lineal (1 MiB adversario en < 0,4 s por caso, medido).
- **Alternativas rechazadas:**
  - Un analizador de Markdown completo (`markdown-it-py`, el de `rich`): otra dependencia, y reescribe el texto ajeno después del saneado.
  - Quitar las marcas (`##`, `**`) al mostrar: lo que se ve dejaría de ser lo que se copia y lo que se guarda, y abre la puerta a que el formato componga una forma que el texto no tenía.
  - Patrones con cuerpo abierto (`\[[^\]]+\]`): cuadráticos con una línea de `[` (control negativo en los tests).
- **Impacto:** spec (Respuesta con formato y marca intacta); tests `tests/unit/test_shell_render.py`.

### D4 · Qué terminal se usa: la de estilo en una consola, la plana si se pide o si hace falta

- **Qué:** `make_terminal` elige la plana (`ConsoleTerminal`, sin cambios) si hay `chat --plain`, `HARNESS_PLAIN` con valor distinto de vacío o `0`, `NO_COLOR` no vacío (no-color.org), `TERM=dumb`, o si la entrada o la salida no son una terminal; si no, construye la de estilo, y si la librería no puede manejar la consola (cualquier excepción al crearla) usa la plana. La ausencia de `TERM` no cuenta (en Windows no existe). Los tests existentes usan terminales inyectadas o piden el camino plano (`HARNESS_PLAIN=1` en el hijo de `test_chat_terminal.py`); `HARNESS_PLAIN` se añade a las variables que los tests no heredan.
- **Por qué:** el camino plano es el medido y revisado; tiene que seguir a mano para una consola rara, para quien no quiera colores y para los scripts. La elección depende del entorno, nunca de la plataforma.
- **Alternativas rechazadas:**
  - Estilo por defecto también sin terminal: `chat` ya se niega sin terminal, y `PlainTextOutput` no aporta nada.
  - Solo la variable o solo la opción: la variable sirve para `main.py` sin argumentos; la opción, para una vez.
- **Impacto:** spec (Terminal con estilo y respaldo plano); `harness/shell/app.py`; README.

### D5 · Barra de estado e indicador de trabajo, solo con estado del harness

- **Qué:** la línea de estado es `ai-harness  PROYECTO  PROVEEDOR  session ID8` (proyecto de la sesión tomada o `-`, nombre del proveedor configurado, 8 primeros caracteres de la sesión), pasada por `terminal_safe`. Se muestra en la cabecera, seguida de una regla, y como barra bajo el indicador mientras se espera una línea; la barra la calcula una función que lee la sesión tomada en ese momento, así que tras `/new` o `/resume` nombra la nueva. Mientras el proveedor trabaja, una línea `PROVEEDOR … thinking (N s), Ctrl+C interrupts` se reescribe cada segundo con `\r` y borrar-hasta-el-final (operaciones de la salida de la librería, también en conhost) y se borra al terminar, también si se cancela. Va cortada a una fila para que `\r` vuelva a su principio.
- **Por qué:** SEC-02: nada de otra sesión ni del texto ajeno puede aparecer en una línea con aspecto de harness. El nombre de la sesión (lo escribe la persona) no entra en la barra.
- **Alternativas rechazadas:**
  - «sesión» en castellano, como en la maqueta: los textos del producto van en inglés (regla del proyecto).
  - Un hilo que repinta el indicador (`rich.Status`): una tarea del bucle basta y no compite con nadie por la terminal.
  - Mostrar el contador de envíos: el dato no existe aún.
- **Impacto:** spec (Línea de estado de la sesión tomada; Indicador mientras el proveedor trabaja).

### D6 · Edición, historial en memoria y completado

- **Qué:** el indicador de la conversación es un `PromptSession` con `InMemoryHistory`, completado con Tab (`complete_while_typing=False`) y los atajos que ejecutan o abren cosas desactivados de forma explícita (indicador de sistema, suspender, abrir en editor, ratón). Completa: el nombre del comando tras `/`; el primer argumento de `/resume` (1..N de la última `/sessions`), de `/skill` (carpetas con forma de nombre de Skill, como mucho 200) y de `/file` (rutas del disco, sin las que tienen caracteres de control o de formato, espacios o comillas). Nada se completa fuera de una línea que empieza por `/`. El historial es del proceso (lo que la persona escribió en esta conversación, también en otra sesión tras `/new`) y desaparece al salir; nunca se escribe a disco.
- **Por qué:** hoy el harness solo guarda contenido real con proveedores sintéticos; un fichero de historial guardaría las preguntas reales escritas a Copilot, que es justo lo que no se guarda (Corte 2). Responde la pregunta abierta de `interactive-shell` («¿guardar en disco el historial de entradas?»): no.
- **Alternativas rechazadas:**
  - `FileHistory` en `HARNESS_DATA_DIR` con permisos 600: sigue siendo contenido real en disco, sin política de retención que lo permita.
  - Vaciar el historial en `/new` y `/resume`: el historial es de la persona, no de la sesión, y repetir una pregunta en otra sesión es un uso natural; no muestra nada de otra sesión que la persona no haya escrito en esta misma ejecución.
  - Completar mientras se escribe: abre un menú en cada `/` y no aporta.
- **Impacto:** spec (Edición e historial de entradas; Completado de comandos); tests `tests/unit/test_shell_completion.py`, `tests/unit/test_shell_styled.py`.

### D7 · Ctrl+C, la aprobación y lo escrito por adelantado en la terminal con estilo

- **Qué:**
  - **Ctrl+C en la espera de línea:** el indicador está en modo crudo, Ctrl+C es una tecla y termina el indicador con `KeyboardInterrupt`, que `read_line` convierte en `WaitInterrupted`: la conversación dice cómo salir y sigue (D7 de `interactive-shell`).
  - **Ctrl+C mientras el proveedor abre, trabaja o cierra:** no hay indicador abierto, la terminal está en modo normal y Ctrl+C es la señal SIGINT que recibe el manejador de la conversación, igual que en el camino plano: primer Ctrl+C al abrir → 130; durante la pregunta → `uncertain`, sin reenvío.
  - **El manejador no se toca:** los indicadores se abren con `handle_sigint=False` (y `set_exception_handler=False`), así que `prompt_toolkit` nunca instala el suyo. Una SIGINT que llega con un indicador abierto (enviada por otro proceso) la recibe el manejador y `interrupt_wait` termina el indicador como la tecla; si llega antes de que el indicador arranque, se recuerda y lo termina en cuanto arranca.
  - **Aviso de aprobación:** el contenido y la cabecera los imprime el motor con el `render_approval` de la conversación, igual que hoy (mismo hash, mismos bytes). La respuesta se lee con un `PromptSession` nuevo en cada pregunta, sin historial que sobreviva, sin completado y sin barra, en un hilo (`in_thread=True`) porque el motor pregunta de forma síncrona desde el bucle. Ctrl+C o fin de entrada → «sin decidir». La confirmación `reject` tras `n` es la del motor, sin cambios.
  - **Lo escrito por adelantado:** lo que se escribe mientras nadie lee sigue en el búfer de la terminal y lo recibe el indicador siguiente (también el de aprobación), como hoy: no puede aprobar (el código es de un hash aún no mostrado) y una `n` sola no rechaza (D8). Un pegado de varias líneas llega ahora como **una** respuesta (pegado delimitado): `n` + `reject` pegados ya no rechazan.
- **Por qué:** cada garantía queda en el mismo sitio que en el camino plano: la cancelación de la pregunta la sigue haciendo el mismo manejador, y la aprobación la sigue decidiendo el motor.
- **Alternativas rechazadas:**
  - Dejar `handle_sigint=True`: durante el indicador sustituye el manejador de la conversación (control negativo en `test_the_conversation_signal_handler_survives_a_prompt`).
  - Leer la aprobación con el `input()` del camino plano: su hilo lector puede quedar bloqueado tras Ctrl+C (D6 de `interactive-shell`) y competiría por la entrada con el indicador siguiente.
  - Convertir los saltos de un pegado en varias líneas: devolvería el límite de D8 (un pegado `n` + `reject` rechaza).
- **Impacto:** spec (Interrupción y aprobación en la terminal con estilo); tests con tubería y con pseudoterminal.

## Supuestos de Windows (sin ejecutar)

Lo que se supone y no se ha medido, porque Windows no se puede ejecutar desde aquí:

- La consola clásica (conhost sin VT) y Windows Terminal: `prompt_toolkit` elige `Win32Output` o la salida VT al crear la salida; los colores ANSI con nombre (`ansicyan`…) existen en las dos.
- Ctrl+C con el indicador abierto llega como tecla (se quita `ENABLE_PROCESSED_INPUT`); sin indicador, es la señal que ya recibe el manejador de D6 (lo medido para el camino plano sigue pendiente en la tarea 1.2 de `interactive-shell`).
- El indicador en un hilo (`in_thread=True`) funciona con la entrada de consola de Windows, que la librería espera con `WaitForMultipleObjects` en un ejecutor.
- PowerShell 5 y 7 sobre conhost o Windows Terminal: sin diferencias para la librería (el anfitrión es la consola).
- Git Bash con mintty no es una consola: `isatty()` es falso → camino plano; si no lo fuera y la librería no pudiera crear la salida, se cae al plano (D4).

## Risks / Trade-offs

- [Dependencia nueva con acceso a la terminal] → fijada exacta, `uv.lock` con hashes; un solo módulo la importa; los atajos que ejecutan o abren cosas desactivados de forma explícita y comprobados.
- [`wcwidth` 0.9.5 se publicó el 2026-11-21, cinco días antes de este change, con extensiones nativas] → queda fijada por `uv.lock`; se revisa al actualizar; la librería tiene wheel puro como alternativa. Límite aceptado.
- [Un cambio de la librería en el manejo de SIGINT o del modo crudo] → los tests de tubería y de pseudoterminal lo detectan (Ctrl+C, señal, aprobación); la versión está fijada.
- [La barra inferior y el menú de completado dibujan con movimientos de cursor] → solo mientras la persona escribe; nada ajeno entra en ellos (la barra es estado del harness; las rutas se filtran).
- [Una consola que no responde a la petición de posición del cursor] → la librería espera un tiempo y sigue sin ella (sin medir aquí; los tests responden como una terminal).
- [Lo escrito por adelantado contesta el aviso siguiente] → sin cambios respecto a D8: no puede aprobar.
- [El ancho ambiguo y el redimensionado] → mismos límites de D9 de `interactive-shell`.
- Límite que no se arregla: el historial de entradas cruza sesiones dentro de una ejecución (D6), por decisión.

## Open Questions

- ¿Contador de envíos en la barra? Cuando exista el dato (Wilson: «más adelante»).
