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

### D6 · Un solo bucle de eventos y la lectura de línea fuera de él

- **Qué:** la conversación corre dentro de un único `asyncio.run`; la lectura de la línea se hace en un hilo auxiliar para no bloquear el bucle. La forma exacta de entregar Ctrl+C (a la pregunta en curso, o a la espera de línea) se fija tras la sonda de la tarea 1.2, que mide P1 en las dos plataformas con un guion de quince líneas.
- **Por qué:** un proveedor con recursos abiertos (Playwright) vive ligado a un bucle de eventos: no se puede crear un bucle nuevo por pregunta.
- **Alternativas rechazadas:**
  - `asyncio.run` por pregunta: incompatible con D5.
  - Leer la línea en el hilo principal y correr el bucle en otro: las señales llegan al hilo principal, y la cancelación de la pregunta tendría que cruzar hilos.
- **Impacto:** spec (Interrumpir una pregunta no cierra la conversación). Si la sonda muestra que en Windows no se puede distinguir de forma fiable «interrumpir la pregunta» de «interrumpir la espera», se reabre esta decisión con Wilson antes de implementar el grupo 4.

### D7 · Interrupción: cancela la pregunta, nunca la conversación

- **Qué:** Ctrl+C durante una pregunta cancela esa tarea; el servicio registra `uncertain` o `failed` según `on_sent`, como ya hace, y el bucle vuelve a esperar. Ctrl+C en la espera imprime cómo salir y sigue. Se sale con `/exit` o con fin de entrada.
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

### D9 · Texto ajeno marcado y saneado al mostrarlo

- **Qué:** cada línea de la respuesta del proveedor se imprime saneada (`harness/text/`: sin controles, sin secuencias de escape, sin invisibles, credenciales enmascaradas) y con un prefijo fijo; las líneas del harness (estado, errores, avisos) llevan otro prefijo y no pueden generarse desde texto ajeno. El contenido de `/file` y la memoria viajan al proveedor marcados como datos, con el mismo marcado que ya usa la memoria.
- **Por qué:** en una conversación todo aparece en la misma pantalla; sin prefijos, una respuesta podría imitar un aviso de aprobación.
- **Alternativas rechazadas:**
  - Colores para distinguir: son secuencias de escape, dependen de la terminal y no existen al redirigir.
- **Impacto:** spec (Salida segura y distinguible).

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

## Open Questions

- ¿Guardar en disco el historial de entradas de la persona entre ejecuciones? No cambia specs ni tareas de este change; choca con «no guardar contenido real» y se decide en el de apariencia.
