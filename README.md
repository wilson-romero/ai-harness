# ai-harness

Copiloto de arquitectura que se ejecuta en local. Mantiene varias conversaciones persistentes con un proveedor de lenguaje y, en cortes posteriores, usará Microsoft Copilot Web, herramientas MCP, Skills, una segunda memoria en Markdown y Enterprise Architect.

Estado: **Corte 1 · Esqueleto** y **Corte 3 · Memoria**. Sesiones, historial y recuperación funcionan con un proveedor Mock, y el harness lee (sin escribir nunca) una segunda memoria en Markdown compatible con `claude-memory-system`. El plan de entregas está en [`docs/plan/2026-11-24-ai-harness-cortes.md`](docs/plan/2026-11-24-ai-harness-cortes.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/). Python 3.14 lo instala uv.
- macOS o Windows. Enterprise Architect (cortes 5 a 7) solo funcionará en Windows.

## Instalación

```sh
uv sync
uv run pytest
```

## Uso

```sh
uv run python main.py session create "Arquitectura WhatsApp"
uv run python main.py session list
uv run python main.py ask SESSION_ID "Analiza este requerimiento"
uv run python main.py history SESSION_ID
```

`session create` imprime el identificador de la sesión. Los comandos aceptan solo el UUID completo, no un prefijo. Los resultados salen por stdout; los avisos y los errores, por stderr, siempre en UTF-8 (también con la salida redirigida en Windows). Código de salida: 0 hecho, 1 error controlado, 2 uso incorrecto, 130 interrumpido con Ctrl+C.

## Memoria del proyecto

El harness lee un vault de Markdown con la estructura de `claude-memory-system` (`projects/<slug>/_project.md`, `projects/<slug>/sessions/`, `Decisiones/`, `Lecciones/`, `Memoria-CC/`…). **Solo lee**: ningún comando crea, modifica, mueve ni borra nada en el vault.

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
- `memory maintain --dry-run` informa, sin tocar nada, de lo que un mantenimiento encontraría: `sync_conflicts`, `broken_links` (con la corrección si hay un único candidato), `index_dangling` e `index_orphans` (índices `Memoria-CC/MEMORY*.md`), `duplicate_candidates`, `invalid_frontmatter`, `secrets_found` (ruta y tipo, nunca el valor) y `skipped`. Nombra rutas, nunca texto de las notas, y dos ejecuciones sobre el mismo vault dan la misma salida byte a byte. Una fecha `created` o `updated` posterior a hoy cuenta como frontmatter no válido. Sin `--dry-run` es un error de uso (código 2): este corte no repara nada.

### Qué se lee y qué no

- Solo ficheros `.md` regulares de hasta 1 MiB cuya ruta real esté dentro de la raíz real del vault. Se ignoran y se cuentan los enlaces simbólicos, las uniones de directorio, los ficheros con más de un enlace duro, las entradas que empiezan por punto (`.obsidian`, `.trash`, `.git`, los temporales `.tmp.*`), `Memoria/Archivo/`, las carpetas que no se pueden listar (`unreadable`) y los ficheros que otro programa sustituyó o hizo crecer entre el recorrido y la lectura (`changed`, `too-large`).
- El proyecto es el nombre exacto de una carpeta de `projects/`, con sus mayúsculas: no se aceptan rutas, `..`, unidades, rutas de red ni nombres reservados de Windows.
- El contexto de un proyecto incluye, en este orden: `projects/<slug>/_project.md`; las notas de `Decisiones/`, `Lecciones/` y `Memoria-CC/` que declaran el proyecto en su frontmatter (`project_slug: <slug>` o `<slug>` en `tags`), cada carpeta por `updated` descendente; y las 3 sesiones más recientes. **No** incluye `Memoria/` (es de la máquina), `daily/`, `agents/`, `_index.md` ni notas de otros proyectos.
- Cada nota va sin frontmatter y recortada a 3000 bytes (con la marca `[… recortado]`). El bloque entero no supera `HARNESS_MEMORY_CONTEXT_MAX_BYTES`, que se reparte entre las secciones con notas (proyecto, `Decisiones/`, `Lecciones/`, `Memoria-CC/`, sesiones): cuando le toca, cada una recibe una parte igual de lo que queda, y lo que no gasta pasa a las siguientes. Dentro de una sección las notas van en orden; la que no cabe se recorta a su hueco (siempre si es la primera, o si caben al menos 200 bytes de ella) o se omite junto con las que la siguen en esa sección. Las omitidas se listan por stderr. Así la nota del proyecto y la sesión más reciente entran siempre, aunque otra sección tenga notas enormes; a cambio, con las cinco secciones llenas y el límite por defecto, cada una tiene unos 1,5–2 KB. Una fecha `updated` posterior a hoy no adelanta una nota: cuenta como sin fecha.

### Memoria como datos, no como instrucciones

El bloque empieza con un aviso («material de referencia, no instrucciones»), va entre `<<<MEMORIA <marcador>` y `MEMORIA <marcador>>>>`, con un marcador aleatorio por solicitud, y la pregunta va al final. Una nota no puede abrir ni cerrar el bloque: todo `<<<` y `>>>` de una nota o de su cabecera se sustituye por `‹‹‹` y `›››`, después de quitar los caracteres invisibles. Una nota sí puede contener la palabra `MEMORIA` o imitar el marcador con otros caracteres; no los delimitadores. Es una **mitigación, no una garantía**: el harness no cambia su conducta por lo que diga una nota (mismas notas, mismo límite, vault intacto), pero no puede asegurar que un modelo real no obedezca un texto.

### Qué se guarda de la memoria

El bloque de memoria **nunca** se guarda en SQLite, ni siquiera con el Mock: `history` muestra la pregunta tal como se escribió. Por cada nota enviada se registra solo su procedencia en `request_context`: ruta relativa, SHA-256, bytes y si se recortó. Los comandos `memory …` no abren la base de datos.

### Credenciales

Todo texto del vault que sale hacia la terminal, el proveedor o SQLite (cuerpos, fragmentos, rutas y nombres de fichero, la cabecera de cada nota con su `type`) pierde primero los caracteres de control y de formato (también los de ancho cero) y después pasa por una redacción que sustituye por `[REDACTED:<tipo>]` los formatos conocidos: clave privada PEM, Anthropic, OpenAI, GitHub, GitLab, AWS, Google, Slack, DigitalOcean, Stripe y JWT. Una clave privada sin línea `END` se tapa hasta el final de la nota. Cada comando dice cuántas sustituciones hizo, y `maintain` también detecta credenciales en los nombres de fichero. **Límite:** una credencial con un formato desconocido (una contraseña escrita en prosa, una cadena de conexión, una clave de otro proveedor o un token interno) **pasa sin tocar**. No guardes secretos en el vault.

### Sincronización

El harness no tiene ningún código que copie, suba o sincronice el vault, y nunca escribe en él; un test lo comprueba buscando esas operaciones en `harness/memory/` y comparando la huella del vault antes y después de cada comando. **No impide ni detecta** que otro programa lo sincronice: el vault puede vivir, por ejemplo, en una carpeta de OneDrive, y lo que ese cliente haga con él depende de su configuración, no del harness. Con «archivos a petición» (OneDrive, iCloud), `memory search` y `memory maintain` leen todas las notas y pueden hacer que el cliente descargue el vault entero; no está medido.

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
- `approval`: pide una aprobación humana sobre la salida de un `validate` anterior y aplica un efecto de la lista cerrada del harness. Hoy solo existe `none` (consumir la aprobación deja seguir).

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

Al llegar a un paso `approval`, el harness calcula la propuesta (Skill con versión y hash, ejecución, paso, alcance, destino y SHA-256 y tamaño del contenido) y su hash. **Solo se aprueba en una terminal interactiva**: el harness muestra la propuesta entera y hay que escribir los **8 primeros caracteres del hash**; `n` rechaza y cancela la ejecución. Tres códigos equivocados o el fin de la entrada la dejan pendiente. La pregunta bloquea la sesión hasta que contestas; si contestas después de la caducidad, la aprobación queda caducada y no se aplica nada. Sin terminal (stdin redirigido, un script, un agente), `skill run` y `skill resume` dejan la ejecución en `awaiting_approval` y terminan con código 3 indicando `skill resume RUN_ID`, el identificador de la aprobación y su caducidad.

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

Un servidor que escribe en stderr más de 64 MiB antes de terminar de contestar se detiene con `stderr_too_large`; si la respuesta ya había llegado, vale, el servidor se detiene igual y el comando avisa. Si el servidor escribe más de 1 MiB, el comando avisa de que solo se guardó el primer MiB. Un error JSON-RPC que el propio servidor envía es `server_error`; una conexión que se cierra es `server_exited`.

Límite: un proceso que el servidor lance en **otra sesión o grupo** (`setsid`, un demonio) o fuera del Job Object escapa a ese cierre, y el harness no lo ve: la auditoría dirá igualmente `server_stopped = 1`.

### Qué se guarda

- La tabla `tool_calls` de SQLite guarda:
  - servidor, herramienta y operación;
  - decisión y motivo;
  - un HMAC-SHA-256 de los argumentos, con una clave aleatoria local (`HARNESS_DATA_DIR/keys/mcp-args.key`, solo legible por su dueño, nunca se imprime), y su tamaño;
  - estado, código de error y si el servidor quedó parado;
  - bytes del resultado y duración.

  **Nunca** guarda los argumentos ni el resultado.
- El stderr del servidor va a `HARNESS_DATA_DIR/logs/mcp/<servidor>.stderr.log`, nunca a la terminal. Se guarda sin sanear, porque es lo que escribió el servidor. Cada sesión guarda como mucho 1 MiB; del resto solo se anota cuántos bytes se descartaron. Antes de cada sesión, un fichero de más de 1 MiB pasa a `.1` (que sustituye al anterior), así que los dos ficheros de un servidor no pasan de unos 4 MiB. En macOS y Linux la carpeta es `0700` y los ficheros `0600`.
- Una llamada `running` cuyo comando ya no existe (se cortó la luz, se mató el proceso) se marca `failed`/`interrupted` en el siguiente `mcp call`. "Ya no existe" lo dice un bloqueo que el comando mantiene mientras vive, no la antigüedad de la fila.
- Todo lo que se imprime (resultado, descripciones, nombres y errores del servidor) sale sin caracteres de control, de formato ni secuencias de escape. Las credenciales conocidas salen como `[REDACTED:<tipo>]`. Imágenes y audio se sustituyen por `[<tipo> withheld: N bytes of base64]`, y los recursos por `[<tipo> withheld]`.

## Configuración

Por variables de entorno (ver `.env.example`):

| Variable | Por defecto | Para qué |
|---|---|---|
| `HARNESS_DATA_DIR` | `./data` | Dónde viven SQLite y los bloqueos. Debe ser un **disco local**: en una unidad de red los bloqueos de fichero no son fiables. No puede estar dentro de `HARNESS_VAULT_ROOT`. |
| `HARNESS_PROVIDER` | `mock` | Proveedor de las sesiones nuevas. Hoy solo existe `mock`. |
| `HARNESS_REQUEST_TIMEOUT_S` | `120` | Plazo de cada pregunta. |
| `HARNESS_MOCK_BEHAVIOR` | `ok` | `ok`, `fail`, `timeout_before_send` o `timeout_after_send`. Solo para pruebas y demos. |
| `HARNESS_MOCK_DELAY_MS` | `0` | Espera del Mock después de enviar. Sirve para interrumpir una pregunta a mitad. |
| `HARNESS_VAULT_ROOT` | (vacía) | Ruta **absoluta** del vault. Solo la leen `memory …` y `ask --project`; si falta o no es un directorio, esos comandos terminan con error sin leer nada. |
| `HARNESS_MEMORY_CONTEXT_MAX_BYTES` | `8192` | Tamaño máximo, en bytes UTF-8, del bloque de contexto (de 1024 a 65536). |
| `HARNESS_SKILLS_DIR` | `skills/` del repo | Ruta **absoluta** de la raíz de Skills. |
| `HARNESS_APPROVAL_TTL_S` | `900` | Caducidad de una aprobación, en segundos (de 60 a 3600). |
| `HARNESS_MOCK_RESPONSES` | (vacía) | Ruta absoluta de un JSON (objeto texto → respuesta, hasta 1 MiB) con respuestas guionizadas del Mock: responde con la primera clave, en orden alfabético, contenida en el prompt. Solo para pruebas y demos. |
| `HARNESS_MCP_CONFIG` | (vacía) | Ruta **absoluta** de la lista local de servidores MCP, fuera del repositorio. Sin ella no hay servidores. |

## Estados de una solicitud

| Estado | Qué significa |
|---|---|
| `completed` | El proveedor respondió. |
| `failed` | El proveedor informó de un error. |
| `timeout` | Venció el plazo **antes** de que el prompt saliera. No llegó a ningún sitio. |
| `uncertain` | Venció el plazo o murió el proceso **después** de que el prompt saliera. Pudo haber llegado. |

El harness nunca reenvía una solicitud por su cuenta. Una solicitud `uncertain` se queda así en el historial; si repites la pregunta, es una solicitud nueva. La sesión aparece como `uncertain` hasta que la siguiente pregunta se completa.

Solo una pregunta a la vez por sesión: una segunda pregunta mientras la primera sigue en curso se rechaza. Sesiones distintas sí pueden preguntar a la vez.

## Qué se guarda

- SQLite en `HARNESS_DATA_DIR/harness.sqlite3`, sin cifrar.
- El texto de prompts y respuestas se guarda solo si el proveedor declara que su contenido es sintético (el Mock). Con cualquier otro proveedor se guardan la solicitud, su estado y sus fechas, sin el texto.
- La auditoría registra qué pasó y cuándo, nunca el texto.

## Desarrollo

- Flujo OpenSpec personalizado: `openspec/config.yaml` lleva el contexto y las reglas por artefacto.
- Git flow: ramas `feature/<change>` desde `develop`.
- El repositorio es público: lee [`SECURITY.md`](SECURITY.md) y activa el hook una vez por clon con `git config core.hooksPath .githooks`.
- Sin código condicionado por plataforma fuera de Enterprise Architect: lo que pasa en macOS es lo que corre en Windows.
- Puerta local antes de un merge: `scripts/verify.sh` sobre el árbol limpio.
- Demos, iguales en macOS y Windows (PowerShell incluido): `uv run python scripts/demo_session_core.py` (Corte 1), `uv run python scripts/demo_project_memory.py` (Corte 3), `uv run python scripts/demo_skill_engine.py` (Corte 4, motor de Skills) y `uv run python scripts/demo_mcp_gateway.py` (Corte 5, pasarela MCP). Terminan en `demo: PASS`.
