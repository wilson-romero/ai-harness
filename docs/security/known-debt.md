# Deuda conocida

Lo que el harness no hace, no prueba o hace de forma más débil de lo que un lector supondría, con la decisión tomada o pendiente. Escrita el 2026-11-25 sobre `develop` = `ee550b6` (`v0.2.0`) y actualizada el 2026-11-27 tras mergear `develop` (`57c413d` y después `1b460ea`, con los botones de aprobación y la guarda de SQL literal) y corregir los hallazgos de la revisión de seguridad de ese día. Complementa la [matriz SEC](sec-matrix.md); no repite el [`README.md`](../../README.md) ni [`SECURITY.md`](../../SECURITY.md).

Decisiones posibles: **aceptado** (se convive con ello, escrito), **arreglar** (en el change que se nombra), **pendiente de Wilson**, **aplazado (proyecto educativo)**. El dueño de todas las decisiones es Wilson.

## 1. La aprobación no prueba que haya una persona delante

- **Qué:** una aprobación se concede escribiendo en una terminal interactiva los 8 primeros caracteres del hash de la propuesta. Se registra el usuario local, que no es una autenticación.
- **Riesgo:** un programa que corre con tu misma cuenta y maneja una pseudoterminal puede leer la propuesta y escribir el código: puede aprobar en tu nombre, también la escritura de la nota en el vault. Desde `develop` = `1b460ea`, la caja de aprobación de la pantalla completa aprueba o rechaza con botones (la auditoría anota `means=button` o `means=code`); el código escrito sigue en texto plano y en la línea de órdenes. Un programa que maneja la terminal de la persona puede pulsar ese botón exactamente igual que podría escribir el código: un botón no añade ninguna prueba de que haya una persona. Además, el camino real de la terminal (`isatty()` e `input()`) no lo ejercita ningún test automático: los tests usan una terminal inyectada.
- **Decisión:** aceptado por Wilson el 2026-11-24 para el MVP. Un canal más fuerte (diálogo del sistema, segundo dispositivo) necesitaría un change propio.
- **Dueño:** Wilson.

## 2. El perfil dedicado de Edge guarda las cookies de sesión con una clave fija

- **Qué:** en macOS, Edge se lanza con opciones que hacen que las cookies del perfil dedicado se cifren con una clave fija en lugar de la del llavero del sistema (en `develop` desde el merge de `copilot-web-provider`).
- **Riesgo:** quien copie la carpeta del perfil (`HARNESS_DATA_DIR`) puede usar la sesión iniciada de Copilot sin la contraseña ni el MFA.
- **Decisión:** Wilson decidió el 2026-11-25 mantenerlo para no perder la sesión iniciada; se revisa cuando la sesión caduque. El texto que lo sostiene está en `SECURITY.md` («Perfil dedicado de Edge») y en el design de `copilot-web-provider`.
- **Dueño:** Wilson.

## 3. Windows: lo que no se ha ejecutado o solo en parte

- **Qué:**
  - En un PC personal con Windows, sobre `develop` = `57c413d` (2026-11-27): la batería sin tests de navegador dio 1592 pasados, 17 omitidos y 1 fallo por carga (`tests/integration/test_mcp_cli.py::test_a_tool_that_never_ends` venció su plazo y pasó 5 de 5 solo); todas las demos, `demo: PASS`. Los tests con marca `edge` **no se ejecutaron** (NOT RUN, falta de disco), así que Copilot Web, el lanzador de Edge y su sandbox no se han probado en Windows.
  - Segunda ejecución, sobre `develop` = `79cde60` (2026-11-27, Windows 11, con Edge): 5 fallos sin navegador y 1 con Edge.
    - Tres son del producto: `private_file` ante una carpeta (otro error que en POSIX), el armado de la caja de aprobación solo por reloj (unas teclas llegadas tras el plazo aprobaron en una máquina lenta) y el perfil de Edge en uso, que en Windows no se reconocía.
    - Dos son tests que no esperaban a la caja montada.
    - Las correcciones están en `bugfix/windows-parity-2` y su ejecución en Windows está **NOT RUN**.
  - Lo que solo existe en `feature/hardening` (la comprobación de la matriz, los tests de la revisión independiente del 2026-11-25 y las correcciones de la revisión de seguridad del 2026-11-27) no se ha ejecutado en Windows (NOT RUN).
  - El defecto de `v0.2.0` con la clave de los HMAC MCP está corregido en `0.2.1`. Para recuperar una instalación de `0.2.0` afectada, con ningún proceso del harness en marcha se borra `keys/mcp-args.key` y el siguiente `mcp call` crea otra; los HMAC guardados antes no se pueden comparar con los nuevos.
  - Probado solo en macOS, porque en Windows esos tests se omiten por capacidad: el rechazo de enlaces simbólicos, el informe de carpetas ilegibles y las comprobaciones de permisos (`0600`/`0700`, dueño de la lista MCP). Las uniones de directorio no las crea ningún test. **En Windows los modos `0600`/`0700` no se usan y el harness no fija ni comprueba ACL** (clave HMAC, logs, lista MCP, directorio de datos, base de datos, bloqueos y `copilot/login.json`): lo creado hereda los permisos de la carpeta padre.
  - Confirmaciones opcionales en Windows sin hacer: `mcp-gateway` 5.3, `skill-engine` 7.6, `architecture-skills-llm` 6.6 y 7.11 (vault en OneDrive), `copilot-web-provider` 7.4.
- **Riesgo:** algo que pasa en macOS puede fallar en Windows, como ya pasó con la clave HMAC; y en Windows los ficheros privados del directorio de datos tienen los permisos que herede la carpeta.
- **Decisión:** aceptado: Windows es confirmación opcional, no puerta de un corte (`openspec/config.yaml`).
- **Dueño:** Wilson.

## 4. Condiciones de uso de Microsoft para el acceso automatizado

- **Qué:** el harness automatiza Copilot Web con un navegador. Las condiciones de uso de los servicios de Microsoft regulan el acceso automatizado.
- **Riesgo:** usar el harness contra un servicio real puede no estar permitido por esas condiciones o por la política de la organización.
- **Decisión:** aceptado: cumplir las condiciones del servicio es responsabilidad de quien usa el harness (lo dice el README). Este documento no las interpreta.
- **Dueño:** quien use el harness; para este repositorio, Wilson.

## 5. Dependencia de funciones privadas del SDK MCP fijado

- **Qué:** `harness/mcp/transport.py` y `harness/mcp/client.py` importan funciones privadas de `mcp==2.3.0` (`_create_platform_compatible_process`, `_terminate_process_tree`, `_close_pipe`, `_drain_stdout`, `_get_executable_command`, `_group_alive`). El design de `mcp-gateway` dice que solo las usa `transport.py`; no es así, y ningún test fija esa lista.
- **Riesgo:** una versión nueva del SDK puede cambiarlas o quitarlas sin aviso, y lo que se rompería es justo el cierre del árbol de procesos y los plazos.
- **Decisión:** aceptado con la versión fijada con `==`; los tests de ciclo de vida (por ejemplo `tests/integration/test_mcp_review.py::test_a_grandchild_of_the_server_is_killed_too`) son el oráculo al subir de versión. Corregir la frase del design al archivar `mcp-gateway`: pendiente de Wilson.
- **Dueño:** Wilson.

## 6. Detección débil de decisiones duplicadas

- **Qué:** el identificador de una nota de decisión sale del proyecto y del título normalizado, y el título lo elige el modelo (`tests/integration/test_architecture_memory.py::test_the_same_title_again_is_a_duplicate_without_an_approval`).
- **Riesgo:** la misma decisión extraída otra vez con otras palabras se escribe como nota nueva; una decisión escrita a mano sin `decision_id` tampoco se detecta.
- **Decisión:** aceptado y documentado en el README («Deduplicación»).
- **Dueño:** Wilson.

## 7. Enterprise Architect en pausa

- **Qué:** `ea-read`, `ea-test-write` y `architecture-skills-ea` no se han empezado (solo la sonda escrita de `ea-read`).
- **Riesgo:** SEC-11 y la parte de COM de SEC-10 no tienen ninguna prueba.
- **Decisión:** pausado por Wilson el 2026-11-25 hasta tener EA instalado; se retoma con la tarea 1.2 de `ea-read`.
- **Dueño:** Wilson.

## 8. Cerrado: el stderr de los servidores MCP se guarda redactado

- **Qué:** `HARNESS_DATA_DIR/logs/mcp/<servidor>.stderr.log` guardaba el stderr tal cual. Desde la revisión de `mcp-gateway` del 2026-11-25 (en `develop`) se guarda línea a línea con las credenciales de formato conocido redactadas, y desde el 2026-11-27 se quitan antes las secuencias de escape de la terminal, que dejaban en claro una credencial pegada a un color.
- **Riesgo que queda:** lo que la redacción del stderr no cubre (`SECURITY.md`): formatos desconocidos, una credencial con un carácter invisible dentro, una cadena hecha a mano de credenciales pegadas, una clave de más de 32 KiB.
- **Decisión:** redactar al guardar (hecho). Se lista para que nadie lo reabra.
- **Dueño:** Wilson.

## 9. Un proceso que escapa del grupo o del Job Object sobrevive

- **Qué:** un proceso que un servidor MCP lance en otra sesión (`setsid`) o fuera del Job Object no se termina, y la auditoría dice `server_stopped = 1` (`tests/integration/test_mcp_review.py::test_a_grandchild_in_its_own_session_escapes_as_documented`).
- **Riesgo:** un servidor de terceros puede dejar procesos vivos sin que el harness lo vea.
- **Decisión:** aceptado y documentado en `SECURITY.md`; añade a la lista solo servidores en los que confíes.
- **Dueño:** Wilson.

## 10. Medición sobre el vault real sin hacer

- **Qué:** el rendimiento y los saltos de la lectura de memoria no se han medido sobre el vault real de Wilson (follow-up de `project-memory`, NOT RUN).
- **Riesgo:** con archivos a petición (OneDrive, iCloud), leer todas las notas puede descargar el vault entero; no está medido.
- **Decisión:** pendiente de Wilson (medir, o cerrarlo como no aplicable a un proyecto que solo usa prompts sintéticos).
- **Dueño:** Wilson.

## 11. Cerrado: argumentos MCP con HMAC y clave local

- **Qué:** los argumentos de cada llamada MCP se guardaban como SHA-256 sin sal; desde `mcp-gateway` 6.11 son un HMAC con una clave local aleatoria.
- **Decisión:** hecho. Se lista para que nadie lo reabra.
- **Dueño:** Wilson.

## 12. Revisión de seguridad del 2026-11-27: hallazgos y estado

Una revisión de seguridad de `develop` (sobre `5af28ed`, con datos sintéticos y el Mock) encontró 7 hallazgos de severidad baja y 2 pendientes de validar; ninguno permite saltarse la aprobación por hash, ejecutar código ni escribir fuera del vault o del directorio de datos. Cada uno se volvió a comprobar sobre el árbol con `develop` mergeado y se corrigió en `feature/hardening` (tareas 5.1–5.9 de `openspec/changes/hardening/tasks.md`, con el test que lo vio fallar antes de corregirlo):

| Hallazgo (en términos generales) | Estado |
|---|---|
| F-01 · Los tokens de GitLab del formato actual, más largo, no se redactaban. | Corregido. Límite: un cuerpo de más de 300 caracteres no se reconoce. |
| F-02 · En el log de stderr MCP, una credencial pegada a una secuencia de escape no se redactaba. | Corregido: las secuencias se quitan antes de redactar. |
| F-03 · `ask` e `history` imprimían el texto del proveedor sin limpiar las secuencias de la terminal. | Corregido, con la misma limpieza que la conversación. |
| F-04 · El aviso de aprobación de `skill run`/`skill resume` no marcaba como ajeno el contenido del modelo, que podía dibujar un final de aviso falso. | Corregido: cada fila del contenido lleva `| ` o `|+`; lo aprobado y su hash no cambian. |
| F-05 · El tope de la respuesta de Copilot solo existía en el JavaScript de la página. | Corregido: se aplica también en Python y lo cortado se avisa. |
| F-06 · `scripts/verify.sh` reescribía un `uv.lock` desfasado antes de comprobarlo. | Corregido: el lock se comprueba primero, `UV_LOCKED=1` impide reescribirlo y la puerta falla si el árbol cambia. |
| F-07 · `memory maintain --dry-run` crecía de forma superlineal con el vault. | Corregido en parte (enlaces lineales, una búsqueda por nombre) y acotado (100 000 pares por pasada, con aviso): ver el punto 13. |
| F-08 (pendiente de validar) · El directorio de datos, la base, los bloqueos y `copilot/login.json` se creaban legibles por otros. | Confirmado el modo (0755/0644 con umask 022 en macOS); no se comprobó si otra cuenta de la máquina llega a la carpeta. Corregido: se crean solo para su dueño. Lo que ya existía conserva sus permisos; en Windows los modos no se usan (punto 3). |
| F-09 (pendiente de validar) · Un emoji con selector de presentación se contaba más estrecho de lo que se dibuja, y una fila ajena podía empezar sin marca en `chat --plain`. | Confirmado con la medida de anchura de Rich; no observado en emuladores reales. Corregido: el selector cuenta una columna. |

- **Dueño:** Wilson.

## 13. Trabajo cuadrático que queda acotado, no eliminado

- **Qué:** `memory maintain --dry-run` compara cada par de notas de `Memoria-CC/` para proponer duplicados: es cuadrático por naturaleza. Desde el 2026-11-27 cada pasada se para a los 100 000 pares (unas 450 notas curadas; unos 2,5 s en la Mac), lo que encontró se mantiene y un aviso por stderr dice que el informe está incompleto. La búsqueda de encabezados de un paso `validate` usa una expresión regular con retroceso cuadrático en el peor caso (segundos con 16 KiB de entrada hostil; mucho más cerca del límite de tamaño), retiene el GIL y no tiene plazo por paso.
- **Riesgo:** un vault muy grande da un informe de duplicados incompleto (avisado); una salida del modelo hostil puede tener ocupado un paso `validate` mucho tiempo, hasta que la persona lo interrumpe.
- **Decisión:** el primero, aceptado con el tope y el aviso. El segundo, pendiente de Wilson (reescribir la búsqueda sin retroceso y dar un plazo al paso, en un change propio).
- **Dueño:** Wilson.

## 14. Endurecimiento señalado por la revisión del 2026-11-27, sin camino de ataque demostrado

- **Qué:** la allowlist de URL compara solo el nombre del host (no el esquema ni el puerto); algunas opciones predeterminadas de Playwright siguen activas y conviene revisarlas; el cuerpo de una nota puede imitar la cabecera de nota del contexto de memoria; el listado de decisiones aplica su tope antes de filtrar y la deduplicación por hash de origen no se vuelve a comprobar bajo el bloqueo; una carrera en la recuperación puede pasar a `uncertain` una sesión ya cerrada; el guard de seguridad pública tiene huecos (ficheros en UTF-16, nombres de fichero de credenciales, cambios de tipo, y el hook es opcional); no hay una edad mínima para las dependencias nuevas; y varias asperezas menores (el entorno completo del proceso de sesión MCP, un doble Enter rápido en la pantalla completa, Ctrl+C durante la espera de un efecto ocupado).
- **Riesgo:** cada uno debilita un control sin un camino de ataque demostrado en el modelo de amenaza del proyecto (una sola persona, su propia cuenta).
- **Decisión:** pendiente de Wilson: cada uno, si se aborda, en un change propio.
- **Dueño:** Wilson.

## 15. Carpeta de trabajo: la carrera que queda abierta y Windows sin ejecutar (rama `feature/workspace-tools`)

- **Qué:**
  - **La carrera.** Entre el paseo componente a componente y la apertura de un fichero de la carpeta de trabajo, otro proceso con la cuenta de la persona puede cambiar una carpeta intermedia por un enlace. El harness detecta:
    - el cambio del fichero mismo: la identidad sobre el descriptor, `O_NOFOLLOW` y la nueva resolución dentro de la carpeta;
    - el de la carpeta raíz: su identidad se comprueba en cada llamada.

    Pero no puede cerrar la ventana de las carpetas intermedias: `os.open` no admite `dir_fd` en Windows, así que no hay `openat` portable.
  - **Windows.** En Windows no se ha ejecutado nada de este tramo (NOT RUN). Las uniones reales, `st_nlink` en NTFS, los nombres cortos 8.3, los flujos alternativos y las rutas largas se rechazan por regla y se prueban simulados en macOS.
- **Riesgo:**
  - un proceso local que ya tiene la cuenta de la persona podría hacer leer al harness un fichero de fuera de la carpeta. Ese proceso podría leerlo igualmente sin el harness;
  - una diferencia de conducta del sistema en Windows que la simulación no reproduzca.
- **Decisión:** aceptado. El atacante de este diseño es el contenido de la carpeta, no un proceso concurrente. Las órdenes para el PC de pruebas están en `docs/runbook/workspace-tools.md` («Windows») y en `openspec/changes/workspace-tools/tasks.md` 8.1 y 8.2.
- **Dueño:** Wilson.

## Fuera del alcance: aplazado (proyecto educativo)

Decidido por Wilson el 2026-11-25: el proyecto sirve para aprender a construir un harness, no para producción. Se aplaza lo que solo sirve para operar en producción:

- **Copia y restauración de `HARNESS_DATA_DIR`.** Los datos de un piloto con prompts sintéticos se regeneran. Lo que hay en el directorio (base SQLite, bloqueos, clave HMAC, logs de stderr MCP, el perfil de Edge y `copilot/`) no se copia fuera de la máquina.
- **Retención y purga de filas de SQLite.** La base crece sin límite.
- **Rotación de logs.** Solo existe la de una generación (`.1`) de los logs de stderr MCP, que ningún test comprueba.
