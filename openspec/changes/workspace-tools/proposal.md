# Proposal

## Why

Hoy el harness no tiene **ninguna** herramienta para leer, buscar, crear ni editar ficheros fuera del vault. `harness/` no tiene herramientas de ficheros. Las únicas escrituras de producto son la nota de decisión del vault y los ficheros del directorio de datos (grep de la tarea 1.1). El plan JSON de code mode (`ai-harness/plan/1`) solo llama a herramientas MCP de lectura, y la pasarela deniega toda escritura (`write_requires_approval`). El dueño aprobó el 2026-11-27 una hoja de ruta para que el harness trabaje como OpenCode. Esta es su **fase B**: herramientas de ficheros dentro de una **carpeta de trabajo** que la persona elige, que se puedan usar desde el bucle de planes JSON (fase A, `code-mode`, notas «Hoja de ruta» y «Requisitos para los tramos siguientes»).

Tres cifras, medidas el 2026-11-27 en macOS sobre `origin/develop` = `a9c51fe` (tarea 1.2 guarda el recibo), condicionan el diseño:
- El lector del plan rechaza como `invisible_character` toda cadena con `\n`, `\t` o `\r\n` (`harness/mcp/plan.py`, `string_refusal`). Si el contenido de un fichero fuera una cadena, no se podría escribir ninguna línea de código.
- `normalise_content` convierte `"a\tb\r\nc"` en `"a b\nc"`. La `Proposal` de los Skills cambia los bytes del código, así que no sirve para aprobar un cambio en un fichero.
- Un plan cabe en **16 384** bytes y tiene como mucho **10** pasos (`MAX_PLAN_BYTES`, `MAX_STEPS`). Una `Proposal` cabe en **32 768** bytes (`MAX_CONTENT_BYTES`).

## What Changes

- **Carpeta de trabajo por sesión.** La persona la elige con `/workspace <ruta>` en la conversación y con `--root <ruta>` en la CLI. No hay valor por defecto ni variable de entorno. Se rechaza en estos casos:
  - es el repo del harness, el directorio de datos o el vault, está dentro de alguno de ellos o contiene alguno;
  - es la carpeta personal misma o la raíz de un sistema de ficheros;
  - es un enlace o una unión.

  Se ve en el panel lateral y en `/status`, y se puede cambiar entre preguntas.
- **Confinamiento de rutas, el mismo código en macOS y en Windows:**
  - solo rutas relativas con `/`;
  - sin `..`, sin `:`, sin nombres reservados, sin punto ni espacio al final;
  - en NFC y con el nombre exacto que da `os.listdir`, sin variantes de mayúsculas;
  - ningún componente puede ser un enlace o una unión;
  - un fichero con más de un enlace duro no se lee ni se escribe;
  - la identidad del fichero se comprueba sobre el descriptor abierto.
- **Reglas fijas que se aplican también dentro de la carpeta.** Nunca se lee ni se escribe:
  - el interior de `.git/`;
  - `.env*` y los nombres de claves y credenciales de una lista cerrada;
  - un fichero cuyo contenido tenga la forma de una credencial que conoce el redactor;
  - un fichero binario, o que no sea UTF-8 válido;
  - un fichero de más de 256 KiB.

  Tampoco se escribe en un componente oculto (`.github/`, `.vscode/`).
- **Lecturas automáticas por regla y auditadas:** `read` (con rango de líneas y topes), `list` (acotada, sin seguir enlaces) y, en un tramo posterior, `glob` y `grep` (literal por defecto, con una sintaxis de regex acotada). Su salida se sanea, se redacta y se acota antes de mostrarla o devolverla.
- **Un servidor interno `workspace` en el catálogo del plan.** No es MCP. Sus herramientas son una tabla literal en el código y pasan por la misma política y la misma auditoría: filas en `tool_calls` con el HMAC de los argumentos y ningún contenido. El nombre `workspace` queda reservado en la lista MCP local.
- **Escrituras siempre aprobadas:**
  - `write` solo crea un fichero nuevo;
  - `edit` sustituye un texto exacto que tiene que aparecer una sola vez, o todas las veces con `replace_all`.

  El contenido viaja como **lista de líneas**, así que el plan no cambia de formato. Cada escritura es un efecto con `prepare`, `apply` y `reconcile`. Todas las escrituras de un plan forman **una lista de efectos y una sola aprobación**. La caja muestra el diff exacto de cada fichero, sin plegar, y la aprobación va ligada a un hash propio: rutas, bytes nuevos enteros, SHA-256 del contenido anterior, modo y fin de línea. Si el fichero cambió desde `prepare`, se rechaza. La escritura es atómica: temporal en la misma carpeta y `os.replace`.
- **`/undo` del último cambio aplicado.** La copia previa se guarda en el directorio de datos, solo para el dueño, con tope de tamaño y de antigüedad. Deshacer se muestra como un diff y se aprueba como cualquier escritura.
- **Con el bucle:** una escritura siempre lo para en la caja. El modelo recibe `applied`, `rejected`, `refused` con su motivo o `uncertain`, y nunca contenido. Enviar el contenido de los ficheros a un proveedor que no sea el Mock exige un **consentimiento por carpeta**.
- **Fila nueva de la matriz SEC** para las escrituras en la carpeta de trabajo (design D17). Hasta que la apruebe el dueño, la numeración se decide al mergear: `code-run` propone la SEC-16.

## Qué NO entra en el alcance

- **No hay sandbox.** El harness no encierra nada. Lo que se escribe con aprobación puede ser código que otra herramienta de la persona ejecute después (un `Makefile`, un `package.json`, un test): el harness no lo sabe ni lo impide. Lo dice la caja.
- No hay `delete`, `move`, `chmod`, `patch` multifichero ni ninguna orden de shell. Tampoco ejecución: eso es `code-run` y la fase C, «órdenes con nombre». La única retirada de un fichero es `/undo` de un fichero que el propio harness creó, si sus bytes siguen siendo los que escribió.
- No hay ediciones aproximadas (los «replacers» de OpenCode) ni reparación de argumentos.
- No se interpreta `.gitignore`: un fichero ignorado por git se lee si no lo prohíbe una regla fija (decisión abierta 2). Tampoco hay imágenes, PDF, cuadernos ni LSP.
- `AGENTS.md` de la carpeta **no** se carga como instrucciones ni como datos en este change (decisión abierta 7).
- La ruta absoluta de la carpeta no se le dice al modelo, y no se le envía ningún listado de la carpeta en el catálogo.
- No se modifica ninguna capacidad vigente. Grep del 2026-11-27 sobre `openspec/specs/` (`grep -rn -i "espacio de trabajo\|carpeta de trabajo\|workspace\|editar un fichero"`): 0 aciertos. `tool-policy` y `code-mode` viven en `openspec/changes/code-mode/`, sin archivar: este change añade su propio delta y no edita los suyos.
- Una lectura «sin secretos» no está garantizada. Un secreto con forma desconocida dentro de un fichero normal se lee, y con el bucle activo se envía al modelo tras una redacción que solo conoce formas de credencial (design D5).

## Corte, riesgo, SEC y plataformas

- **Corte:** nuevo **Corte 12 · Herramientas de la carpeta de trabajo (fase B)**, que hay que añadir a `docs/plan/2026-11-24-ai-harness-cortes.md` con la aprobación de Wilson (tarea 1.3). Nota: `code-run` propone llamarse «Corte 11», pero ese número ya lo usa `response-mode`; la numeración final la fija el dueño.
- **Riesgo:**
  - **N1** en los tramos B1, B2 y B5 (lecturas confinadas y automáticas);
  - **N2** en B3 y B4 (escrituras en ficheros de la persona).
- **SEC que cubre:**
  - 01: nombres y contenidos de credencial; salida redactada;
  - 03: el contenido de un fichero es dato y nunca aprueba ni elige destino sin la caja;
  - 04: traversal, enlaces, uniones, enlaces duros, TOCTOU;
  - 05: herramienta o argumentos fuera de la tabla;
  - 07: una escritura interrumpida queda `uncertain` y no se reaplica;
  - 08: reconciliación al reiniciar;
  - 12: diff y hash exactos, uso único y caducidad;
  - 15: topes de bytes, líneas, ficheros y tiempo;
  - y la fila nueva (D17).
- **Plataformas:** la puerta es macOS. Las reglas de nombre de Windows se prueban en macOS con `PureWindowsPath` y cadenas literales. En Windows, el mismo código queda **NOT RUN** hasta ejecutarlo en el PC de pruebas: uniones, `os.replace` sobre un fichero abierto, `st_nlink`, rutas largas, flujos alternativos y la sensibilidad a mayúsculas (design D2, tabla «Qué se prueba dónde»).

## Capabilities

### New Capabilities
- `workspace-files`: elegir y mostrar la carpeta de trabajo; confinar cada ruta; las reglas fijas de lo que nunca se lee ni se escribe; las lecturas automáticas y su salida acotada; las escrituras como lista de efectos aprobada por diff y hash; deshacer; qué recibe el modelo.

### Modified Capabilities
Ninguna en `openspec/specs/` (grep de arriba). La conducta de `tool-policy` (en `openspec/changes/code-mode/`) **se amplía** con un servidor interno y escrituras aprobadas. Como esa capacidad no está archivada, sus requisitos nuevos van en `specs/workspace-files/spec.md`, que la cita, y no en un delta sobre un change abierto.

## Impact

- **Código nuevo (en la implementación, no en esta propuesta):**
  - `harness/workspace/`: carpeta, rutas, reglas fijas, lecturas, efectos, deshacer y catálogo interno;
  - `/workspace` y `/undo` en `harness/shell/commands.py`;
  - `main.py workspace …` en `harness/cli.py`;
  - una migración numerada nueva (número al implementar: 008 y 009 ya existen).
- **Código que cambia:**
  - la vista de política del plan (`harness/mcp/plan.py`, `policy.py`) admite el servidor interno y las escrituras de ese servidor, y solo de ese;
  - `config.py` reserva el nombre `workspace`;
  - `PanelState` gana el campo de la carpeta.
- **Dependencias:** ninguna nueva. Biblioteca estándar (`difflib`, `os`, `stat`, `re`, `fnmatch`) y pydantic.
- **Depende de** `feature/code-mode-loop` (A2 y A3) **solo por diseño**. B1 no lo necesita. B2 y siguientes se construyen cuando esté mergeado.
- **Documentación:**
  - `SECURITY.md` (sección «Carpeta de trabajo»);
  - `docs/security/sec-matrix.md` y `sec-states.json` (fila nueva);
  - `docs/security/known-debt.md` (sin sandbox, ventana TOCTOU residual, Windows NOT RUN);
  - `docs/runbook/workspace-tools.md`;
  - el plan por cortes.
