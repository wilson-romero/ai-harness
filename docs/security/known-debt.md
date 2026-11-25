# Deuda conocida

Lo que el harness no hace, no prueba o hace de forma más débil de lo que un lector supondría, con la decisión tomada o pendiente. Escrita el 2026-11-25 sobre `develop` = `ee550b6` (`v0.2.0`). Complementa la [matriz SEC](sec-matrix.md); no repite el [`README.md`](../../README.md) ni [`SECURITY.md`](../../SECURITY.md).

Decisiones posibles: **aceptado** (se convive con ello, escrito), **arreglar** (en el change que se nombra), **pendiente de Wilson**, **aplazado (proyecto educativo)**. El dueño de todas las decisiones es Wilson.

## 1. La aprobación no prueba que haya una persona delante

- **Qué:** una aprobación se concede escribiendo en una terminal interactiva los 8 primeros caracteres del hash de la propuesta. Se registra el usuario local, que no es una autenticación.
- **Riesgo:** un programa que corre con tu misma cuenta y maneja una pseudoterminal puede leer la propuesta y escribir el código: puede aprobar en tu nombre, también la escritura de la nota en el vault. Además, el camino real de la terminal (`isatty()` e `input()`) no lo ejercita ningún test automático: los tests usan una terminal inyectada.
- **Decisión:** aceptado por Wilson el 2026-11-24 para el MVP. Un canal más fuerte (diálogo del sistema, segundo dispositivo) necesitaría un change propio.
- **Dueño:** Wilson.

## 2. El perfil dedicado de Edge guarda las cookies de sesión con una clave fija

- **Qué:** en `feature/copilot-web-provider` (sin mergear), Edge se lanza con opciones que hacen que las cookies del perfil dedicado se cifren con una clave fija en lugar de la del llavero del sistema.
- **Riesgo:** quien copie la carpeta del perfil (`HARNESS_DATA_DIR`) puede usar la sesión iniciada de Copilot sin la contraseña ni el MFA.
- **Decisión:** Wilson decidió el 2026-11-25 mantenerlo para no perder la sesión iniciada; se revisa cuando la sesión caduque. **Pendiente de merge:** no está en `develop`.
- **Dueño:** Wilson.

## 3. Windows: lo que no se ha ejecutado o solo en parte

- **Qué:**
  - La batería de `v0.2.0` se ejecutó una vez en Windows (Wilson, 2026-11-25): 997 pasados, 13 fallados, 28 omitidos. El detalle por test no está en el repositorio.
  - Defecto de producto encontrado ahí: la clave de los HMAC MCP (`keys/mcp-args.key`) se escribe sin modo binario y en Windows sale dañada; todo `mcp call` falla. Se corrige en `0.2.1` (`hotfix/0.2.1`). Para recuperar una instalación afectada, con ningún proceso del harness en marcha se borra ese fichero y el siguiente `mcp call` crea otro; con `0.2.0` el nuevo puede volver a salir dañado (en torno a 1 de cada 8 veces), con `0.2.1` no. Los HMAC guardados antes no se pueden comparar con los nuevos.
  - Dos módulos de tests MCP no se recogían en Windows (corregido en `hotfix/0.2.1`, `871ab1b`).
  - Probado solo en macOS, porque en Windows esos tests se omiten por capacidad: el rechazo de enlaces simbólicos, el informe de carpetas ilegibles y las comprobaciones de permisos (`0600`/`0700`, dueño de la lista MCP). Las uniones de directorio no las crea ningún test. En Windows el harness no fija ni comprueba ACL (clave HMAC, logs, lista MCP).
  - Confirmaciones opcionales en Windows sin hacer: `mcp-gateway` 5.3, `skill-engine` 7.6, `architecture-skills-llm` 6.6 y 7.11 (vault en OneDrive), y las demos de los cortes.
  - El sandbox de Edge en Windows no está comprobado (rama `feature/copilot-web-provider`, pendiente de merge).
- **Riesgo:** algo que pasa en macOS puede fallar en Windows, como ya pasó con la clave HMAC; y en Windows los ficheros privados del directorio de datos tienen los permisos que herede la carpeta.
- **Decisión:** aceptado: Windows es confirmación opcional, no puerta de un corte (`openspec/config.yaml`). La clave HMAC se arregla en `0.2.1`.
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

## 8. El stderr de los servidores MCP se guarda sin redactar

- **Qué:** `HARNESS_DATA_DIR/logs/mcp/<servidor>.stderr.log` guarda hasta 1 MiB por sesión de lo que el servidor escribió en stderr, tal cual.
- **Riesgo:** un servidor que escriba una credencial en stderr la deja en claro en el disco (legible solo por su dueño en macOS y Linux).
- **Decisión:** pendiente de Wilson (redactar al guardar o aceptarlo con `0600`).
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

## Fuera del alcance: aplazado (proyecto educativo)

Decidido por Wilson el 2026-11-25: el proyecto sirve para aprender a construir un harness, no para producción. Se aplaza lo que solo sirve para operar en producción:

- **Copia y restauración de `HARNESS_DATA_DIR`.** Los datos de un piloto con prompts sintéticos se regeneran. Lo que hay en el directorio (base SQLite, bloqueos, clave HMAC, logs de stderr MCP y, con la rama de Copilot, el perfil de Edge) no se copia fuera de la máquina.
- **Retención y purga de filas de SQLite.** La base crece sin límite.
- **Rotación de logs.** Solo existe la de una generación (`.1`) de los logs de stderr MCP, que ningún test comprueba.
