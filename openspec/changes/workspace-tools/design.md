# Design

## Context

El motivo y las cifras están en `proposal.md`. Este diseño se apoya en lo que ya existe y lo mide antes de usarlo, todo en `origin/develop` = `a9c51fe`, el 2026-11-27, en macOS:

| Pieza | Dónde | Medido aquí |
|---|---|---|
| Lector del plan y reglas de sus cadenas | `harness/mcp/plan.py`: `read_plan`, `string_refusal` (D5 de code-mode) | `string_refusal("a\nb")`, `("a\tb")` y `("a\r\nb")` dan `invisible_character`; `"x = 1"` pasa. El contenido de un fichero no puede ser una cadena del plan (D8). |
| Valores de un paso | `PlanStep.arguments`: «every value a JSON scalar»; `check_arguments` solo conoce `string`, `integer`, `boolean` y `enum` | Una lista de líneas necesita un tipo de argumento nuevo (D8). |
| Topes del plan | `MAX_PLAN_BYTES = 16384`, `MAX_STEPS = 10`, profundidad 6 | Lo que se escribe en un plan cabe en 16 KiB entre todos sus pasos (D8, D15). |
| Política sin arrancar nada | `harness/mcp/policy.py`: `decide_before_start`, `Decision`, `DENIAL_REASONS` | Toma `LoadedConfig.servers`; `ServerEntry` exige `command` absoluto, así que el servidor interno no puede ser una `ServerEntry` (D7). |
| Nombre de servidor | `config.py`: `NAME_PATTERN = [a-z][a-z0-9_-]{0,63}` | `workspace` casa con el patrón: una lista local podría declarar un servidor MCP con ese nombre (D7). |
| Auditoría | `004_tool_calls.sql`: `reason` y `error_code` con `CHECK` de listas cerradas | Los motivos nuevos de la carpeta no caben en esas listas sin reconstruir la tabla (D7). |
| Aprobación | `harness/skills/approvals.py`: `Proposal`, `normalise_content`, `MAX_CONTENT_BYTES = 32768`, `ButtonPress`, `decide` | `normalise_content("a\tb\r\nc") == "a b\nc"`: la `Proposal` de Skills cambia bytes de código. Se reutiliza `decide`, el botón y la caducidad, no el contenido (D10). |
| Efectos | `harness/skills/effects.py`: `Effect` (`bind`, `prepare`, `exclusive`, `apply`, `reconcile`), `EffectRefused`, `EffectUncertain` | El protocolo está atado a `EffectContext` de un Skill (`run_id`, `skill_name`): se copia el contrato, no la clase (D9). |
| Confinamiento del vault | `harness/memory/paths.py`: `is_within`, `_WINDOWS_RESERVED`, `read_vault_file` (identidad con `fstat`), `walk_vault` (sin seguir enlaces, `st_nlink > 1` fuera); `decisions.py` (temporal exclusivo, `fsync`, publicación) | Se reutilizan la lista de nombres reservados, `is_within` y el patrón «comprobar sobre el descriptor». No se reutiliza la regla de nombres del vault (`[A-Za-z0-9._-]`): es demasiado estrecha para código (D2). |
| Ficheros privados | `harness/storage/private.py`: `private_dir`, `private_file` (0700/0600, `O_BINARY`) | Para las copias de deshacer (D12). |
| Redacción y saneado | `harness/text/redaction.py` (`redact`, `secret_kinds`), `safe_text.py` (`safe_foreign_text`, `terminal_safe`, `neutralise_delimiters`) | `secret_kinds` decide la regla fija de contenido (D3). |
| Caja de aprobación | `harness/shell/tui.py`: `open_approval(header, content, approval_hash, question)`; «Approve» espera a que el final se vea | Se usa tal cual, con el diff como `content` (D10). |
| Bucle (fase A) | `openspec/changes/code-mode/design.md`, «Hoja de ruta» y «Requisitos para los tramos siguientes»; rama `feature/code-mode-loop` **sin commits** sobre `develop` (`git log origin/develop..feature/code-mode-loop` vacío) | Solo se depende de su diseño: `auto_read`, modo de aprobación `rule`, resultados marcados como datos, tope de turnos, consentimiento antes de devolver resultados. |
| `code-run` | `feature/code-run`, `openspec/changes/code-run/` (2 commits, solo propuesta) | Su `work_root` tiene las mismas reglas de rechazo que esta carpeta; D1 las comparte y prohíbe el solape entre las dos. |

Lo que hacen OpenCode, Claude Code y Codex con sus herramientas de ficheros está en «Referencias» al final. Cada decisión cita lo que copia o evita.

## Goals / Non-Goals

**Goals:**
- Que ninguna ruta que el modelo escriba pueda leer o cambiar algo fuera de la carpeta elegida. Que esa garantía sea el mismo código en macOS y en Windows.
- Que lo aprobado, lo hasheado y lo aplicado en una escritura sean los mismos bytes. Que la persona vea el cambio entero, no un resumen.
- Que lo que el modelo lee y lo que se muestra estén acotados, saneados y redactados, y que su auditoría no guarde contenido.

**Non-Goals:**
- Aislamiento. El harness no es un sandbox y no lo dice (`SECURITY.md`).
- Paridad con OpenCode en ergonomía: ni ediciones aproximadas, ni `patch`, ni `delete`/`move`, ni formateadores, ni LSP.
- Proteger de un proceso local con la cuenta de la persona que cambia la carpeta a la vez (deuda conocida 1: quien controla la cuenta ya puede todo).

## Decisions

### D1. La carpeta de trabajo: `/workspace <ruta>` por sesión, sin valor por defecto

- **Qué.**
  - **Cómo se elige.** En la conversación, con `/workspace <ruta>`, `/workspace` (muestra la actual) y `/workspace off`. En la CLI, con `main.py workspace --root <ruta> …` en cada orden (tramo B1). No hay variable de entorno ni valor por defecto. Sin carpeta, el servidor `workspace` no aparece en el catálogo y sus herramientas no existen para el plan.
  - **Qué se comprueba, en este orden**, antes de aceptarla:
    1. la ruta es absoluta y no contiene NUL;
    2. no es un enlace ni una unión (`is_symlink`, `is_junction`), y tampoco lo es ninguno de sus componentes;
    3. se resuelve con `resolve(strict=True)` y es una carpeta;
    4. la resuelta no es, ni está dentro de, ni contiene: la raíz del repo del harness (la carpeta que contiene el paquete `harness`, resuelta), `HARNESS_DATA_DIR`, `HARNESS_VAULT_ROOT` (si está puesta) y el `work_root` de `code-run` (si existe su configuración);
    5. no es la carpeta personal (`Path.home()` resuelta) ni la raíz de un sistema de ficheros (`path == Path(path.anchor)`). Una subcarpeta de la carpeta personal sí vale.

    La comparación usa `is_within` de `memory/paths.py` en los dos sentidos. Cada rechazo tiene un motivo estable: `not_absolute`, `link`, `not_a_directory`, `harness_repo`, `data_dir`, `vault`, `code_run_root`, `home`, `filesystem_root`. **Revisado tras la revisión de `d0a65d8` (B1-6):** además `device_path` (una ruta que empieza por dos separadores, escrita o resuelta), `mount_point` (su `st_dev` no es el de su padre), `home` también para una carpeta que **contiene** la personal, y la búsqueda de un segundo camino a las carpetas protegidas.
  - **Qué se guarda.** ~~La ruta resuelta y su identidad (`st_dev`, `st_ino`) en una tabla nueva de la sesión.~~ **Revisado en B2 (2026-11-28, B2-1):** la ruta resuelta y su identidad viven solo en la memoria de la conversación; en la base de datos no se escribe la ruta. En cada uso se vuelve a hacer `lstat` de la raíz: si la identidad cambió o ahora es un enlace, la carpeta queda **suspendida** (`workspace_changed`) hasta un `/workspace` nuevo.
  - **Qué ve la persona:**
    - el panel lateral gana una línea `workspace: <ruta resuelta>` o `workspace: -`;
    - `/status` la repite junto con el consentimiento de envío (D14);
    - la ruta es estado del harness, se escribe con `terminal_safe` y nunca va al proveedor.
  - **Cambiarla a mitad de sesión.** Se puede entre preguntas. No se puede con una caja abierta ni con el bucle en marcha (`workspace_busy`). Cambiar de carpeta:
    - vacía el registro de lecturas (D11);
    - deja el `/undo` de la carpeta anterior inservible en esta sesión;
    - se anota en la auditoría.
- **Por qué.**
  - Lo decidió el dueño: la carpeta la elige él, no es «todo el disco» ni «cualquier repo por defecto».
  - Una variable de entorno se hereda en silencio de un perfil de shell y se aplicaría a todas las sesiones.
  - Elegir por sesión hace visible la decisión justo donde se trabaja.
  - Los rechazos de la lista son los mismos que `code-run` D6 aplica a su `work_root`, más el propio `work_root`. Un fichero que `code-run` va a ejecutar no puede editarse por esta vía después de aprobarse.
- **Alternativas rechazadas.**
  - `HARNESS_WORKSPACE`: es un valor por defecto encubierto y no se ve dónde se decidió.
  - El directorio actual (`cwd`) por defecto: es lo que hace OpenCode. Cualquier `cd` amplía lo que el modelo alcanza.
  - Varias carpetas a la vez (como `additionalDirectories` de Claude Code): multiplica la confinación y el panel, sin una necesidad medida.
  - Exigir que sea un repo git: excluye carpetas normales y no añade seguridad.
- **Impacto.** Requisitos «Elegir la carpeta de trabajo», «Ver y cambiar la carpeta», «Carpeta suspendida si cambia» y «Carpetas que no se aceptan»; `PanelState`; una tabla en la migración nueva; tareas 2.x.

### D2. Confinamiento de una ruta: una sola regla, sin ramas por plataforma

- **Qué.** Toda ruta que llega en un argumento es **relativa a la carpeta**. Pasa por tres fases.
  - **Fase 1. Forma, una función pura sobre la cadena.** Se rechaza:
    - vacía, de más de 1 024 caracteres, o con un componente de más de 255 bytes en UTF-8;
    - absoluta en cualquier sabor: `/x`, `C:\x`, `C:x`, `\\servidor\x`, `\\?\x`, `//x`;
    - con `\` (en Windows es un separador y en POSIX un nombre: se rechaza en los dos), con `:` (unidades y flujos alternativos `fichero:flujo`) o con NUL;
    - componentes vacíos (`a//b`), `.` o `..`;
    - un componente que acaba en punto o en espacio, o cuyo tronco es un nombre reservado de Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, sin distinguir mayúsculas ni extensión, como `_WINDOWS_RESERVED`);
    - algún carácter que `string_refusal` rechaza (invisibles, control) o una cadena que no está en NFC;
    - los caracteres que Windows prohíbe en un nombre: `<>"|?*`.

    Resultado: una lista de componentes. Se prueba con cadenas literales, igual en las dos plataformas.
  - **Fase 2. Camino real, componente a componente desde la raíz.** Para cada componente:
    - su nombre tiene que ser **exactamente** una entrada de `os.listdir(padre)`, mismos bytes después de NFC. Una variante de mayúsculas, una forma NFD guardada por el sistema o un nombre corto 8.3 de Windows (`PROGRA~1`) no es esa entrada: se rechaza con `name_not_exact`;
    - ningún componente puede ser enlace simbólico ni unión (`lstat`, `is_symlink`, `is_junction`): `link`;
    - los intermedios tienen que ser carpetas;
    - para un nombre que **no existe** (`write` de un fichero nuevo), se rechaza si alguna entrada del padre coincide con él tras `casefold()` y NFC (`name_collision`). Así la regla es la misma en un sistema que distingue mayúsculas y en uno que no.
  - **Fase 3. Al abrir.** `os.open` con `O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_BINARY`; cada bandera se busca con `getattr(os, …, 0)`, por capacidad y no por plataforma, como en `read_vault_file`. Después, sobre el descriptor:
    - `fstat`: fichero regular, la misma identidad (`st_dev`, `st_ino`) que el `lstat` de la fase 2 y `st_nlink == 1`. Si no, `changed` o `hard_link`;
    - se vuelve a resolver la ruta (`resolve(strict=True)`) y tiene que seguir dentro de la raíz resuelta (`is_within`): `outside_root`.
- **TOCTOU, qué queda abierto.** Entre la fase 2 y la apertura, otro proceso podría cambiar un componente intermedio por un enlace. La fase 3 lo detecta para el fichero final (identidad y nueva resolución) y para la raíz (D1), pero no hay `openat` portable: `os.supports_dir_fd` no incluye `os.open` en Windows. Este hueco no se cierra. El atacante de este diseño es el **contenido** de la carpeta (un repo clonado), no un proceso concurrente con la cuenta de la persona (deuda conocida 1). Se escribe en `known-debt.md`.
- **Enlaces duros.** Un fichero con `st_nlink > 1` ni se lee ni se escribe. Un enlace duro plantado podría apuntar a un fichero de fuera (en el mismo volumen), y escribir por él cambiaría ese fichero. Las carpetas no se comprueban (en POSIX su `st_nlink` cuenta subcarpetas).
- **Qué se prueba dónde:**

  | Regla | macOS (puerta) | Windows |
  |---|---|---|
  | Forma (fase 1), con cadenas y `PureWindowsPath` | test | mismo test, NOT RUN hasta el PC |
  | Nombre exacto y colisión por mayúsculas | test sobre APFS (no distingue mayúsculas por defecto) | NOT RUN (NTFS no distingue) |
  | Forma NFD guardada | test sobre APFS | NOT RUN |
  | Enlace simbólico en un componente | test con `make_symlink` | omitido por capacidad si la cuenta no crea enlaces |
  | Unión de directorio | no existe en macOS: solo el `is_junction` del código, sin test | NOT RUN; sería el primer test de uniones del repo (tarea 8.2) |
  | Enlace duro | test con `os.link` | NOT RUN (`st_nlink` en NTFS por medir) |
  | Flujo alternativo `a.txt:x` | rechazo por forma (test) | NOT RUN el efecto real |
  | Ruta absoluta larga (más de 260) | sin límite en macOS | NOT RUN; la fase 1 limita la relativa, no la absoluta |
  | Nombre reservado `NUL`, `con.txt` | rechazo por forma (test) | NOT RUN el efecto real |
- **Por qué.**
  - Una sola función de forma, pura, hace que lo probado en macOS sea lo mismo que corre en Windows (regla de `config.yaml`).
  - Exigir el nombre exacto de `listdir` cierra a la vez tres problemas: mayúsculas, NFC/NFD y nombres 8.3, sin preguntar al sistema si distingue mayúsculas.
  - Rechazar `\` y `:` en los dos sistemas evita que una ruta signifique cosas distintas en cada uno.
- **Alternativas rechazadas.**
  - Resolver y comprobar la contención solamente, como hace OpenCode: sigue enlaces dentro de la carpeta y acepta un enlace a fuera si la comprobación se hace antes de resolver (OpenCode compara la ruta tal como se escribe).
  - `os.path.normcase` / `casefold` para comparar: depende de la plataforma y no cubre NFD.
  - Aceptar enlaces que resuelven dentro: complica la regla y abre el cambio de destino entre comprobar y usar.
  - `dir_fd` y `openat`: no son portables a Windows.
  - Limitar la ruta absoluta a 260: la longitud de la raíz no la decide el modelo. Se deja como NOT RUN medido en Windows.
- **Impacto.** Requisitos «Forma de las rutas» y «Camino real de las rutas»; módulo de rutas puro y testeable con fixtures; fila SEC-04.

### D3. Lo que nunca se lee ni se escribe, aunque esté dentro

- **Qué.** Una lista cerrada en código, comparada con `casefold()` sobre cada componente:
  - **Componentes prohibidos en cualquier posición:** `.git` (carpeta o fichero, como en un worktree), `.hg`, `.svn`, `.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`, `.docker`.
  - **Nombres de fichero prohibidos:**
    - `.env`, y cualquier nombre que empiece por `.env.` salvo `.env.example`, `.env.sample` y `.env.template`;
    - `.envrc`, `.netrc`, `_netrc`, `.npmrc`, `.pypirc`, `.git-credentials`;
    - `id_rsa*`, `id_dsa*`, `id_ecdsa*`, `id_ed25519*`;
    - `credentials`, `credentials.json`;
    - `secrets.json`, `secrets.yaml`, `secrets.yml`.
  - **Extensiones prohibidas:** `.pem`, `.key`, `.p12`, `.pfx`, `.jks`, `.keystore`, `.kdbx`, `.ovpn`.
  - **Por contenido:**
    - si `secret_kinds` encuentra una forma de credencial, el fichero se rechaza **entero** (`credential_in_file`) para leer y para editar;
    - si un fichero no es UTF-8 válido o tiene un NUL en los primeros 8 KiB, se rechaza como binario (`binary`);
    - pasar de **256 KiB** da `too_large`.
  - **Solo para escribir:** ningún componente oculto, es decir, que empiece por punto (`hidden_target`). Eso cubre `.github/workflows`, `.vscode/tasks.json`, `.devcontainer`, `.husky` y `.pre-commit-config.yaml`. Leerlos sí se puede.
  - **Lo que el modelo recibe** es el motivo, nunca el contenido. `list` muestra las entradas prohibidas con su motivo, sin abrirlas.
- **Qué NO protege, en claro:**
  - un secreto con forma desconocida dentro de un fichero normal (una contraseña en `config.py`, un token de un proveedor que el redactor no conoce) se lee. Con el bucle activo y consentimiento (D14), **se envía al modelo**;
  - los nombres son convenciones: un `deploy.txt` con una clave dentro solo cae si la clave tiene una forma conocida;
  - la regla de ocultos no impide escribir otros ficheros que se ejecutan solos: `Makefile`, `package.json` (`scripts`), `conftest.py`, `setup.py`, un test. Lo para solo la caja (D10), que lo dice con un aviso fijo.
- **Por qué.**
  - Rechazar el fichero entero, en vez de redactarlo y seguir, hace que lo mostrado sea igual a lo leído y que el modelo no edite un fichero cuyo texto no ha visto entero.
  - Codex protege `.git`, `.codex`, `.agents` y `.aws` como solo lectura dentro de las raíces escribibles. OpenCode pregunta (`ask`) solo para `*.env`. Aquí se deniega, de acuerdo con deny-by-default.
- **Alternativas rechazadas.**
  - Redactar y entregar: el modelo editaría a ciegas alrededor de un `[REDACTED:…]`, y un `edit` sobre ese texto no casaría nunca.
  - Patrones configurables por la persona: es otra lista que un repo no puede aportar, pero que la persona tendría que mantener. Se aplaza.
  - Prohibir todos los ocultos también para leer: `.github/` y los ficheros de configuración son contexto legítimo.
- **Impacto.** Requisitos «Ficheros prohibidos por nombre», «Ficheros prohibidos por contenido o tamaño» y «Escrituras en rutas ocultas»; fixture de carpeta sintética con cada caso; `known-debt.md`.

### D4. `read` y `list`: qué devuelven y con qué topes

- **Qué.**
  - **`read {path, offset?, limit?}`:**
    - `offset` empieza en 1; `limit` vale 200 por defecto y 400 como máximo;
    - una línea de más de 500 caracteres se corta con la marca `… [line cut at 500 characters]`;
    - la salida no pasa de 16 KiB;
    - formato: una cabecera del harness (`path`, `lines a–b of N`, `sha256` corto, `newline: lf|crlf|mixed`, `bom: yes|no`) y las líneas numeradas `   12| texto`;
    - solo UTF-8 estricto, con el BOM aceptado y quitado del texto pero anotado;
    - un `offset` fuera de rango da `offset_out_of_range` con el total de líneas. No hay sugerencias de nombres parecidos (OpenCode las da): un nombre que no existe da `not_found` sin listar nada.
  - **`list {path?, depth?}`:**
    - `depth` es 1 por defecto y 3 como máximo;
    - como mucho 500 entradas, por orden de nombre, carpetas con `/` al final;
    - nunca sigue un enlace: los enlaces, las uniones y lo prohibido salen con su marca (`[link]`, `[denied: .git]`);
    - no abre ningún fichero;
    - el tope se dice. **Revisado tras la revisión de `d0a65d8`:** antes solo decía `[listing stopped at 500 entries]`, sin la cuenta. Ahora, pasado el tope, el paseo sigue solo para contar, como mucho 5 000 entradas más (`LIST_COUNT_MAX`): `[listing stopped at 500 entries; 120 more not listed]`, o `more than 5000`. Si lo corta el tope de 16 KiB del servidor, `[listing cut at 16384 bytes after N entries; M more not shown; list a subfolder]`.
  - **Para la pantalla:** el resultado es texto ajeno, pasa por `safe_foreign_text` (saneado y redactado) y va en un bloque plegable marcado como ajeno. Nada se guarda en SQLite ni en disco.
  - **Para el modelo (con A3):** lo mismo, con `neutralise_delimiters` y dentro del marco de datos de A3. Además se aplica su tope de envío, muy por debajo de los 32 000 caracteres del proveedor (requisito A3).
- **Por qué.**
  - OpenCode usa 2 000 líneas y 50 KiB por página, y Claude Code 25 000 tokens y 256 KB. Aquí cada vuelta es un envío de Copilot con un límite de unos 32 000 caracteres (code-mode T2-1), así que el tope útil es mucho menor.
  - Los números de línea permiten al modelo citar sin copiar.
  - El `sha256` de la cabecera es lo que D11 registra como «leído».
- **Alternativas rechazadas.**
  - Devolver el fichero entero: rompe el presupuesto del envío.
  - Guardar el completo en disco y dar la ruta (OpenCode v1): contradice «los resultados nunca se guardan» (`SECURITY.md`, servidores MCP).
  - Aceptar Latin-1 u otras codificaciones: dos lecturas posibles de los mismos bytes, y una escritura que no sabría con qué codificar.
- **Impacto.** Requisitos «Lectura de un fichero acotada», «Listado de una carpeta acotado» y «Resultados saneados y no guardados»; fixtures con CRLF, BOM, líneas largas y no UTF-8.

### D5. `grep` y `glob` (tramo B5): búsqueda acotada sin ReDoS

- **Qué.**
  - **`glob {pattern}`:**
    - patrón relativo con `*`, `?`, `**` y clases `[]`, comparado con `fnmatch.fnmatchcase` sobre la ruta POSIX de cada fichero, sin `os.walk(followlinks=True)`;
    - se recorre con el mismo paseo que `list`, con un tope de 5 000 ficheros vistos y 200 resultados, por orden de nombre (no por fecha de modificación: el orden se puede repetir en los tests).
  - **`grep {pattern, path?, glob?, literal?}`:**
    - `literal` vale **`true` por defecto**: búsqueda de subcadena;
    - con `literal: false`, el patrón (como mucho 200 caracteres) se compila con `re` **tras una comprobación de sintaxis conservadora**: se rechazan las referencias atrás (`\1`, `(?P=`), los «lookaround» (`(?=`, `(?!`, `(?<=`, `(?<!`) y todo grupo cuantificado (un `)` seguido de `*`, `+`, `?` o `{`). El motivo es `regex_not_supported`;
    - solo se buscan las líneas de 2 000 caracteres como mucho; las más largas se saltan y se cuentan;
    - presupuesto total de 8 MiB leídos, 2 000 ficheros y 100 coincidencias, con cada línea cortada a 300 caracteres;
    - se aplican las reglas de D3 a cada fichero antes de abrirlo, y `credential_in_file` lo salta con su marca.
- **Por qué.** `re` no tiene plazo y un hilo no se puede interrumpir. Sin grupos cuantificados ni referencias atrás, el peor caso de `re` con líneas de 2 000 caracteres es polinómico y pequeño. La tarea 6.3 mide el peor caso con patrones del fixture.
- **Alternativas rechazadas.**
  - ripgrep (como OpenCode, Claude Code y Codex): es un binario externo, otra dependencia y otro proceso.
  - Un subproceso de Python con plazo para matar el regex: otro sitio que crea procesos (code-run lo concentra en dos sitios fijados por test).
  - El módulo `regex` con `timeout`: dependencia nueva.
  - El analizador privado `re._parser`: API privada.
  - Respetar `.gitignore`: ver la decisión abierta 2.
- **Impacto.** Requisito «Búsqueda acotada»; tramo B5.

### D6. Las herramientas como servidor interno `workspace` en el catálogo

- **Qué.**
  - Las herramientas son una **tabla literal en código**: nombre, `operation` (`read` o `write`), argumentos con su tipo, longitud y patrón, tope de resultado y si es `auto_read`.
  - `read`, `list`, `glob` y `grep` son `auto_read: true`. `write` y `edit` son `operation: write` y siempre necesitan una aprobación por diff (D10).
  - La persona no puede cambiar la tabla. Lo único que decide es si hay carpeta (D1) y si hay consentimiento de envío (D14).
  - Aparecen en el catálogo del plan como cualquier herramienta (`server: "workspace"`), con una `description` fija escrita por el harness, y solo si hay carpeta.
  - El catálogo **no** incluye la ruta absoluta ni ningún listado. ~~Dice solo: «a work folder is set; paths are relative to it; use `list` to see it».~~ **Revisado en B2 (B2-4):** lo dicen las dos descripciones fijas de las herramientas, sin una línea aparte.
- **Por qué.**
  - code-mode, «Consecuencia para el esquema»: el plan ya admite un servidor que no es MCP, porque `server` y `tool` son nombres del catálogo.
  - Una tabla en código no la puede ampliar un fichero de la carpeta ni de la lista local.
  - No enviar el listado mantiene el catálogo bajo su tope de 8 000 caracteres y evita que unos nombres de fichero escritos por un atacante entren en la parte de instrucciones del prompt.
- **Alternativas rechazadas.**
  - Un servidor MCP propio en un proceso aparte: añade arranque (unos 519 ms por llamada, estudio de code-mode §2.1), protocolo y un proceso que confinar, para leer ficheros que el harness puede leer él mismo con más control.
  - Declarar la carpeta en la lista MCP local: mezcla dos superficies y obliga a escribir un `command` que no existe.
  - Enviar un árbol acotado en cada pregunta: gasta presupuesto en cada envío y mete texto ajeno en las instrucciones.
- **Impacto.** Requisito «Herramientas en el catálogo»; tramo B2.

### D7. Misma política y misma auditoría que MCP

- **Qué.**
  - **La política.** La vista de política que recibe el lector del plan se compone de las `ServerEntry` de la lista MCP más la tabla interna, que se construye en el código con los mismos `ToolEntry`. No es una `ServerEntry` porque no tiene `command`.
  - **El nombre reservado.** Una lista MCP local que declare un servidor `workspace` se rechaza al cargar (`reserved_server_name`).
  - **Las comprobaciones.** `decide_before_start` decide igual: servidor, herramienta, argumentos, tipos y patrones. El tipo nuevo `lines` (D8) solo lo admite la tabla interna en este change.
  - **La auditoría:**
    - cada llamada deja una fila en `tool_calls` con `server = 'workspace'`, el HMAC de los argumentos canónicos (la clave de `audit.args_key`), `args_bytes`, `result_bytes`, `duration_ms`, `plan_id`, `plan_step` y `server_stopped` nulo;
    - los motivos propios de la carpeta (`link`, `outside_root`, `credential_in_file`…) no caben en las listas `CHECK` de `tool_calls`. La fila lleva el `reason`/`error_code` existente más cercano (`argument_invalid` para la forma, `tool_error` para lo que se descubre al abrir), y el motivo exacto va en una tabla nueva `workspace_events (call_id, code, relative_path_hmac)`. La ruta va como HMAC, nunca en claro.
  - **`auto_read`.** Un plan cuyos pasos son todos `auto_read` corre sin caja, con la línea `running plan:` y el modo de aprobación `rule` de A2. La política se decide otra vez al ejecutar cada paso. Un plan con algún `write` nunca es `auto_read`.
- **Por qué.**
  - El dueño pidió la misma tabla y la misma auditoría.
  - Reconstruir `tool_calls` para ampliar sus `CHECK` es una migración con riesgo sobre datos existentes. Una tabla al lado solo añade.
  - La ruta en HMAC respeta «sin contenido» y sigue permitiendo contar repeticiones.
- **Alternativas rechazadas.**
  - Una tabla de auditoría propia sin `tool_calls`: dos sitios para contestar «qué llamó el modelo».
  - Guardar la ruta en claro: la ruta de un fichero es contenido de la persona (puede llevar nombres de cliente) y el repo es público.
- **Impacto.** Requisitos «Misma auditoría» y «Nombre reservado»; migración nueva; filas SEC-05.

### D8. Cómo viaja el contenido en un plan: listas de líneas, sin cambiar `plan/1`

- **Qué.**
  - **`write {path, lines}`** crea un fichero nuevo cuyo texto es `"\n".join(lines) + "\n"`.
  - **`edit {path, old_lines, new_lines, replace_all?}`.** El texto `"\n".join(old_lines)` tiene que aparecer **exactamente una vez** en el texto del fichero, visto con LF, o al menos una vez si `replace_all: true`. Se sustituye por `"\n".join(new_lines)`.
    - Cero coincidencias dan `no_match`; más de una sin `replace_all`, `ambiguous_match` con el número.
    - No hay coincidencia aproximada.
    - `old_lines` vacío o igual a `new_lines` da `no_change`.
  - **Las cadenas.** Cada elemento de una lista es una cadena del plan y sigue **todas** las reglas de D5 de code-mode, sin excepción: sin `\n`, `\t`, `\r` ni invisibles, en NFC y sin credencial. El salto de línea lo pone la estructura, no la cadena.
  - **Consecuencias que se aceptan en v1:**
    - no se puede escribir un tabulador. Un `Makefile` o un fichero con sangría de tabuladores no se puede editar en las líneas que los contienen (decisión abierta 8);
    - todo el contenido de un plan cabe en 16 KiB.
  - **El formato del plan sigue siendo `ai-harness/plan/1`.** Cambia la vista de política: una escritura de `workspace` deja de ser `write_not_allowed`, una escritura MCP sigue siéndolo, y un plan con escrituras solo puede tener escrituras (`mixed_plan`, motivo nuevo de la lista cerrada).
- **Por qué.**
  - Las cadenas del plan no pueden llevar saltos de línea (medido arriba), y relajar D5 rompería la garantía «lo mostrado es lo enviado» de todo el plan.
  - Una lista de líneas no necesita ninguna excepción.
  - La coincidencia exacta y única es lo que hacen OpenCode y Claude Code. La versión 1 de OpenCode añadía nueve «replacers» aproximados. La actual solo tolera variantes tipográficas y espacios al final. Aquí no hace falta tolerancia, porque la persona ve el resultado real en el diff: si el modelo falla, recibe `no_match` y vuelve a leer.
  - Separar los planes de lectura de los de escritura deja la caja de un plan de escritura sin lecturas «ya ejecutadas» que explicar.
- **Alternativas rechazadas.**
  - Una cadena con `\n` escapado en un campo `content`: exige una excepción en D5 justo en el campo de más riesgo.
  - Un bloque de código aparte referenciado desde el plan: rompe «un único bloque» (D3 de code-mode), y la página real solo conserva la etiqueta de lenguaje.
  - El formato `apply_patch` de Codex (`*** Begin Patch`): otra gramática que leer y validar, con contexto aproximado.
  - `plan/2`: no hace falta mientras la sintaxis no cambie.
  - Planes mixtos de lectura y escritura: sin referencias (D2 de code-mode) no ganan nada, y complican la caja.
- **Impacto.** Requisitos «Contenido como lista de líneas», «Edición por texto exacto» y «Planes de escritura»; tipo de argumento `lines` (máximo de elementos y de longitud por elemento); motivo `mixed_plan`; tramo B3.

### D9. Cada escritura es un efecto: `prepare`, `apply`, `reconcile`

- **Qué.** El mismo contrato de `harness/skills/effects.py`, en una clase propia del paquete `workspace`, con su propio contexto (sesión, plan, paso y carpeta) y no el de un Skill.
  - **`prepare`** (sin escribir nada), por paso:
    - confina la ruta (D2) y aplica las reglas de D3;
    - lee el contenido actual (`edit`) o comprueba que no existe (`write`; si existe, `exists`);
    - calcula los **bytes nuevos completos**, conservando el fin de línea (D13), el BOM y el modo;
    - genera el diff unificado (`difflib.unified_diff`, 3 líneas de contexto, rutas `a/<rel>` y `b/<rel>`);
    - guarda en memoria `(identidad, tamaño, mtime_ns, sha256)` del contenido anterior.

    Un plan de escrituras da **una lista de efectos** en el orden de sus pasos. Si alguno se rechaza en `prepare`, no se pide aprobación y el modelo recibe los motivos.
  - **`exclusive`:** un `NamedLock` por carpeta, desde antes de consumir la aprobación hasta que termina el último `apply`.
  - **`apply`**, por efecto y en orden:
    1. vuelve a confinar y a leer, y compara el `sha256` con el de `prepare`. Si difiere, `changed_since_prepare`, que es un `EffectRefused` antes de cualquier efecto;
    2. copia el contenido anterior a deshacer (D12);
    3. crea un temporal `.<nombre>.ai-harness-<id>.tmp` en la **misma carpeta**, con `O_CREAT | O_EXCL | O_BINARY`, escribe los bytes, hace `fsync` y aplica el modo con `chmod`;
    4. `os.replace(temporal, destino)`.

    Si una escritura se rechaza limpia, las siguientes no se aplican. El plan termina `failed` con la lista de lo hecho.
  - **`reconcile`**, tras una caída: compara el `sha256` actual del destino con el nuevo (`applied`), con el anterior o con «no existe» (`absent`), o nada de eso (`conflict`). Además borra su propio temporal si quedó. Un efecto interrumpido queda `uncertain` y **nunca se reaplica solo**.
  - **Carpetas que faltan.** `write` puede crear las carpetas que falten (como mucho 4 niveles, con nombres que pasan D2 y D3). Se crean con `mkdir` exclusivo, se listan en la caja y entran en el hash.
- **Portabilidad de `os.replace`.** Reemplaza el destino en un solo paso en POSIX y en Windows (MoveFileEx con REPLACE_EXISTING). En Windows **falla** si otro programa tiene el destino abierto sin compartir el borrado, por ejemplo un editor o un antivirus. Entonces `apply` da `EffectRefused("target_busy")`, borra su temporal y no ha cambiado nada. Ya pasó algo parecido en este repo: el commit `b9364a3` («the system refuses to replace an open file»). Queda NOT RUN en Windows hasta la tarea 8.2.
- **Lo que se pierde al reemplazar:** atributos extendidos, ACL propias, etiquetas de Finder, propietario si no es la persona, y el inode (el «fichero» es otro). Se escribe en el runbook. Los enlaces duros no se pierden porque se rechazan (D2).
- **Ventana sin cerrar.** Entre la comprobación del `sha256` en `apply` y el `os.replace`, otro programa puede escribir el fichero, y esa escritura se pierde. No hay comparar-e-intercambiar portable para ficheros. La ventana es de milisegundos y se documenta.
- **Por qué.** Es el patrón probado de la nota de decisión (`decisions.py`: temporal exclusivo, `fsync`, publicación). Aquí se publica con `replace` porque se edita un fichero que existe, cosa que la nota nunca hace.
- **Alternativas rechazadas.**
  - Escribir en el sitio (`truncate` + `write`): una caída deja medio fichero.
  - Temporal en el directorio de datos y `replace` entre volúmenes: no es atómico y falla entre unidades.
  - `os.link` como en la nota: no puede sustituir un fichero existente.
  - Registrar `EffectContext` de Skills: obligaría a fingir un `run_id` y un Skill.
- **Impacto.** Requisitos «Escritura atómica», «Fichero cambiado desde la vista previa» y «Escritura interrumpida»; SEC-07 y SEC-08; tests de muerte del proceso como `test_skill_crash.py`.

### D10. La caja: el diff exacto de cada fichero y un hash propio

- **Qué.**
  - **La propuesta.** Formato `ai-harness/workspace-change/1` y dominio de hash `ai-harness/workspace-change/v1\n`. El hash es el SHA-256 del dominio más el JSON canónico de:
    - la sesión, la solicitud, el `plan_id` y el hash del plan;
    - la carpeta (ruta resuelta e identidad);
    - por efecto, en orden: ruta relativa, tipo (`create` o `edit`), carpetas creadas, `sha256` del contenido anterior (o `absent`), `sha256` y longitud de los bytes nuevos, los **bytes nuevos completos en base64**, el modo, el fin de línea y el BOM.

    Caduca y vale una vez, como toda aprobación. Se decide con `approvals.decide`: botón en la pantalla completa, código de 8 caracteres en el modo plano y en la CLI.
  - **Lo que muestra la caja,** escrito por el harness. La cabecera dice:
    - la carpeta;
    - `N files, +a −b lines`;
    - el hash corto;
    - el aviso fijo: «these files are written with your account; a written file may be run later by your tools (make, npm, pytest)».

    Después, por fichero: `create`/`edit`, la ruta relativa, el modo, el fin de línea y el diff unificado entero, **nunca plegado**. «Approve» solo se habilita cuando el final ya se ha visto (regla vigente de la caja).
  - **Por qué el diff basta para «lo mostrado es lo aplicado».** Los bytes nuevos son una función de dos cosas: los bytes anteriores, atados por su `sha256` (que `apply` vuelve a comprobar), y las líneas cambiadas que se muestran. Las líneas de contexto y las eliminadas son texto del fichero anterior. Si llevan tabuladores, controles o invisibles (Trojan Source, bidi), se escriben escapados como `<U+XXXX>` para que se vean. Las líneas añadidas ya no pueden llevarlos (D8).
  - **Topes.** Como mucho 10 ficheros (los pasos de un plan) y 32 KiB de diff mostrado en total, igual que `MAX_CONTENT_BYTES`. Pasarlo es `diff_too_large`: no se recorta y no se pide aprobación.
- **Por qué.** La `Proposal` de Skills normaliza el contenido (medido arriba) y no puede ligar bytes de código. Un formato propio, con su dominio, impide que una aprobación de un Skill o de un plan de lectura valga para una escritura.
- **Alternativas rechazadas.**
  - Mostrar el fichero nuevo entero: no se ve qué cambia y no cabe.
  - Un hash por fichero y una aprobación por fichero: N códigos que solo cansan (estudio §5.2, opción C).
  - Plegar ficheros largos: la persona aprobaría algo que no ha visto.
  - Ligar solo el diff: sin el `sha256` anterior, el mismo diff aplicado a otro contenido da otro fichero.
- **Impacto.** Requisitos «Aprobación ligada al hash del cambio», «Lo que muestra la caja de una escritura» y «Una aprobación por plan de escritura»; SEC-12; `tui.open_approval` sin cambios.

### D11. «Leído antes de editar»: obligatorio dentro de la misma carpeta y sesión

- **Qué.**
  - **El registro.** La sesión lleva en memoria un registro de lecturas `ruta relativa → sha256 del fichero entero`, alimentado por cada `read` que termina bien, aunque sea de un rango.
  - **`edit`** se rechaza con `not_read` si la ruta no está en el registro, y con `changed_since_read` si el `sha256` actual no es el registrado.
  - **`write` de un fichero nuevo** no lo necesita.
  - **Cuándo se vacía el registro:** al cambiar de carpeta, al cerrar la sesión y tras aplicar una escritura sobre esa ruta. En este último caso queda el `sha256` nuevo: el modelo puede encadenar ediciones sin volver a leer.
- **Por qué.**
  - Es lo que hacía OpenCode v1 (`FileTime.assert`) y lo que hace Claude Code con los modelos antiguos.
  - Aquí cuesta poco y enseña: el modelo no edita a partir de lo que imagina que dice un fichero.
  - Además, `changed_since_read` avisa al modelo cuando la persona editó el fichero entre turnos.
- **Alternativas rechazadas.**
  - Sin registro, confiando solo en la coincidencia exacta (Codex, y OpenCode v2 según lo leído): un `edit` a ciegas que por casualidad casa se aplicaría.
  - Exigir haber leído el rango exacto que se edita: complica el registro sin cambiar lo que ve la persona en la caja.
- **Impacto.** Requisito «Leer antes de editar»; decisión abierta 4.

### D12. Deshacer: copia previa en el directorio de datos y `/undo` aprobado

- **Qué.**
  - **La copia.** Antes de cada `apply`, los bytes anteriores (o la marca «no existía», con las carpetas creadas) se guardan en `HARNESS_DATA_DIR/workspace-undo/<sesión>/<efecto>/`, con `private_dir` y `private_file` (0700/0600; en Windows, las ACL heredadas). Junto a ellos va un manifiesto con la ruta relativa, los `sha256` y el modo.
  - **Topes:** 1 MiB por lista de efectos (si se pasa, `undo_too_large` en `prepare`, antes de pedir nada), las 20 últimas listas por sesión y 7 días. Se purga al arrancar el harness.
  - **`/undo`** deshace la **última lista aplicada** de la sesión, una sola vez:
    - se muestra como un diff (de lo actual a lo anterior) y se aprueba como cualquier escritura, con el mismo D10;
    - si el fichero ya no tiene los bytes que escribió el harness, se rechaza (`changed_since_apply`) y no hace nada;
    - deshacer un `create` borra **ese** fichero, y las carpetas que creó si están vacías. Es el único borrado de v1;
    - un `/undo` no se deshace.
- **Por qué.**
  - Un cambio aprobado puede ser un error que solo se ve después.
  - La copia es de la persona y vive donde viven sus otros datos privados.
  - Aprobar el `/undo` mantiene la regla «toda escritura, aprobada».
- **Alternativas rechazadas.**
  - Instantáneas con git (`stash`, `commit`, un `GIT_DIR` aparte):
    - la carpeta puede no ser un repo;
    - tocaría `.git/`, que D3 prohíbe;
    - mezcla el historial de la persona con el del harness;
    - y necesita un binario externo y un proceso.
  - Copia solo en memoria: se pierde si el harness muere, que es justo cuando hace falta reconciliar.
  - Deshacer en varios niveles: la segunda vez se deshace sobre algo que quizá cambió. Ver la decisión abierta 5.
- **Impacto.** Requisito «Deshacer el último cambio»; tramo B4; `SECURITY.md` dice que hay copias de ficheros de la persona en el directorio de datos.

### D13. Fin de línea, codificación y modo

- **Qué.**
  - **Codificación:** solo UTF-8.
  - **Fin de línea en `edit`.** El fichero se lee, se clasifica en `lf`, `crlf` o `mixed` y se trabaja sobre su vista LF; al escribir se vuelve a poner el fin de línea del fichero. Un fichero `mixed` no se edita (`mixed_newlines`). Un `\r` suelto cuenta como `mixed`.
  - **Fin de línea en `write`:** LF.
  - **BOM:** se conserva si estaba.
  - **Salto final.** Si el fichero no terminaba en salto de línea, se conserva así.
  - **Modo:** se copian los bits de permiso del fichero anterior. Uno nuevo toma `0o644` menos la `umask`; en Windows solo cuenta el bit de solo lectura. Un fichero de solo lectura se rechaza (`read_only`), no se le quita el bit.
- **Por qué.** El diff tiene que mostrar el cambio del modelo, no un cambio de todas las líneas por el fin de línea.
- **Alternativas rechazadas.**
  - Normalizar a LF: convierte cada edición de un fichero de Windows en un diff entero.
  - Detectar otras codificaciones: dos lecturas posibles de los mismos bytes.
- **Impacto.** Fixtures CRLF, BOM, sin salto final, solo lectura.

### D14. El bucle, el envío y el consentimiento por carpeta

- **Qué.**
  - **Escrituras.** Una escritura **siempre** detiene el bucle en la caja, aunque las lecturas del mismo bucle corran solas. Cuenta como una vuelta del tope de A3.
  - **Lo que el modelo recibe** de una escritura: `applied`, `rejected by the person`, `refused: <motivo estable>` o `uncertain`. Nunca el contenido ni el diff.
  - **Lo que el modelo sabe de la carpeta** (D6): que existe y qué herramientas tiene. Su contenido, solo si lo pide con `list` o `read`.
  - **Consentimiento.** Con un proveedor que no es el Mock, el resultado de una lectura de la carpeta **solo vuelve al proveedor** si la persona dio un consentimiento **por carpeta**:
    - se da con `/workspace send on`, que pide el código tecleado o el botón con el texto «file contents of <ruta> will be sent to <proveedor>»;
    - se guarda con la identidad de la carpeta y se revoca con `/workspace send off`;
    - sin él, las lecturas se muestran solo a la persona y el bucle termina en esa vuelta con el aviso `not sent: no consent for this folder`;
    - con el Mock, no hace falta.
- **Por qué.**
  - A3 exige un consentimiento explícito, distinto de la aprobación del plan, para que los resultados salgan de la máquina.
  - Leer el código de la persona y mandarlo a Copilot es justo eso, y depende de la carpeta: una carpeta de código propio y otra de un cliente no son lo mismo.
- **Alternativas rechazadas.**
  - Un consentimiento global: se olvida y cubre carpetas que nadie pensó.
  - Por fichero: cansa y no cambia el riesgo.
  - Devolver también el diff aplicado: el modelo ya sabe lo que propuso.
- **Impacto.** Requisitos «Lo que vuelve al modelo» y «Consentimiento de envío por carpeta»; decisión abierta 6.

### D15. Topes, en un solo sitio y con números literales

| Qué | Tope |
|---|---|
| Fichero leído o editado | 256 KiB |
| `read`: líneas por llamada / longitud de línea / salida | 200 (máx. 400) / 500 caracteres / 16 KiB |
| `list`: profundidad / entradas | 1 (máx. 3) / 500 |
| `glob`: ficheros vistos / resultados | 5 000 / 200 |
| `grep`: patrón / línea buscada / bytes / ficheros / coincidencias | 200 caracteres / 2 000 / 8 MiB / 2 000 / 100 |
| Ruta relativa / componente | 1 024 caracteres / 255 bytes |
| Escritura: ficheros por plan / diff mostrado / carpetas nuevas | 10 / 32 KiB / 4 niveles |
| Deshacer: por lista / listas / antigüedad | 1 MiB / 20 / 7 días |

Cada tope es una constante con su número literal en la frontera, como en `code-mode` D4. La tarea de mutaciones multiplica cada uno por 10 y comprueba que un test falla.

### D16. Inyección: lo que un fichero hostil puede hacer proponer

- **Qué puede hacer.** El contenido de la carpeta lo controla un tercero (un repo clonado, una dependencia, un PR). Un fichero puede decir «ignora tus instrucciones», y con el bucle el modelo puede proponer:
  1. leer otros ficheros y mandar su contenido al proveedor en la vuelta siguiente;
  2. editar un fichero que se ejecuta después (un `Makefile`, un `postinstall`, `conftest.py`, un test);
  3. escribir una puerta trasera que parezca inocua en un diff largo;
  4. salirse de la carpeta (`../`, un enlace, `C:\`);
  5. leer `.env`, claves o `.git/config`;
  6. tocar `.github/workflows` o `.git/hooks`;
  7. agotar el presupuesto con lecturas grandes;
  8. imitar una caja o un botón en el texto.
- **Qué lo para:**
  - **4, 5 y 6:** el confinamiento (D2) y las reglas fijas (D3), antes de preguntar nada;
  - **7:** los topes (D15) y el tope de vueltas de A3;
  - **8:** el texto ajeno va en su recuadro y los botones reales están fijos (regla vigente);
  - **2 y 3:** solo la caja con el diff exacto y su aviso fijo (D10). La persona es la única puerta.
- **Qué no para:**
  - **1:** las lecturas son automáticas. Con consentimiento de envío, un fichero hostil puede hacer que el modelo lea un fichero normal que contenga un secreto sin forma conocida y lo devuelva al proveedor. El daño se acota así: la carpeta no contiene las rutas prohibidas, el consentimiento es por carpeta y las lecturas se auditan. Pero no se impide;
  - una persona que aprueba sin leer;
  - que el código aprobado se ejecute después con otras herramientas.
- **Por qué.** Es la misma separación que CaMeL y el estudio §5.2: los datos no confiables solo pueden ser valores, y la puerta final es una persona que ve esos valores.
- **Impacto.** Requisito «El contenido de un fichero nunca aprueba»; caso de inyección en el fixture (un `README.md` que pide leer `.env` y editar el `Makefile`); filas SEC-03 y la nueva.

### D17. Matriz SEC: una fila nueva

- **Qué.** **SEC-17 · Escritura en la carpeta de trabajo** (o SEC-16 si `code-run` no se mergea antes):
  - **propiedad:** ningún fichero de la carpeta cambia sin una aprobación vigente, de un solo uso, ligada al hash de sus bytes nuevos y del `sha256` anterior; ninguna escritura sale de la carpeta ni toca una ruta prohibida;
  - **estado inicial:** `parcial`;
  - **cambios necesarios:** `scripts/check_sec_matrix.py` y `docs/security/sec-states.json` (dos ediciones, regla vigente).

  Las lecturas se añaden a las filas existentes: 01 (nombres y contenido), 03, 04, 05 y 15.
- **Por qué.** SEC-11 es la escritura en EA, y SEC-04 trata de lecturas y de la nota del vault. Ninguna fila dice qué protege una escritura arbitraria en ficheros de código.
- **Alternativas rechazadas.**
  - Meterla en SEC-04: mezcla traversal con aprobación.
  - Meterla en SEC-12: no cubre el confinamiento.
- **Impacto.** Tareas 5.x (fila) y la decisión abierta 9.

### D18. Tramos, del más pequeño al mayor

| Tramo | Qué | Tamaño **[I]** | Depende de |
|---|---|---|---|
| **B1** | Carpeta (D1), confinamiento (D2), reglas fijas (D3), `read` y `list` (D4), solo por `main.py workspace --root <ruta> read|list|check`, con auditoría (D7). Sin conversación ni bucle | **M** (≈ 450–600 líneas de producto, 600–800 de tests) | nada |
| **B2** | `/workspace` y el panel; servidor interno en el catálogo; lecturas `auto_read` en `/plan` y en el bucle; consentimiento de envío (D14) | **M** (≈ 300–400 / 400–500) | merge de `feature/code-mode-loop` (A2, A3) |
| **B3** | `write` y `edit` como efectos (D8, D9, D13), caja con diff (D10), leer antes de editar (D11), reconciliación | **L** (≈ 700–900 / 900–1 100) | B2 |
| **B4** | `/undo` (D12) | **S** (≈ 200 / 300) | B3 |
| **B5** | `glob` y `grep` (D5) | **M** (≈ 300 / 400) | B2 (puede ir en paralelo a B3) |
| **B6** (opcional) | Ejecución en Windows: uniones, `os.replace` con el fichero abierto, `st_nlink`, rutas largas | S | B3 |

`[I]` significa estimado, no medido. **Queda fuera de todos los tramos:** `delete` y `move` (salvo el borrado de `/undo`), `patch`, shell, `.gitignore`, `AGENTS.md`, tabuladores, imágenes y PDF, varias carpetas, ediciones aproximadas.

## Seguridad (SEC)

| SEC | Amenaza | Qué la detiene aquí |
|---|---|---|
| 01 | Credenciales | Nombres prohibidos y fichero entero rechazado por `secret_kinds` (D3); salida redactada (D4); contenido nuevo con credencial rechazado por D5 de code-mode; ruta en HMAC en la auditoría |
| 03 | Inyección desde un fichero | Contenido = datos marcados; no aprueba; las escrituras pasan por la caja (D16) |
| 04 | Traversal, enlaces, TOCTOU | D2 en tres fases; enlaces duros fuera; identidad sobre el descriptor; hueco residual documentado |
| 05 | Herramienta o argumentos fuera de la tabla | Tabla literal (D6) bajo `decide_before_start` (D7) |
| 07 | Escritura interrumpida | `uncertain`; `reconcile` antes de seguir; nunca se reaplica (D9) |
| 08 | Reinicio | Reconciliación de efectos y purga de deshacer al arrancar |
| 12 | Aprobación reutilizada o cambio alterado | Hash propio con bytes nuevos y `sha256` anterior; caducidad y uso único (D10) |
| 15 | Topes | D15 |
| nueva | Escritura en la carpeta | D17 |

## Risks / Trade-offs

- [Una persona aprueba un diff largo sin leerlo] → La caja no se pliega, «Approve» espera al final, hay un tope de 32 KiB y un aviso fijo. **Límite que no se arregla:** la persona es la puerta (deuda 1).
- [Un secreto sin forma conocida sale al proveedor] → Las reglas de nombre (D3), el consentimiento por carpeta (D14) y la auditoría. **Límite que no se arregla**, dicho en `SECURITY.md`.
- [Otro programa escribe el fichero entre la comprobación y `os.replace`] → La ventana es de milisegundos. **Límite que no se arregla:** no hay comparar-e-intercambiar portable (D9).
- [Un componente cambia por un enlace entre comprobar y abrir] → Identidad y nueva resolución tras abrir (D2). **Límite residual:** no hay `openat` portable.
- [En Windows, `os.replace` falla con el fichero abierto en un editor] → `target_busy`, limpio. NOT RUN hasta B6.
- [Sin tabuladores, algunos ficheros no se pueden editar] → Límite aceptado en v1, con la decisión abierta 8.
- [El modelo real no escribe listas de líneas a la primera] → La medición de A4 con Copilot real cuenta los motivos de rechazo, como en el tramo 3 de code-mode.
- [Copias de ficheros de la persona en el directorio de datos] → Solo para el dueño, con tope, purga a los 7 días y documentadas. En Windows, con las ACL heredadas (deuda 3).

## Migration Plan

- **B1:** una migración numerada nueva (el número se fija al implementar; 008 y 009 existen) con la tabla de eventos de la carpeta. Solo añade. Revertir es quitar el paquete `harness/workspace/`; la tabla se queda vacía.
- **B2:** la tabla de la carpeta por sesión y del consentimiento, en la misma migración o en la siguiente. Revertir quita `/workspace` y la tabla interna del catálogo; las listas MCP no cambian, salvo que un servidor llamado `workspace` vuelve a ser legal.
- **B3 y B4:** sin migración, si la fila del plan (`plan_runs`, migración 009) basta para la aprobación de escritura (se mide en la tarea 4.1). Si no basta, una columna nueva.

## Decisiones del dueño (2026-11-27)

El dueño contestó el 2026-11-27 y autorizó solo el tramo **B1**. Lo que sigue sustituye a las decisiones abiertas que había aquí. «Tomada» quiere decir que la decidió él. «Por defecto» quiere decir que se adopta la recomendación de este diseño y que él puede revisarla.

1. **Cómo se elige la carpeta. Tomada:**
   - `/workspace <ruta>` por sesión y `--root <ruta>` en la CLI;
   - sin variable de entorno y sin valor por defecto;
   - se rechazan las carpetas que propone D1.

   D1 queda como está, con la precisión de B1 que se anota en D1.
2. **Ficheros ignorados por git. Por defecto:** se leen si no los prohíbe D3, y `.gitignore` no se interpreta.
3. **`delete` y `move`. Tomada:** no existen en v1. El único borrado es el de `/undo` de un fichero que el harness creó.
4. **Leer antes de editar. Tomada:** obligatorio, y se rechaza si el fichero cambió desde esa lectura (`not_read`, `changed_since_read`; D11).
5. **Profundidad de deshacer. Tomada:** un nivel, aprobado como cualquier escritura (D12).
6. **Contenido de ficheros hacia un proveedor que no es el Mock. Tomada:**
   - solo con un consentimiento por carpeta, apagado por defecto (D14);
   - `.env*`, los ficheros de claves y `.git` se rechazan siempre, haya o no consentimiento (D3).
7. **`AGENTS.md`. Por defecto:** fuera de este change.
8. **Tabuladores y `\r` en lo que se escribe. Por defecto:** prohibidos en B3, porque D5 de code-mode se aplica sin excepciones.
9. **Fila SEC. Por defecto:** una fila nueva para las escrituras en la carpeta (D17). Llega con B3.
10. **Número del corte. Tomada:** **Corte 12**, ya añadido a `docs/plan/2026-11-24-ai-harness-cortes.md`.
11. **Orden. Tomada:**
    - B1 empieza ya, en paralelo al bucle;
    - B2 y los tramos siguientes, que dependen del bucle, esperan al merge de `feature/code-mode-loop`.

## Lo que enseñó el tramo B1 (2026-11-27)

### B1-1. Las carpetas del sistema que son enlaces (decisión D1 precisada)

- **Qué.** D1 decía que no puede ser un enlace ni la carpeta ni «ninguno de sus componentes». En B1:
  - la carpeta misma no puede ser un enlace ni una unión;
  - los componentes de **encima** de ella se resuelven, y lo que se muestra y se guarda es la ruta resuelta.
- **Por qué.**
  - En macOS, `/tmp`, `/var` y `/etc` son enlaces del sistema a `/private/…`, así que la regla original rechazaba cualquier carpeta bajo `/tmp`.
  - El atacante de este diseño es el contenido de la carpeta, que no controla las carpetas de encima.
  - **Dentro** de la carpeta, la regla sigue siendo la de D2: ningún componente puede ser un enlace.
- **Alternativas rechazadas.**
  - Exigir que la ruta escrita coincida con la resuelta: también rechaza `/tmp/x` en macOS.
- **Impacto.** `harness/workspace/root.py` (`check_root`); test `test_a_folder_under_a_system_link_is_accepted_resolved`.

### B1-2. Contención por identidad además de por nombre

- **Qué.** «Está dentro de» y «contiene» se deciden de dos maneras, y basta que una diga sí:
  - **por los nombres** de las rutas resueltas, comparados componente a componente tras NFC y `casefold()`;
  - **por la identidad** (`st_dev`, `st_ino`) de cada carpeta antepasada, cuando la ruta protegida existe.
- **Por qué.**
  - `resolve()` no corrige las mayúsculas en un sistema que no las distingue: `…/AI-Harness` y `…/ai-harness` son la misma carpeta en APFS y en NTFS.
  - La identidad no depende de cómo se escriba el nombre.
  - Ser más estricto que el sistema solo rechaza más carpetas, nunca menos.
- **Alternativas rechazadas.**
  - Solo `is_within`: distingue mayúsculas en `PosixPath`, así que en macOS dejaría pasar el repo escrito con otras mayúsculas.
- **Impacto.** `root.py`; tests `test_protected_folder_written_with_other_case_is_refused` y `test_containment_by_identity_when_names_differ`.

### B1-3. `code_run_root` todavía no se comprueba

- **Qué.** La configuración de `code-run` no existe en `develop`: es una propuesta sin código. El rechazo `code_run_root` queda en la lista cerrada, pero B1 no lo puede comprobar.
- **Impacto.** Se añadirá con su test cuando `code-run` se mergee. Queda anotado en `tasks.md` 2.2.

### B1-4. Cómo se ve el texto de un fichero

- **Qué.** Cada línea de un fichero (o cada nombre de una entrada de `list`) se escribe así, en este orden:
  1. todo carácter invisible, de control o separador de línea pasa a `<U+XXXX>` (también el tabulador y ESC);
  2. se redacta;
  3. se corta;
  4. se imprime tras `| `, como `mcp call`.

  Las líneas del harness (la cabecera, el resumen y los errores) van por stderr y nunca llevan texto del fichero. La ruta solo aparece en ellas después de pasar la fase 1 de D2.
- **Por qué.** Una línea `error: …` dentro de un fichero sale como `| error: …`. Una secuencia de escape o un carácter bidi se ve en vez de actuar. Así la persona ve un intento de «Trojan Source» en lugar de que se lo oculten.
- **Límite.** Un fichero que contiene el texto literal `<U+202E>` se ve igual que uno con el carácter real. Para leer es aceptable. Para la caja de B3, el hash ata los bytes.
- **Impacto.** `harness/workspace/render.py`; tests de `test_workspace_output.py`.

### B1-5. Auditoría: qué fila deja cada caso (D7 concretada)

- **Qué.** Migración **011** (`011_workspace_events.sql`): la 009, la 010 y la 013 son de `code-mode` y la 012 está reservada para otra rama (revisado el 2026-11-28, tras el merge de `develop` = `8a8afbd`). El ejecutor de migraciones aplica cada versión que falte, así que un hueco no estorba: la 011 entra igual en una base que está en la 010 que en una que ya tiene la 013 (`test_011_applies_on_a_database_at_010_and_at_013`). Qué deja cada caso:
  - un rechazo por la forma de la ruta o por las reglas de nombre (se decide sin tocar el disco): fila `denied` con `argument_invalid`;
  - un rechazo de la carpeta en la CLI (`--root`, antes de cualquier llamada): fila `denied` con `server_not_allowed`. **Revisado tras la revisión de `d0a65d8`:** la carpeta sustituida que encuentra una llamada de un plan (`workspace_changed`) se guardaba igual, `denied`/`server_not_allowed`, mientras el plan veía `tool_error`. La política sí la permitió: ahora es `allowed`, `failed` con `tool_error`, lo mismo que ve el plan;
  - una llamada de un plan cortada por su plazo o por Ctrl+C (B2-9): `timeout`/`timeout` o `failed`/`interrupted`, con el código `timeout` o `interrupted` en `workspace_events`;
  - lo que se descubre en el disco (enlace, binario, credencial, tamaño, nombre inexacto): fila `allowed` y `failed` con `tool_error`;
  - una lectura correcta: fila `completed` con `result_bytes`.

  En todos los casos hay además una fila en `workspace_events` con el código exacto (o `ok`) y el HMAC de la ruta. La clave es la de `mcp-args.key`, con un dominio propio (`ai-harness/workspace-path/v1`). Las lecturas no dejan fila `running`: no tienen efecto que reconciliar.
- **Impacto.** `harness/workspace/audit.py`; tests de `test_workspace_audit.py`.

### B1-6. Un segundo camino a las carpetas protegidas (revisión de `d0a65d8`, hallazgo 1)

- **Qué.** Medido en macOS 26 (2026-11-28): `/System/Volumes/Data`, `/System/Volumes` y `/System` se aceptaban como carpeta, y por ellas se leían el repo, el directorio de datos, el vault y la carpeta personal. `/System/Volumes/Data/Users` es `/Users` (un *firmlink* de APFS: mismo `st_dev` y `st_ino`), pero los antepasados de `/Users/…` suben hasta `/` sin pasar por `/System/Volumes/Data`, así que ni el nombre ni la identidad de los antepasados lo ven. Y la premisa de la revisión, «es un punto de montaje porque su `st_dev` difiere», **no se cumple aquí**: `os.stat` da el mismo `st_dev` (`16777232`) para `/`, `/Users` y `/System/Volumes/Data`, y `os.path.ismount('/System/Volumes/Data')` es `False`. Por eso se añaden tres reglas:
  1. **Segundo camino:** se buscan, dentro de la carpeta elegida y de sus subcarpetas hasta dos niveles (`MIRROR_SEARCH_DEPTH`), sin seguir enlaces, los finales de la ruta de cada carpeta protegida (`Users/<nombre>/…`, `<nombre>/…`…) que tengan su misma identidad. Encontrar uno rechaza la carpeta con el motivo de la protegida. Se listan como mucho 2 000 carpetas (`MIRROR_SEARCH_DIRS`). Con `/System`, el primer nombre del final está dos niveles más abajo (`Volumes/Data/Users`).
  2. **Punto de montaje:** una carpeta cuyo `st_dev` no es el de su padre se rechaza (`mount_point`). Cubre un disco externo, un volumen de Linux o de Windows montado en una carpeta; no cubre el caso de APFS, que lo cubre la regla 1.
  3. **Rutas de red y de dispositivo:** una ruta que empieza por dos separadores (`\\servidor\recurso`, `\\localhost\C$\…`, `\\?\GLOBALROOT\…`, `\\.\…`, `//x`), escrita así o resuelta así, se rechaza (`device_path`), en todas las plataformas por la misma función de cadenas. La forma larga de una unidad local (`\\?\C:\…`, que `resolve` puede dar para una ruta larga en Windows) se admite.

  Además, `home` rechaza también una carpeta que **contiene** la personal (por nombre y por identidad), no solo la personal misma.
- **Por qué.** Comparar el volumen (`statvfs().f_fsid`) sí distingue los volúmenes de APFS, pero `os.statvfs` no existe en Windows y la regla sería distinta por plataforma. La búsqueda por identidad usa solo `os.scandir` y `os.stat`, igual en las dos.
- **Alternativas rechazadas.**
  - Solo la regla del punto de montaje (lo que proponía la revisión): no rechaza `/System/Volumes/Data` en este Mac, como se midió arriba.
  - Recorrer toda la carpeta elegida: sin tope, una carpeta grande tardaría mucho en aceptarse.
  - Una lista de rutas del sistema (`/System`, `/Volumes`…): depende de la plataforma y se queda vieja.
- **Límites que no se arreglan.** Un segundo camino a más de tres niveles de la carpeta elegida, o tras 2 000 carpetas listadas, no se ve. Los puntos de montaje **dentro** de la carpeta se atraviesan sin aviso (decisión del dueño pendiente). En Windows no se ha ejecutado (NOT RUN): que `\\?\GLOBALROOT` y `\\localhost\C$` sean los únicos caminos de ese tipo es plausible, no comprobado.
- **Impacto.** `harness/workspace/root.py`, `codes.py` (`device_path`, `mount_point`), la migración 011 (que no ha salido de esta rama); tests nuevos de `tests/unit/test_workspace_root.py`; SEC-04.

## Lo que enseñó el tramo B2 (2026-11-28)

Medido sobre `develop` = `8a8afbd` (tarea 3.1): la marca de lectura por regla se llama `auto_read` (`ToolEntry.auto_read`); el modo de aprobación es `means = 'rule'` en `plan_runs`; lo que se envía tiene topes de 4 KiB por paso (`loop.STEP_SEND_MAX_BYTES`), 12 KiB de resultados por vuelta (`RESULTS_SEND_MAX_BYTES`) y 28 000 caracteres por vuelta (`TURN_SEND_MAX_CHARS`); los datos van entre `<<<RESULTADOS <marca>` y `RESULTADOS <marca>>>>`, cada línea tras `| `. Lo que dentro de `/agent` corre por regla es lo que además tiene todos los argumentos acotados (A3-12: `pattern` y `max_length` ≤ 64). Con un proveedor no sintético, la primera vuelta con resultados de cada bucle pide la caja (A3-14).

### B2-1. La carpeta vive en la memoria de la conversación

- **Qué.** `/workspace <ruta>` guarda en la conversación la raíz aceptada (`Root`: ruta resuelta, `st_dev`, `st_ino`) dentro de un `Folder` que también sabe si está suspendida. No hay tabla de carpeta por sesión. `/new`, `/resume` y un `chat` nuevo empiezan sin carpeta, y lo dicen. La auditoría (`workspace.folder`: `set`, `off` o el motivo del rechazo) guarda 16 caracteres del HMAC de la carpeta.
- **Por qué.** La ruta es contenido de la persona (D7). Guardarla en claro para recordarla entre arranques contradice «la ruta solo como HMAC». Elegirla otra vez cuesta una línea y hace visible la decisión.
- **Alternativas rechazadas.**
  - La tabla de D1 con la ruta en claro: la ruta quedaría en SQLite.
  - La tabla con la ruta cifrada: una clave más que gestionar para ahorrar una línea.
- **Impacto.** D1 revisado en su sitio; `conversation._workspace`; `PanelState.workspace`; `/status`; test `test_the_folder_does_not_follow_the_person_to_another_session`.

### B2-2. La ruta que elige el modelo cuenta como argumento acotado

- **Qué.** `path` se declara `string` con `max_length` 64 y el patrón `\.?[A-Za-z0-9_][A-Za-z0-9._-]*(/\.?[A-Za-z0-9_][A-Za-z0-9._-]*)*`: componentes ASCII de letras, cifras, `.`, `_` y `-`, ninguno `.` ni `..`, `/` entre ellos. Así cumple la regla de A3-12 sin cambiarla, y dentro de `/agent` las lecturas corren por regla. `offset`, `limit` y `depth` son enteros con tope. El patrón va **además** del confinamiento de D2 y de las reglas de D3, que siguen decidiendo cada ruta: el patrón solo estrecha lo que el modelo puede pedir.
- **Por qué (exfiltración).**
  - A3-12 existe porque un argumento de texto libre puede llevar lo leído a un **servidor** (un proceso que puede tener red). Aquí el argumento no sale de la máquina: lo recibe el propio harness, que lo usa para abrir un fichero local y lo guarda solo como HMAC.
  - Lo que el modelo elige es un canal pequeño: 64 caracteres de un alfabeto de 65 símbolos, que solo se ven en la pantalla y en la auditoría como hash.
  - El canal grande es el **contenido** devuelto. Ese va al proveedor solo con el consentimiento por carpeta (B2-3), con la caja de la primera vuelta de cada bucle (A3-14) y acotado a 4 KiB por paso. Sin ellos, nada sale.
- **Alternativas rechazadas.**
  - Que las lecturas de ficheros vayan siempre a la caja dentro de `/agent`: un bucle de lectura pediría una caja por vuelta, sin proteger más, porque el riesgo es el contenido y ese ya tiene su consentimiento.
  - Declarar la ruta con 1 024 caracteres (el tope de D2): sería texto libre, y la regla de A3-12 la mandaría a la caja.
  - Admitir Unicode en el patrón: NFC, invisibles y confusables ya los rechaza D2, pero el patrón dejaría de ser legible en el catálogo.
- **Límite que no se arregla en v1.** Un fichero con espacios, acentos u otros caracteres en el nombre, o con una ruta de más de 64 caracteres, no se puede leer desde un plan (sí con `main.py workspace read`). Decisión abierta 12.
- **Impacto.** `harness/workspace/server.py` (`PATH_PATTERN`, `TOOLS`); tests `test_a_path_outside_the_pattern_refuses_the_plan_before_anything_runs` y `test_agent_lists_then_reads_then_answers`.

### B2-3. El consentimiento de envío por carpeta

- **Qué.**
  - **Dónde vive.** Una tabla `workspace_consents (folder_hmac, provider, state, approval_hash, decided_at)` en la migración 011, que no ha salido de esta rama. `folder_hmac` es el HMAC (clave `mcp-args.key`, dominio `ai-harness/workspace-folder/v1`) de la ruta resuelta **y** de su identidad: otra carpeta con el mismo nombre no hereda el consentimiento.
  - **Cómo se da.** `/workspace send on` abre la caja (botones en la pantalla completa, código tecleado en el modo plano) con el texto «file contents of <ruta> will be sent to <proveedor>», ligado al hash de una `Proposal` de alcance `workspace-tools.send-consent`. Se decide con `approvals.decide`; `ApprovalScreen`, `ApprovalButton` y `ProposalArea` no cambian. Rechazado, sin decidir o caducado: no se da y la auditoría lo dice.
  - **Revisado tras la revisión de `d0a65d8` (hallazgo 4).** «Caducado» no existía en el código: la caja no tenía plazo y `decide` nunca devuelve `expired`, y tampoco se retiraba un Ctrl+C pendiente. Ahora la caja copia el control de `loop_flow._Loop._consent`: muestra `expires:`, una respuesta después del plazo de las aprobaciones (`approval_ttl_s`) queda `expired`, y lo escrito tras un Ctrl+C (`withdraw_pending_interrupt`) queda `undecided`. Lo concedido sigue sin caducar: dura hasta `/workspace send off` (decisión del dueño pendiente, `tasks.md` 3b.8).
  - **Cómo se revoca.** `/workspace send off` deja la fila en `revoked`.
  - **Qué hace.** En `/agent`, con un proveedor no sintético, antes de componer una vuelta con resultados el bucle pregunta a `PlanSetting.withhold`: si algún paso **completado** de `workspace` está en el informe y no hay consentimiento para esa carpeta y ese proveedor, se ve `not sent: no consent for this folder`, no se envía nada y el bucle termina `stopped (send_not_approved)`. Se comprueba en cada vuelta. Con consentimiento, la caja de A3-14 se sigue pidiendo una vez por bucle. Un paso rechazado (solo el motivo del harness) no necesita consentimiento. `/plan` nunca envía resultados: el contenido solo se muestra a la persona. El Mock no lo necesita.
- **Por qué.**
  - D14 y la decisión 6 del dueño: apagado por defecto, por carpeta, revocable.
  - Se reutiliza `send_not_approved` de la 013: un motivo nuevo exigiría reconstruir `loop_runs` para ampliar su `CHECK`. La línea de la pantalla dice el motivo exacto.
- **Alternativas rechazadas.**
  - Un consentimiento por proveedor solamente: cubriría carpetas que nadie pensó.
  - Pedirlo con la caja de A3-14: esa caja es por bucle y por texto, y se olvidaría en el siguiente bucle.
  - Guardarlo en memoria: habría que darlo en cada `chat`, y la persona acabaría aprobando sin leer.
- **Impacto.** `harness/workspace/session.py`, `PlanSetting.withhold`, `loop_flow._Loop._withhold`, `conversation._workspace_send`; tests de consentimiento de `tests/unit/test_workspace_shell.py`.

### B2-4. El servidor interno en la vista de política

- **Qué.**
  - `config.InternalServer`: una clase base sin `command` (`tools`, `bound()`, `call()`), y `LoadedConfig.internal`, que se suma a `servers`. Lo que no es la vista de un `/plan` o un `/agent` (`mcp list`, `mcp call`, `main.py plan`) sigue sin servidores internos.
  - `gateway.call_tool` decide la política igual y, si el servidor es interno, le pasa la llamada en vez de arrancar un proceso. El servidor escribe su fila de `tool_calls` con el plan y el paso, y la de `workspace_events`.
  - `policy.entry_sha256` ata `bound()` = `{"internal": "workspace", "folder": <HMAC>}`: si la carpeta cambia entre leer y ejecutar el plan, el paso da `list_changed`.
  - Una llamada que la política deniega antes del servidor (argumento fuera del patrón, tope, argumento no declarado) deja solo su fila `denied` de `tool_calls`, como cualquier llamada MCP. Lo que el servidor rechaza deja las dos filas de B1-5 y vuelve al plan como un fallo `tool_error` con el texto `refused: <motivo>: <detalle del harness>`.
  - El catálogo dice la carpeta con las dos descripciones fijas de las herramientas (D6 revisado), 572 caracteres en total.
- **Por qué.** Es lo mínimo para que el plan, el bucle y la auditoría traten igual al servidor interno, sin tocar el lector del plan.
- **Alternativas rechazadas.** Una `ServerEntry` con un `command` ficticio: mentiría a `mcp list` y al hash de la lista.
- **Impacto.** `config.py`, `gateway.py`, `plan_run.approval_header` (la línea `server:` dice que no se arranca nada); tests `test_the_policy_decides_before_the_folder_is_touched` y `test_the_plan_binds_the_folder_it_was_read_with`.

### B2-5. Lo que el modelo recibe de una lectura

- **Qué.** El texto de un paso es la línea del harness (`read: <ruta>, lines a-b of N, sha256 …` o `list: …`) y cada línea del fichero o nombre tras `| `. El bucle lo vuelve a limpiar, lo acota (4 KiB por paso, cabeza y cola) y antepone su propio `| `: el modelo ve `| |      4  def greet…`. El listado de un plan se corta a 16 KiB con su marca.
- **Por qué.** Las reglas del bucle se aplican sin excepción: lo enviado es lo mostrado y se limpia después del corte (A3-16).
- **Límite.** Si el texto de un paso pasa de 4 KiB, el modelo ve su cabeza y su cola, con la marca del corte: para leer el resto tiene que pedir rangos con `offset` y `limit`.

### B2-6. Una carpeta sustituida queda suspendida

- **Qué.** Si una llamada encuentra la raíz cambiada (`workspace_changed`), el `Folder` queda suspendido: las siguientes llamadas se rechazan igual aunque vuelva la misma carpeta, hasta un `/workspace` nuevo. El panel y `/workspace` lo dicen.
- **Precisión (revisión de `d0a65d8`).** El cambio se detecta **al principio de cada llamada** (`check_root_unchanged` en `locate`), no durante ella: una carpeta sustituida a mitad de una lectura se ve en la llamada siguiente.
- **Impacto.** Requisito «Carpeta suspendida si cambia»; test `test_a_folder_replaced_after_it_was_chosen_stays_suspended`.

### B2-7. `workspace_busy` es una segunda capa

- **Qué.** La conversación hace una sola acción a la vez: con una caja abierta, lo que se escribe es la respuesta de la caja, no una orden. Aun así, `/workspace` se rechaza con `workspace_busy` mientras corre un `/plan` o un `/agent`.
- **Impacto.** Test `test_the_folder_cannot_change_while_a_plan_is_in_course`.

### B2-9. El plazo de una llamada (revisión de `d0a65d8`, hallazgos 5 y 6)

- **Qué.**
  - `InternalServer.call_timeout_s = 10` se declaraba y no se aplicaba, y el servidor ignoraba la señal de parada: un `read` o un `list` sobre un disco de red que no contesta bloqueaba el plan, y Ctrl+C no lo cortaba. Ahora `WorkspaceServer.call` corre la herramienta en un hilo aparte (`server.bounded`) y espera como mucho `call_timeout_s`, o hasta que la `StopSignal` del plan se activa (Ctrl+C o el plazo del plan), que el gateway le pasa como a un servidor MCP (`run_session`). Cortada por el plazo, la llamada es `timeout` (como el `timeout` de MCP); por la parada, lanza `KeyboardInterrupt` con su `outcome`, como `run_session`, y el plan la cuenta `interrupted` o `deadline`. Las dos dejan su fila y su código en `workspace_events`.
  - **Cuánto sale por bucle.** No estaba escrito. Solo llevan resultados las vueltas 2 a N y la de cierre: como mucho N × 12 KiB (`RESULTS_SEND_MAX_BYTES`) de resultados por `/agent`, **60 KiB con 5 vueltas** y **120 KiB con 10** (el máximo de `HARNESS_LOOP_MAX_TURNS`). La revisión estimó unos 72 y 132 KiB contando también el primer envío, que no lleva resultados. Medido (2026-11-28, macOS): 59 280 bytes de líneas de fichero en los 5 envíos con resultados de un bucle que lee tres ficheros de 16 KiB en cada vuelta (`test_what_one_loop_sends_of_the_folder_is_bounded`).
- **Por qué.** Es el mismo control que la ruta MCP: un plazo por llamada y la parada del plan.
- **Alternativas rechazadas.** Un proceso aparte por llamada, para poder matarlo: cuesta un arranque por lectura y otra frontera que auditar, para un caso (el disco de red colgado) que el hilo ya acota para el plan.
- **Límites que no se arreglan.** Se acota la **espera**, no la llamada al sistema: el hilo sigue bloqueado dentro del sistema hasta que el disco responde, y lo que lee después se descarta; no tiene cerrojos ni escribe nada. `main.py workspace` y la elección de la carpeta (`--root`, `/workspace`) no tienen plazo. Queda en `known-debt.md` 15.
- **Impacto.** `harness/workspace/server.py` (`call`, `bounded`), `harness/mcp/gateway.py` (pasa `stop`), `harness/mcp/config.py` (`InternalServer.call`), `codes.py` (`CALL_CODES`), `audit.py`, la migración 011; tests de `tests/unit/test_workspace_shell.py`; SEC-15.

### B2-8. Sin herramienta de escritura en B2

- **Qué.** Un plan que pide `workspace.edit` se rechaza con `tool_not_allowed` al leerlo (no con `write_not_allowed`, como suponía la tarea 3.7): la herramienta no existe en la tabla. Llega en B3.

### Decisiones abiertas del tramo B2

12. **Nombres que un plan no alcanza** (B2-2).
    - (a) el patrón ASCII de 64 caracteres (tomada en esta rama);
    - (b) admitir también letras Unicode en NFC (`\w`), con el mismo tope;
    - (c) subir el tope a 128 y aceptar que dentro de `/agent` esas lecturas vayan a la caja.

    **Recomiendo (a)** para la primera versión que el dueño prueba: es legible en el catálogo y basta para el fixture y para un repo de código normal; (b) cuando una carpeta real lo pida.
13. **Dónde vive la carpeta** (B2-1).
    - (a) solo en memoria, por `chat` (tomada);
    - (b) recordarla por sesión con su HMAC y pedir la ruta otra vez al reanudar, para comprobar que es la misma.

    **Recomiendo (a)**: más simple, y no guarda nada de la ruta.
14. **El consentimiento dentro de `/plan`.**
    - (a) `/plan` no lo pide, porque no envía resultados (tomada);
    - (b) avisar en `/plan` de que, sin consentimiento, `/agent` no enviará.

    **Recomiendo (a)**, con el aviso que ya da `/workspace` (`send: off for …`).

## Referencias: cómo lo hacen OpenCode, Claude Code y Codex

Consultado el 2026-11-27. Donde no se pudo confirmar, se dice.

**OpenCode** (`anomalyco/opencode`, rama `dev`, v2: `packages/core/src/tool/plugin/*.ts`; v1.4.0: `packages/opencode/src/tool/`):
- `read` (`read-filesystem.ts`, `plugin/read.ts`): 2 000 líneas por defecto y como máximo, 50 KiB por página, líneas cortadas a 2 000 caracteres, binario si hay NUL, imágenes y PDF como adjunto, y sugerencias de nombres parecidos si no existe.
- `edit` (`plugin/edit.ts`): `oldString`/`newString`/`replaceAll`, con fallo si hay más de una coincidencia. Si no casa exacto, tolera variantes tipográficas y espacios al final. Trabaja sobre una vista LF y conserva CRLF. v1.4.0 tenía nueve «replacers» aproximados y `FileTime.assert` («You must read file X before overwriting it», mtime y tamaño). **En v2 no se encontró ese control de lectura previa**, solo un bloqueo por fichero; sin confirmar en todo el repo.
- `glob`/`grep`: ripgrep, 100 resultados, 30 s, `.git/**` siempre fuera. Que respete `.gitignore` **no está confirmado** (se deduce del comportamiento de ripgrep).
- Permisos (`permissions.mdx`): todo `allow` salvo `ask` para `*.env`, y `external_directory` permitido. La contención se compara sobre la ruta escrita (`file-access.ts`).
- Fuentes: https://github.com/anomalyco/opencode/tree/dev/packages/core/src/tool y https://github.com/anomalyco/opencode/blob/v1.4.0/packages/opencode/src/file/time.ts. **Se copia:** reemplazo exacto y único, `replaceAll`, NUL = binario y vista LF. **Se evita:** ediciones aproximadas, todo permitido por defecto y la contención sin resolver.

**Claude Code** (https://code.claude.com/docs/en/tools-reference.md, `permissions.md`, `sandboxing.md`; confirmado en la documentación):
- `Edit`: reemplazo exacto; `old_string` único salvo `replace_all`.
- Lectura previa obligatoria con los modelos anteriores. Con los nuevos, solo si leer no pediría permiso. Una lectura parcial no cuenta.
- Si el fichero cambió desde la lectura, la edición se aplica igual cuando el texto casa una vez.
- `Read`: 25 000 tokens y 256 KB.
- `Glob` ordena por fecha e ignora `.gitignore` por defecto; `Grep` lo respeta.
- Carpetas de trabajo con `--add-dir`. Reglas `Read(...)`/`Edit(...)` con sintaxis de `.gitignore`.
- El sandbox solo cubre Bash, no las herramientas de ficheros, y no existe en Windows nativo.

**Se copia:** la lectura previa. **Se evita:** aplicar sobre un fichero cambiado desde la lectura sin volver a leer.

**Codex CLI** (https://github.com/openai/codex, `codex-rs/`; confirmado en el código):
- Modos `read-only`, `workspace-write` y `danger-full-access` (`protocol/src/config_types.rs`).
- Aprobación `untrusted`, `on-request` (`on-failure` es un alias), `granular` y `never`.
- `writable_roots`, sin red por defecto. `.git`, `.agents`, `.codex` y `.aws` son de solo lectura dentro de las raíces escribibles (`protocol/src/permissions.rs`).
- `apply_patch` con su gramática (`core/assets/tools/apply_patch.lark`) y contexto tolerante a espacios (`apply-patch/src/seek_sequence.rs`).
- Seatbelt en macOS, bubblewrap con seccomp en Linux y un sandbox de Windows (`windows-sandbox-rs`), cuya madurez **no está confirmada**.
- **No se encontró** un control de lectura previa ni de fichero cambiado, aparte de que un parche con contexto viejo no casa (sin confirmar en todo el repo).
- La página de seguridad de la documentación redirige ahora a otra cosa, así que se usó el código.

**Se copia:** las rutas protegidas dentro de la raíz escribible. **Se evita:** el formato de parche propio y un sandbox por plataforma, que aquí está prohibido.
