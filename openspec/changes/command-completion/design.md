# Design

## Context

La conversación tiene un núcleo (`harness/shell/conversation.py`) que corre en su propio hilo, con su propia conexión SQLite, y dos pantallas: el texto plano y la pantalla completa de Textual (`shell-tui`). El núcleo lee una línea, la analiza (`harness/shell/parser.py`) y la ejecuta. Hasta este change había dos listas de comandos escritas a mano (`COMMANDS` en el analizador y el texto de `/help`), y el completado era `complete()` en `completion.py`: Tab con la lista cerrada, el nombre de un comando, el número de `/resume`, el nombre de un Skill o una ruta de `/file`, sin nada a la vista. Motivación: proposal.md, «Why».

### Qué hacen otras herramientas (consultado el 2026-11-27)

- **Claude Code**, `https://code.claude.com/docs/en/interactive-mode`: `/` abre la lista de comandos con su descripción y se filtra al escribir; Tab completa; `@` abre la búsqueda de ficheros. En la pantalla completa ninguna fila está elegida al abrir la lista, así que Intro envía lo escrito; las flechas eligen y Tab o Intro ponen la elegida. Es el modelo que se adopta (D4).
- **Codex CLI**, `openai/codex`, commit `6bf1e3e68765`: `codex-rs/tui/src/bottom_pane/command_popup.rs` (lista de comandos bajo la entrada, filtrada por principio), `file_search_popup.rs` (búsqueda de ficheros *fuzzy* y asíncrona, tras `@`) y `popup_consts.rs` (`MAX_POPUP_ROWS = 8`). De ahí la altura de 8 filas y el listado fuera del hilo de la pantalla.
- **OpenCode**, `https://opencode.ai/docs/tui`: `/` lista los comandos y escribir filtra; `@` busca ficheros. Confirma el patrón; nada propio que copiar.

Ninguna de las tres convierte una forma corta en otro comando sin enseñarlo: Claude Code y Codex ejecutan lo que se ve. De ahí la regla de D3: lo que se ejecuta se ve entero antes.

### Premisas leídas en el Textual instalado (8.2.8, `.venv/lib/python3.14/site-packages/textual/`, 2026-11-27)

- `widgets/_input.py:976`: toda edición de teclado o pegado pasa por `Input.replace`; `insert_text_at_cursor` (`:833`) también. `_watch_value` (`:543-555`) publica `Input.Changed` también cuando un programa pone `value`. Para saber si un cambio lo escribió la persona hace falta marcarlo en `replace`, no en `Changed`.
- `_input.py:265`: `selection` es reactiva y `cursor_position` (`:256-261`) es una propiedad sobre ella; mover el cursor dispara `watch_selection`.
- `_input.py:743-754`: `Input._on_key` inserta las teclas imprimibles y llama a `prevent_default()`. Por la MRO (`message_pump.py`), el `_on_key` de una subclase corre antes y puede quedarse la tecla.
- `app.py:3966-3985` y `:4136`: los atajos con prioridad se comprueban **cuando la aplicación recibe la tecla**, antes de entregarla al widget con el foco. Medido en la prueba PTY (tarea 4.8): con `tab` como atajo con prioridad, `"/new demo-a\t"` escrito de una vez completaba sobre un valor en el que aún no estaban las teclas anteriores. Por eso Tab se atiende en `PromptInput._on_key`, en el orden de las teclas.
- `widgets/_option_list.py:108, 196, 264`: `OptionList(markup=False)` dibuja `Content` sin interpretar marcado; `highlighted` puede ser `None` (ninguna fila elegida). Con `can_focus=False` en la clase, la lista nunca toma el foco y las teclas siguen en la entrada.
- `worker.py:284-326`: un *worker* de hilo (`run_worker(thread=True)`) corre en el *executor* por defecto del bucle (`run_in_executor(None, …)`), y `asyncio.run` espera a esos hilos al terminar. **Revertido** tras la revisión independiente del 2026-11-27: un listado atascado en una carpeta muerta retenía la salida (8,87 s medidos con un listado de 8 s) y cada tecla dejaba otro hilo atascado. El listado va ahora en hilos *daemon* propios (D2).
- `message_pump.py:882-885`: `post_message` desde otro hilo usa `call_soon_threadsafe` y no espera; un hilo de listado nunca se queda colgado de una pantalla que ya no está (`call_from_thread`, `app.py:1788`, sí espera al resultado).
- `app.py:2895`: `push_screen` no quita el foco a la entrada de debajo; la lista se cierra a mano al abrir una pantalla encima.

## Goals / Non-Goals

**Goals:** escribir las órdenes de siempre con muchas menos teclas, ver los comandos y sus valores sin `/help`, y que nada de eso pueda enviar, ejecutar, leer un fichero o dejar pasar texto ajeno como cromo.

**Non-Goals:** menciones `@`, herencia de proyecto en `/new`, texto fantasma, Tab en `--plain`, entradas de la paleta derivadas de la tabla.

## Decisions

### D1 · Una sola tabla de comandos

- **Qué:** `harness/shell/commands.py` declara cada comando (`CommandSpec`): nombre, mínimo y máximo de argumentos, uso, resumen, qué completa cada posición (`PROJECT`, `PROJECT_OR_NAME`, `SESSION`, `SKILL`, `SKILL_INPUT`, `PATH`, `TEXT`), sus opciones (`--project`, `--file`) y su forma corta. `COMMANDS` del analizador, el texto de `/help` y los candidatos de la lista salen de ella. `resolve_name` da el comando de un nombre entero o de un principio que solo tiene un comando.
- **Por qué:** con dos listas a mano, la tercera (la del completado) habría sido otra fuente de desacuerdo. Una tabla declarativa se prueba de una vez (`test_the_parser_and_help_read_the_one_table`, `test_slash_lists_every_command_of_the_one_table_with_its_summary`).
- **Alternativas rechazadas:**
  - Derivar la lista del texto de `/help` con expresiones regulares: frágil y al revés (la ayuda es la salida, no la fuente).
  - `argparse` por comando: obliga a reescribir el analizador y cambia sus mensajes de error, que las pruebas fijan.
- **Impacto:** `parser.py`, `conversation.py` (`HELP = help_text()`), `completion.py`. Las pruebas del analizador no cambian. La paleta (`COMMAND_ENTRIES` de `tui.py`) sigue a mano: fuera de alcance.

### D2 · La lista de completado: candidatos, orden, datos y rutas

- **Qué:**
  - `suggest(texto antes del cursor, datos)` es puro: decide la palabra que se completa y sus candidatos (`Item`: lo que se inserta, una ayuda corta, el tipo). Una línea que no empieza por `/`, `//`, una comilla o un salto de línea no completa nada.
  - Orden (`rank`): primero los que empiezan así, sin distinguir mayúsculas; después los que contienen las letras en orden, por tramo más corto, inicio más temprano y posición original. Una pasada lineal, como mucho `MAX_ITEMS = 50`.
  - Datos (`CompletionData`): una foto que hace el núcleo, en su hilo (no en el de la pantalla), en cada lectura de línea: proyectos (carpetas de `vault/projects` con nombre seguro y que no son enlaces, hasta 500), Skills válidos con su descripción y sus entradas (hasta 100) y las últimas 100 sesiones, leídas con `LIMIT ?` (`recent_sessions`), no la tabla entera. Cargar 100 Skills cuesta 20 ms (medido el 2026-11-27 con 100 copias de `hls-review`), así que no tienen caché. La pantalla la recibe con `bind_completion`, que entra en las llamadas permitidas al núcleo (`CORE_CALLS`).
  - Rutas (`list_folder`): `os.scandir` de la carpeta escrita, relativa a la carpeta de trabajo; `~` ofrece `~/` y `~/` lista la carpeta personal sin cambiar el texto. Para cada entrada solo se mira el nombre y si es enlace (`is_symlink()` o `is_junction()`) o carpeta (`is_dir(follow_symlinks=False)`): nunca se abre ni se sigue. Nombres ocultos solo si lo escrito empieza por `.`. Tope de 100 000 entradas y 0,5 s; un error del sistema da una lista vacía sin mensaje. Carpetas primero, luego ficheros, luego el orden de `rank`.
  - Lo que se ofrece: cada valor (ruta, proyecto, Skill, entrada, identificador de sesión) pasa por `one_word`: se ve tal cual (`terminal_safe`), no tiene ningún carácter `isspace()` (también NBSP, U+202F, U+3000, U+2000–200A), ni comillas, ni empieza por `-`, y el analizador lo lee como exactamente esa palabra (`split_words(texto) == [texto]`). Hasta la revisión independiente del 2026-11-27 solo se rechazaban el espacio y la comilla: un fichero `" z.md"` adjuntaba `z.md`, y `a<NBSP>--file<NBSP>focus=.env` se convertía en una opción más que leía `.env`. Inserción y ayuda se cortan a 120 y 60 caracteres. Cada fila es `Content.assemble((texto, ""), (ayuda, "dim"))` en una `OptionList(markup=False)`: nunca marcado.
  - La lista (`SuggestionList`): no enfocable, 8 filas de candidatos (más el borde), sobre la entrada, con un título fijo que dice las teclas. Su estilo vivió en su `DEFAULT_CSS`, con cuentas de celdas, hasta integrar `tui-spacing` y `reply-rendering` (2026-11-27). Desde entonces está en el CSS de la aplicación (`#suggestions`), porque el `DEFAULT_CSS` de un widget no ve las variables que declara la aplicación: márgenes laterales `$edge`, relleno `$inset`, marco `$picker-frame`, fondo `$box-fill`, título `$chrome-muted` y `width: 100%`, igual que la entrada. El margen inferior no es un hueco de la escala: son las filas que ocupa la entrada bajo la lista (4; 3 en una pantalla `-short`, donde la entrada tiene 2 filas). En una pantalla `-short` la entrada solo tiene la raya de arriba, así que la vista previa de D3 va en su título y no en su borde inferior. Medido con `Pilot` en 80 × 24 (panel lateral oculto), 100 × 30 y 120 × 40: el borde inferior de la lista coincide con la primera fila de la entrada, con la misma columna y el mismo ancho.
  - En la pantalla, el listado de una carpeta va en hilos *daemon* propios (`FolderLister`), como mucho `MAX_LISTERS = 2` vivos: uno puede quedar atascado en una carpeta muerta mientras otro atiende lo escrito después. Una petición que los encuentra ocupados espera en un único hueco, donde la sustituye cualquier petición más nueva. La respuesta vuelve con `post_message`; cada petición lleva un número de generación y una respuesta vieja, o que llega con una pantalla encima o recorriendo bloques, se tira. Salir no espera a esos hilos. Antes de la revisión independiente iba en `run_worker(thread=True)` (Premisas, revertido).
- **Por qué:** la foto evita tocar SQLite desde el hilo de la pantalla (el núcleo es dueño de su conexión) y deja a `suggest` sin E/S salvo las carpetas. 50 000 entradas se listan en 0,12 s y 20 000 en 0,05 s (medido el 2026-11-27, macOS arm64, `test_a_folder_of_fifty_thousand_entries_is_listed_in_bounded_time`); el tope de 100 000 entradas y el hilo aparte hacen que escribir no se pare aunque la carpeta sea enorme o lenta.
- **Alternativas rechazadas:**
  - Consultar la base de datos al escribir: otra conexión desde otro hilo, y una carrera con el núcleo.
  - `widgets.Select` o un `Autocomplete` de terceros: el primero toma el foco; lo segundo es una dependencia nueva.
  - Seguir enlaces para saber si son carpetas: un enlace podría llevar fuera de la carpeta o a un dispositivo; un nombre basta.
  - Contar notas del vault: no hace falta para completar; solo se listan carpetas de proyecto, así un vault de miles de notas cuesta lo mismo.
- **Impacto:** `completion.py` (reescrito), `conversation.py` (`_completion_data`), `terminal.py` (`ShellState.completion`), `tui.py` (`SuggestionList`, `PromptInput`). Requisitos «Lista de completado bajo la entrada», «Candidatos ajenos dibujados literalmente», «Completar no envía, no ejecuta ni lee ficheros» y «Listar una carpeta no detiene la escritura».

### D3 · Formas cortas y lo que se ejecuta, a la vista

- **Qué:**
  - El núcleo analiza cada línea con `parse_short` (acepta un nombre cortado si es único; si no, `LineError` con los candidatos) y la convierte con `expand` (`shortforms.py`) usando solo datos del harness: si una palabra es una carpeta de proyecto y qué entradas declara un Skill.
  - `/new SLUG` → `/new --project SLUG` si el primer argumento no empieza por `-` y es un proyecto. `/skill NOMBRE RUTA` → `/skill NOMBRE --file ENTRADA=RUTA` si hay exactamente una palabra suelta (sin `=`, sin `-`, que no es el valor de `--file`), el Skill declara una sola entrada y esa entrada no se ha dado ya.
  - Si el comando que resulta no es el que daría el analizador estricto (`parse_line`) con la línea tal cual, el núcleo escribe `running: <comando entero>` (saneado) antes de ejecutarlo. Un comando escrito entero no se repite.
  - En la pantalla completa, `preview_of` calcula lo mismo con la foto de D2 y lo pone en el borde inferior de la entrada mientras se escribe (`border_subtitle`, saneado y cortado a 300 caracteres).
  - `/resume ID`: un argumento que no es un número es un identificador: el entero, o un principio de 8 caracteres o más que solo tiene una sesión. Los 8 primeros caracteres de un UUIDv7 son su hora: dos sesiones del mismo minuto pueden compartirlos, y entonces el error lo dice.
  - `~/` al principio de una ruta de `/file` o `--file` es la carpeta personal.
- **Por qué:** una forma corta cambia lo escrito; la regla de Wilson es que lo que se ejecuta se vea entero antes. El eco del núcleo sirve a los dos modos y queda en la conversación; la vista previa de la pantalla llega antes de Intro.
- **Alternativas rechazadas:**
  - Expandir en la entrada (reescribir lo escrito al pulsar Intro y pedir otro Intro): dos pulsaciones para cada orden corta y una entrada que cambia bajo los dedos.
  - Que `/new` herede el proyecto de la sesión: cambia lo que hace hoy `/new` sin argumentos y una prueba existente; decisión de Wilson.
  - Decidir la forma corta por el contenido de un fichero o una respuesta: nunca; solo datos del harness.
- **Impacto:** `parser.py`, `shortforms.py`, `conversation.py`, `tui.py`. `tests/unit/test_shell_skills.py` cambia una línea (proposal, «Impact»). Requisitos «Nombre de comando cortado», «Formas cortas de /new y /skill», «Lo que se ejecuta se ve entero antes» y «Reanudar por identificador».

### D4 · Teclas: el orden de precedencia

- **Qué:** con la lista abierta, la entrada atiende primero Esc, ↑, ↓, Intro y Tab en su `_on_key`; el resto, como antes.

  | Tecla | Lista abierta | Lista cerrada | Caja de aprobación / paleta / selector |
  |---|---|---|---|
  | Tab | pone la fila elegida o la primera | pone el primer candidato | la de la caja (foco de botones) |
  | ↑ / ↓ | eligen fila | historial de lo escrito | las de la caja |
  | Intro | con fila elegida: la pone, no envía; sin fila: cierra y envía | envía | las de la caja |
  | Esc | cierra la lista | recorre los bloques | la de la caja |
  | letras, borrar, pegar | se escriben y la lista se filtra | se escriben | las de la caja |
  | ctrl+c, ctrl+q, ctrl+n, ctrl+p | lo de siempre (atajos con prioridad de la aplicación); la paleta cierra la lista (es una pantalla encima); `ctrl+n` no toca lo escrito ni su lista | lo de siempre | lo de siempre |

  La lista no se abre con otra pantalla encima (`_covered`), y abrir una la cierra. Un valor puesto por un programa (historial, paleta, «insert:», el envío) cierra la lista; solo lo escrito la abre. Lo escrito se marca en `replace` (`_typed`): con teclas que llegan de una vez, la lista sigue a la última.
  Tab compara la lista con el texto antes del cursor; si la lista es de un texto anterior (teclas aún sin procesar), la calcula otra vez.
- **Por qué:** ninguna fila elegida al abrir hace que Intro nunca cambie lo que la persona quería enviar (Claude Code). Esc cierra la lista antes de recorrer bloques, para que la tecla de «salir de esto» quite lo último que apareció.
- **Alternativas rechazadas:**
  - Primera fila elegida al abrir (Codex): Intro pondría un candidato en vez de enviar, y una pregunta que empieza por una palabra de la lista cambiaría.
  - Tab como atajo con prioridad (lo que había): se ejecutaba antes de que llegaran las teclas escritas justo antes (Premisas; prueba PTY de la tarea 4.8).
- **Impacto:** `tui.py`. Requisitos «Teclas de la lista y su orden» y «La lista nunca sobre otra pantalla».

### D5 · Texto plano sin Tab

- **Qué:** `--plain` acepta las mismas formas cortas (D3, en el núcleo), sin lista ni Tab.
- **Por qué:** el CPython de Windows no trae el módulo `readline`; en macOS es `libedit`, con otra sintaxis para ligar Tab (`bind ^I rl_complete` frente a `tab: complete`); y la conversación lee en un hilo auxiliar, donde `readline` no se puede usar tal cual. Hacerlo exigiría ramas por plataforma, que `config.yaml` prohíbe fuera de EA, o una dependencia nueva (`pyreadline3`).
- **Alternativas rechazadas:** `readline` solo donde exista (rama por plataforma); `prompt_toolkit` (dependencia nueva, y fue lo que `shell-tui` sustituyó).
- **Impacto:** ninguno en código; README lo dice.

## Risks / Trade-offs

- [Un nombre de fichero hostil (escape, `[bold]`, invisible) en la lista] → no se ofrece si no se ve tal cual; lo que se ofrece se dibuja sin marcado (`test_hostile_names_are_never_offered`, `test_a_hostile_name_is_drawn_and_inserted_literally`; M1, M2).
- [Un título de sesión o una descripción de Skill que imita el cromo] → saneado, de una línea, acotado y en gris, siempre a la derecha de un candidato que pone el harness (`test_a_title_in_the_list_is_one_clean_bounded_line`; M3).
- [Una carpeta enorme o lenta (red, 50 000 entradas)] → hilo aparte, tope de entradas y de tiempo, respuestas viejas tiradas (M6, M7, M8).
- [Una carpeta muerta (montaje de red caído) que nunca contesta] → hilos *daemon* propios, como mucho 2, y salir no los espera (M27, M28).
- [Un nombre que el analizador parte o lee como opción] → solo se ofrece lo que se lee como una sola palabra (M2, M24, M25, M26).
- [Teclas de una misma escritura que la lista no ha visto, con Tab o Intro] → Tab calcula otra vez; Intro con la lista desfasada envía lo escrito (M14, M29). Un clic en una fila solo la elige (`OptionList._on_click` la resalta y publica `OptionSelected`, que nadie atiende): el que pone algo es Tab o Intro, con la misma comprobación.
- [Un enlace a un dispositivo o fuera de la carpeta] → nunca se sigue ni se abre (M4, M22).
- [La forma corta ejecuta algo distinto de lo que se esperaba] → solo con datos del harness, `running:` antes, vista previa en la pantalla; una ambigüedad es un error que no ejecuta nada (M15, M16, M17, M18).
- [La vista previa puede no coincidir con el eco] → la pantalla usa la foto de la última lectura de línea; si un proyecto o un Skill cambia entre medias, manda el eco del núcleo, que se calcula al ejecutar. Límite aceptado.
- **Límites que no se arreglan:**
  - Nombres con espacios o comillas no se ofrecen (se escriben a mano, entre comillas).
  - Una sesión no puede llamarse con `/new NOMBRE` igual que un proyecto: se toma como proyecto (para eso, `/new --project` o un nombre distinto; el eco lo enseña).
  - Tab con la lista cerrada pone el primer candidato aunque haya varios; el común denominador del completado anterior se pierde.
  - Sin Tab en `--plain` (D5).

## Migration Plan

Nada que migrar: las formas largas siguen igual y no hay datos nuevos. Para volver atrás basta revertir los commits del change.

## Open Questions

Ninguna que cambie lo construido. Las decisiones que quedan para Wilson (herencia del proyecto en `/new`, `@`) cambiarían el alcance y van en el informe, no aquí.
