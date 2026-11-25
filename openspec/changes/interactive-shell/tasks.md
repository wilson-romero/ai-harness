# Tasks

Cada `[x]` lleva su recibo debajo (comando y salida relevante, o SHA). Los oráculos se nombran en cada tarea.

## 1. Rama, plan y sonda de interrupción

- [x] 1.1 Crear la rama `feature/interactive-shell` con `git flow feature start`. Hecho: `git branch --show-current` la muestra.
  - Recibo (2026-11-25): `git flow feature start interactive-shell` → `feature/interactive-shell`.
- [ ] 1.2 Sonda de P1: un guion de unas quince líneas, fuera del producto, con un `asyncio.run`, una tarea que espera y una lectura de línea en un hilo; medir qué recibe cada parte con Ctrl+C durante la tarea y durante la espera, en macOS (el agente) y en Windows (Wilson, con el comando de PowerShell escrito en la tarea). Oráculo: la tabla de resultados por plataforma pegada en `design.md` D6. Si Windows no permite distinguir los dos casos, parar y reabrir D6 y D7 con Wilson.
  - Recibo parcial (2026-11-25, macOS arm64, Python 3.14.8): `uv run python scripts/probe_interrupt.py --drive` (hijo real sobre pseudoterminal, Ctrl+C escrito como `\x03`) → `task: cancelled; the loop is still running`, `wait: the reader thread is still blocked after the interrupt`, `wait: reader outcome line 'after'` (lo escrito a medias se descarta), `prompt: first outcome interrupt`, `exit 0`. Tabla y fuentes de Windows en `design.md` D6 (revisada); la documentación permite distinguir los dos casos, así que el grupo 4 sigue. Queda sin marcar hasta que Wilson pegue la fila de Windows (comando en D6). El guion tiene unas 130 líneas, no quince: mide tres fases y trae su propio conductor.
- [ ] 1.3 Añadir el Corte 9 a `docs/plan/2026-11-24-ai-harness-cortes.md` con el orden nuevo (interfaz → puerta MVP → apariencia → experimento de agente → endurecimiento), en una revisión fechada. Hecho: la tabla lo muestra y `scripts/verify.sh` pasa.

## 2. Analizador y entrada

- [ ] 2.1 Analizador puro de líneas (D3): pregunta, comando con argumentos, `//`, línea vacía, comillas. Oráculo: tests parametrizados con los escenarios «Comando conocido», «Comando desconocido», «Pregunta que empieza por barra» y «Línea vacía». Control negativo: hacer que un comando desconocido se devuelva como pregunta y ver fallar el test.
- [ ] 2.2 Interfaz `Terminal` común y su uso desde `harness/skills/approvals.py`, en un commit que no cambia conducta. Oráculo: la batería existente pasa sin tocar ningún test de aprobación.
- [ ] 2.3 Entrada `chat` y programa sin argumentos (D1). Oráculo: tests de «Entrada con terminal» (terminal inyectada), «Entrada sin terminal» y «Sin argumentos y sin terminal» con subproceso real y entrada redirigida: código de uso y `SELECT count(*) FROM sessions` = 0. Control negativo: quitar la comprobación de terminal y ver que el subproceso crea una sesión.

## 3. Sesión de la conversación

- [ ] 3.1 Separar en `SessionService` tomar la sesión y preguntar con la sesión tomada (D4), sin cambiar `ask`. Oráculo: los tests de `ask`, de bloqueo y de recuperación pasan sin modificarse.
- [ ] 3.2 Bucle mínimo: cabecera, pregunta, respuesta, `/exit` y fin de entrada. Oráculo: tests de «Pregunta respondida», «Dos preguntas seguidas en la misma sesión», «Pregunta fallida», «Salida ordenada» y «Fin de entrada», con `SELECT status FROM requests` y el código de salida.
- [ ] 3.3 `/new`, `/sessions`, `/resume N`, `/history`, `/status` (D10). Oráculo: tests de «Sesión nueva por defecto», «Reanudar una sesión existente» y «Cambiar de sesión dentro de la conversación»; SEC-02: `/history` no muestra texto de otra sesión.
- [ ] 3.4 Dueña de su sesión (D4). Oráculo: tests con subprocesos reales de «Segunda conversación sobre la misma sesión», «Pregunta suelta sobre una sesión en conversación» (`count(*) FROM requests` sin cambios) y «Conversación muerta» (matar el proceso y preguntar después). Control negativo: soltar el bloqueo tras cada pregunta y ver fallar los dos primeros.

## 4. Interrupción y recursos del proveedor (4.1–4.2 BLOCKED hasta 1.2)

- [ ] 4.1 Interrupción durante una pregunta y en la espera (D6, D7). Oráculo: tests de «Interrupción después del envío» (`uncertain`, y el proveedor de prueba cuenta 1 llamada tras la pregunta siguiente), «Interrupción antes del envío», «Interrupción en la espera» y «Pregunta siguiente tras una incierta». Control negativo: reintentar la pregunta interrumpida y ver que el contador pasa de 1.
- [ ] 4.2 Prueba de extremo a extremo de la interrupción con un proceso real y la señal de interrupción entregada como en la sonda 1.2, sin código condicionado por plataforma. Si en alguna plataforma no se puede entregar a un solo proceso hijo, omitir por capacidad con motivo visible y decirlo en el recibo.
- [ ] 4.3 Abrir y cerrar recursos del proveedor (D5): operaciones opcionales en el contrato y su uso desde la conversación. Oráculo: tests de «Una apertura para varias preguntas» (el proveedor de prueba cuenta 1 apertura y 1 cierre con tres preguntas), «Cierre aunque una pregunta falle» y «Pregunta suelta sin cambios». Control negativo: no cerrar al salir y ver fallar el segundo.

## 5. Memoria, ficheros y Skills

- [ ] 5.1 Memoria del proyecto en cada pregunta y `/memory`, `/context`. Oráculo: tests de «Pregunta con memoria» (el proveedor de prueba recibe el bloque marcado; filas en `request_context`), «Sesión sin proyecto» y «Contexto a la vista» (misma salida que `memory context`). El test de huella del vault incluye la conversación.
- [ ] 5.2 `/file` y límite de entrada. Oráculo: tests de «Pregunta demasiado grande» (`count(*) FROM requests` sin cambios), «Fichero adjunto» y «Fichero que no es normal» (enlace por capacidad, binario, tubería por capacidad). El contenido del fichero no aparece en SQLite con un proveedor no sintético.
- [ ] 5.3 `/skill` con aprobación en la conversación (D8). Oráculo: tests de «Skill aprobado en la conversación» (el efecto de prueba se aplica 1 vez), «Aprobación rechazada» y «Línea que parece una aprobación» (escribir el código como línea normal no aplica el efecto). Control negativo: aceptar el código fuera del aviso y ver que el efecto se aplica.

## 6. Salida segura

- [ ] 6.1 Prefijos y saneado (D9). Oráculo: tests de «Respuesta con secuencias de control» (los bytes de salida no contienen ESC ni caracteres de control) y «Respuesta que imita al harness» (toda línea ajena lleva el prefijo del proveedor). Control negativo: imprimir sin prefijo y ver fallar el segundo. Test de tiempo lineal con 1 MiB de texto adversario.

## 7. Documentación, integración y demo

- [ ] 7.1 `README.md`: cómo entrar, la lista de comandos, qué hace Ctrl+C, que la conversación ocupa su sesión, y qué no hace esta versión. Hecho: los ejemplos funcionan copiados tal cual, y están escritos para PowerShell y para un shell POSIX donde difieren.
- [ ] 7.2 Sin código condicionado por plataforma. Oráculo: `tests/unit/test_portability.py`. Control negativo: añadir una rama por plataforma en `harness/shell/` y ver fallar el test.
- [ ] 7.3 `scripts/demo_interactive_shell.py`: recorre con la terminal inyectada entrada, dos preguntas, `/context`, un Skill con aprobación, `/history` y salida, y termina en `demo: PASS`. Imprime, como instrucciones, los comandos para hacerlo a mano.
- [ ] 7.4 `scripts/verify.sh` sobre el árbol limpio. Oráculo: línea `verify: PASS on <SHA>`. Control negativo: romper un escenario en un worktree desechable y ver que termina distinto de 0.
- [ ] 7.5 Confirmación opcional en Windows (no bloquea el corte): `uv run pytest` y la conversación a mano en PowerShell, incluida una interrupción con Ctrl+C. Estado: PASS, FAIL, NOT RUN o BLOCKED.
- [ ] 7.6 Demo del Corte 9. Wilson reproduce, con el SHA de 7.4, en una terminal real: (a) entrar con el programa sin argumentos; (b) dos preguntas en una sesión con proyecto; (c) `/context`; (d) `/skill architecture-memory` y aprobar escribiendo los 8 caracteres; (e) interrumpir una pregunta lenta con Ctrl+C y seguir; (f) `/exit`, volver a entrar con `--session` y ver `/history`. Evidencia: lo que muestra la terminal, sin contenido real. Estado: PASS, FAIL, NOT RUN o BLOCKED.

## Workflow follow-up

- Mantener Edge abierto durante la conversación se implementa en `copilot-web-provider` cuando esté mergeado, con la premisa P2 medida.
- La demo manual de `mvp-without-ea` pasa a hacerse dentro de la conversación.
- Cerrar la rama con `git flow feature finish interactive-shell` tras la aprobación de Wilson; archivar el change cuando la demo esté en PASS.
