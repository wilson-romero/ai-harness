# Proposal

## Why

La conversación (`main.py chat`, Corte 9, `interactive-shell`) funciona, pero se ve y se maneja como una lectura de líneas de 1970. Medido el 2026-11-26 sobre `develop` `c39b93f`, en macOS arm64 con `main.py chat` real sobre una pseudoterminal (recibos en la tarea 1.2):

- **0 colores**: toda la salida es texto plano; las líneas del harness, la entrada de la persona y el texto ajeno solo se distinguen por el prefijo `| `.
- **0 teclas de edición**: la lectura es `input()` sin `readline` (que no existe en Windows, D2 de `interactive-shell`). La flecha arriba seguida de Intro no recupera la línea anterior: la terminal la muestra como `^[[A` y llega a la conversación como una **pregunta de 3 caracteres** (ESC `[` `A`) que se envía al proveedor tal cual (el Mock contestó `Received 3 characters.` y `messages` guarda `'\x1b[A'`).
- **0 completado** de comandos con Tab, ni de sus argumentos.
- **Respuesta sin formato**: un `## Resumen` o un `**importante**` se ven con sus marcas, igual que el resto.
- **Ninguna señal mientras el proveedor trabaja** salvo la línea fija `waiting for the provider (Ctrl+C interrupts)`; con Copilot Web una respuesta tarda segundos (4,4 s de mediana solo en abrir el editor, medido en `interactive-shell`).

Wilson decidió el 2026-11-26 el alcance: que la conversación se parezca a Claude Code, Codex u OpenCode con **una conversación que se desplaza, mejorada con UNA librería de terminal conocida, no una interfaz de pantalla completa**, con la maqueta que aprobó (barra de estado arriba, respuesta con Markdown, indicador «pensando (4 s)», completado de `/sk[TAB]`).

Es el paso 3 del orden fijado en el plan de cortes («**Apariencia** (change posterior): paneles, colores, barra de estado, edición de línea; decide si se añade una librería de terminal», `docs/plan/2026-11-24-ai-harness-cortes.md`, revisión del 2026-11-25). Pertenece al **Corte 9 · Interfaz conversacional**, como su segunda entrega. Riesgo **N1**: no toca datos ni el proveedor, pero sí la frontera entre texto ajeno y texto del harness y la vía por la que llega la aprobación. SEC que cubre: **SEC-02** (la barra de estado no muestra nada de otra sesión), **SEC-07** (Ctrl+C sigue cancelando la pregunta sin reenviarla), **SEC-12** (la aprobación sigue ligada al hash y lo escrito en ella no se guarda ni se ofrece después) y **SEC-15** (el texto ajeno con formato sigue acotado y saneado). Se demuestra en **macOS**; Windows es confirmación opcional (no se puede ejecutar desde aquí: ver «Supuestos de Windows» en `design.md`).

## What Changes

- **Dependencia nueva: `prompt_toolkit==3.0.53`** (BSD-3-Clause; trae solo `wcwidth`). Es la única librería de terminal; la decisión y la comparación con `rich` están en `design.md` D1.
- **Terminal con estilo** (`harness/shell/styled.py`), elegida al entrar en una consola: colores, edición de línea, historial de entradas **en memoria** (flechas), completado con Tab de los comandos `/` y de su primer argumento (`/resume N`, `/skill NOMBRE`, `/file RUTA`), y la barra de estado (proyecto, proveedor, sesión de 8 caracteres) bajo el indicador.
- **Respuesta con un subconjunto de Markdown resaltado**: títulos, listas, citas, reglas, bloques de código, `código`, **negrita**, *cursiva* y enlaces como texto. Solo se colorea: ningún carácter se quita ni se añade, y se hace sobre el texto ya saneado.
- **Indicador mientras el proveedor trabaja**: `mock … thinking (4 s), Ctrl+C interrupts`, reescrito cada segundo en su línea y borrado al llegar la respuesta.
- **Cabecera** con la línea de estado de la maqueta.
- **Texto plano como respaldo**, el de hoy sin cambios, cuando no hay terminal, con `NO_COLOR`, con `TERM=dumb`, con `chat --plain` o con `HARNESS_PLAIN=1`, o si la librería no puede manejar la consola. `scripts/verify.sh`, las demos y los tests existentes usan ese camino.
- Un pegado de varias líneas llega como **una** línea en la terminal con estilo (pegado delimitado): ya no puede contestar dos avisos seguidos.

**No entra**, aunque esas herramientas lo tengan:

- Pantalla completa, paneles, ventanas divididas o barra fija fuera del momento de escribir (la barra de estado solo se ve mientras se espera una línea).
- Texto que aparece poco a poco (streaming) ni paginación de respuestas largas.
- Historial de entradas guardado en disco entre ejecuciones (D6: no se guarda lo que la persona escribe).
- Contador de envíos en la barra de estado («más adelante», según Wilson): no existe aún el dato.
- Resaltado de sintaxis dentro de los bloques de código, tablas, imágenes, HTML o enlaces que se puedan pulsar (OSC 8).
- Cambios en las órdenes sueltas (`ask`, `skill run`…): siguen imprimiendo texto plano.
- Cambios en el aviso de aprobación del motor ni en `skill run`.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `interactive-shell` (delta sobre la capacidad que añade el change `interactive-shell`, mergeado y sin archivar): se **añaden** requisitos de aspecto (terminal con estilo y su respaldo, Markdown resaltado con la marca de texto ajeno intacta, indicador de trabajo, barra de estado, edición e historial en memoria, completado). Ningún requisito existente cambia: «Salida segura y distinguible», «Interrumpir una pregunta…» y «Skills y aprobación…» se cumplen en los dos caminos, y sus tests pasan sin tocar una aserción.

`openspec list --specs` (2026-11-26) muestra 8 capacidades vigentes; `grep -rn -i "color\|colour\|prompt_toolkit\|historial de entradas\|autocomplet" openspec/specs` → 0 coincidencias: ninguna capacidad vigente habla de aspecto. `interactive-shell` aún no está en `openspec/specs/` (su change está sin archivar), por eso el delta va como requisitos añadidos.

## Impact

- Código: `harness/shell/` (`render.py`, `styled.py`, `completion.py` nuevos; `conversation.py`, `terminal.py` y `app.py` cambiados). Las filas y el saneado del texto ajeno se mueven de `conversation.py` a `render.py` sin cambiar su conducta (se reexportan con los mismos nombres).
- Ficheros fuera de `harness/shell/` y de sus tests: `pyproject.toml` y `uv.lock` (la dependencia), `tests/conftest.py` (`HARNESS_PLAIN` en la lista de variables que no se heredan), `tests/integration/test_chat_terminal.py` (su hijo pide el camino plano, una línea), `README.md` (sección de aspecto) y este change.
- Sin migración y sin datos nuevos: nada se guarda.
- Conflictos previstos: `feature/prompt-economy` cambia `_cmd_context` y los imports de `conversation.py` y `tests/shell_support.py`; `feature/copilot-web-provider` cambia `harness/cli.py` y `harness/core/service.py`. Este change no toca `cli.py`, `service.py` ni `shell_support.py`.
