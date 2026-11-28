# ai-harness

Copiloto de arquitectura que se ejecuta en local. Mantiene varias conversaciones persistentes con un proveedor de lenguaje, lee una segunda memoria en Markdown, ejecuta Skills declarativos y llama a herramientas de solo lectura de servidores MCP. En cortes posteriores usará Microsoft Copilot Web y Enterprise Architect.

**Es un proyecto educativo:** sirve para aprender a construir un harness, no está pensado para uso en producción. Se ejercita solo con prompts sintéticos y no guarda contenido real. Quien lo use para automatizar un servicio real es responsable de cumplir las condiciones de uso de ese servicio.

Estado (revisado el 2026-11-26, rama `feature/copilot-web-provider`): **Corte 1 · Esqueleto**, **Corte 3 · Memoria**, **Corte 4 · Skills**, **Corte 9 · Interfaz conversacional** ([Conversación](#conversación)) y, del Corte 5, la **pasarela MCP** (`mcp-gateway`); la lectura de Enterprise Architect (`ea-read`) está en pausa. Sesiones, historial y recuperación funcionan con el proveedor Mock y, en esta rama, con el proveedor de **Copilot Web** (Corte 2, ver [Copilot Web](#copilot-web)). Copilot Web se ha probado contra la página real solo en macOS y con una cuenta de prueba: preguntas completadas en sesiones distintas, la misma conversación desde otro proceso, un plazo vencido que queda `uncertain` sin reenviar, el historial sin contenido y una respuesta sin las sugerencias de seguimiento que la página dibuja debajo, y respuestas con encabezados y con un bloque `json` que pasan las comprobaciones de los Skills `hls-review` y `architecture-memory`. La conversación con Edge abierto todo el rato está probada solo contra el chat sintético. Faltan la demo de Wilson (tarea 7.5) y la prueba en Windows. Con `ask`, cada pregunta abre y cierra Edge (en `chat`, una vez por conversación); cerrarlo cuesta unos 10 s mientras siga activa la red en segundo plano de Edge (ver `SECURITY.md`). El harness lee una segunda memoria en Markdown compatible con `claude-memory-system`, ejecuta Skills declarativos y llama por stdio a herramientas de solo lectura de servidores MCP declarados en una lista local (ver [Herramientas MCP](#herramientas-mcp)). Su única escritura en esa memoria es una nota de decisión nueva en `Decisiones/`, después de una aprobación humana (ver [Skills de arquitectura](#skills-de-arquitectura)). El plan de entregas está en [`docs/plan/2026-11-24-ai-harness-cortes.md`](docs/plan/2026-11-24-ai-harness-cortes.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/). Python 3.14 lo instala uv.
- macOS o Windows. Enterprise Architect (cortes 5 a 7) solo funcionará en Windows.

## Instalación

```sh
uv sync --locked
uv run pytest
```

`--locked` instala exactamente lo que fija `uv.lock` y falla si el lock no corresponde a `pyproject.toml`, en lugar de reescribirlo.

## Uso

```sh
uv run python main.py session create "Arquitectura WhatsApp"
uv run python main.py session list
uv run python main.py ask SESSION_ID "Analiza este requerimiento"
uv run python main.py history SESSION_ID
```

`session create` imprime el identificador de la sesión. Los comandos aceptan solo el UUID completo, no un prefijo. Los resultados salen por stdout; los avisos y los errores, por stderr, siempre en UTF-8 (también con la salida redirigida en Windows). Código de salida: 0 hecho, 1 error controlado, 2 uso incorrecto, 130 interrumpido con Ctrl+C.

## Copilot Web

Con `HARNESS_PROVIDER=copilot_web`, cada sesión pregunta a Microsoft Copilot Web en su propia conversación, a través de un Edge con un **perfil dedicado** (nunca tu Edge personal). Requisitos: Microsoft Edge instalado, haber iniciado sesión una vez con `main.py copilot login` y haber medido la interfaz con la sonda (`ui.json`). Los pasos, en [`docs/runbook/copilot.md`](docs/runbook/copilot.md).

```sh
export HARNESS_PROVIDER=copilot_web
export HARNESS_COPILOT_URL='https://copilot.cloud.microsoft/chat'   # la dirección donde aparece tu chat
uv run python main.py session create "Integraciones"
uv run python main.py ask SESSION_ID "Pregunta"
uv run python main.py history SESSION_ID
```

En PowerShell, `$env:HARNESS_PROVIDER = "copilot_web"` y `$env:HARNESS_COPILOT_URL = "https://copilot.cloud.microsoft/chat"`; los comandos son los mismos.

- Cada `ask` abre Edge con una ventana, escribe la pregunta en el chat, espera la respuesta, la imprime y cierra Edge. Tarda unos segundos más que la respuesta (medido en macOS: arranque de unos 4 a 8 s).
- En una [conversación](#conversación) (`main.py chat`), Edge se abre una sola vez al entrar y se cierra al salir; cada pregunta, también con `/new` y `/resume`, carga la conversación de su sesión en ese mismo Edge. Mientras dure, otro comando que necesite el navegador recibe «the harness browser is in use by another command». Tras una pregunta interrumpida con Ctrl+C, la siguiente usa una pestaña nueva.
- La respuesta sale como Markdown reconstruido desde la página (encabezados, listas, tablas, bloques de código con su lenguaje), sin los botones ni las sugerencias de seguimiento, para que los Skills puedan comprobar sus encabezados y su JSON.
- La primera pregunta de una sesión abre una conversación nueva. Copilot le da un identificador unos segundos después de responder; el harness lo guarda y las preguntas siguientes de esa sesión, también desde otra terminal, van a esa misma conversación. Antes de escribir comprueba que la página abierta es esa conversación; si ya no existe, no envía nada y la sesión queda `closed`.
- Si Copilot pide iniciar sesión, la pregunta termina en `authentication_required` sin escribir nada en la página: ejecuta `main.py copilot login` y vuelve a preguntar.
- Un prompt más largo que el máximo medido (o que `HARNESS_COPILOT_MAX_PROMPT_CHARS`) se rechaza antes de abrir Edge.
- **Modo de respuesta** (`auto`, `quick`, `deep`): cada sesión recuerda el suyo, `auto` por defecto. Se elige con `/mode` en la conversación o con `ask SESSION_ID "Pregunta" --mode deep` (queda para las preguntas siguientes de la sesión). Cambiarlo no envía nada ni abre Edge. Antes de escribir cada pregunta, el harness pone el modo con el selector de la página y lo relee; si no puede confirmarlo, la pregunta termina en `failed` sin escribir nada. Tras la respuesta lo relee: si la página cambió de modo sola, la solicitud guarda el modo que quedó y lo avisa. `quick` y `deep` necesitan que la sonda haya medido el selector (`copilot_probe.py response-mode`, ver el runbook); sin esa medida se rechazan con un mensaje y `auto` deja la página como está. Una pregunta en `deep` tiene su propio plazo, `HARNESS_DEEP_REQUEST_TIMEOUT_S`. El modo se ve en el panel lateral, en `/status` y, cuando no es el automático sin cambios, en `/history` y `history`.
- **Qué se guarda:** de una sesión de Copilot, solo la sesión, el identificador de su conversación, cada solicitud con su estado y sus fechas, y la auditoría. **Nunca** el texto de las preguntas ni de las respuestas: la respuesta solo sale por stdout, sin caracteres de control ni invisibles. `history` muestra el identificador y las solicitudes, sin texto.
- No actives `DEBUG=pw:api` con contenido real: Playwright escribiría en la terminal lo que se teclea y se lee.

Para verlo sin Copilot, contra un chat sintético local y sin ventana: `uv run python scripts/demo_copilot_provider.py` (termina en `demo: PASS`).

## Conversación

Además de las órdenes sueltas, el harness se usa como una conversación: se entra una vez y se escriben preguntas y comandos.

```sh
uv run python main.py                                  # en una terminal: abre la conversación
uv run python main.py chat --project demo-alpha        # sesión nueva con la memoria de un proyecto
uv run python main.py chat --session SESSION_ID        # continúa una sesión
```

`main.py` sin argumentos abre la conversación solo si la entrada y la salida son una terminal; en un script o con una tubería sigue mostrando la ayuda. `chat` sin terminal termina con código 2 sin crear ni tocar ninguna sesión: para scripts están las órdenes sueltas, que no cambian.

Al entrar se ve el proveedor, la sesión y el proyecto. Una línea normal es una pregunta en esa sesión, con los mismos estados y reglas que `ask` (y la memoria del proyecto, si la sesión lo tiene, como `ask --project`). Una línea que empieza por `/` es un comando y **nunca** se envía al proveedor, tampoco si está mal escrito; para preguntar algo que empieza por `/`, se escribe `//`.

| Comando | Qué hace |
|---|---|
| `/help` | Lista los comandos. |
| `/status` | Sesión, proyecto, proveedor, última solicitud, modo de respuesta y adjunto pendiente. |
| `/new [--project SLUG] [NOMBRE]` | Pasa a una sesión nueva; la anterior queda libre y sin cambios. Forma corta: `/new SLUG` si `SLUG` es una carpeta de `projects/` del vault. |
| `/sessions` | Lista numerada de sesiones. |
| `/resume N` o `/resume ID` | Pasa a la sesión número N de la última `/sessions`, o a la sesión con ese identificador (entero, o sus primeros 8 caracteres o más si solo una sesión empieza así). |
| `/history` | Historial de esta sesión, y de ninguna otra. |
| `/memory TÉRMINOS` | Lo mismo que `memory search` (dentro del proyecto de la sesión, si lo tiene). |
| `/context` | Lo mismo que `memory context` para el proyecto de la sesión. |
| `/skill NOMBRE [CLAVE=VALOR…] [--file CLAVE=RUTA…]` | Ejecuta un Skill en esta sesión, como `skill run`, con el proyecto de la sesión. Su aprobación se pide ahí mismo, con el aviso de siempre. Forma corta: `/skill NOMBRE RUTA` si el Skill declara una sola entrada. |
| `/file RUTA` | Adjunta un fichero de texto (hasta 64 KiB, UTF-8, un fichero normal: no un enlace, una tubería ni un dispositivo) a la **siguiente** pregunta. Va marcado como datos y no se guarda nunca. |
| `/mode [auto\|quick\|deep]` | Sin argumento, el modo de respuesta de la sesión; con uno, lo cambia y lo recuerda. No envía nada. En la pantalla completa, Tab tras `/mode ` ofrece `auto`, `quick` y `deep`. Forma corta: `/mo`; `/m` ya no es `/memory`, porque empieza dos comandos, y es un error que los nombra. Ver [Copilot Web](#copilot-web). |
| `/exit` | Sale. El fin de entrada (Ctrl+D; en Windows, Ctrl+Z e Intro) también. |

**Formas cortas** (`command-completion`). Las formas largas siguen igual. Basta el principio del nombre de un comando si solo uno empieza así (`/sk` es `/skill`, `/c` es `/context`); si hay más de uno (`/s`), es un error que los nombra y no se ejecuta nada. `/new demo-alpha` es `/new --project demo-alpha` cuando `demo-alpha` es una carpeta de `projects/`; si no lo es, sigue siendo el nombre de la sesión. `/skill architecture-memory RUTA` es `/skill architecture-memory --file source=RUTA`, porque ese Skill declara una sola entrada (`source`). `/file` y `--file` leen `~/…` de la carpeta personal. Antes de ejecutar un comando escrito en forma corta, la conversación muestra el comando entero (`running: /skill architecture-memory --file source=…`); en la pantalla completa, además, se ve en el borde de la entrada mientras se escribe. Un comando escrito entero no se repite.

- **Ctrl+C** durante una pregunta la interrumpe: queda `uncertain` si el prompt ya había salido, `failed` si no, nunca se reenvía y la conversación sigue. Ctrl+C mientras se espera una línea solo recuerda cómo salir. Ctrl+C durante `/skill` lo detiene: si el paso del modelo estaba en curso, queda `uncertain` (no se reenvía) y la conversación escribe los dos comandos que lo continúan o lo cancelan, que se usan tras dejar la sesión. Ctrl+C en el aviso de aprobación lo deja sin decidir: no se aplica nada. Ctrl+C mientras el proveedor abre sus recursos, al entrar, termina la conversación (código 130) sin preguntar nada; mientras los cierra, al salir, deja de esperar y avisa de que algo puede haber quedado abierto.
- **Lo que se escribe mientras nadie lee se queda en la terminal** y es la primera línea que recibe la lectura siguiente, también el aviso de aprobación. No puede aprobar (el código sale de un hash que aún no se había mostrado). Tampoco rechaza sola: en la conversación, tras `n` el aviso pide la palabra `reject` completa, y cualquier otra respuesta deja la aprobación pendiente (sin cancelar la ejecución; se continúa con `skill resume` tras dejar la sesión) y no se envía ni se ejecuta. En texto plano (`--plain`), un pegado que contenga `n` y `reject` rechaza. En la pantalla completa, la caja de aprobación se decide con botones que no tienen el foco al abrirse y están deshabilitados el primer medio segundo, y lo escrito mientras el núcleo trabaja no se envía. `skill run` desde la línea de órdenes sigue rechazando con `n`.
- **La conversación ocupa su sesión** mientras está abierta: otro `chat` o un `ask` sobre esa sesión reciben «in use by another process» / «question in progress». Si el proceso muere, la sesión queda libre sola. Una ejecución de Skill que quede esperando aprobación se continúa con `skill resume` cuando la conversación ya no tiene esa sesión (`/new`, `/resume` o `/exit`).
- **Lo que no es del harness lleva `| ` delante**: respuestas del proveedor, historial, notas de memoria y salida de Skills salen saneadas (sin secuencias de escape ni caracteres de control o invisibles, con las credenciales conocidas enmascaradas) y con ese prefijo, que ninguna línea del propio harness usa. Una pregunta de más de 64 KiB se rechaza sin registrar nada. El contenido dentro del aviso de aprobación también lleva `| ` (la cabecera, las reglas y la pregunta no). Una línea más ancha que la terminal se corta en filas, y cada fila que continúa la anterior empieza por `|+`: así la terminal nunca parte por su cuenta una línea ajena en una fila sin marca.
- **Qué no hace esta versión:** la respuesta aparece entera, no poco a poco; el modelo no ejecuta herramientas por su cuenta ni hay llamadas MCP desde la conversación (`mcp call` sigue siendo una orden suelta); el historial de lo escrito no se guarda entre ejecuciones.

### Aspecto

En una consola, la conversación ocupa la pantalla completa ([Textual](https://textual.textualize.io/), la única librería de terminal del proyecto): la conversación con su propio desplazamiento, un panel con la sesión a la derecha (desde 100 columnas), la entrada fija abajo y los atajos al pie. Así se ve en 100 × 30, con el Mock y dos preguntas con respuestas sintéticas (captura de texto de la pantalla tomada con el `Pilot` de Textual, sin colores; las líneas de bienvenida del harness ya están plegadas):

```text
    ▸ harness · 4 lines · done  ai-harness - mock session 01a21…    │  Session
                                                                    │   chat 2026-11-27 12:04
  █ revisa este requerimiento 0                                     │   01a21df7-8eef-76f9-a1c2-0e
                                                                    │  18af454a62
  ╭─ mock ───────────────────────────────────────────────────────╮  │  Project
  │ ## Resumen                                                   │  │   -
  │ El requerimiento pide **avisar** de pedidos con              │  │  Provider
  │ `order.created`.                                             │  │   mock
  │                                                              │  │  Sends
  │ ## Preguntas pendientes                                      │  │   2
  │ - Que pasa con un evento que no se publica?                  │  │  Last request
  ╰──────────────────────────────────────────────────────────────╯  │   completed
                                                                    │  Memory
  █ revisa este requerimiento 1                                     │   0 note(s) in the last
                                                                    │  question
  ╭─ mock ───────────────────────────────────────────────────────╮  │
  │ ## Resumen                                                   │
  │ El requerimiento pide **avisar** de pedidos con              │
  │ `order.created`.                                             │
  │                                                              │
  │ ## Preguntas pendientes                                      │
  │ - Que pasa con un evento que no se publica?                  │
  ╰──────────────────────────────────────────────────────────────╯



  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎
  ▊ Type a question, or / for a command                                                          ▎
  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎
  ctrl+p commands  ctrl+c interrupts  ctrl+q leaves  ctrl+n new  esc blocks  ctrl+o open/close
```

- **Espaciado y colores** (`tui-spacing`): todo color sale del tema de Textual por roles con nombre (`harness/shell/palette.py`), sin colores propios, y los huecos salen de una escala (`harness/shell/spacing.py`: columnas 1/2/4/8, filas 1/2, una fila mide como dos columnas). Todo el texto (lo que escribes, el harness, el texto ajeno dentro de su recuadro y la entrada) empieza en la misma columna, a 2 del borde. Desde 30 filas hay una fila en blanco entre bloques; por debajo no, y la entrada pasa a 2 filas. Por debajo de 100 columnas el panel lateral se oculta y la conversación usa todo el ancho; `/status` da lo mismo que el panel (peticiones, última petición, modo de respuesta y notas de memoria). Lo que escribes lleva una barra a la izquierda y un fondo suave; en un tema de terminal sin fondos, la barra basta.
- **Bloques:** lo que escribes (con una barra a la izquierda), las líneas del harness (en gris) y el texto ajeno, siempre dentro de un recuadro cuyo título pone el harness (el nombre del proveedor); plegado, de él solo queda un extracto de una línea tras `| `. Lo de dentro del recuadro se muestra como caracteres: `[@click=…]`, `[link=…]` o una secuencia de escape no hacen nada. El resaltado de Markdown colorea sin quitar ni añadir un carácter respecto al texto plano, que muestra lo mismo sin color.
- **Tablas y bloques de código** (`reply-rendering`, desde el 2026-11-27): el harness alinea una tabla de Markdown de una respuesta como texto, con columnas del ancho de su contenido, una raya bajo la cabecera y las marcas de alineación (`:--`, `:-:`, `--:`); los únicos caracteres que añade son `│`, `─`, `┼` y espacios, atenuados, sin esquinas ni fondo. Si no cabe, parte las celdas dentro de su columna; si ni así cabe, o la tabla está mal formada o pasa de 200 filas, 16 columnas o 1000 caracteres por celda, se queda como llegó. Un bloque de código pierde sus ```` ``` ```` y queda entre dos rayas, la de arriba con el lenguaje (`── python ───`). El texto plano (`--plain`) hace lo mismo, sin color. El ancho es el del panel cuando llega la respuesta: si después cambias el tamaño de la terminal, esa tabla no se vuelve a alinear.
- **Bloques que se pliegan** (`collapsible-blocks`): cada turno (tu línea y lo que vino después) y cada bloque de un turno se abren y se cierran. Al llegar, una respuesta se ve entera (desde el 2026-11-27, `reply-rendering`): si es más alta que el panel, el panel se coloca en su principio y el pie dice cuántas filas quedan debajo (`↓ 50 more rows below`), hasta que llegas al final. Solo una respuesta de más de 64 000 caracteres llega plegada: muestra sus primeras filas y el borde de abajo dice cuántas líneas faltan (`… 30 more lines · enter/click to expand`); igual llega otro texto ajeno largo (`/history`, `/memory`). Los pasos de una Skill quedan en una línea. Siempre enteros: los errores y avisos, las líneas `omitted:` y `attached:` (la nota que no cupo, el fichero que sí se envió), cómo terminó una Skill (`skill: run … is completed`) y lo que aplicó (`applied:`) y lo que muestra `/context`, que es exactamente lo que se envía. Al enviar una pregunta, los turnos anteriores al penúltimo se pliegan a una línea (`▸ you → mock · 42 lines · completed  › revisa el HLS`), salvo los que abriste o cerraste tú (tu elección se mantiene) y los que tuvieron un error o un aviso; plegado a mano, un turno así lo dice (`completed · 1 warning`). Plegado, un bloque dice quién es, cuántas líneas tiene y, tras `| `, los títulos de la respuesta (`## Resumen · ## Riesgos`) o su primera línea; lo del harness va sobre un fondo propio que el texto ajeno no puede tener. Teclas: `Esc` recorre los bloques (flechas, `enter` o espacio abre y cierra, `+`/`-` todo, `end` el último, `Esc` o cualquier letra vuelve a escribir y la letra se escribe; abrirse la caja de aprobación o la paleta también); desde la entrada, `alt+↑`/`alt+↓` eligen bloque y `ctrl+o` abre o cierra el elegido o la última respuesta. Un clic en la cabecera o el pie de un bloque lo abre o cierra; en el texto, nada. En la paleta: «Browse blocks», «Open or close the block», «Expand all blocks», «Collapse all blocks», «Jump to latest». Al abrir o cerrar, la cabecera no se mueve de su fila, y lo que llega mientras recorres o lees más arriba no mueve el panel. Cada sesión tiene sus bloques: `/new` y `/resume` muestran los de la sesión tomada. Nada de esto se guarda. Tras dos preguntas largas, `Esc` y `home` (100 × 30, sintético; la primera, plegada; la segunda, abierta a mano):

  ```text
   ▸ harness · 4 lines · done  ai-harness - mock session 01a21c5d   │  chat 2026-11-27 04:37
                                                                    │  01a21c5d-eb10-736a-98c3-28e8b9
   ▸ you → mock · 2 lines · completed  › ¿está claro el alcance?    │ d286ca
                                                                    │ Project
   █ revisa el HLS sintético                                        │  -
                                                                  ▃ │ Provider
   ╭─ mock · 41 lines ───────────────────────────────────────────╮  │  mock
   │ ## Resumen del HLS                                          │  │ Sends
   │ El requerimiento sintético pide **avisar** de cada pedido.  │  │  3
   │                                                             │  │ Last request
   │ ## Riesgos                                                  │  │  completed
   │ - Riesgo sintético 1: el evento `order.created` puede       │  │ Memory
   │ llegar dos veces.                                           │  │  0 note(s) in the last question
   │ - Riesgo sintético 2: el evento `order.created` puede       │  │
   │ llegar dos veces.                                           │
   │ - Riesgo sintético 3: el evento `order.created` puede       │
   │ llegar dos veces.                                           │
   │ - Riesgo sintético 4: el evento `order.created` puede       │
   │ llegar dos veces.                                           │
   │ - Riesgo sintético 5: el evento `order.created` puede       │
   │ llegar dos veces.                                           │
   │ - Riesgo sintético 6: el evento `order.created` puede       │
   │ llegar dos veces.                                           │
   │ - Riesgo sintético 7: el evento `order.created` puede       │
   │ llegar dos veces.                                           │
  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎
  ▊  browsing the blocks: esc or any letter goes back to typing                                      ▎
  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎
   up/down move  enter open/close  +/- all  end latest  esc back to typing
  ```
- **Panel:** sesión (nombre e identificador completo), proyecto, proveedor, peticiones enviadas en esta sesión, estado de la última y las notas de memoria que llevó la última pregunta. Sale solo del estado del harness y siempre describe la sesión tomada.
- **Teclas:** `ctrl+p` abre la paleta de órdenes (solo órdenes del harness: estado, sesión nueva, cambiar de sesión, historial, contexto, elegir Skill, adjuntar fichero, buscar en la memoria…). «Switch session...» lista las sesiones y elige con el teclado; «Choose a skill...» rellena `/skill NOMBRE `; «Attach a file...» lista los ficheros de la carpeta de trabajo. `ctrl+n` sesión nueva. Flechas arriba y abajo: lo escrito en esta ejecución (solo en memoria); `Esc` cambia las flechas a recorrer los bloques. Tab completa (ver «Completar»). `ctrl+c` interrumpe la pregunta en curso; sin nada en curso no sale. `ctrl+q`, `ctrl+d` con la entrada vacía o `/exit` salen: se cierra el proveedor y la terminal vuelve a como estaba.
- **Completar** (`command-completion`): al escribir `/` aparece debajo de la entrada la lista de comandos con una línea de ayuda; al seguir escribiendo se filtra (primero los que empiezan así, después los que contienen esas letras en orden). Después del comando, la lista ofrece sus opciones (`--project`, `--file`) y sus valores: los proyectos del vault, los Skills válidos con su descripción, las entradas que declara el Skill (`source=`), las sesiones (identificador, proyecto y título) para `/resume`, y rutas para `/file`, `--file NOMBRE=` y la ruta corta de un Skill de una entrada. Las rutas son relativas a la carpeta de trabajo, carpetas primero; `~/` se lista y se queda escrito `~/`; los nombres ocultos solo salen si lo escrito empieza por `.`; un enlace sale como nombre y nunca se sigue. Ninguna fila está elegida al abrirse. Teclas, en este orden:
  | Tecla | Con la lista abierta | Con la lista cerrada |
  |---|---|---|
  | `Tab` | pone la fila elegida, o la primera | pone el primer candidato (si hay) |
  | `↑`/`↓` | eligen fila | historial de lo escrito |
  | `Enter` | con una fila elegida, la pone y no envía; sin fila elegida, cierra y envía lo escrito | envía |
  | `Esc` | cierra la lista | recorre los bloques |
  | letras, borrar | se escriben y la lista se filtra | se escriben |
  | `ctrl+c`, `ctrl+q`, `ctrl+n`, `ctrl+p` | lo de siempre (la paleta cierra la lista) | lo de siempre |

  Completar nunca envía ni ejecuta nada y nunca lee el contenido de un fichero, solo nombres. La lista no se abre sobre la caja de aprobación, la paleta ni un selector. Solo se ofrece lo que la conversación lee como ese mismo valor: un nombre con secuencias de escape, caracteres invisibles, cualquier espacio (también el duro o el estrecho de Unicode), comillas, o que empieza por `-`, no se ofrece; los demás se dibujan como caracteres, nunca como estilos. Una carpeta se lista en otro hilo, con un tope de 100 000 entradas y medio segundo; una que no se puede leer no ofrece nada y no da error, y una que nunca contesta no retiene la salida. Así, tras escribir `/` (110 × 32, captura de texto del `Pilot`):
  ```text
  ╭─ tab completes · ↑↓ choose · enter takes the chosen · esc closes ──────────────────────────────────────────╮
  │ /help      this list                                                                                       │
  │ /status    session, project, provider and last request                                                     │
  │ /new       switch to a new session                                                                         │
  │ /sessions  numbered list of sessions                                                                       │
  │ /resume    switch to session N of the last /sessions list, or to session ID                                │
  │ /history   the history of this session                                                                  ▁▁ │
  │ /memory    search the memory (of the session's project, if it has one)                                     │
  │ /context   the memory block sent with each question of this session                                        │
  ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
  ▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎
  ▊  /                                                                                                         ▎
  ▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎
  ```
  En texto plano (`--plain`) no hay lista ni Tab (la biblioteca estándar de Python no trae `readline` en Windows), pero las formas cortas son las mismas.
- **Mientras el proveedor trabaja** se ve `mock: thinking (N s), ctrl+c interrupts` y la entrada no envía (lo escrito se queda en ella).
- **La aprobación** se abre en su propia caja: la cabecera del motor (destino, hash, caducidad), el contenido propuesto en un recuadro de texto ajeno y, fija abajo, la fila **[Approve] [Reject]** (desde el 2026-11-27, `approval-buttons`). Cómo funciona:
  - El foco empieza en la propuesta, que se recorre con `AvPág`/`RePág`, flechas, `Inicio`, `Fin` o la rueda. La caja dice cuántas líneas quedan debajo o que la propuesta se ha mostrado entera.
  - Durante el primer medio segundo los dos botones están deshabilitados. Un botón deshabilitado se ve tachado y el enfocado, invertido, también en una terminal sin color. Los botones miden lo mismo y van centrados, y la caja deja filas en blanco solo cuando la terminal tiene 30 filas o más (escala en `harness/shell/spacing.py`).
  - «Approve» se habilita cuando el final de la propuesta ha estado en pantalla. Se pulsa con el ratón, o con Tab y Enter.
  - «Reject» pregunta otra vez dentro de la caja, con el foco en «Back»; solo «Yes, reject» rechaza.
  - Escape no decide. `ctrl+c` y `ctrl+q` la dejan sin decidir.
  - En la caja no se escribe nada: no hay código, y un pegado o `ctrl+v` no hacen nada.
  - La auditoría registra `means=button`.
  - En texto plano (`--plain`) y en `skill run`/`skill resume` se sigue escribiendo el código.
- **Lo que la pantalla no hace:** capturas, guardar ficheros, abrir enlaces, suspenderse ni copiar al portapapeles de la terminal. Si falla por dentro, imprime una línea fija sin nada de la conversación. Si la consola no admite la pantalla completa, lo dice en una línea y sigue en texto plano.
- **Texto resaltado en azul:** es la selección de Textual. Arrastrar, o hacer doble o triple clic, sobre la conversación resalta el texto, pero no lo copia (`ctrl+c` interrumpe y Terminal.app no acepta la copia por OSC 52); un clic lo quita. Para copiar, usa la selección de la terminal: en Terminal.app (macOS), arrastra con `Fn` pulsada, o desactiva «Visualización › Permitir informes del ratón» (`⌘R`) y copia con `⌘C`; en Windows Terminal, arrastra con `Mayús` pulsada y copia con `ctrl+shift+c`.
- **Un pegado de varias líneas** en la entrada se queda con la primera.
- **Para quitarlo:** `main.py chat --plain`, o `HARNESS_PLAIN=1`, `NO_COLOR=1` o `TERM=dumb` en el entorno: la conversación de texto plano de siempre (la que usan los tests y las demos). También se usa sola sin consola, si Textual no carga o si hay puesta una variable de depuración de Textual (`TEXTUAL`, `TEXTUAL_LOG`, `TEXTUAL_SCREENSHOT`…), que guardaría o enviaría lo que se ve.

### Paso a paso con el Mock

Con una copia del vault sintético en una carpeta temporal y una respuesta guionizada para el Skill `architecture-memory`. En PowerShell, desde la raíz del repositorio:

```powershell
$w = Join-Path $env:TEMP "ai-harness-chat"
Remove-Item -Recurse -Force $w -ErrorAction SilentlyContinue
New-Item -ItemType Directory $w | Out-Null
Copy-Item -Recurse tests\fixtures\vault-synthetic "$w\vault"
$answer = [IO.File]::ReadAllText((Resolve-Path tests\fixtures\skill-inputs\decision-ok.json).Path, [Text.Encoding]::UTF8)
$json = @{ "tarea: architecture-memory/extract" = $answer } | ConvertTo-Json
[IO.File]::WriteAllText("$w\respuestas.json", $json, (New-Object Text.UTF8Encoding $false))
$env:HARNESS_DATA_DIR = "$w\data"
$env:HARNESS_VAULT_ROOT = "$w\vault"
$env:HARNESS_MOCK_RESPONSES = "$w\respuestas.json"
$env:HARNESS_MOCK_DELAY_MS = "0"
uv run python main.py
```

Las tres líneas de `respuestas.json` valen igual en Windows PowerShell 5.1 y en PowerShell 7. En 5.1, `ConvertTo-Json` convierte en un objeto el texto que devuelve `Get-Content -Raw`, porque ese texto lleva propiedades añadidas (`PSPath`…), y el Mock lo rechaza. `[IO.File]::ReadAllText` devuelve un texto sin nada más. El fichero se escribe en UTF-8 sin BOM. Uno con BOM, el que escribe `Set-Content -Encoding utf8` en 5.1, también carga, como cualquier fichero UTF-8 que lee el harness.

En zsh o bash:

```sh
w="$(mktemp -d)"
cp -R tests/fixtures/vault-synthetic "$w/vault"
python3 -c 'import json,sys; print(json.dumps({"tarea: architecture-memory/extract": open(sys.argv[1], encoding="utf-8").read()}))' tests/fixtures/skill-inputs/decision-ok.json > "$w/respuestas.json"
export HARNESS_DATA_DIR="$w/data" HARNESS_VAULT_ROOT="$w/vault" HARNESS_MOCK_RESPONSES="$w/respuestas.json" HARNESS_MOCK_DELAY_MS=0
uv run python main.py
```

Dentro de la conversación (las líneas son iguales en las dos terminales; en zsh la ruta del fichero va con `/`):

```text
/new demo-alpha "Demo Corte 9"
¿Qué decisiones de mensajería tiene el proyecto?
¿Qué riesgos ves en esa decisión?
/context
/skill architecture-memory tests\fixtures\skill-inputs\fuente-decision.md
```

Son formas cortas: antes de ejecutarse, la conversación muestra `running: /new --project demo-alpha "Demo Corte 9"` y `running: /skill architecture-memory --file source=…`. En la pantalla completa se escriben aún menos: `/new demo-a` y Tab; `/sk`, Tab, `arch`, Tab, y la ruta con Tab en cada carpeta (`tests/fi` Tab, `sk` Tab, `fu` Tab).

Cada pregunta muestra una línea `context: demo-alpha, 7 note(s) included…` y la respuesta del Mock con `| ` delante. `/context` muestra el bloque de memoria. El Skill abre la caja `Approval requested` con la nota entera, su destino `Decisiones/…` y su hash. Cuando la caja dice «The whole proposal has been shown», Tab y Enter, o un clic en «Approve», la aprueban, y se ve `applied: Decisiones/…md` y `skill: run … is completed`. Con `--plain`, el aviso es de texto y se aprueba escribiendo los 8 primeros caracteres del hash. Después, `/status` (anotar el identificador de la sesión) y `/exit`.

Para interrumpir una pregunta lenta, se vuelve a entrar en la misma sesión con el Mock lento:

```powershell
$env:HARNESS_MOCK_DELAY_MS = "60000"
uv run python main.py chat --session SESSION_ID
```

(en zsh: `HARNESS_MOCK_DELAY_MS=60000 uv run python main.py chat --session SESSION_ID`). Se escribe una pregunta, se pulsa Ctrl+C mientras se ve `mock: thinking` (en texto plano, `waiting for the provider`) y se ve `interrupted: request … is uncertain: the prompt may have reached the provider; it was not resent`; la conversación sigue. `/history` muestra las preguntas anteriores, el marcador del Skill y la pregunta interrumpida como `[uncertain]`. `/exit` sale con código 0.

## Memoria del proyecto

El harness lee un vault de Markdown con la estructura de `claude-memory-system` (`projects/<slug>/_project.md`, `projects/<slug>/sessions/`, `Decisiones/`, `Lecciones/`, `Memoria-CC/`…). Los comandos `memory …` y `ask --project` **solo leen**: no crean, modifican, mueven ni borran nada en el vault. La única escritura del harness en el vault es la del Skill `architecture-memory`: una nota de decisión nueva en `Decisiones/` (y la carpeta, si no existe), solo después de que una persona apruebe en la terminal el contenido exacto; nunca modifica ni borra una nota existente (ver [Skills de arquitectura](#skills-de-arquitectura)).

```sh
export HARNESS_VAULT_ROOT="$HOME/ruta/al/vault"   # ruta absoluta
uv run python main.py memory search "orquestador ventas"
uv run python main.py memory search latencia --project demo-alpha --limit 5
uv run python main.py memory context demo-alpha
uv run python main.py session create "Demo" --project demo-alpha
uv run python main.py ask SESSION_ID "Resume el contexto" --project demo-alpha
uv run python main.py memory maintain --dry-run
```

- `memory search QUERY [--project SLUG] [--limit N]` busca las notas que contienen **todos** los términos, sin distinguir mayúsculas. Una línea por nota: ruta relativa, `updated`, coincidencias y un fragmento de una línea (con credenciales enmascaradas y sin caracteres de control). Orden: coincidencias, después `updated` y después ruta. 20 resultados por defecto, 200 como máximo.
- `memory context SLUG` imprime **exactamente** el bloque que `ask --project` enviaría (con otro marcador aleatorio) y, por stderr, cuántas notas entraron, cuántas se recortaron u omitieron, los bytes y las credenciales enmascaradas.
- `ask SESSION_ID PROMPT --project SLUG` envía ese bloque antes de la pregunta. La sesión tiene que haberse creado con `session create ... --project SLUG` y con el mismo proyecto. Si se rechaza (identificador no válido, vault sin configurar, proyecto inexistente o distinto del de la sesión), no se registra ninguna solicitud ni ningún contenido: solo un evento de auditoría `memory.context denied`, sin rutas ni texto. Sin `--project`, `ask` no lee el vault.
- `memory maintain --dry-run` informa, sin tocar nada, de lo que un mantenimiento encontraría: `sync_conflicts`, `broken_links` (con la corrección si hay un único candidato), `index_dangling` e `index_orphans` (índices `Memoria-CC/MEMORY*.md`), `duplicate_candidates`, `invalid_frontmatter`, `secrets_found` (ruta y tipo, nunca el valor) y `skipped`. Nombra rutas, nunca texto de las notas, y dos ejecuciones sobre el mismo vault dan la misma salida byte a byte. Una fecha `created` o `updated` posterior a hoy cuenta como frontmatter no válido. Sin `--dry-run` es un error de uso (código 2): este corte no repara nada. Comparar nombres tiene un tope de 100 000 pares por pasada (la búsqueda de la corrección de cada enlace roto, una vez por nombre, y los pares de notas de `Memoria-CC/`, unas 450 notas): pasado el tope, esa pasada se detiene, lo que encontró hasta ahí se mantiene y un aviso por stderr dice que `duplicate_candidates` o las correcciones de `broken_links` están incompletos (revisión de seguridad del 2026-11-27).

### Qué se lee y qué no

- Solo ficheros `.md` regulares de hasta 1 MiB cuya ruta real esté dentro de la raíz real del vault. Se ignoran y se cuentan los enlaces simbólicos, las uniones de directorio, los ficheros con más de un enlace duro, las entradas que empiezan por punto (`.obsidian`, `.trash`, `.git`, los temporales `.tmp.*`), `Memoria/Archivo/`, las carpetas que no se pueden listar (`unreadable`) y los ficheros que otro programa sustituyó o hizo crecer entre el recorrido y la lectura (`changed`, `too-large`).
- El proyecto es el nombre exacto de una carpeta de `projects/`, con sus mayúsculas: no se aceptan rutas, `..`, unidades, rutas de red ni nombres reservados de Windows.
- El contexto de un proyecto incluye, en este orden: `projects/<slug>/_project.md`; las notas de `Decisiones/`, `Lecciones/` y `Memoria-CC/` que declaran el proyecto en su frontmatter (`project_slug: <slug>` o `<slug>` en `tags`), cada carpeta por `updated` descendente; y las 3 sesiones más recientes. **No** incluye `Memoria/` (es de la máquina), `daily/`, `agents/`, `_index.md` ni notas de otros proyectos.
- Cada nota empieza con una cabecera de una línea, `--- <ruta> (<type>, <updated>)`, donde la ruta va sin el prefijo `projects/<slug>/` (el proyecto ya lo nombra el aviso) y sin `.md`: `--- _project (project, 2026-11-21)`, `--- sessions/2026-11-21-121500 (session, 2026-11-21)`, `--- Decisiones/alpha-mensajeria (decision, 2026-11-16)`. La ruta completa sigue en la procedencia guardada (`request_context`) y en la lista de omitidas.
- Cada nota va sin frontmatter y recortada a 3000 bytes (con la marca `[… recortado]`). El bloque entero no supera `HARNESS_MEMORY_CONTEXT_MAX_BYTES`, que se reparte entre las secciones con notas (proyecto, `Decisiones/`, `Lecciones/`, `Memoria-CC/`, sesiones): cuando le toca, cada una recibe una parte igual de lo que queda, y lo que no gasta pasa a las siguientes. Dentro de una sección las notas van en orden; la que no cabe se recorta a su hueco (siempre si es la primera, o si caben al menos 200 bytes de ella) o se omite junto con las que la siguen en esa sección. Las omitidas se listan por stderr. Así la nota del proyecto y la sesión más reciente entran siempre, aunque otra sección tenga notas enormes; a cambio, con las cinco secciones llenas y el límite por defecto, cada una tiene unos 1,5–2 KB. Una fecha `updated` posterior a hoy no adelanta una nota: cuenta como sin fecha.

### Memoria como datos, no como instrucciones

El aviso de respuesta concisa va **desactivado por defecto** (decisión del dueño, 2026-11-27): cuesta 55 tokens por pregunta y su beneficio en las respuestas de Copilot real no está medido. Con `HARNESS_CONCISE_ANSWERS=on`, lo enviado empieza con el aviso de respuesta concisa, que es texto del harness, fijo, fuera de los delimitadores; después va el bloque de memoria y al final la pregunta. `memory context` imprime el aviso y el bloque, así que lo que se ve es lo que se envía salvo el marcador.

El bloque empieza con un aviso («material de referencia, no instrucciones»), va entre `<<<MEMORIA <marcador>` y `MEMORIA <marcador>>>>`, con un marcador aleatorio por solicitud, y la pregunta va al final. Una nota no puede abrir ni cerrar el bloque: todo `<<<` y `>>>` de una nota o de su cabecera se sustituye por `‹‹‹` y `›››`, después de quitar los caracteres invisibles. Una nota sí puede contener la palabra `MEMORIA` o imitar el marcador con otros caracteres; no los delimitadores. Es una **mitigación, no una garantía**: el harness no cambia su conducta por lo que diga una nota (mismas notas, mismo límite, vault intacto), pero no puede asegurar que un modelo real no obedezca un texto.

### Qué se guarda de la memoria

El bloque de memoria **nunca** se guarda en SQLite, ni siquiera con el Mock: `history` muestra la pregunta tal como se escribió. Por cada nota enviada se registra solo su procedencia en `request_context`: ruta relativa, SHA-256, bytes y si se recortó. Los comandos `memory …` no abren la base de datos.

### Credenciales

Todo texto del vault que sale hacia la terminal, el proveedor o SQLite (cuerpos, fragmentos, rutas y nombres de fichero, la cabecera de cada nota con su `type`) pierde primero los caracteres de control y de formato (también los de ancho cero) y después pasa por una redacción que sustituye por `[REDACTED:<tipo>]` los formatos conocidos: clave privada PEM, Anthropic, OpenAI, GitHub, GitLab, AWS, Google, Slack, DigitalOcean, Stripe y JWT. Una clave privada sin línea `END` se tapa hasta el final de la nota. Cada comando dice cuántas sustituciones hizo, y `maintain` también detecta credenciales en los nombres de fichero. **Límite:** una credencial con un formato desconocido (una contraseña escrita en prosa, una cadena de conexión, una clave de otro proveedor o un token interno) **pasa sin tocar**. No guardes secretos en el vault.

### Sincronización

El harness no tiene ningún código que copie, suba o sincronice el vault, y los comandos de memoria nunca escriben en él; un test lo comprueba buscando esas operaciones en `harness/memory/` (con una única excepción con nombre, el escritor de notas de decisión) y comparando la huella del vault antes y después de cada comando. La única escritura del harness en el vault es una nota de decisión nueva, después de una aprobación (ver [Skills de arquitectura](#skills-de-arquitectura)). **No impide ni detecta** que otro programa lo sincronice: el vault puede vivir, por ejemplo, en una carpeta de OneDrive, y lo que ese cliente haga con él depende de su configuración, no del harness. Con «archivos a petición» (OneDrive, iCloud), `memory search` y `memory maintain` leen todas las notas y pueden hacer que el cliente descargue el vault entero; no está medido.

`HARNESS_DATA_DIR` no puede estar dentro del vault: `memory …` y `ask --project` lo rechazan con un error (código 1) antes de escribir nada, también si se llega por un enlace. El vault dentro del directorio de datos sí vale. `session …`, `history` y `ask` sin `--project` no leen el vault y no lo comprueban.

## Skills

Un Skill es una carpeta con instrucciones declarativas que el harness ejecuta paso a paso dentro de una sesión. **No contiene código**: el harness nunca ejecuta ni carga nada de un Skill.

```sh
export HARNESS_SKILLS_DIR="$PWD/tests/fixtures/skills"   # ruta absoluta; por defecto, skills/ del repo
# Respuesta guionizada del Mock para el paso `draft` (la del Mock sin guion no pasa el `validate`).
mkdir -p data && printf '%s' '{"tarea: demo-echo/draft": "## Resumen\nok\n\n## Preguntas pendientes\n- Ninguna."}' > data/respuestas.json
export HARNESS_MOCK_RESPONSES="$PWD/data/respuestas.json"
uv run python main.py skill list
uv run python main.py skill show demo-echo
uv run python main.py session create "Demo"
uv run python main.py skill run demo-echo --session SESSION_ID --input text="Texto de prueba"
uv run python main.py skill status RUN_ID
uv run python main.py skill resume RUN_ID --input text="Texto de prueba"
uv run python main.py skill cancel RUN_ID
```

- `skill list` muestra cada Skill con su versión y `valid` o `invalid` con el motivo; `skill show NAME` imprime descripción, versión, hash, entradas y pasos sin preguntar nada ni crear ninguna ejecución (un Skill inválido termina con código 1 y sus motivos).
- `skill run NAME --session ID [--input N=V]… [--input-file N=RUTA]…` ejecuta los pasos en orden y, si termina, imprime la salida declarada por stdout. Las entradas tienen que ser las declaradas, de hasta 64 KiB cada una y 128 KiB en total; `--input-file` lee UTF-8 y comprueba el tamaño antes de leer.
- `skill status RUN_ID [--output]` muestra el Skill, su versión y hash, la sesión, el estado de la ejecución y de cada paso con su intento, y la aprobación pendiente con su identificador y su caducidad (nunca su hash); nunca el texto de las entradas ni de las salidas. `--output` imprime la salida final si se guardó, sin caracteres de control ni de formato y con las credenciales conocidas redactadas, igual que `skill run`.
- `skill resume RUN_ID [--input…] [--retry-step ID]` sigue desde el primer paso no completado. `skill cancel RUN_ID` deja la ejecución `cancelled` y revoca su aprobación.
- Una sesión tiene como mucho una ejecución abierta. Mientras una espera aprobación, la sesión admite `ask`.
- Con esos comandos, `run` y `resume` sin terminal interactiva terminan con código 3 (`awaiting_approval`); en una terminal, `resume` muestra la propuesta y pide el código. `scripts/demo_skill_engine.py` recorre lo mismo en cualquier sistema, PowerShell incluido.

### Formato de un Skill

`<raíz>/<nombre>/SKILL.md` (frontmatter con exactamente `name`, igual al nombre de la carpeta, y `description`, de hasta 300 caracteres), `workflow.json` y ficheros `.md` en `templates/` y `references/`. Cualquier otro fichero visible (un script, un `.py`), un enlace simbólico, una unión o un fichero con más de un enlace duro invalidan el Skill entero; lo que empieza por punto se ignora. El nombre usa minúsculas, dígitos y guiones (hasta 64 caracteres) y no puede ser un nombre reservado de Windows.

`workflow.json` es JSON estricto (sin claves duplicadas, `NaN` ni anidamiento de más de 32 niveles) con un esquema cerrado: `schema: 1`, `version`, `inputs`, `steps` y `output`. Tipos de paso:

- `llm`: envía la plantilla `templates/<nombre>.md` a través de la sesión, con el mismo plazo y los mismos estados que `ask`. `"memory": "project"` añade el contexto del proyecto de la sesión (la sesión tiene que tener proyecto). `timeout_s` de 1 a 600.
- `validate`: comprueba la salida de un paso anterior (`of`) con reglas declaradas: `min_bytes`/`max_bytes`, `required_headings` (Markdown), o `format: json` con campos tipados (`string`, `integer`, `boolean`, `string_list`, con `max_length`, `single_line`, `enum`, `slug`, `date`, `min`, `max`, `max_items`) y sin campos extra. Su salida es el texto saneado y redactado, o el JSON canónico.
- `approval`: pide una aprobación humana sobre la salida de un `validate` anterior y aplica un efecto de la lista cerrada del harness: `none` (consumir la aprobación deja seguir) o `vault.save_decision` (escribe una nota de decisión nueva; ver [Skills de arquitectura](#skills-de-arquitectura)).

Referencias en las plantillas: `{{inputs.NOMBRE}}`, `{{steps.ID.output}}` y `{{steps.ID.fields.CAMPO}}`, a una entrada declarada o a un paso anterior. Cualquier otra cosa entre `{{` y `}}` invalida el Skill. Se sustituyen una sola vez, sin evaluar nada, y cada valor va marcado como datos entre `<<<DATOS <código>` y `DATOS <código>>>>`, con los mismos `‹‹‹`/`›››` que la memoria. El hash del Skill (SHA-256 de sus ficheros con los finales de línea normalizados) es el mismo en macOS y en Windows.

### Estados y códigos de salida

| Estado | Qué significa |
|---|---|
| `running` | Un proceso la está ejecutando. |
| `awaiting_approval` | Espera a una persona. Código de salida **3**. |
| `completed` | Terminó; la salida va por stdout. Código 0. |
| `failed` | Un paso falló, una comprobación no pasó o se superó un límite. Código 1. |
| `uncertain` | Una pregunta pudo llegar al proveedor y no hubo respuesta, o un efecto se interrumpió y no se sabe si se aplicó. Código 1. |
| `pending` | Se interrumpió entre pasos; se puede reanudar. |
| `cancelled` | Cancelada o aprobación rechazada. Código 1. |

Errores de uso (una opción mal escrita, `--input-file` demasiado grande): código 2. Interrumpido con Ctrl+C: 130.

### Aprobación

Al llegar a un paso `approval`, el harness calcula la propuesta (Skill con versión y hash, ejecución, paso, alcance, destino y SHA-256 y tamaño del contenido) y su hash. **Solo se aprueba en una terminal interactiva**: el harness muestra la propuesta entera y hay que escribir los **8 primeros caracteres del hash**. El contenido propuesto sale entre las dos reglas con `| ` delante de cada línea y cortado en filas más estrechas que la terminal (cada fila que continúa la anterior empieza por `|+`), también en `skill run` y `skill resume` desde la línea de órdenes (revisión de seguridad del 2026-11-27): así el modelo no puede dibujar dentro del contenido una regla ni un segundo aviso que parezcan del harness. Lo que se aprueba y su hash no cambian; `n` rechaza y cancela la ejecución. Tres códigos equivocados o el fin de la entrada la dejan pendiente. La pregunta bloquea la sesión hasta que contestas; si contestas después de la caducidad, la aprobación queda caducada y no se aplica nada. Sin terminal (stdin redirigido, un script, un agente), `skill run` y `skill resume` dejan la ejecución en `awaiting_approval` y terminan con código 3 indicando `skill resume RUN_ID`, el identificador de la aprobación y su caducidad.

Lo que se muestra es lo que se aprueba y lo que se aplica: el contenido sin caracteres de control ni de formato, con las credenciales conocidas redactadas, como máximo 32 KiB, y con cualquier otro carácter invisible escrito como `<U+XXXX>` (un emoji con selector de variación se ve como `❤<U+FE0F>`). Un destino con caracteres invisibles o que no está en NFC hace fallar el paso sin preguntar.

Qué garantiza la aprobación:

- El código sale del contenido exacto que se muestra, de su destino, de la ejecución, del paso y del Skill. El código, o cualquier parte del hash, solo aparece dentro de la pregunta interactiva, junto al contenido: ni el mensaje del código 3 ni `skill status` lo muestran.
- No se aprueba con stdin redirigido, con el fin de la entrada, con Enter, con una opción de la CLI ni con una variable de entorno. Ningún texto del modelo ni ningún fichero aprueba.
- Una aprobación vale para una sola propuesta, caduca a los `HARNESS_APPROVAL_TTL_S` segundos (900 por defecto; al reanudar se pide otra) y se usa una vez: si cambia un byte de lo aprobado, del Skill o de la ejecución, se deniega y se revoca.
- Un efecto interrumpido no se aplica dos veces: `skill resume` pregunta al efecto si ya está en su destino. Si está, el paso termina; si no hay nada, pide una aprobación nueva; si hay otra cosa, se niega (código 1) y la ejecución queda `uncertain` para que lo mires y la canceles. `--retry-step` nunca acepta un paso `approval`.

Qué **no** garantiza: que haya una persona delante. Un proceso que corre con tu misma cuenta y maneja una pseudoterminal puede leer la propuesta y escribir el código. Se registra el usuario local que la concedió, pero no es una autenticación (ver [`SECURITY.md`](SECURITY.md)).

### Un paso incierto

Si una pregunta vence después de enviarse, o el proceso muere a mitad, el paso queda `uncertain` y **nunca se repite solo**: `skill resume` se niega y dice qué paso es. Decides tú: `skill resume RUN_ID --retry-step ID` vuelve a preguntar (un intento nuevo, que puede duplicar la pregunta en la conversación; como mucho 3 intentos por paso) o `skill cancel RUN_ID`. Al reanudar hay que volver a pasar las entradas, porque nunca se guardan: el harness comprueba que tienen el mismo SHA-256 y que el Skill no cambió en disco (si cambió, se niega nombrando los dos hashes).

### Límites

32 ficheros, 64 KiB por fichero y 512 KiB por Skill; 12 pasos y 8 entradas; 64 KiB de prompt sin contar la memoria; 128 KiB de respuesta; 32 KiB de propuesta; 1800 s por invocación de `run` o `resume`; 3 intentos por paso. Cada parada queda en la auditoría como `skill.limit`.

### Qué se guarda de una ejecución

Nombre, versión y hash del Skill, estados, intentos, fechas y, de las entradas, solo su SHA-256 y su tamaño (`inputs_manifest`): **nunca** su contenido. Como pregunta de la sesión se guarda una marca `[skill <nombre>/<paso> intento <n>]`, nunca el prompt compuesto. La salida de cada paso se guarda solo con un proveedor sintético (el Mock); con cualquier otro, solo su SHA-256 y su tamaño, y una ejecución interrumpida no se puede reanudar. La propuesta no se guarda: se recalcula. La auditoría lleva la ejecución, el paso, el hash y el resultado, sin texto.

## Skills de arquitectura

Dos Skills en `skills/` (la carpeta por defecto de `HARNESS_SKILLS_DIR`), los dos en una sesión creada con `--project`, que les da el contexto de memoria de ese proyecto:

- **`hls-review`** revisa un documento de diseño de alto nivel: una pregunta con el documento marcado como datos y la memoria del proyecto, y una comprobación de que la respuesta tiene `Resumen`, `Alternativas`, `Restricciones`, `Requisitos no funcionales`, `Supuestos` y `Preguntas pendientes` (como mucho 32 KiB). La revisión sale por stdout. **No escribe nada** y no pide aprobación. Si falta un encabezado, termina `failed` con `validation_failed:required_headings:<encabezado>` y no imprime la respuesta.
- **`architecture-memory`** extrae una decisión de un texto fuente como un único objeto JSON (`title` de 8 a 120 caracteres en una línea; `context` y `decision` de hasta 2000; `alternatives`, `consequences` y, opcional, `assumptions`, de hasta 8 elementos de 400), la valida con un esquema cerrado, prepara la nota, **la muestra entera** con su ruta y su hash, y solo si la apruebas la escribe en el vault.

Con el vault sintético y las respuestas guionizadas del repo, en PowerShell (desde la raíz del repo):

```powershell
$base = Join-Path $env:TEMP "ai-harness-demo"
New-Item -ItemType Directory -Force $base | Out-Null
Copy-Item -Recurse tests\fixtures\vault-synthetic (Join-Path $base "vault")
$env:HARNESS_DATA_DIR = Join-Path $base "data"
$env:HARNESS_VAULT_ROOT = Join-Path $base "vault"
$env:HARNESS_MOCK_RESPONSES = (Resolve-Path tests\fixtures\skill-inputs\respuestas-demo.json).Path
uv run python main.py skill list
$sesion = uv run python main.py session create "Demo" --project demo-alpha
uv run python main.py skill run hls-review --session $sesion --input-file document=tests\fixtures\skill-inputs\hls-corto.md
uv run python main.py skill run architecture-memory --session $sesion --input-file source=tests\fixtures\skill-inputs\fuente-decision.md
uv run python main.py memory context demo-alpha
```

En zsh o bash, lo mismo con `export` y rutas con `/`:

```sh
base="$(mktemp -d)"
cp -R tests/fixtures/vault-synthetic "$base/vault"
export HARNESS_DATA_DIR="$base/data" HARNESS_VAULT_ROOT="$base/vault"
export HARNESS_MOCK_RESPONSES="$PWD/tests/fixtures/skill-inputs/respuestas-demo.json"
sesion="$(uv run python main.py session create "Demo" --project demo-alpha)"
uv run python main.py skill run hls-review --session "$sesion" --input-file document=tests/fixtures/skill-inputs/hls-corto.md
uv run python main.py skill run architecture-memory --session "$sesion" --input-file source=tests/fixtures/skill-inputs/fuente-decision.md < /dev/null   # código 3
uv run python main.py skill resume RUN_ID --input-file source=tests/fixtures/skill-inputs/fuente-decision.md   # en una terminal
```

Qué se ve: `skill list` muestra los dos Skills `1.0.0 valid`; `hls-review` imprime la revisión y termina con 0. `architecture-memory` en una terminal muestra la cabecera de la aprobación (`vault:` con la raíz resuelta del vault, `target: Decisiones/<fecha>-cola-gestionada-para-los-eventos-de-pedidos-f43c794e.md`, `bytes`, `hash`, `expires`) y la nota completa entre dos líneas de guiones; al escribir los 8 primeros caracteres del hash, imprime la nota y `applied: Decisiones/<fecha>-cola-gestionada-para-los-eventos-de-pedidos-f43c794e.md` y termina con 0 (`<fecha>` es el día local en que empezó la ejecución). `n` la cancela (código 1) sin escribir nada. Con stdin redirigido no pregunta: termina con 3 y `skill resume RUN_ID` en una terminal la retoma. Después, `memory context demo-alpha` incluye la nota en la sección de decisiones. Repetir la extracción con el mismo título termina `failed` con `duplicate_decision` y la ruta de la nota existente, sin pedir aprobación. `scripts/demo_architecture_skills.py` recorre los pasos que no necesitan a una persona y comprueba la huella del vault en cada uno.

### Dónde y cómo se escribe una decisión

- **Dónde:** directamente en `Decisiones/` de `HARNESS_VAULT_ROOT`, que es donde el contexto de un proyecto ya busca sus decisiones. La ejecución queda ligada al vault con el que empezó: la cabecera de la aprobación muestra su raíz y el hash la incluye, y si al reanudar `HARNESS_VAULT_ROOT` apunta a otro vault, falla con `vault_changed` sin escribir en ninguno (SQLite guarda solo un resumen SHA-256 de la raíz, nunca la ruta). Si la carpeta no existe, el harness la crea en la primera escritura aprobada, y solo entonces; ningún comando de solo lectura la crea. Si `Decisiones/` es un enlace, una unión, no es una carpeta, sale de la raíz real del vault o solo se diferencia en mayúsculas (`decisiones/`), la ejecución falla con `unsafe_target` antes de pedir aprobación.
- **Nombre:** `YYYY-MM-DD-<slug>-<id8>.md`. La fecha es el día local en que empezó la ejecución (no cambia al reanudar); el slug sale del título (ASCII, minúsculas, `[a-z0-9-]`, como mucho 48 caracteres; `decision` si quedaría vacío o sería un nombre reservado de Windows); `id8` son los 8 primeros caracteres hexadecimales del identificador. El nombre es válido en Windows y en macOS.
- **Identificador:** `decision_id = dec-` + 16 caracteres del SHA-256 del proyecto y del título normalizado (NFKC, sin distinguir mayúsculas, espacios colapsados). El mismo título en el mismo proyecto da el mismo identificador.
- **Frontmatter:** `type: decision`, `decision_id`, `project_slug` (el de la sesión), `status: accepted`, `created`, `updated`, `tags: [decision, <proyecto>]`, `source: ai-harness`, `skill: architecture-memory@1.0.0` y `run_id`. Ningún valor del frontmatter sale del texto del modelo, ni siquiera el título.
- **Cuerpo:** título, `Contexto`, `Decisión`, `Alternativas consideradas`, `Consecuencias`, `Supuestos` («Ninguno declarado.» si no hay) y `Procedencia` (Skill con versión y hash, ejecución, notas de memoria consultadas con su hash, tamaño y hash de la fuente, y número de credenciales enmascaradas). El texto del modelo pasa por el mismo saneado y la misma redacción que lo que se aprueba; una línea suya que empieza por `#` o `---` se escribe con `\` delante, y `<<<`/`>>>` se cambian por `‹‹‹`/`›››`, así que no puede abrir secciones, imitar un frontmatter ni falsificar los delimitadores cuando `memory context` la lea.
- **Inerte en Obsidian:** en todo texto que viene del modelo (y en las rutas de la procedencia), estos caracteres se escriben como entidad HTML, que Obsidian muestra tal cual en la vista de lectura sin que nada los ejecute: `&` → `&amp;`, `<` → `&lt;` (HTML, `<script>`, comentarios `<!-- -->`, Templater `<% %>` y `<%* %>`), `` ` `` → `&#96;` (bloques ```` ``` ```` de `dataview`/`dataviewjs` y código en línea `` `= …` `` y `` `$= …` ``), `~~` → `~&#126;` (bloques `~~~`), `%%` → `%&#37;` (comentarios de Obsidian, ocultos al leer pero que `memory context` devolvería al modelo), `![` → `!&#91;` (imágenes, también remotas, y embebidos `![[…]]`), `[[` → `[&#91;` (enlaces internos, que añadirían enlaces y aristas del grafo hacia notas que elige el modelo) y `::` → `:&#58;` (campos en línea de Dataview). Se escapa, no se borra: al leer la nota ves exactamente lo que escribió el modelo; en el fichero, o en el modo fuente, verás las entidades. **Supuesto que queda:** un plugin que actúe sobre otra sintaxis que no está en esta lista (por ejemplo, un enlace Markdown normal `[texto](url)`, que solo actúa si haces clic) no está neutralizado.
- **Deduplicación:** antes de pedir la aprobación y otra vez justo antes de escribir, el harness busca en `Decisiones/` una nota con ese `decision_id` en su frontmatter. Si existe, falla con `duplicate_decision` y su ruta. **Es una deduplicación débil:** el identificador sale del título, y el título lo elige el modelo; la misma decisión extraída otra vez con otro título (otras palabras, otro orden) da otro identificador y se escribe como nota nueva. Solo detecta el mismo título salvo mayúsculas, espacios y formas Unicode equivalentes. Una decisión equivalente escrita a mano sin `decision_id` tampoco se detecta. **Antes de preguntar al modelo** (revisado el 2026-11-25), el harness mira si ya guardó una decisión de ese proyecto, en ese vault, desde el mismo texto fuente y si su nota sigue en `Decisiones/`: si es así, falla con `duplicate_decision` y su ruta sin enviar nada al proveedor. «El mismo texto» se mide con un SHA-256 calculado sin BOM, con CRLF y CR sueltos como LF y sin los saltos de línea del final (solo para este hash; el texto enviado no cambia); otros espacios u otra forma Unicode cuentan como otro texto. Cuenta toda decisión escrita de verdad: aprobada y aplicada, también si la ejecución se reanudó con `skill resume RUN_ID` sin entradas o si un paso `uncertain` se reconcilió como escrito en `skill resume` o en `skill cancel`; no cuenta una aprobación rechazada o abandonada. Las decisiones guardadas antes de esta versión no tienen ese registro: las encuentra solo la comprobación por título. Para extraer otra decisión del mismo texto, cámbialo.
- **Nunca sobrescribe ni edita:** escribe un temporal oculto (`Decisiones/.harness-<ejecución>-<paso>.tmp`, que la memoria no lee) y lo publica con un enlace duro, que **falla si el nombre final ya existe**; nunca usa una operación que sustituya un fichero. Nunca modifica, mueve ni borra una nota existente. Las escrituras de dos procesos del harness se ordenan con un bloqueo (`locks/vault-decisions.lock` en el directorio de datos): el segundo espera hasta 5 s y, si no le toca, falla con código 1 dejando la aprobación concedida para `skill resume` (con el proveedor Mock, cuyas salidas se guardan). Con un proveedor real, cuyas salidas no se guardan, el harness reintenta en la misma invocación hasta 30 s y, si el escritor sigue ocupado, revoca la aprobación, termina `failed` con `effect_busy` y hay que repetir la ejecución con `skill run`. Por lo mismo, con un proveedor real, si el proceso muere antes de publicar la nota, `skill resume` termina `failed` diciendo que hay que repetir la ejecución; nunca queda una aprobación usable en una ejecución terminada.
- **Si el proceso muere a mitad**, `skill resume` mira el vault sin escribir: si la nota con ese identificador y esos bytes está, termina; si no está, pide una aprobación nueva para los mismos bytes; si hay otra nota con ese identificador, se niega (código 1) y la ejecución queda `uncertain` para que lo mires. Lo mismo si algo falla después de publicar la nota (por ejemplo, no se puede borrar el temporal porque OneDrive o un antivirus lo tiene abierto en Windows): la ejecución queda `uncertain`, nunca `failed`, y `skill resume` lo vuelve a intentar. Mientras el temporal no se pueda borrar, la nota existe pero **la memoria no la lee** (tiene dos enlaces duros), y `skill resume` termina con código 1 nombrando el temporal; cierra el programa que lo retiene y repite `skill resume`. `skill cancel RUN_ID` sobre una ejecución `uncertain` también comprueba el vault primero: borra el temporal propio si puede (así una nota publicada vuelve a ser visible), dice por stderr si la nota está en el vault o si no se escribió nada, y termina la ejecución sin borrar nunca una nota.
- **Qué guarda SQLite:** con un proveedor real, de la nota solo el identificador (`skill_steps.effect_ref`), su SHA-256 y su tamaño; nunca el título, el texto ni la ruta.

Para comprobar en tu vault (por ejemplo, una carpeta de OneDrive) las operaciones de ficheros de las que depende la escritura, sin tocar nada tuyo:

```powershell
uv run python scripts/diag_vault_write.py <carpeta-de-prueba>
```

Crea una subcarpeta nueva dentro de la que indiques, comprueba allí la creación exclusiva, el enlace duro que no sustituye un nombre existente, el número de enlaces, que `fstat` y `lstat` dan el mismo inodo y el borrado del temporal, lo borra todo y escribe un bloque `--- ai-harness diag_vault_write ---` con valores `true`/`false`, recuentos, categorías de error y tiempos, sin rutas ni nombres.

Límites conocidos:

1. El vault tiene que estar en un sistema de ficheros con enlaces duros (APFS, NTFS). En FAT32, exFAT o algunas unidades de red la escritura falla con `write_failed` sin escribir nada.
2. El bloqueo solo ordena a los procesos del harness que comparten directorio de datos. Otro programa (Obsidian, el curador de `claude-memory-system`) puede crear un fichero con el mismo nombre en el mismo instante: el harness no lo sobrescribe, falla con `conflict`. Entre la comprobación de `Decisiones/` y la escritura del temporal, alguien con permiso de escritura en el vault podría cambiar la carpeta por un enlace; el harness lo detecta después de publicar, retira su nota y falla, pero el temporal habrá existido un momento fuera.
3. No se sincroniza el directorio tras publicar: después de un corte de luz justo en ese momento, la nota podría no estar, y `skill resume` lo vería como ausente y pediría aprobarla otra vez.
4. **Riesgo de atribución del curador:** el curador de `claude-memory-system` atribuye a su propia ejecución cualquier `.md` de `Decisiones/` modificado después de que empiece. Si el harness escribe una decisión mientras el curador corre en el mismo equipo, el log del curador la contará como suya. No se pierde ni se rompe nada.

## Puerta MVP sin EA

El flujo completo sin Enterprise Architect: **requerimiento → memoria del proyecto → `hls-review` → tu decisión → `architecture-memory` → aprobación → nota nueva en `Decisiones/` → la nota vuelve en `memory context`**. Son los dos Skills de arriba, por separado y en la **misma sesión**, con tu decisión entre medias: lees la revisión, escribes en un fichero tuyo la decisión que tomas y se la pasas a `architecture-memory` con `--input-file source=<fichero>`. Nada pasa de un Skill al otro sin que lo leas. No hay código nuevo: es la integración de lo que ya existe.

- **Demo automática** (sin persona, salvo la aprobación, que imprime como instrucciones con los comandos exactos para PowerShell y zsh/bash): `uv run python scripts/demo_mvp_without_ea.py`. Termina en `demo: PASS`. Con `--keep` deja la carpeta temporal y la ejecución esperando, para que la apruebes tú en una terminal.
- **A mano**, paso a paso y con qué se ve en cada uno: [`docs/runbook/mvp-without-ea.md`](docs/runbook/mvp-without-ea.md), primero con el vault sintético y el Mock, después con una copia de tu vault.
- **Datos:** los requerimientos sintéticos, la revisión y la decisión guionizadas del Mock y una decisión de ejemplo están en `tests/fixtures/mvp/`. Los tres `requerimiento-<n>-*.md` son también los de la medición con Copilot real (seis preguntas), que queda pendiente del merge del proveedor de Copilot.
- **Test:** `tests/integration/test_mvp_flow.py` recorre el flujo con la CLI: `session create`, `memory context`, `skill status` y `history` en procesos separados, y los dos Skills en proceso con un proveedor guionizado que guarda en memoria lo que recibe (para comprobar que la memoria del proyecto, el requerimiento y tu decisión llegan a la pregunta) y la terminal de prueba del motor para aprobar. También comprueba que repetir `architecture-memory` con el mismo fichero de decisión se rechaza con `duplicate_decision` antes de preguntar al modelo (ningún envío más), que otro texto de la misma decisión del que el modelo saca el mismo título se rechaza después de su respuesta, y que un modelo que obedece las órdenes de un requerimiento no aprueba, no elige carpeta ni proyecto. No dice nada de si Copilot real cumple los formatos.

## Herramientas MCP

El harness puede hablar con servidores MCP locales por stdio, usando el SDK oficial (`mcp==2.3.0`). Tiene tres reglas:

- **Solo arranca los servidores que tú escribes en una lista local.**
- Solo llama a las herramientas que esa lista declara, y solo con los argumentos que declara.
- En este corte **deniega toda herramienta que escribe**.

```powershell
$env:HARNESS_MCP_CONFIG = "C:\ruta\fuera\del\repo\mcp.local.json"   # ruta absoluta
uv run python main.py mcp list
uv run python main.py mcp tools synthetic
uv run python main.py mcp call synthetic get_project_metadata --args '{\"project\": \"demo-alpha\"}'
```

En macOS o Linux se usa `export HARNESS_MCP_CONFIG=/ruta/absoluta/mcp.local.json` y `--args '{"project": "demo-alpha"}'`. En PowerShell 7.3 o posterior, las comillas internas no necesitan `\`.

- `mcp list` lee la lista sin arrancar nada. Muestra cada servidor con `external` y su número de herramientas, y cada herramienta con su operación. Nunca muestra la orden de arranque ni rutas. Sin `HARNESS_MCP_CONFIG`, dice `No MCP servers configured.` y termina con 0.
- `mcp tools SERVIDOR` arranca el servidor, le pide sus herramientas y lo cierra. Escribe una línea por herramienta con:
  - el nombre;
  - la operación declarada, o `-`;
  - el estado: `allowed`, `denied:<motivo>` o `absent` (declarada, pero el servidor no la ofrece);
  - la descripción del servidor, saneada y cortada a 120 caracteres.
- `mcp call SERVIDOR HERRAMIENTA [--args JSON]` hace, en orden:
  1. comprueba la política;
  2. arranca el servidor;
  3. comprueba que el servidor ofrece la herramienta con un esquema compatible;
  4. hace **una** llamada;
  5. cierra el servidor.

  El resultado saneado va por stdout, y **cada línea empieza por `| `** (una línea vacía es `|`). Así ninguna línea de una herramienta puede pasar por una línea del harness; para quedarte con el resultado tal cual, quita los dos primeros caracteres de cada línea. El mensaje de error de una herramienta va por stderr con el mismo prefijo. El resumen va por stderr: `call: <servidor>/<herramienta> <estado> in <ms> ms, <bytes> bytes, <n> credential(s) redacted`.
- Códigos de salida:
  - 0: llamada completada.
  - 1: llamada denegada, error de la herramienta o del servidor, o plazo vencido.
  - 2: error de uso; `--args` no es JSON, no es un objeto o pasa de 16 KiB.
  - 130: interrumpida con Ctrl+C.

### La lista local

La escribes y la editas tú, a mano; el harness solo la lee. Vive **fuera del repositorio**, porque contiene rutas locales. Si la ruta está dentro de un árbol de Git y no está ignorada, el harness la rechaza. En macOS y Linux también rechaza una lista (o el enlace que la nombra, o la carpeta que contiene a cualquiera de los dos) que sea de otro usuario o que el grupo u otros puedan escribir: deja la lista con `chmod 600` y su carpeta sin escritura para otros. En Windows no se comprueban las ACL: protege la carpeta tú. Este ejemplo usa el servidor sintético de los tests:

```json
{
  "format": "ai-harness/mcp/1",
  "servers": {
    "synthetic": {
      "command": ["C:\\ruta\\al\\repo\\.venv\\Scripts\\python.exe", "C:\\ruta\\al\\repo\\tests\\fixtures\\mcp\\synthetic_server.py", "--state", "C:\\ruta\\temporal\\estado"],
      "env": [],
      "startup_timeout_s": 20,
      "call_timeout_s": 30,
      "tools": {
        "get_project_metadata": {
          "operation": "read",
          "max_result_bytes": 65536,
          "arguments": {
            "project": {"type": "string", "max_length": 64, "pattern": "[a-z0-9][a-z0-9-]*", "required": true}
          }
        },
        "set_project_metadata": {"operation": "write", "arguments": {"project": {"type": "string", "max_length": 64}}}
      }
    }
  }
}
```

- `command` es una lista, y su primer elemento es una ruta **absoluta**. No hay shell ni búsqueda en `PATH`. Lo que pase por `--args` nunca llega a la orden de arranque.
- `env` lista **nombres** de variables. El servidor recibe esas variables con el valor que tienen en tu sesión. Recibe también las que cualquier proceso necesita para arrancar, copiadas solo si existen en tu sesión. La lista es la misma en todos los sistemas; las de Windows solo existen allí:
  - de macOS y Linux: `PATH`, `HOME`, `LOGNAME`, `SHELL`, `TERM`, `USER`, `TMPDIR`;
  - de Windows: `SYSTEMROOT`, `WINDIR`, `COMSPEC`, `PATH`, `PATHEXT`, `TEMP`, `TMP`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `HOMEDRIVE`, `HOMEPATH`, `SYSTEMDRIVE`, `USERNAME`, `PROCESSOR_ARCHITECTURE`.

  Además recibe `AI_HARNESS_MCP_CHILD=1` (la marca de recursión). No recibe ninguna otra, tampoco las `HARNESS_*`.
- Tipos de argumento:
  - `string`, con `max_length` obligatorio y `pattern` opcional;
  - `integer`, con `minimum` y `maximum`;
  - `boolean`;
  - `enum`.

  Un argumento que no está declarado se deniega.
- Los plazos van de 1 a 300 s. `max_result_bytes` va de 1 KiB a 1 MiB, y por defecto es 64 KiB. Un campo desconocido o un valor fuera de rango hace fallar la lista entera, y el error nombra el campo.

### Qué se deniega

Antes de arrancar nada, el harness comprueba estos motivos:

- `server_not_allowed`, `tool_not_allowed`;
- `argument_not_allowed`, `argument_missing`, `argument_invalid`;
- `write_requires_approval`;
- los de uso: `args_not_json`, `args_not_object`, `args_too_large`.

Después de preguntar al servidor, comprueba dos más:

- `tool_absent`: el servidor no ofrece la herramienta.
- `schema_mismatch`: el esquema del servidor no tiene un argumento declarado, o exige uno que no está declarado.
- `annotation_conflict`: la lista declara la herramienta `read`, pero el servidor la anota con `readOnlyHint: false` o `destructiveHint: true`.

Lo que el servidor dice de sí mismo (descripción, esquema, anotaciones) solo puede restringir, nunca permitir. De los esquemas del servidor solo se comparan formas (nombres, `required`, tipos); nunca se evalúa un `pattern`, un `format` ni nada parecido que mande el servidor. Un `mcp` lanzado desde dentro de un servidor se niega con `recursion`.

### Plazos y procesos

La conversación con el servidor no corre en el proceso del harness, sino en un **proceso de sesión** (`python -m harness.mcp.worker`) que el harness arranca en su propio grupo de procesos (macOS y Linux) o Job Object (Windows). El servidor arranca dentro de ese grupo. El harness conserva la política, la auditoría y la última palabra:

1. al acabar la conversación, o al vencer su plazo, **siempre** termina el árbol entero del proceso de sesión: el servidor y lo que este haya lanzado en su grupo (SIGTERM, 2 s, SIGKILL; en Windows, el Job Object);
2. anota en la auditoría si vio terminar el árbol (`server_stopped`);
3. atiende Ctrl+C en cualquier momento: termina el árbol y sale con 130.

Dentro del proceso de sesión, el cierre del servidor es: cerrar su entrada, esperar 2 s, matarlo, esperar 2 s.

El plazo de arranque cubre la negociación y la lista de herramientas. El plazo de llamada cubre la llamada. **Garantía**: `mcp tools` y `mcp call` terminan en menos de arranque + llamada + 15 s, haga lo que haga el servidor o el proceso de sesión (aunque se cuelgue en código C sin soltar el intérprete). Al vencer, el error es `timeout` y la llamada queda como `timeout` en la auditoría.

Una respuesta que pasa de `max_result_bytes` se corta mientras llega: el error es `result_too_large` y no se imprime nada del resultado. Una línea que no es JSON-RPC termina la sesión con `protocol_error`.

Un servidor que escribe en stderr más de 64 MiB antes de terminar de contestar se detiene con `stderr_too_large`; si la respuesta ya había llegado, vale, el servidor se detiene igual y el comando avisa. Si algo del stderr del servidor no llegó a su log, el comando avisa de cuántos bytes faltan; la última línea del log dice por qué. Un error JSON-RPC que el propio servidor envía es `server_error`; una conexión que se cierra es `server_exited`.

El harness no abre ningún socket que acepte conexiones de otros: habla con el servidor por los tubos que él mismo crea. En Windows, al arrancar, el bucle de eventos de Python crea su par de sockets interno escuchando un instante en `127.0.0.1` con un puerto efímero; acepta una sola conexión, comprueba que es la suya y cierra esa escucha. Los tests lo distinguen de cualquier otro socket por la pila de llamadas, no por la dirección; el detalle y lo que no prueban está en `SECURITY.md` (revisado el 2026-11-25).

Límite: un proceso que el servidor lance en **otra sesión o grupo** (`setsid`, un demonio) o fuera del Job Object escapa a ese cierre, y el harness no lo ve: la auditoría dirá igualmente `server_stopped = 1`.

### Qué se guarda

- La tabla `tool_calls` de SQLite guarda:
  - servidor, herramienta y operación;
  - decisión y motivo;
  - un HMAC-SHA-256 de los argumentos, con una clave aleatoria local (`HARNESS_DATA_DIR/keys/mcp-args.key`, nunca se imprime; en macOS y Linux el fichero es `0600` y su carpeta `0700`; en Windows el harness no fija ninguna ACL y el fichero hereda los permisos de la carpeta donde esté `HARNESS_DATA_DIR`), y su tamaño;
  - estado, código de error y si el servidor quedó parado;
  - bytes del resultado y duración.

  **Nunca** guarda los argumentos ni el resultado.
- El stderr del servidor va a `HARNESS_DATA_DIR/logs/mcp/<servidor>.stderr.log`, nunca a la terminal. Se guarda línea a línea, con las credenciales de formato conocido sustituidas por `[REDACTED:<tipo>]` antes de escribirse (revisado el 2026-11-25), aunque un token llegue partido en varias lecturas. Una línea termina en LF, CRLF o un CR suelto (una barra de progreso). Una línea de más de 16 KiB no se redacta por partes: se descarta entera y en su lugar queda una marca que lo dice, así que una credencial en ella no llega al log, pero el resto de la línea tampoco. Una clave privada PEM se sustituye por una marca y se descartan las líneas siguientes hasta su línea END; si END no llega en 32 KiB, una marca lo dice y el log sigue en la línea siguiente. Lo que **no** cubre: una credencial de formato desconocido; una clave de más de 32 KiB; una credencial cuyo comienzo se tragó otra (una clave de Anthropic o de Slack que acaba en la cabecera de un JWT deja en claro el resto del JWT); y si el harness mata el proceso de sesión al vencer su plazo, la última línea sin final y el recuento se pierden. Cada sesión escribe como mucho 1 MiB, entrega al log como mucho 65 536 líneas (un CRLF es una) y pasa a la redacción como mucho 4 MiB; la primera línea que pasaría cualquiera de los tres no se escribe, ni nada después, y una línea final anota cuántos bytes del stderr no están en el log de ninguna forma y por qué. Así, una ráfaga de líneas vacías o de CR (64 KiB de saltos) termina el log para el resto de la sesión. Las secuencias de escape de la terminal (colores, títulos) se quitan de cada línea antes de redactarla, para que una credencial pegada a un color no se escape (revisión de seguridad del 2026-11-27); el resto de caracteres de control se guarda como lo escribió el servidor. Un fallo del propio registro no corta la sesión ni escribe nada sin redactar: el log dice dónde se paró, salvo si lo que falla es escribir en el log. Una cadena hecha a mano de más de cuatro credenciales pegadas puede dejar las primeras en claro. Antes de cada sesión, un fichero de más de 1 MiB pasa a `.1` (que sustituye al anterior), así que los dos ficheros de un servidor no pasan de unos 4 MiB. En macOS y Linux la carpeta es `0700` y los ficheros `0600`.
- Una llamada `running` cuyo comando ya no existe (se cortó la luz, se mató el proceso) se marca `failed`/`interrupted` en el siguiente `mcp call`. "Ya no existe" lo dice un bloqueo que el comando mantiene mientras vive, no la antigüedad de la fila.
- Todo lo que se imprime (resultado, descripciones, nombres y errores del servidor) sale sin caracteres de control, de formato ni secuencias de escape. Las credenciales conocidas salen como `[REDACTED:<tipo>]`. Imágenes y audio se sustituyen por `[<tipo> withheld: N bytes of base64]`, y los recursos por `[<tipo> withheld]`.

### Un plan de lecturas: `/plan`

En la rama `feature/code-mode-plan` (sin merge, 2026-11-27; `openspec/changes/code-mode/`, tramo 2). En la conversación escribes `/plan <pregunta>`; fuera de ella, `uv run python main.py plan SESSION_ID "<pregunta>"`, que necesita una terminal interactiva y, sin ella, no envía nada. `/plan` se escribe entero: `/pla` o `/p` no lo abren.

1. El harness manda **una** pregunta: primero sus instrucciones (la gramática del plan, un ejemplo y un nonce nuevo), después el catálogo de las herramientas `read` de tu lista local (una línea cada una, con los argumentos declarados y la `description` que tú escribas, una línea de 120 caracteres como mucho), la memoria del proyecto como datos y tu pregunta. Nada de lo que dice un servidor entra en el catálogo. `/context` muestra ese bloque. Si no cabe en el límite del proveedor, no se envía nada.
2. Si la respuesta no trae un bloque `json` con un plan, es la respuesta y no pasa nada más. Si lo trae y no es válido (una escritura, una herramienta o un servidor fuera de la lista, dos bloques, otro nonce, un campo desconocido…), se dice el motivo y no se ejecuta nada; nunca se vuelve a preguntar solo. Una respuesta incierta, fallida o truncada no se lee.
3. Si el plan es válido, la caja de aprobación lo muestra paso a paso (servidor, herramienta, argumentos canónicos, decisión de la política y qué lee). Una línea por servidor recuerda que la orden que lo arranca sale de tu lista local y no forma parte de lo aprobado. Solo se ejecuta el plan de la caja: lo que la respuesta pinte encima no cuenta. Se aprueba con el botón en la pantalla completa y con el código tecleado en `--plain` y en la CLI; Ctrl+C en el aviso del código no aprueba nada, aunque después se teclee el código (la CLI sale con 130). La aprobación caduca (`HARNESS_APPROVAL_TTL_S`), vale una vez y solo para ese plan, esa pregunta y esa sesión.
4. Los pasos se ejecutan en orden por la misma pasarela que `mcp call`, con la política decidida otra vez en ese momento. El primero que falla detiene el plan. El plan entero tiene un plazo (la suma de los plazos de arranque y de llamada de sus pasos más 10 s, 300 s como mucho; así un paso que agota el suyo termina como `timeout` de ese paso) y Ctrl+C lo para, también a mitad de un paso. Un plan parado no se vuelve a ejecutar.
5. Cada resultado se muestra como texto de fuera del harness, saneado (en la CLI, por stdout y con cada línea tras `| `, como en `mcp call`; la respuesta del modelo también), con las credenciales enmascaradas y 256 KiB como mucho entre todos. **Solo lo ves tú: no vuelve al proveedor.**

Se guarda una fila por plan en `plan_runs` (su hash, el de la aprobación, el estado, el paso donde paró y cómo se aprobó) y, en `tool_calls`, cada paso con el `plan_id` y su posición. Como en `mcp call`, sin argumentos ni resultados.

## Configuración

Por variables de entorno (ver `.env.example`):

| Variable | Por defecto | Para qué |
|---|---|---|
| `HARNESS_DATA_DIR` | `./data` | Dónde viven SQLite, los bloqueos, la clave de los HMAC de MCP (`keys/`), los logs de stderr de los servidores MCP (`logs/mcp/`) y, con Copilot, el perfil dedicado de Edge (`edge-profile/`) y `copilot/`. En macOS y Linux, lo que el harness crea ahí (la carpeta y las que le falten por encima, la base y sus `-wal`/`-shm`, `locks/` y sus ficheros, `copilot/login.json`) es solo de su dueño (`0700`/`0600`); lo que ya existía conserva sus permisos. En Windows esos modos no se usan: lo creado hereda los permisos de la carpeta y el harness no fija ninguna ACL. Debe ser un **disco local**: en una unidad de red los bloqueos de fichero no son fiables. No puede estar dentro de `HARNESS_VAULT_ROOT`. |
| `HARNESS_PROVIDER` | `mock` | Proveedor de las sesiones nuevas: `mock` o `copilot_web`. |
| `HARNESS_REQUEST_TIMEOUT_S` | `120` | Plazo de cada pregunta. Con Copilot cubre todo: esperar el navegador, arrancarlo, enviar y recibir la respuesta. La sonda propone un valor. |
| `HARNESS_DEEP_REQUEST_TIMEOUT_S` | el triple de `HARNESS_REQUEST_TIMEOUT_S` | Plazo de una pregunta en modo `deep` (`/mode deep`, `ask --mode deep`), que razona antes de responder. No puede ser menor que `HARNESS_REQUEST_TIMEOUT_S`. Los estados no cambian: `timeout` si vence antes de enviar, `uncertain` después, sin reenvío. El triple es una cota sin medir: la sonda no envía en `deep`. Un paso de Skill conserva su propio plazo. |
| `HARNESS_COPILOT_URL` | (vacía) | Dirección del chat de Copilot, la que se abre para una conversación nueva. Solo en tu `.env` local. |
| `HARNESS_EDGE_PROFILE` | `HARNESS_DATA_DIR/edge-profile` | Carpeta del perfil dedicado de Edge. Nunca la de tu Edge personal: el harness la rechaza. |
| `HARNESS_COPILOT_READY_TIMEOUT_S` | `60` | Cuánto esperar a que el chat esté listo antes de rendirse sin enviar nada. |
| `HARNESS_COPILOT_MAX_PROMPT_CHARS` | el máximo medido | Solo puede bajar el máximo que midió la sonda. |
| `HARNESS_MOCK_BEHAVIOR` | `ok` | `ok`, `fail`, `timeout_before_send` o `timeout_after_send`. Solo para pruebas y demos. |
| `HARNESS_MOCK_DELAY_MS` | `0` | Espera del Mock después de enviar. Sirve para interrumpir una pregunta a mitad. |
| `HARNESS_VAULT_ROOT` | (vacía) | Ruta **absoluta** del vault. Solo la leen `memory …` y `ask --project`; si falta o no es un directorio, esos comandos terminan con error sin leer nada. |
| `HARNESS_MEMORY_CONTEXT_MAX_BYTES` | `8192` | Tamaño máximo, en bytes UTF-8, del bloque de contexto (de 1024 a 65536). |
| `HARNESS_SKILLS_DIR` | `skills/` del repo | Ruta **absoluta** de la raíz de Skills. |
| `HARNESS_APPROVAL_TTL_S` | `900` | Caducidad de una aprobación, en segundos (de 60 a 3600). |
| `HARNESS_CONCISE_ANSWERS` | `off` | `off` (por defecto, también vacía) u `on`. Con `on`, cada pregunta suelta (`ask` y las preguntas de `chat`) empieza con un aviso fijo del harness que pide responder breve: primero la respuesta, sin preámbulo, sin repetir la pregunta, sin resumen ni ofrecimientos al final, listas solo si el contenido es una lista. Cuando está activo cuesta 246 caracteres (55 tokens `o200k_base`) por pregunta y cuenta en el límite de tamaño del proveedor; su ahorro en la respuesta no está medido con Copilot real, y por eso va desactivado por defecto. `memory context` y `/context` lo muestran antes del bloque de memoria. No va en los pasos de los Skills, cuya plantilla fija la forma de la respuesta. Cualquier otro valor es un error. |
| `HARNESS_MOCK_RESPONSES` | (vacía) | Ruta absoluta de un JSON (objeto texto → respuesta, hasta 1 MiB) con respuestas guionizadas del Mock: responde con la primera clave, en orden alfabético, contenida en el prompt. Solo para pruebas y demos. |
| `HARNESS_MCP_CONFIG` | (vacía) | Ruta **absoluta** de la lista local de servidores MCP, fuera del repositorio. Sin ella no hay servidores. |

## Estados de una solicitud

| Estado | Qué significa |
|---|---|
| `completed` | El proveedor respondió. |
| `failed` | El proveedor informó de un error. |
| `authentication_required` | Copilot pidió iniciar sesión; no se envió nada. La sesión queda igual hasta la siguiente pregunta completada. |
| `timeout` | Venció el plazo **antes** de que el prompt saliera. No llegó a ningún sitio. |
| `uncertain` | Venció el plazo o murió el proceso **después** de que el prompt saliera. Pudo haber llegado. |

El harness nunca reenvía una solicitud por su cuenta. Una solicitud `uncertain` se queda así en el historial; si repites la pregunta, es una solicitud nueva. La sesión aparece como `uncertain` hasta que la siguiente pregunta se completa.

Una sesión de Copilot queda `closed` cuando su conversación remota ya no se encuentra: no acepta más preguntas (crea una sesión nueva). Si una pregunta queda `uncertain`, la siguiente avisa si la conversación tiene más turnos de los completados: la pregunta incierta pudo llegar, y su respuesta está en Edge.

Solo una pregunta a la vez por sesión: una segunda pregunta mientras la primera sigue en curso se rechaza. Sesiones distintas sí pueden preguntar a la vez.

## Qué se guarda

- SQLite en `HARNESS_DATA_DIR/harness.sqlite3`, sin cifrar.
- El texto de prompts y respuestas se guarda solo si el proveedor declara que su contenido es sintético (el Mock). Con cualquier otro proveedor se guardan la solicitud, su estado y sus fechas, sin el texto.
- La auditoría registra qué pasó y cuándo, nunca el texto.
- De cada decisión que `architecture-memory` escribe de verdad, SQLite (tabla `effect_sources`) guarda su identificador, el resumen SHA-256 de la raíz del vault, el proyecto y el SHA-256 del texto fuente normalizado; la ejecución guarda esos mismos hashes desde que empieza. Nunca el texto, el título ni la ruta (ver [Skills de arquitectura](#skills-de-arquitectura)).
- El stderr de cada servidor MCP, redactado, en `HARNESS_DATA_DIR/logs/mcp/` (ver [Herramientas MCP](#herramientas-mcp)).

## Desarrollo

- Flujo OpenSpec personalizado: `openspec/config.yaml` lleva el contexto y las reglas por artefacto.
- Git flow: ramas `feature/<change>` desde `develop`.
- El repositorio es público: lee [`SECURITY.md`](SECURITY.md) y activa el hook una vez por clon con `git config core.hooksPath .githooks`.
- Sin código condicionado por plataforma fuera de Enterprise Architect: lo que pasa en macOS es lo que corre en Windows.
- Copilot Web (Corte 2): perfil dedicado de Edge, login manual, sonda y uso real en [`docs/runbook/copilot.md`](docs/runbook/copilot.md).
- Puerta local antes de un merge: `scripts/verify.sh` sobre el árbol limpio.
- Demos, iguales en macOS y Windows (PowerShell incluido): `uv run python scripts/demo_session_core.py` (Corte 1), `uv run python scripts/demo_copilot_provider.py` (Corte 2, proveedor de Copilot contra el chat sintético), `uv run python scripts/demo_project_memory.py` (Corte 3), `uv run python scripts/demo_skill_engine.py` (Corte 4, motor de Skills), `uv run python scripts/demo_architecture_skills.py` (Corte 4, Skills de arquitectura), `uv run python scripts/demo_mcp_gateway.py` (Corte 5, pasarela MCP), `uv run python scripts/demo_mvp_without_ea.py` (Puerta MVP sin EA) y `uv run python scripts/demo_interactive_shell.py` (Corte 9, conversación). Terminan en `demo: PASS`.
