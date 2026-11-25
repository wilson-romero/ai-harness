# Design

## Context

`develop` (`ee550b6`, igual a `v0.2.0`): una CLI de órdenes sueltas en `harness/cli.py`; `SessionService.ask` toma el bloqueo de la sesión, pregunta y lo suelta (`harness/core/service.py`); la aprobación ya está detrás de una terminal inyectable (`harness/skills/approvals.py`, que pregunta `isatty()` y usa `input()`); el texto ajeno se sanea en `harness/text/`. La motivación y el alcance están en `proposal.md`.

Premisas medidas el 2026-11-25:

- `main.py --help`: 6 subcomandos, ningún modo interactivo.
- Un `ask` con el proveedor de Copilot Web (rama sin mergear) arranca Edge en cada pregunta: 4,4 s de mediana hasta tener el editor listo, medido en macOS con la cuenta de prueba.
- El estudio de OpenCode (`docs/estudios/2026-11-25-arquitectura-opencode.md`): su conversación vive en un servidor con clientes y su bucle depende de llamadas a herramientas nativas. Ninguna de las dos cosas se copia aquí.

Premisas **sin medir**, cada una con su tarea:

- P1: cómo llega Ctrl+C a un proceso que tiene un bucle de `asyncio` en marcha y una lectura de línea bloqueada, en macOS y en Windows (tarea 1.2).
- P2: que mantener Edge abierto varios minutos entre preguntas no rompe la sesión de Copilot ni la detección de fin de respuesta (se mide al integrar con `copilot-web-provider`, fuera de este change).

## Goals / Non-Goals

**Goals:**

- Que la demo de la «Puerta MVP sin EA» se pueda hacer sin salir de una conversación.
- Que la conversación no añada ninguna vía nueva para aprobar, reenviar o leer otra sesión: todo pasa por los servicios que ya existen.
- Mismo código en macOS y Windows, solo con la biblioteca estándar.

**Non-Goals:**

- Apariencia de aplicación de terminal (paneles, colores, barra fija). Se decide en un change posterior, con la conversación ya en uso.
- Respuesta que aparece poco a poco.
- Bucle de agente con herramientas.

## Decisions

### D1 · Entrada: `chat`, y el programa sin argumentos si hay terminal

- **Qué:** `main.py chat [--session ID] [--project SLUG] [--name TEXTO]` abre la conversación. `main.py` sin argumentos hace lo mismo solo si `stdin` y `stdout` son una terminal; si no, muestra la ayuda con código de uso, como hoy.
- **Por qué:** es el gesto de las herramientas de referencia (entrar con el nombre del programa) sin quitar nada a los scripts, que siempre pasan argumentos o no tienen terminal.
- **Alternativas rechazadas:**
  - Solo `chat`: obliga a recordar un subcomando para el uso principal.
  - Sin argumentos siempre abre la conversación: un script o una tubería que hoy recibe la ayuda quedaría colgado esperando entrada.
- **Impacto:** spec `interactive-shell` (Entrar en la conversación); tareas 2.x.

### D2 · Un bucle de líneas con la biblioteca estándar y una terminal inyectable

- **Qué:** `harness/shell/` con tres piezas: un analizador puro (línea → pregunta o comando con argumentos), un bucle que despacha a los servicios existentes, y una interfaz `Terminal` (leer línea, escribir, preguntar si es interactiva) con la implementación real sobre `input()` y otra de prueba. La de aprobaciones ya existe; se unifica en una sola interfaz en lugar de tener dos.
- **Por qué:** todo lo que hace la conversación ya existe como servicio; falta el bucle. Con la terminal inyectable se prueba el bucle entero sin pseudoterminal, que no existe de forma portable.
- **Alternativas rechazadas:**
  - `prompt_toolkit`, Textual o Rich ahora: una dependencia y decisiones de aspecto antes de saber qué hace falta; el proyecto es biblioteca estándar más pydantic.
  - `cmd.Cmd` de la biblioteca estándar: está pensado para que toda línea sea un comando; aquí la línea normal es una pregunta y habría que rodearlo.
  - `readline` para editar la línea: no existe en Windows; usarlo solo donde está es una rama por plataforma.
- **Impacto:** spec `interactive-shell` completa; `harness/skills/approvals.py` pasa a usar la interfaz común (cambio sin conducta nueva, en un commit propio).

### D3 · Gramática: `/` es comando, lo demás es pregunta

- **Qué:** una línea que empieza por `/` es un comando: nombre de una lista cerrada y argumentos separados por espacios, con comillas dobles para un argumento con espacios. `//` al principio escapa la barra. Un comando desconocido o con argumentos de más es un error local. No hay alias ni abreviaturas.
- **Por qué:** una regla que se explica en una línea y que no puede enviar un comando mal escrito al proveedor por accidente.
- **Alternativas rechazadas:**
  - Enviar al proveedor lo que no se reconoce: un `/exti` acabaría como pregunta en Copilot.
  - Prefijos abreviados (`/s` por `/sessions`): ambiguos en cuanto crece la lista.
- **Impacto:** spec (Comandos con barra); tarea 2.1.

### D4 · La conversación conserva el bloqueo de su sesión

- **Qué:** al abrir una sesión, la conversación toma su bloqueo y lo mantiene hasta `/new`, `/resume` o la salida. `SessionService` separa dos operaciones que hoy van juntas: tomar la sesión (bloqueo) y preguntar con la sesión ya tomada. `ask` como orden suelta sigue haciendo las dos seguidas.
- **Por qué:** una conversación es dueña de su hilo. Si otro proceso pudiera preguntar entre dos turnos, la conversación remota de Copilot recibiría mensajes intercalados que la persona no ve. El bloqueo es de sistema operativo: si el proceso muere, se libera solo, y la recuperación de solicitudes huérfanas sigue funcionando.
- **Alternativas rechazadas:**
  - Tomar el bloqueo en cada pregunta, como hoy: permite el intercalado.
  - Una marca «en conversación» en SQLite: se queda mintiendo si el proceso muere.
- **Impacto:** spec (La conversación es dueña de su sesión); `request-recovery` no cambia (una sesión con el bloqueo tomado se considera viva, como ya dice). Tareas 3.x.

### D5 · Recursos del proveedor abiertos durante la conversación

- **Qué:** el contrato del proveedor gana dos operaciones opcionales, abrir y cerrar. La conversación abre al entrar y cierra al salir, también si una pregunta falló. El Mock no tiene nada que abrir; un proveedor de prueba cuenta aperturas y cierres. Las órdenes sueltas no llaman a abrir: el proveedor sigue gestionando sus recursos por pregunta.
- **Por qué:** con Copilot Web, 4,4 s de arranque en cada turno hacen incómoda una conversación.
- **Alternativas rechazadas:**
  - Dejarlo para el change de Copilot: la conversación quedaría definida sin su pieza más cara y habría que reabrir el bucle.
  - Un proceso aparte que mantenga el navegador entre ejecuciones: es el «navegador de fondo» que el diseño de Copilot descartó (otro proceso que vigilar y proteger).
- **Impacto:** spec `llm-provider` (Recursos del proveedor con vida de conversación). En `copilot-web-provider`, mantener Edge abierto exige revisar su D3 y el bloqueo `browser` (que quedaría tomado mientras dure la conversación): se hace allí, con la premisa P2 medida.
- **Añadido el 2026-11-25 (revisión independiente):** abrir y cerrar corren como la acción en curso, así que Ctrl+C las cancela. El primer Ctrl+C mientras el proveedor abre basta: todavía no se ha preguntado nada, no hay nada que perder y, con un proveedor que se cuelga al abrir, era la única salida. La conversación dice que se interrumpió, cierra lo que el proveedor alcanzó a abrir, suelta la sesión y termina con código 130 (el habitual de una interrupción; `/exit` sigue siendo 0). Ctrl+C mientras cierra deja de esperar el cierre y lo dice: el proveedor puede haber dejado algo abierto (una ventana, un proceso). Se descartó pedir dos Ctrl+C: el primero no haría nada visible, que es justo la trampa que se quería quitar (y D7 ya descarta depender de dos pulsaciones).

### D6 · Un solo bucle de eventos y la lectura de línea fuera de él

**Revisada el 2026-11-25** tras la sonda de la tarea 1.2: la redacción original dejaba abierta «la forma exacta de entregar Ctrl+C»; ahora queda fijada con lo medido en macOS y con lo que dice la documentación para Windows.

- **Qué:** la conversación corre dentro de un único `asyncio.run`; la lectura de la línea se hace en un hilo auxiliar (un hilo `daemon` por línea pedida, como mucho uno vivo) para no bloquear el bucle. Ctrl+C se recibe con un manejador propio instalado con `signal.signal(SIGINT, …)` **antes** de `asyncio.run` y restaurado al salir; el manejador nunca lanza una excepción. Lo que hace depende solo del estado que la conversación lleva en el hilo principal, nunca de en qué hilo o llamada cayó la señal:
  - si hay una lectura esperando (la espera de línea o el aviso de aprobación), deja una marca de interrupción en la cola de esa lectura (`queue.SimpleQueue.put`, la única operación de cola que la documentación declara reentrante);
  - si no, pide al bucle, con `loop.call_soon_threadsafe` (lo mismo que hace el manejador de `asyncio.Runner`), que cancele la tarea en curso (la pregunta o el comando).
  Una lectura que una interrupción deja pendiente sigue siendo la única; la línea que llegue después la recibe quien la esté esperando entonces. Un fin de entrada que llega a una lectura durante la cual hubo una interrupción no se toma como fin de entrada. **Añadido el 2026-11-25 (revisión independiente):** tampoco uno al que sigue una interrupción en menos de 0,25 s (`EOF_GRACE_S`): una consola puede terminar la lectura antes de que corra el manejador, y entonces el fin de entrada llega primero. Un fin de entrada real cierra igual, 0,25 s después. Y un `KeyboardInterrupt` que salte en el hilo lector termina esa lectura sin más: el hilo deja siempre un resultado en la cola (antes, una excepción que no fuera `Exception` lo mataba sin dejar nada y no volvía a empezar ninguna lectura). El orden real en Windows lo mide la fase (d) de la sonda.
- **Por qué:** un proveedor con recursos abiertos (Playwright) vive ligado a un bucle de eventos: no se puede crear un bucle nuevo por pregunta. Y la sonda y la documentación dicen que la señal llega siempre al hilo principal, que el hilo que lee no se entera y que su lectura sigue abierta: decidir por el estado del hilo principal es lo único que da la misma conducta en las dos plataformas.
- **Sonda (tarea 1.2).** `scripts/probe_interrupt.py`, fuera del producto, solo biblioteca estándar: un `asyncio.run` con el manejador anterior y tres fases: (a) una tarea pendiente, (b) una línea leída con `input()` en un hilo auxiliar mientras el bucle espera, (c) el hilo del bucle bloqueado esperando la línea que lee otro hilo (el caso del aviso de aprobación). En macOS se ejecuta con `--drive`: el guion se lanza a sí mismo como proceso hijo sobre una pseudoterminal y escribe Ctrl+C (`\x03`) en ella, que es lo que hace el teclado: la disciplina de línea de la terminal genera SIGINT para el proceso.

  | Caso | macOS arm64, Python 3.14.8 (medido el 2026-11-25) | Windows (sin medir — lo ejecuta Wilson) |
  |---|---|---|
  | (a) Ctrl+C con una tarea pendiente | el manejador corre en el hilo principal; la tarea queda cancelada y el bucle sigue vivo | sin medir |
  | (b) Ctrl+C con `input()` bloqueado en un hilo auxiliar | el manejador corre en el hilo principal; el hilo lector **sigue bloqueado**; lo escrito a medias antes de Ctrl+C se descarta; la línea siguiente (`after`) llega entera a esa misma lectura | sin medir |
  | (c) Ctrl+C con el hilo del bucle esperando en `SimpleQueue.get(timeout=0.1)` | el manejador corre en el hilo principal y su marca despierta la espera en el acto; el hilo lector sigue bloqueado y entrega la línea siguiente (`end`) | sin medir |
  | (d) Ctrl+C con la espera real de la conversación (`ConsoleTerminal.read_line`) y su manejador (fase añadida el 2026-11-25) | primero el manejador (a los 306 ms del inicio de la fase); el hilo lector no termina; `read_line` acaba en `WaitInterrupted` (la conversación sigue) y la línea siguiente (`after`) llega a la misma lectura | sin medir: debe decir si el lector termina (`EOFError` o `KeyboardInterrupt`) antes del manejador |
  | Qué ve una persona | `^C` al final de la línea, y luego las líneas del programa; el proceso no termina (salida 0 al final de la sonda) | sin medir |

  Recibo: `uv run python scripts/probe_interrupt.py --drive` → líneas `probe: task: cancelled; the loop is still running`, `probe: wait: the reader thread is still blocked after the interrupt`, `probe: wait: reader outcome line 'after'`, `probe: prompt: first outcome interrupt`, `probe: prompt: reader outcome line 'end'`, `probe: real: read_line raised WaitInterrupted (the conversation goes on)`, `probe: events: handler ran in the main thread; handler at 306.2 ms`, `probe: real: read_line returned 'after'`, `probe: exit 0`, `drive: child exit status 0`.

- **Windows, según la documentación y el código de CPython 3.14 (consultado el 2026-11-25), sin medir:**
  - `signal` (docs.python.org/3.14/library/signal.html): «Python signal handlers are always executed in the main Python thread of the main interpreter, even if the signal was received in another thread»; en Windows `signal()` admite `SIGINT`. Que el manejador no lance nada evita el «out of thin air» que la misma página describe.
  - `asyncio` (asyncio-platforms.html): en Windows `loop.add_signal_handler()` no existe; por eso se usa `signal.signal`. `asyncio-runner.html` («Handling Keyboard Interruption»): `Runner.run()` instala su propio manejador, que cancela la tarea principal; según `Lib/asyncio/runners.py` (3.14, línea 113) solo lo instala si el manejador vigente es `signal.default_int_handler`, de modo que uno propio instalado antes se respeta.
  - `ProactorEventLoop` (`Lib/asyncio/proactor_events.py`, 3.14, línea 675) llama a `signal.set_wakeup_fd` en el hilo principal: Ctrl+C despierta el bucle aunque esté esperando E/S. `call_soon_threadsafe` escribe además en el mismo canal.
  - `input()` en la consola de Windows (`Parser/myreadline.c`, 3.14, `_PyOS_WindowsConsoleReadline`): con Ctrl+C, `ReadConsoleW` termina sin datos; el hilo comprueba las señales (en un hilo que no es el principal no hay nada que ejecutar) y **vuelve a empezar la lectura** («The console cancelled the read and flushed its input buffer, but no exception was raised. Start the read over»): la misma conducta medida en macOS en (b). Hay una rama (`n_read == -1`) que devolvería una línea vacía, que `input()` convierte en `EOFError`: por eso un fin de entrada con una interrupción en medio no cierra la conversación.
  - `threading` (threading.html): «Changed in version 3.14: Lock acquisition can now be interrupted by signals on Windows»; aun así la espera de (c) usa `get(timeout=0.1)` en bucle, que no depende de ese cambio.
  - `queue` (queue.html): `SimpleQueue.put` es reentrante («a put() or get() call can be interrupted by another put() call in the same thread without deadlocking»), que es justo lo que hace el manejador cuando la señal cae dentro de un `get`.
  Conclusión: la documentación permite distinguir de forma portable «interrumpir la pregunta» de «interrumpir la espera», porque la distinción la hace el estado del hilo principal y no la lectura. La implementación del grupo 4 sigue adelante; la fila de Windows la confirma Wilson (tarea 7.5).
- **Comando para Wilson en Windows (PowerShell, en la raíz del repositorio):**

  ```powershell
  git fetch origin; git checkout feature/interactive-shell; uv run python --version; uv run python scripts/probe_interrupt.py
  ```

  Seguir las líneas `READY`: pulsar Ctrl+C cuando lo pida (también en `READY real`); en `READY wait`, escribir unas letras sin Intro y pulsar Ctrl+C; cuando pida `after` o `end`, escribirlo y pulsar Intro. Pegar de vuelta la versión de Python y **todas** las líneas que empiezan por `probe:` (no contienen datos de la empresa ni rutas).
- **Alternativas rechazadas:**
  - `asyncio.run` por pregunta: incompatible con D5.
  - Leer la línea en el hilo principal y correr el bucle en otro: las señales llegan al hilo principal, y la cancelación de la pregunta tendría que cruzar hilos.
  - `loop.add_signal_handler`: no existe en Windows.
  - Dejar el manejador de `asyncio.Runner`: cancela la tarea principal (la conversación entera), no la pregunta.
  - Un manejador que lance una excepción (como `KeyboardInterrupt`) para cortar la lectura: puede aparecer en cualquier instrucción del hilo principal, también dentro del motor de Skills o de una transacción.
  - Un hilo lector permanente que lea por adelantado: el programa tendría en su cola líneas que nadie ha pedido todavía. Se lee solo cuando alguien espera una línea. **Revisada el 2026-11-25 (revisión independiente):** esto no impide que una línea escrita mientras corre un Skill conteste el aviso de aprobación que aparece después, como decía la versión anterior de este punto: lo que se escribe sin que nadie lea se queda en el búfer de la propia terminal y lo recibe la lectura siguiente, sea cual sea. Es un límite de diseño, descrito en D8.
- **Impacto:** spec (Interrumpir una pregunta no cierra la conversación). Tareas 4.1 y 4.2. La espera del aviso de aprobación usa la misma lectura (D8).

### D7 · Interrupción: cancela la pregunta, nunca la conversación

- **Qué:** Ctrl+C durante una pregunta cancela esa tarea; el servicio registra `uncertain` o `failed` según `on_sent`, como ya hace, y el bucle vuelve a esperar. Ctrl+C en la espera imprime cómo salir y sigue. Se sale con `/exit` o con fin de entrada. **Añadido el 2026-11-25 (sonda 1.2):** Ctrl+C durante `/skill` cancela el comando (el estado de la ejecución queda para `skill resume`, fuera de la conversación o en otra sesión); Ctrl+C en el aviso de aprobación cuenta como «sin decidir»: la ejecución queda `awaiting_approval`, nada se aplica y la conversación sigue. **Revisada el 2026-11-25 (revisión independiente):** la cancelación dejaba la ejecución y su paso en `running`, de modo que otro `/skill` se rechazaba («already has an open run (running)») y `skill cancel` también (no acepta `running`). Ahora el motor, al cancelarse su tarea y con el bloqueo aún tomado, deja la ejecución como la deja `recover_runs` tras un proceso muerto: el paso LLM en curso pasa a `uncertain` con `interrupted` (nunca se reenvía), la ejecución a `uncertain`, y la conversación dice el comando exacto: salir de la sesión (`/new`, `/resume` o `/exit`) y `skill resume RUN --retry-step PASO` (pregunta otra vez) o `skill cancel RUN`. El aviso de una interrupción habla solo de lo que se registró durante esa línea: si Ctrl+C llega tras pulsar Intro y antes de que empiece la pregunta, dice que no se registró ni envió nada, y ya no nombra la solicitud anterior.
- **Por qué:** es el comportamiento de las herramientas de referencia y reutiliza la regla que ya existe para la interrupción.
- **Alternativas rechazadas:**
  - Dos Ctrl+C seguidos para salir: depende de tiempos y es difícil de probar sin reloj.
- **Impacto:** spec (Interrumpir…, Salir libera…). Tareas 4.x.

### D8 · La aprobación se pide en la conversación, con el mismo mecanismo

- **Qué:** `/skill NOMBRE [clave=valor…] [--file clave=RUTA]` llama al motor con la terminal de la conversación. El aviso de aprobación es el del motor: contenido, hash y los 8 caracteres. La conversación no interpreta ninguna línea como aprobación fuera de ese aviso, y no añade opción, variable ni comando que apruebe.
- **Por qué:** la frontera de aprobación ya pasó dos revisiones independientes; la conversación no debe ser una segunda puerta.
- **Alternativas rechazadas:**
  - Un comando `/approve`: separa la decisión del contenido mostrado, que es justo lo que el diseño de la aprobación evita.
- **Impacto:** spec (Skills y aprobación dentro de la conversación). Sigue valiendo el límite declarado en `skill-engine`: la aprobación no prueba que haya una persona delante.
- **Añadido el 2026-11-25 (implementación):** el motor toma el bloqueo de la sesión en `run` y `resume`, y la conversación ya lo tiene (D4). `SkillEngine` gana una opción `held_session`: para esa sesión usa el bloqueo que ya tiene quien lo llama en vez de pedir otro (que se rechazaría). Solo la pasa la conversación, con su propia sesión. Una ejecución que queda esperando aprobación se continúa con `skill resume` cuando la conversación ha dejado la sesión; la conversación no tiene `/skill resume` en esta versión.
- **Límite de diseño: lo escrito por adelantado (2026-11-25, revisión independiente).**
  - **Qué:** lo que la persona escribe mientras nadie lee (mientras corre un Skill, por ejemplo) se queda en el búfer de la terminal y es la primera línea que recibe la lectura siguiente, también si esa lectura es el aviso de aprobación. Medido con `main.py chat` real sobre pseudoterminal: `n` e Intro escritos durante el paso LLM contestaron el aviso que apareció después (aprobación `rejected`, ejecución `cancelled`). Una línea así **no puede aprobar**: el código son los 8 primeros caracteres de un hash que aún no se había mostrado. Sí puede rechazar o gastar los tres intentos; si los gasta, la aprobación queda `pending` y `skill resume` vuelve a preguntar con tres intentos nuevos (`test_wrong_answers_typed_ahead_leave_the_approval_pending`). Un pegado de varias líneas hace lo mismo con la conversación: por ejemplo `/file RUTA` y después una pregunta, en ese orden, como si se hubieran escrito.
  - **Por qué:** vaciar el búfer de la terminal antes del aviso exige código de plataforma (`termios.tcflush` en POSIX, `FlushConsoleInputBuffer` o `msvcrt` en Windows), que la conversación no tiene por regla del proyecto. Lo que el programa controla, no leer por adelantado, ya lo hace.
  - **Alternativas rechazadas:**
    - Vaciar el búfer con código de plataforma: rompe la regla de no tener código condicionado por plataforma.
    - Descartar las líneas que lleguen en un margen corto tras mostrar el aviso: depende de tiempos (una persona rápida o una terminal lenta lo confunden) y no se puede probar sin reloj.
    - Que `n` dentro de la conversación deje siempre la aprobación `pending` (lo que propuso la revisión): la conversación se quedaría sin forma de rechazar.
    - Dejarlo como límite sin más: una `n` escrita de más cancela una ejecución que hay que lanzar otra vez.
  - **Decisión de Wilson (2026-11-25): confirmar el rechazo.** Solo en el aviso dentro de la conversación (`SkillEngine(confirm_rejection=True)`, que solo pasa la conversación); `skill run` y `skill resume` desde la línea de órdenes siguen igual. Tras `n`, el aviso pide la palabra `reject` escrita completa y en minúsculas (`REJECT` no vale; se ignoran los espacios de los extremos). Con `reject`, el rechazo es el de siempre: aprobación `rejected`, ejecución `cancelled`. Con cualquier otra cosa, o con fin de entrada o Ctrl+C, la respuesta es «sin decidir»: la aprobación queda `pending` (se reanuda con `skill resume`), la ejecución no se cancela, no se gasta ningún intento (el aviso termina sin decidir y `skill resume` vuelve a preguntar con tres) y lo escrito en la confirmación lo consume el aviso: no se envía al proveedor ni se ejecuta como comando. El uso único, la caducidad y el hash no cambian.
  - **Límite que queda:** un pegado de varias líneas que contenga `n` y después `reject` rechaza. Nunca puede aprobar.
  - **Impacto:** spec: escenario «Aprobación rechazada» con la confirmación y escenario nuevo «Rechazo sin confirmar». README, sección «Conversación». Tests: `test_a_rejected_approval`, `test_n_alone_leaves_the_approval_pending`, `test_n_then_other_text_is_pending_and_the_text_goes_nowhere` y, sobre pseudoterminal real, `test_an_n_typed_ahead_cannot_reject_the_approval`.

### D9 · Texto ajeno marcado y saneado al mostrarlo

- **Qué:** cada línea de la respuesta del proveedor se imprime saneada (`harness/text/`: sin controles, sin secuencias de escape, sin invisibles, credenciales enmascaradas) y con un prefijo fijo; las líneas del harness (estado, errores, avisos) llevan otro prefijo y no pueden generarse desde texto ajeno. El contenido de `/file` y la memoria viajan al proveedor marcados como datos, con el mismo marcado que ya usa la memoria.
- **Por qué:** en una conversación todo aparece en la misma pantalla; sin prefijos, una respuesta podría imitar un aviso de aprobación.
- **Alternativas rechazadas:**
  - Colores para distinguir: son secuencias de escape, dependen de la terminal y no existen al redirigir.
- **Impacto:** spec (Salida segura y distinguible).
- **Añadido el 2026-11-25 (implementación):** el prefijo del texto ajeno es `| ` y ninguna línea del harness empieza por `|`; el texto ajeno se corta a 256 Ki caracteres antes de sanearlo (se dice cuántos quedan fuera) y una pregunta de más de 64 KiB se rechaza sin registrar nada. ~~Límite que queda: el contenido de una propuesta dentro del aviso de aprobación lo imprime el motor como en `skill run`, sin prefijo.~~ **Revisada el 2026-11-25 (revisión independiente):** ese límite permitía que una salida válida del modelo imprimiera dentro del aviso una regla, `skill: run 0000 is completed`, `nothing more to approve` y `> ` justo antes de la pregunta real, o una cabecera falsa con otro `target:`. Ahora, en la conversación, el motor imprime el aviso con un `render_approval` que le pasa la conversación: la cabecera y las reglas son las mismas líneas del harness, y cada línea del contenido va con `| `, sin volver a sanearla (ya está normalizada: se muestra exactamente lo que se firma). El hash no cambia: es el de la propuesta, no el del texto impreso. `skill run` sigue imprimiendo y firmando lo mismo que antes.
- **Añadido el 2026-11-25 (revisión independiente): cortar a lo ancho de la terminal.** Una línea más ancha que la terminal la parte la propia terminal, y lo que pasa a la fila siguiente empieza esa fila con lo que diga el texto: 78 caracteres seguidos de `applied: Decisiones/fake.md` dejaban una fila `applied: …` sin prefijo. Ahora toda línea que imprime la conversación (ajena o del harness, también el aviso de aprobación) se corta en filas más estrechas que la terminal (`shutil.get_terminal_size`, 80 si no se sabe; nunca menos de 20), y cada fila que continúa la anterior empieza por `|+`; el corte se hace después del último espacio de la fila si lo hay, para que un identificador o un comando no queden partidos (por eso los comandos que la conversación propone van en su propia línea). Así ninguna fila que no empiece por `|` puede venir de fuera: o es el principio de una línea del harness, o no existe. El ancho de cada carácter se calcula con `unicodedata` (anchos y completos cuentan 2; combinantes y de formato, 0; un tabulador, 8). Límites que quedan: si la terminal se estrecha después de imprimir, o si reordena el texto al cambiar de tamaño, las filas viejas pueden partirse otra vez; y los caracteres de anchura ambigua cuentan 1, como en las terminales occidentales, de modo que una terminal configurada para mostrarlos dobles (algunas en chino, japonés o coreano) puede partir una fila.

### D10 · Comandos de la primera versión

- **Qué:** `/help`, `/status` (sesión, proyecto, proveedor, última solicitud), `/new [--project SLUG] [nombre]`, `/sessions` (lista numerada), `/resume N` (número de esa lista, no un identificador escrito a mano), `/history`, `/memory TÉRMINOS`, `/context`, `/skill …`, `/file RUTA`, `/exit`.
- **Por qué:** son las capacidades que existen. `/resume` por número evita copiar identificadores sin aceptar prefijos, que el diseño de sesiones descartó.
- **Alternativas rechazadas:**
  - `/mcp`: una llamada a herramienta desde la conversación es el primer paso del bucle de agente, que está fuera.
  - `/project` para cambiar el proyecto de una sesión: el proyecto es de la sesión; se cambia con `/new --project`.
- **Impacto:** spec (Sesión de la conversación, Memoria…, Entrada acotada…).

## Risks / Trade-offs

- [P1 sin medir: Ctrl+C con un bucle de eventos y un hilo leyendo, sobre todo en Windows] → sonda antes de implementar (tarea 1.2); si no hay forma portable, se reabre D6 y D7 con Wilson.
- [La conversación mantiene tomado el bloqueo de la sesión mucho tiempo] → es lo que se quiere; un `ask` suelto sobre esa sesión recibe «ocupada». Queda documentado.
- [Con Copilot, el bloqueo `browser` quedaría tomado mientras dure la conversación: ninguna otra orden del harness podría usar el navegador] → límite aceptado para una persona y un navegador; se decide en `copilot-web-provider`.
- [Sin edición de línea ni historial de entradas en Windows] → se usa lo que da la terminal. Mejorarlo es parte del change de apariencia.
- [La terminal real no se puede probar de forma portable] → el bucle se prueba con la terminal inyectada; la implementación real sobre `input()` se cubre con la demo de Wilson, y así se dice en los recibos.
- [Una respuesta larga llena la pantalla] → sin paginación en esta versión; `/history` permite volver a verla.
- [Lo escrito por adelantado contesta el aviso de aprobación siguiente (2026-11-25)] → no puede aprobar; puede gastar los intentos de ese aviso (queda `pending`). Rechazar exige además la palabra `reject` (decisión de Wilson, D8); solo un pegado con `n` y `reject` rechaza.

## Open Questions

- ¿Guardar en disco el historial de entradas de la persona entre ejecuciones? No cambia specs ni tareas de este change; choca con «no guardar contenido real» y se decide en el de apariencia.
