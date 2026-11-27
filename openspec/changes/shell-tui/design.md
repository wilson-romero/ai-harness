# Design

## Context

La conversación (`harness/shell/conversation.py`) es un núcleo que habla con una `ConversationTerminal`: lee líneas (`read_line`), muestra filas ya cortadas y marcadas (`show_rows`), pregunta la aprobación (`ask`, bloqueante, desde el motor de Skills) y recibe Ctrl+C por `Conversation.interrupt()`. `shell-appearance` añadió una terminal con estilo sobre `prompt_toolkit` que conserva la conversación desplazable. Wilson pidió el 2026-11-26 una pantalla completa con Textual (proposal). Este diseño dice cómo se dibuja esa pantalla sin bifurcar el núcleo y sin aflojar ninguna garantía.

Premisas leídas en el código instalado de Textual 8.2.8 (`.venv/lib/python3.14/site-packages/textual/`; context7 no estaba disponible) el 2026-11-26:

- `app.py:454-463`: `App.BINDINGS` trae `ctrl+q` → `quit` (prioridad) y `ctrl+c` → `help_quit`. Una subclase puede declarar los mismos atajos con prioridad.
- `drivers/linux_driver.py:338-340`: el modo crudo quita `ISIG` salvo que `TEXTUAL_ALLOW_SIGNALS` esté puesta; `drivers/win32.py:176-179` deja la consola de Windows solo con `ENABLE_VIRTUAL_TERMINAL_INPUT` (sin `ENABLE_PROCESSED_INPUT`). En los dos, Ctrl+C llega como la tecla `ctrl+c`, no como señal.
- `visual.py:102-107`: un `str` se interpreta como *markup* salvo `markup=False`; un `Content` o un `Text` se usan tal cual. `content.py:415-460`: `Content.assemble` toma texto literal con estilos por tramo y quita caracteres de control (`strip_control_codes=True`).
- `widget.py:256-266`: `border_title` pasa un `str` por `render_str` (*markup*); un `Content` se usa tal cual.
- `widgets/_markdown.py:269, 614, 1194-1196`: el widget `Markdown` convierte los enlaces en acciones y, al pulsarlos, llama a `app.open_url`, que abre el navegador (`app.py:4790`).
- `widgets/_input.py:139, 756-763`: `Input` liga `ctrl+c` a copiar y su pegado inserta solo la primera línea.
- `constants.py:104-173`, `app.py:596, 762, 3386, 3534-3541, 1585-1596, 2249`: `TEXTUAL=devtools|debug`, `TEXTUAL_LOG`, `TEXTUAL_DEBUG`, `TEXTUAL_SCREENSHOT*`, `TEXTUAL_PRESS` y `TEXTUAL_DRIVER` se leen del entorno al importar o al arrancar y escriben registros, mandan el registro a un servidor local, guardan capturas SVG, pulsan teclas o importan un módulo.
- `app.py:1318-1376`: la paleta añade por defecto órdenes de sistema (tema, captura SVG, salir, teclas, maximizar).
- `app.py:2133`: `run_test()` y `Pilot` (`pilot.press`, `pilot.click`, `resize_terminal`) conducen la aplicación sin terminal.

## Goals / Non-Goals

**Goals:** la maqueta aprobada; las mismas garantías que la conversación de hoy, reescritas para una pantalla completa y probadas con Pilot; un solo núcleo para los dos modos.

**Non-Goals:** streaming, temas, ratón más allá de desplazar y elegir, enlaces pulsables, imágenes, varias conversaciones, historial en disco, límite de envíos.

## Decisions

### D1 · Textual como única librería de terminal; se quita `prompt_toolkit`

- **Qué:** `textual==8.2.8` fijada exacta (publicada el 2026-06-30, MIT, `requires_python >=3.9,<4`; funciona con Python 3.14.8). Sus dependencias, también en `uv.lock`: `rich` 15.0.0, `markdown-it-py` 4.3.0, `mdit-py-plugins` 0.7.0, `linkify-it-py` 2.2.0, `uc-micro-py` 2.0.0, `mdurl` 0.1.2, `platformdirs` 4.14.8, `pygments` 2.21.0 y `typing-extensions` 4.16.0 (datos de PyPI, 2026-11-26). Se quitan `prompt-toolkit` y `wcwidth`. Quedan dos modos: pantalla completa en una consola y texto plano.
- **Por qué:** es lo que Wilson eligió. Con Textual dentro, `prompt_toolkit` solo serviría para un tercer modo (línea con edición) que nadie pidió, con su propio manejo de SIGINT y de la aprobación que habría que seguir probando; menos dependencias y menos modos. Las razones por las que `shell-appearance` rechazó `rich` siguen valiendo y se cumplen sin renunciar a Textual: **el harness nunca le da a Textual ni a `rich` un renderable de Markdown ni una cadena con *markup***; todo lo que se dibuja es `Content` construido con `Content.assemble` a partir de las filas del núcleo (D3). Por eso no hay OSC 8, ni reescritura del texto saneado, ni nada que obtenga o ejecute algo.
- **Alternativas rechazadas:**
  - Conservar `prompt_toolkit` como tercer modo (TUI, línea, plano): se pierde menos, pero son tres caminos de Ctrl+C y de aprobación. **Lo que se pierde al quitarlo:** quien no quiera pantalla completa (por conservar el desplazamiento de su propia terminal, copiar con la selección de la terminal o usar un lector de pantalla) tiene ahora el texto plano, sin colores, sin edición con flechas y sin completado con Tab.
  - El widget `Markdown` de Textual: convierte enlaces en acciones que abren el navegador (`app.open_url`) y reescribe el texto ajeno tras sanearlo; desactivar `open_links` deja el resto.
  - `rich` directamente (`Markdown`, `Text.from_markup`): las mismas razones de `shell-appearance` D1.
- **Impacto:** `pyproject.toml`, `uv.lock`; `harness/shell/tui.py` es el único módulo que importa Textual, y `harness/shell/app.py` lo importa solo al elegir la pantalla completa. El camino plano no importa Textual.

### D2 · El núcleo corre entero en su hilo, con su bucle; la pantalla tiene el hilo principal

- **Qué:** `run_chat` decide la terminal en el hilo principal. Con pantalla completa, `HarnessApp.run()` ocupa el hilo principal y el bucle de Textual; en `on_mount` arranca un hilo `conversation` (demonio) que abre la base de datos, recupera, construye la `Conversation` y hace `asyncio.run(conversation.run(...))`, exactamente la función `converse` que usa el camino plano. Cuando el hilo termina, la pantalla sale con su código. `TuiTerminal` es la `ConversationTerminal` del núcleo: el núcleo la llama en su hilo; la pantalla, en el principal. Lo que cruza: líneas y respuestas por `queue.SimpleQueue` (con un `asyncio.Event` del bucle del núcleo para despertarlo), lo que se muestra por `loop.call_soon_threadsafe` sobre el bucle de Textual (sin esperar; si ese bucle ya cerró, se descarta).
- **Por qué:** el motor de Skills pregunta la aprobación con `terminal.ask`, **síncrona**, desde el bucle del núcleo (`harness/skills/approvals.py:decide`). En el bucle de Textual eso congelaría la pantalla que tiene que mostrar la caja. Con el núcleo en su hilo, `ask` bloquea su hilo como en todos los modos y la pantalla sigue viva. Así no se bifurca nada: la sesión tomada (`take_session`, `ask_taken`, `held_session`), la apertura y el cierre del proveedor en todos los caminos de salida (`open_resources`/`close_resources` en `Conversation.run`) y el bucle único **del núcleo** siguen siendo el mismo código, cubierto por las mismas pruebas. La conexión SQLite se abre, usa y cierra en el hilo del núcleo (Python la ata a su hilo); nada de la pantalla toca la base de datos.
- **Alternativas rechazadas:**
  - El núcleo como *worker* asíncrono en el bucle de Textual: exige que `decide` y el motor sean asíncronos, es decir, cambiar `harness/skills/` y sus pruebas, fuera del alcance y en otra frontera de seguridad.
  - Un *worker* de hilo de Textual (`run_worker(thread=True)`): equivale, pero su cancelación y su ciclo de vida son de Textual; un `threading.Thread` propio deja claro quién lo cierra (D8).
  - Copiar el bucle de la conversación dentro de la TUI: dos núcleos; las pruebas de seguridad del núcleo dejarían de cubrir la pantalla.
- **Impacto:** `app.py` (`converse`, `run_chat`); `tui.py` (`TuiTerminal`, `HarnessApp._run_core`, `run_full_screen`). Ninguna aserción de las pruebas del núcleo cambia.

### D3 · El texto ajeno vive solo en su bloque, construido sin *markup*

- **Qué:** la pantalla agrupa las filas que manda el núcleo: las que empiezan por `| ` (y sus continuaciones `|+`) forman un `ForeignBlock` con borde y título del harness (el nombre del proveedor tras una pregunta; si no, «text from outside the harness»); las demás, un bloque del harness; la línea que la persona envía, un bloque «you». Cada bloque es un `Static(markup=False)` cuyo contenido es `Content.assemble` de los tramos de las filas, con estilos de una tabla fija (`STYLES`) que no nombra enlaces ni acciones; el título es un `Content`. El subconjunto de Markdown es el de `render.py` (solo colorea, sobre el texto ya saneado). Dentro del bloque se quita el prefijo `| `: en esta pantalla la marca es el borde. Ningún bloque es enfocable. El núcleo no corta las filas aquí (`pane_columns` le da 10 000 columnas): el corte existe para que el ajuste de una terminal que se desplaza no empiece una fila con texto ajeno; en esta pantalla cada bloque es su propia región y Textual ajusta dentro de ella, también al cambiar el tamaño.
- **Por qué:** es el equivalente del prefijo `| ` en una pantalla completa: el texto ajeno no puede inyectar estilos, enlaces ni acciones (`[bold]`, `[link=…]` y `[@click=…]` son caracteres), no puede dibujar fuera de su bloque (Textual recorta cada widget a su región) y no puede parecerse a la caja de aprobación ni al panel, que no son bloques del registro sino widgets propios con datos del harness.
- **Alternativas rechazadas:** `Static(texto)` con *markup* activado (el riesgo n.º 1: una acción `@click` en una respuesta ejecutaría una acción de la aplicación); escapar el *markup* (depende de conocer toda la sintaxis presente y futura); el widget `Markdown` (D1).
- **Impacto:** `tui.py` (`rows_content`, `ForeignBlock`, `Block`, `HarnessApp.show_rows`). Pruebas: respuesta hostil, 1 MiB, cambio de tamaño, control negativo con `Content.from_markup`.

### D4 · Panel lateral y estado: solo estado del harness, leído en el hilo del núcleo

- **Qué:** `ShellState` gana `panel` (devuelve un `PanelState`) y `sessions`. `Conversation._panel` lee la sesión tomada (nombre, id8, proyecto), el proveedor configurado, las notas de la última pregunta, el número de peticiones de la sesión y el estado de la última. `TuiTerminal` lo llama **en el hilo del núcleo** cada vez que vuelve a esperar una línea, y la pantalla lo pinta. Las notas son los nombres que el contexto ya lista (`ContextNote.relative`, limpios y redactados) pasados otra vez por `safe_line`; se vacían al cambiar de sesión y en cada pregunta. Mientras el proveedor trabaja, el panel dice `running`.
- **Por qué:** SEC-02: el panel describe siempre la sesión tomada; se refresca justo después de cada acción (incluidas `/new` y `/resume`) y nunca lee texto ajeno. La base de datos solo se toca en su hilo.
- **Alternativas rechazadas:** consultar la base de datos desde la pantalla (otra conexión, otro hilo, la posibilidad de describir una sesión distinta de la tomada); extraer datos de las líneas que imprime el núcleo (sería leer texto que puede venir de fuera).
- **Impacto:** `terminal.py`, `conversation.py` (`_panel`, `_notes`), `tui.py` (`SidePanel`). «Envíos» es el número de peticiones de la sesión: en esta rama no hay límite que mostrar.

### D5 · Paleta y selectores: órdenes del harness que pasan por la misma línea

- **Qué:** la paleta (`ctrl+p`) tiene un único proveedor, `HarnessCommands`, con una lista cerrada (`COMMAND_ENTRIES`); `get_system_commands` no devuelve nada y `save_screenshot` falla. Cada entrada envía una línea (`/status`, `/new`…), rellena la entrada (`/memory `) o abre un selector. El de sesiones pide al núcleo, por la misma cola de líneas, la lista de `/sessions` (que fija los números de `/resume` igual que `/sessions`) y envía `/resume N`; el de Skills ofrece los nombres que ya da el completado y rellena `/skill NOMBRE `; el de ficheros recorre la carpeta de trabajo (sin ocultos, hasta 500) con el filtro de `acceptable_path` y envía `/file RUTA`. Las opciones son `Content`, nunca *markup*.
- **Por qué:** los selectores no ganan poderes: todo acaba en una línea que el núcleo analiza y comprueba como si se hubiera escrito. Solo funcionan cuando el núcleo espera una línea.
- **Alternativas rechazadas:** que el selector cambie de sesión llamando al núcleo directamente (otra vía que probar); dejar las órdenes de sistema (la captura SVG escribe la pantalla en un fichero).
- **Impacto:** `tui.py` (`HarnessCommands`, `PickerScreen`, `_file_choices`), `conversation.py` (`_session_choices`).

### D6 · La caja de aprobación: cromo del harness, contenido ajeno dentro, entrada propia

- **Qué:** `Conversation._render_approval` construye el aviso como hoy y, si la terminal es `ApprovalTerminal`, le pasa las piezas (`shown`, cabecera, filas del contenido). Cuando el motor muestra ese texto exacto, la pantalla escribe la cabecera en el registro; cuando pregunta, abre `ApprovalScreen` (modal): título «Approval requested», la cabecera del motor (destino, hash, caducidad), el contenido en un área con borde marcada como ajena, la pregunta del motor y una `CodeInput`. La respuesta vuelve a `decide`, sin cambios: mismo hash de los mismos bytes, mismo código de 8 caracteres, y `n` pide escribir `reject` (el mismo segundo paso, en la misma caja). `CodeInput` no tiene historial, ignora el pegado, no se muestra como bloque «you» y no se registra; una respuesta enviada antes de `ARM_S` (0,5 s) desde que se abrió la caja se rechaza («Too soon»). La paleta no se abre sobre la caja. Ctrl+C en la caja deja la aprobación sin decidir.
- **Por qué:** lo escrito por adelantado va a la cola de líneas, nunca a la de respuestas, y la pantalla no acepta líneas mientras el núcleo trabaja (D8); las pulsaciones que el *driver* aún no entregó cuando se abre la caja chocan con `ARM_S`. El pegado se ignora porque lo pedido es que un pegado no pueda aprobar. El foco: el texto que llega no es enfocable y la caja es modal.
- **Alternativas rechazadas:** escribir el código en la entrada de la conversación (mezcla historial y aprobación); un botón «Aprobar» (un clic accidental o un `Enter` adelantado aprobarían sin leer el hash).
- **Revisado el 2026-11-26 (revisión independiente):**
  - **Una línea y una respuesta por espera.** `submit_line` comprobaba `_waiting == "line"`, pero el núcleo lo ponía a `None` en su propio hilo, en el `finally` de `read_line`. La pantalla atiende todas las teclas de una lectura antes de que el núcleo vuelva a correr, así que una sola escritura `uno\rdos\r` daba dos peticiones. Ahora `_take` comprueba y cierra la espera en un solo paso, en el hilo de la pantalla y bajo `_state_lock`. Lo mismo vale para `answer`. `ask` vacía la cola de respuestas al empezar, porque ninguna respuesta vale antes de su caja.
  - **La propuesta entera antes del código.** `AvPág`, `RePág`, las flechas, `Inicio` y `Fin` son atajos de la caja, con prioridad: desplazan el área del contenido mientras el foco sigue en `CodeInput`. El área sigue sin poder tomar el foco. Una línea en negrita dice cuántas líneas quedan debajo y la regla («el código solo se toma cuando el final de la propuesta se ha mostrado»). La caja recuerda que ese contenido llegó al final de la vista. Hasta entonces rechaza todo lo que no sea `n` o `reject`, porque rechazar no exige leer. Perdido a cambio: `Inicio` y `Fin` ya no mueven el cursor de la entrada; `ctrl+a` y `ctrl+e` sí.
  - **Sin portapapeles en `CodeInput`.** Estos son los atajos de `Input` en Textual 8.2.8 (`widgets/_input.py:76-140`). Tres meten o sacan texto y se anulan: `ctrl+v` (`paste`, que pega el portapapeles de la aplicación), `ctrl+x` (`cut`) y `ctrl+c`/`super+c` (`copy`), que además escriben OSC 52. `ctrl+c` ya lo toma antes la aplicación. Los demás mueven el cursor, seleccionan o borran dentro de la caja y se quedan: flechas, `ctrl+←/→`, `home`/`end`, `ctrl+a`/`ctrl+e`, `shift+…`, `backspace`, `delete`, `ctrl+d`, `ctrl+w`, `ctrl+u`, `ctrl+f`, `ctrl+k`, `ctrl+shift+a` y `enter`.
- **Impacto:** `terminal.py` (`ApprovalTerminal`), `conversation.py` (`_render_approval`), `tui.py` (`ApprovalScreen`, `CodeInput`, `TuiTerminal._take`).

### D7 · Qué terminal se usa, y Textual callado

- **Qué:** pantalla completa en una consola. Texto plano con `--plain`, `HARNESS_PLAIN`, `NO_COLOR`, `TERM=dumb`, sin consola, con cualquier variable de depuración de Textual puesta (`TEXTUAL`, `TEXTUAL_LOG`, `TEXTUAL_DEBUG`, `TEXTUAL_SCREENSHOT*`, `TEXTUAL_PRESS`, `TEXTUAL_DRIVER`, `TEXTUAL_DEVTOOLS_*`, `TEXTUAL_ALLOW_SIGNALS`, `TEXTUAL_SHOW_RETURN`) o si Textual no carga. Además, `textual_is_quiet()` comprueba lo que Textual leyó al importarse, y `HarnessApp` se niega a construirse si no está callado.
- **Por qué:** «nada de lo escrito se guarda en disco»: con esas variables Textual escribiría el registro, lo mandaría a un servidor local o guardaría capturas; `TEXTUAL_ALLOW_SIGNALS` haría de Ctrl+C una señal que mata el proceso.
- **Alternativas rechazadas:** borrar esas variables del entorno antes de importar Textual (cambia el entorno del proveedor y no sirve si Textual ya se importó).
- **Revisado el 2026-11-26 (revisión independiente).** Sobrescribir `save_screenshot` no bastaba: `App.action_screenshot` → `deliver_screenshot` → `deliver_text` escribía el fichero sin pasar por él. Se leyó `textual/app.py` 8.2.8 buscando todo lo que escribe un fichero, abre un enlace, toca el portapapeles de la terminal o deja la pantalla:
  - `action_screenshot`, `deliver_screenshot`, `deliver_text`, `deliver_binary`, `save_screenshot`, `open_url` y `action_suspend_process` se anulan: avisan y no hacen nada; `save_screenshot` lanza una excepción.
  - `copy_to_clipboard` (`app.py:1770`, que escribe OSC 52) guarda el texto solo dentro de la aplicación.
  - Los widgets que llaman a esos métodos (`Link`, `TextArea`, la selección de `Screen`) acaban en las mismas sobrescrituras.
  - Si la pantalla falla por dentro, `_fatal_error` y `panic` no dejan la traza de `rich` con `show_locals=True` (`app.py:3285-3296`), cuyas variables locales podían llevar texto ajeno. Dejan un mensaje fijo, `CRASHED`.
  - Si Textual carga pero `app.run()` no puede arrancar en la consola (falla antes de `on_mount`, sin núcleo), `run_full_screen` lanza `FullScreenUnavailable` y `run_chat` sigue en texto plano tras una línea en la salida de error, sin traza. Nada de la conversación había empezado.
- **Impacto:** `app.py` (`plain_reason`, `make_terminal`, `run_chat`), `tui.py` (`textual_is_quiet`, las sobrescrituras de `HarnessApp`, `run_full_screen`).

### D8 · Ctrl+C, salir y devolver la terminal

- **Qué:** `ctrl+c` (con prioridad, por encima del copiar de `Input`) llama a `Conversation.interrupt()`: si el núcleo espera una línea o una respuesta, la espera recibe la interrupción; si trabaja, se cancela la acción (petición `uncertain`, nunca reenviada); mientras el proveedor abre, la apertura se cancela y la conversación sale con 130. Con nada en marcha, Ctrl+C no sale: el núcleo dice que la conversación sigue abierta. Para salir hay una tecla distinta, `ctrl+q` (o `ctrl+d` con la entrada vacía, o `/exit`): cierra la entrada, interrumpe lo que corra y la pantalla sale cuando el núcleo ha cerrado el proveedor y soltado la sesión; un segundo `ctrl+q` sale ya. Mientras el núcleo trabaja, `Enter` no envía (la línea se queda en la entrada). SIGINT hace lo de Ctrl+C; SIGTERM y SIGHUP (donde existe) lo de `ctrl+q`. Textual restaura la terminal al salir y ante una excepción (deja la pantalla alternativa, muestra el cursor); si la pantalla cae antes que el núcleo, `run_full_screen` cierra la entrada y espera al núcleo hasta 30 s.
- **Por qué:** mantiene D6/D7 de `interactive-shell` con una tecla de salida explícita en vez de una confirmación.
- **Alternativas rechazadas:** pedir confirmación al pulsar Ctrl+C sin nada en marcha (otra caja modal que podría contestarse por adelantado).
- **Revisado el 2026-11-26 (revisión independiente).** Con SIGHUP y una pregunta en curso, la petición quedaba `uncertain` y la sesión libre, pero el proceso salía con 120: Python no podía vaciar `stdout` hacia una terminal que ya no existe. Ahora el manejador de SIGHUP marca `hung_up`, y después de esperar al núcleo `run_full_screen` dirige los descriptores 1 y 2 al dispositivo nulo (`_streams_to_nowhere`). La salida es 0.
- **Impacto:** `tui.py` (`HarnessApp.action_interrupt`, `action_leave`, `_signals_to`, `run_full_screen`, `_streams_to_nowhere`). Límite: SIGKILL no se puede atender; la terminal queda en modo crudo (`reset` la arregla).

## Supuestos de Windows (sin ejecutar)

- Textual usa en Windows su `WindowsDriver` (consola con VT): Ctrl+C llega como tecla (`win32.py:176-179`), así que el camino de Ctrl+C es el mismo que en macOS. No hay `SIGHUP`; se busca con `getattr` y no se instala.
- No hay código por plataforma en el producto (`tests/unit/test_portability.py`).
- Qué ejecutar en la máquina Windows: `uv sync`, `uv run pytest -q tests/unit/test_shell_tui.py tests/unit/test_portability.py`, y a mano `uv run python main.py chat` con `HARNESS_PROVIDER=mock`: escribir una pregunta, Ctrl+C durante una pregunta con `HARNESS_MOCK_DELAY_MS=60000`, `ctrl+p` → «Switch session...», `ctrl+q`; confirmar que la consola vuelve a su estado (cursor visible, sin pantalla alternativa). Repetir en Windows Terminal y en conhost.

## Risks / Trade-offs

- [Cadena de suministro: 9 paquetes nuevos, entre ellos un parser de Markdown que no usamos] → versiones fijadas en `uv.lock`; ninguno se invoca sobre texto ajeno (D3); revisar al subir Textual.
- [Versiones muy recientes (revisión independiente, 2026-11-26)] → `platformdirs` 4.14.8 salió el 2026-11-20, y `markdown-it-py` 4.3.0 y `mdit-py-plugins` 0.7.0 el 2026-11-10. Tienen días de uso, y un fallo o un paquete comprometido tendría poco tiempo para notarse. Qué se hace:
  - Las tres están fijadas por hash en `uv.lock`.
  - El harness no llama a ninguna. `markdown-it-py` y `mdit-py-plugins` solo los importa el widget `Markdown` (`textual/widgets/_markdown.py`), que no se usa (D3).
  - `platformdirs` sí se importa al cargar Textual (`textual/app.py:56`), pero su única llamada (`user_downloads_path`, `app.py:4975`) está en `_deliver_binary`, al que ya no se llega (D7).
  - Antes de archivar, o al subir Textual, mirar si alguna se retiró (*yanked*) o tiene avisos.
- [Una versión futura de Textual interprete `Content` o `border_title` de otra forma] → pruebas de la respuesta hostil y el control negativo con `Content.from_markup`; Textual fijado exacto.
- [El núcleo en otro hilo: llamadas que crucen sin cola] → la pantalla nunca llama al núcleo salvo `submit_line`, `answer`, `request_sessions`, `close_input` e `interrupt_wait`, que solo ponen marcas en colas; el núcleo nunca toca widgets (todo va por `call_soon_threadsafe`).
- [Salida colgada si el proveedor no cierra] → el segundo `ctrl+q` sale; `run_full_screen` espera 30 s y el hilo es demonio.
- [`ARM_S` molesta a quien escribe rápido] → 0,5 s, y el mensaje lo explica.
- [Pegado de varias líneas en la entrada: Textual guarda solo la primera] → se documenta; nunca se envían varias preguntas.
- [Varias líneas llegadas en una sola lectura de la terminal (revisión independiente, 2026-11-26)] → Textual inserta todos los caracteres antes de atender los `Enter`. Así, `uno\rdos\r` escrito de golpe es una sola pregunta, `unodos`, y el segundo `Enter` se rechaza («Busy»). No hay dos peticiones, que era el fallo. La línea unida es lo que deja Textual y no se corrige: escribiendo a mano, el núcleo vuelve a correr entre una tecla y otra.

## Open Questions

- Si se quiere el límite de envíos en el panel, depende de `feature/copilot-web-provider`.
