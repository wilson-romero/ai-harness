# Design

## Context

Parte del árbol de `skill-engine` implementado: formato de Skill y `workflow.json` (D2–D4 de ese change), referencias marcadas como datos (D5), reglas de `validate` (D6), pasos `llm` a través de la sesión con memoria del proyecto (D7), migración `003` con `skill_steps.prepared_at` y `effect_ref` (D8), `NamedLock` (D9), reconciliación de un efecto incierto (D10), aprobación ligada al hash (D12), protocolo de efectos `prepare`/`apply`/`reconcile` con registro cerrado (D13) y Mock guionizado (D15). De `project-memory`: `load_memory_settings` (raíz real del vault), validación pura de nombres y recorrido sin enlaces (`paths.py`), `parse_frontmatter` y `frontmatter_problem` (`notes.py`), selección del contexto, que ya incluye las notas de `Decisiones/` con `project_slug` del proyecto (D6 de ese change), y `redact()`. La motivación está en `proposal.md`; los requisitos, en `specs/`.

Premisas heredadas, **vueltas a medir** el 2026-11-24:

- `claude-memory-system` en `92b19ea` (rama `master`, último commit 2026-09-30; lectura con `gh api` de su árbol público): ninguna plantilla (`templates/`) ni migración (`migrations/001`–`006`) menciona `Decisiones/`; `docs/arquitectura.md` la marca como zona del **curador** con un `_INDEX.md` que no se comparte; `scripts/memoria-curator.sh` (líneas 252–255) verifica su propio trabajo listando los `.md` de `Memoria/`, `Lecciones/`, `Memoria-CC/` y `Decisiones/` cuyo `mtime` es posterior al inicio de su ejecución. Confirma D9 de `project-memory`: no hay convención que seguir y hay que fijar una.
- Fixture `tests/fixtures/vault-synthetic/Decisiones/alpha-mensajeria.md`: frontmatter `type: decision`, `machine`, `project_slug`, `created`, `updated`, `tags` en línea; es la forma que el lector de memoria ya acepta.
- `os.replace` sobrescribe un destino existente; `os.link` lo rechaza con `FileExistsError` (medido en la Mac, CPython 3.14.8, con un script desechable).
- `harness/memory/` no tiene ninguna primitiva de escritura (`tests/security/test_memory_no_writes.py` en verde sobre `032e989`).

## Goals / Non-Goals

**Goals:**

- Dos Skills de producto que usan solo lo que da `skill-engine`: dos carpetas y un efecto, sin tocar el motor ni la aprobación.
- Una escritura en el vault tan pequeña y comprobable como sea posible: un fichero nuevo, en una carpeta, con bytes aprobados, sin sobrescribir nada.
- Que una decisión registrada vuelva sola al contexto del proyecto en la siguiente pregunta.

**Non-Goals:**

- Editar o versionar decisiones existentes, mantener índices o coordinarse con el curador.
- Medir la calidad de las revisiones o decisiones con un modelo real.

## Decisions

### D1 · `hls-review`: una pregunta con memoria y una comprobación de estructura

- **Qué:** `skills/hls-review/workflow.json`:

  ```json
  {
    "schema": 1,
    "version": "1.0.0",
    "inputs": {"document": {"description": "Documento HLS a revisar", "required": true}},
    "steps": [
      {"id": "review", "kind": "llm", "template": "templates/review.md", "memory": "project", "timeout_s": 300},
      {"id": "check", "kind": "validate", "of": "review", "format": "markdown", "max_bytes": 32768,
       "required_headings": ["Resumen", "Alternativas", "Restricciones", "Requisitos no funcionales", "Supuestos", "Preguntas pendientes"]}
    ],
    "output": "check"
  }
  ```

  `templates/review.md` (en español, genérica) pide revisar alternativas, restricciones y requisitos no funcionales del documento a la luz de la memoria del proyecto; distinguir **evidencia** (lo que dicen el documento o la memoria), **supuesto** y **propuesta**; no inventar hechos ni nombres; devolver exactamente esas seis secciones con `##`. Lleva la línea fija `tarea: hls-review/review`, que el Mock guionizado usa como clave (D15 de `skill-engine`). El documento entra con `{{inputs.document}}`, marcado como datos. La revisión sale por stdout; la persona la redirige a un fichero si quiere.
- **Por qué:** es el flujo de §12 del plan maestro («recuperar contexto → revisar alternativas, restricciones y NFR → preguntas pendientes») en los pasos que el motor ya tiene. Una sola pregunta mantiene el coste y el tiempo acotados con Copilot; los encabezados son lo único que se puede comprobar sin interpretar el texto.
- **Alternativas rechazadas:**
  - Dos preguntas (resumir y después revisar): duplica tiempo y superficie sin una comprobación intermedia útil.
  - Guardar la revisión en el vault o en un fichero: sería una segunda escritura que aprobar; el plan no la pide.
  - Pedir JSON en lugar de Markdown: la revisión es para leerla una persona; JSON obliga a otro render sin ganar comprobaciones.
- **Impacto:** spec `hls-review`; tareas 2.x.

### D2 · `architecture-memory`: extraer, validar, preparar, aprobar, escribir

- **Qué:** `skills/architecture-memory/workflow.json`: entrada `source`; paso `extract` (`llm`, memoria del proyecto, plantilla `templates/extract.md` con `tarea: architecture-memory/extract`), paso `check` (`validate`, `format: json`) y paso `save` (`approval`, `of: check`, `effect: vault.save_decision`); salida `save`. Campos de `check`:

  | Campo | Tipo | Límites |
  |---|---|---|
  | `title` | `string`, `single_line` | 8–120 caracteres |
  | `context` | `string` | ≤ 2000 |
  | `decision` | `string` | ≤ 2000 |
  | `alternatives` | `string_list` | ≤ 8 elementos de ≤ 400 |
  | `consequences` | `string_list` | ≤ 8 elementos de ≤ 400 |
  | `assumptions` | `string_list`, opcional | ≤ 8 elementos de ≤ 400 |

  La plantilla pide un único objeto JSON con esos campos, separar evidencia de supuesto (`assumptions`), y no inventar. El proyecto sale de la sesión; ningún campo del JSON puede ser destino ni proyecto (el esquema cerrado los rechaza).
- **Por qué:** es «extraer decisión → revisión humana → persistir» del §12. Los límites hacen que la nota completa quepa con holgura en los 32 KiB aprobables de `skill-engine` (como mucho unos 16 KiB) y sea legible antes de aprobar.
- **Alternativas rechazadas:**
  - Que el modelo escriba la nota Markdown entera: el frontmatter y el destino saldrían de texto no confiable.
  - Un paso `llm` de «revisión» entre `check` y `save`: la revisión que el plan pide es humana.
- **Impacto:** spec `architecture-memory`; tareas 3.x.

### D3 · Dónde se escribe: `Decisiones/`, directamente

- **Qué:** las notas van a `<vault>/Decisiones/<nombre>.md`, sin subcarpeta. Si `Decisiones/` es un enlace, una unión o cualquier cosa que no sea un directorio real, la ejecución falla antes de pedir aprobación. No se toca `_INDEX.md` ni ninguna otra nota. **Revisada el 2026-11-24:** Wilson decidió que el harness **sí** crea `Decisiones/` si no existe (respuesta «créala»), lo que invierte la versión anterior («el harness no la crea»). Qué implica: (1) la carpeta se crea solo en `apply`, en el momento de la primera escritura aprobada, con el bloqueo del vault tomado y después de consumir la aprobación (D6), nunca en `prepare`, en una consulta ni en ningún comando de solo lectura (`memory …`, `skill list|show|status`, `ask --project`); (2) se crea con un único `os.mkdir` (sin `parents`) dentro de la raíz real y confinada del vault, y después se comprueba con `lstat` que es un directorio real y que `resolve()` es exactamente `raíz/Decisiones`; si otro proceso puso un enlace en su lugar, la escritura se deniega; (3) sin `Decisiones/`, `prepare` no encuentra duplicados (D8) y `reconcile` devuelve `absent`; (4) una carpeta creada por el harness no se borra nunca, ni si la escritura falla después.
- **Por qué:** el contexto de un proyecto (D6 de `project-memory`) ya lee `Decisiones/` y prioriza sus notas tras la nota de proyecto; escribir ahí hace que la decisión vuelva sola en la siguiente pregunta, que es el objetivo del Norte. El nombre propio (D4) y `source: ai-harness` (D5) distinguen las notas del harness de las del curador. Crear la carpeta solo cuando hay una escritura aprobada evita que un vault sin decisiones gane estructura vacía por usar el harness.
- **Alternativas rechazadas:**
  - Carpeta propia `Harness/Decisiones/`: no la lee el contexto del proyecto, ni la sincronización de conocimiento de `claude-memory-system`; habría que cambiar la selección de `project-memory` para leerla.
  - `Decisiones/harness/`: el contexto sí la leería (acepta cualquier profundidad bajo una carpeta curada), pero crea una subcarpeta que el curador no conoce y que habría que crear.
  - No crear `Decisiones/` si falta y fallar pidiendo crearla: era la opción de la primera versión de este diseño; **revisada el 2026-11-24**, Wilson la descartó y prefiere que el harness la cree en la primera escritura aprobada.
- **Riesgo de propiedad (medido):** el curador de `claude-memory-system` atribuye a su propia ejecución cualquier `.md` de `Decisiones/` cuyo `mtime` sea posterior a su inicio. Si el harness escribe una decisión mientras el curador corre en la misma máquina, el log del curador la contará como suya. No rompe datos; se escribe en el README.
- **Impacto:** spec `decision-notes` (Escritura confinada a Decisiones); tarea 4.3. Queda cerrada en este diseño; Wilson confirmó el destino y la creación de la carpeta el 2026-11-24 (tarea 1.1).

### D4 · Identificador y nombre de fichero

- **Qué:**
  - Título normalizado: NFKC, `casefold()`, espacios colapsados y recortados.
  - `decision_id = "dec-" + sha256("ai-harness/decision/v1\n" + project_slug + "\n" + título_normalizado)[:16]` (hexadecimal).
  - Slug: NFKD, solo ASCII, minúsculas, cada tramo fuera de `[a-z0-9]` → `-`, sin guiones repetidos ni en los extremos, recortado a 48 caracteres en un guion si lo hay. Vacío o nombre reservado de Windows (la misma lista de `paths.py`) → `decision`.
  - Nombre: `<YYYY-MM-DD>-<slug>-<id8>.md`, con la fecha de preparación y `id8` = los 8 primeros hexadecimales tras `dec-`. El nombre pasa la validación pura de `paths.py` (`is_safe_file_name`: sin separadores, sin punto ni espacio final, sin nombre reservado de Windows, ≤ 128 caracteres) antes de usarse. Dos slugs que solo difieren en mayúsculas no pueden darse (el slug es siempre minúsculas), y la comparación de duplicados es por `decision_id`, no por nombre, así que un sistema de ficheros que no distingue mayúsculas no cambia el resultado.
  - **Revisada el 2026-11-24 (implementación):** la «fecha de preparación» es la fecha **local** de creación de la ejecución (`skill_runs.created_at` pasado a la zona del equipo), no `prepared_at` del paso. Motivo: en el motor mergeado `prepared_at` se escribe al consumir la aprobación, es decir, después de mostrar y firmar la nota, así que no puede formar parte de los bytes firmados; y la fecha UTC de las 19:00 de Bogotá ya es «mañana», que el lector de memoria rechaza como `created is in the future`. La fecha de creación de la ejecución está en SQLite desde el primer momento, no cambia al reanudar ni al volver a preparar, y da los mismos bytes con el reloj movido un día.
- **Por qué:** un identificador que depende del proyecto y del título hace que «la misma decisión otra vez» se detecte aunque cambie la fecha o el texto del cuerpo; uno aleatorio no deduplicaría nada. La fecha delante sigue la convención medida de `Lecciones/` (`YYYY-MM-DD-<slug>.md`) y ordena por tiempo en el explorador de Obsidian; el `id8` hace casi imposible que dos títulos distintos con el mismo slug choquen el mismo día.
- **Alternativas rechazadas:**
  - Identificador por hash del contenido completo: dos redacciones de la misma decisión serían dos notas.
  - UUID en el nombre: ilegible en el explorador y sin deduplicación.
  - Usar el título tal cual: acentos, signos y nombres reservados darían rutas distintas por plataforma.
- **Impacto:** spec `decision-notes` (Nombre e identificador de la nota); tarea 4.1.

### D5 · Plantilla de la nota y render determinista

- **Qué:** la nota es una función pura de: el JSON canónico validado, el proyecto de la sesión, `prepared_at`, el Skill (nombre, versión, hash), `run_id`, el manifiesto de entradas y las filas de `request_context` del paso `extract`. Forma:

  ```markdown
  ---
  type: decision
  decision_id: dec-0123456789abcdef
  project_slug: demo-alpha
  status: accepted
  created: 2026-11-24
  updated: 2026-11-24
  tags: [decision, demo-alpha]
  source: ai-harness
  skill: architecture-memory@1.0.0
  run_id: <uuid de la ejecución>
  ---
  # <título>

  ## Contexto
  ## Decisión
  ## Alternativas consideradas
  ## Consecuencias
  ## Supuestos
  ## Procedencia
  - Skill `architecture-memory` 1.0.0 (sha256 <8 hex>), ejecución <run_id>.
  - Notas de memoria consultadas: `<ruta relativa>` (sha256 <8 hex>), …
  - Fuente: <n> bytes (sha256 <8 hex>).
  ```

  Cada texto del modelo pasa por `redact()` y por la normalización de contenido aprobable de `skill-engine` (D12: sin controles, NFC, `\n`); las listas se escriben como `- elemento`; `assumptions` vacía escribe «Ninguno declarado». El frontmatter solo contiene valores del harness y debe dar `frontmatter_problem(...) is None` con el lector de `project-memory`. **Revisada el 2026-11-24 (implementación):** la fecha sale de la creación de la ejecución (D4), no de `prepared_at`, así que volver a preparar la propuesta (para comprobar alteraciones, tras una caducidad o al reconciliar) da los mismos bytes. Además: (1) el texto del modelo se normaliza campo a campo con `normalise_content` antes del render y la nota entera otra vez después (la segunda pasada no cambia nada; un test lo comprueba); (2) en cada campo, una línea que empieza por `#` o que es solo guiones (`---`) se escribe con una barra invertida delante, para que el modelo no pueda abrir secciones ni simular un bloque de frontmatter, y `<<<`/`>>>` se cambian por sus equivalentes visuales con `neutralise_delimiters`, para que la nota no pueda falsificar los delimitadores del bloque de memoria cuando `memory context` la lea; (3) el frontmatter no lleva ningún texto del modelo (ni siquiera el título), solo valores del harness; (4) la procedencia añade «Credenciales enmascaradas: N», el número de marcas `[REDACTED:…]` de la nota, y la terminal lo muestra también en la cabecera de la aprobación (`redacted: N credential(s) redacted`).
- **Por qué:** es lo que pide §12 («guardar referencias a versión de Skill, fuentes y aprobación; no guardar datos sensibles innecesarios») con lo que ya existe: la procedencia de la memoria se lee de `request_context`, que se guarda con cualquier proveedor, y de la fuente solo se escriben tamaño y hash. Sin `machine`: el campo es opcional en la convención medida y nombraría el equipo.
- **Alternativas rechazadas:**
  - Incluir el hash de la propuesta o el `approval_id` en el frontmatter: el hash depende del contenido (circular) y el `approval_id` cambia en cada reaprobación, lo que cambiaría los bytes aprobados; `run_id` ya enlaza con la aprobación en SQLite.
  - Copiar la fuente entera en la nota: puede ser un documento corporativo largo; la nota es la decisión, no el expediente.
- **Impacto:** spec `decision-notes` (Frontmatter compatible con el vault), `architecture-memory` (Credenciales enmascaradas en la nota); tarea 4.2.

### D6 · Escritura: bloqueo, comprobaciones, consumo, temporal y enlace

- **Revisada el 2026-11-24 (implementación).** La versión anterior terminaba con `os.replace(temporal, destino)`. Se cambia por dos motivos: `os.replace` **sobrescribe** un destino existente (medido en macOS y documentado así para todas las plataformas), lo que deja abierta la ventana de sobrescritura por un tercero que la versión anterior aceptaba; y en el motor mergeado de `skill-engine` la aprobación la consume el motor antes de llamar a `apply` (revisión 8.1), no el efecto. Qué queda:
- **Qué:** el motor y el efecto, en este orden:
  1. `prepare` (antes de pedir la aprobación, y otra vez al reanudar): confinamiento de la raíz y de `Decisiones/` sin crear nada (D3), deduplicación (D8) y render (D5). Si algo falla, el efecto lanza `EffectRefused(código)` y el motor deja el paso y la ejecución `failed` con ese código, sin fila en `approvals`.
  2. El motor entra en `effect.exclusive(contexto)`: para este efecto, `NamedLock(data_dir, "vault-decisions")` con espera de como mucho 5 s. Si no se obtiene, error controlado (código 1), la aprobación sigue `granted`, el paso y la ejecución quedan `awaiting_approval` y `skill resume` lo reintenta; nada consumido, nada escrito.
  3. Con el bloqueo tomado, el motor consume la aprobación y pone el paso en `applying` con `effect_ref = decision_id` y el SHA-256 de la nota, en una transacción (D12 de `skill-engine`).
  4. `apply` recibe solo la propuesta verificada (destino y contenido ya firmados) y vuelve a comprobar con el bloqueo tomado: confinamiento, que `Decisiones/` es un directorio real cuya ruta resuelta es exactamente `raíz/Decisiones` (si no existe la crea con un único `os.mkdir` y lo vuelve a comprobar, D3), que el destino es un nombre legal (`is_safe_file_name`), que no existe (`lstat`) y que ninguna nota tiene ese `decision_id` (D8). Cualquier fallo: `EffectRefused` y paso `failed` (`unsafe_target`, `conflict` o `duplicate_decision`).
  5. Escribe los bytes en `Decisiones/.harness-<run_id>-<paso>.tmp` con `os.open(O_WRONLY | O_CREAT | O_EXCL | O_BINARY | O_NOINHERIT)` (los dos últimos por capacidad con `getattr(os, …, 0)`): `O_CREAT | O_EXCL` no abre nunca algo que ya existe, tampoco un enlace en ese nombre; después `os.write` hasta el final, `os.fsync` y `os.close`. Comprueba con `fstat` que lo escrito es un fichero regular de ese tamaño.
  6. Publica con `os.link(temporal, destino)`: un enlace duro nuevo **falla si el destino existe, de cualquier tipo** (`FileExistsError`, medido en macOS; POSIX `link()` devuelve `EEXIST`), así que no puede sobrescribir nada aunque un tercero cree el fichero entre la comprobación del paso 4 y este paso. Después comprueba con `lstat` que el destino tiene el dispositivo e inodo del temporal y borra el temporal (`os.unlink`). Si el enlace falla porque el destino existe: borra el temporal y `EffectRefused("conflict")`. Si falla por otra causa (por ejemplo, un sistema de ficheros sin enlaces duros): borra el temporal y `EffectRefused("write_failed")`; **no hay vuelta atrás a `os.replace`**.
  7. El motor marca el paso `completed` con la nota como salida (texto solo con proveedor sintético) y la ruta relativa sale por stdout.
- **Por qué:** cada paso deja el vault con la nota entera o sin ella (el nombre final aparece de una vez, con todos sus bytes, al crear el enlace), nunca sobrescribe una nota de nadie, y el consumo de la aprobación queda registrado antes de tocar el disco, así que un fallo después nunca deja una aprobación reutilizable. El temporal empieza por punto: el lector de memoria (D5 de `project-memory`) no entra en ocultos. Entre el enlace y el borrado del temporal, la nota tiene dos enlaces duros y el lector la salta (`st_nlink > 1`); si el proceso muere justo ahí, la reconciliación (D7) borra el temporal y la nota vuelve a ser visible. El nombre del temporal se deriva del `run_id` y del paso, no del contenido, para poder borrarlo al reconciliar.
- **Windows (supuesto, no medido por un agente):** la documentación oficial de Python dice que `os.link` existe en Windows desde 3.2 y que allí `follow_symlinks` vale `False` por defecto; la de `CreateHardLinkW` (lo que usa `os.link`) dice que solo funciona en NTFS, para ficheros y dentro del mismo volumen; la de `os.rename` dice que en Windows un destino existente da siempre `FileExistsError`, mientras que `os.replace` lo sustituye. Que `CreateHardLinkW` falle con `ERROR_ALREADY_EXISTS` (que Python convierte en `FileExistsError`) cuando el nombre nuevo existe es el comportamiento conocido de la función, pero el extracto consultado no lo dice con esas palabras: se da por supuesto y lo confirma la tarea 6.6 (el test «Destino ocupado» pasa por ese camino). Un vault en FAT32/exFAT o en una unidad de red sin enlaces duros no puede recibir decisiones: el efecto falla con `write_failed` sin escribir.
- **Alternativas rechazadas:**
  - `os.replace(temporal, destino)` (la versión anterior): sobrescribe en silencio un destino que aparezca entre la comprobación y el renombrado.
  - `os.rename`: en Windows rechaza un destino existente, pero en POSIX lo sustituye; el mismo código tendría dos semánticas.
  - `open(destino, "xb")` y escribir directamente: atómico contra sobrescritura, pero un lector puede ver la nota a medias.
  - Consumir la aprobación después de escribir: una muerte entre la escritura y el consumo dejaría una aprobación viva para una nota ya escrita.
  - Que el efecto tome el bloqueo dentro de `apply`: la aprobación ya estaría consumida si el bloqueo no se obtiene, y el escenario «Escritor ocupado» pide que siga `granted`.
- **Límites que no se arreglan:** el bloqueo solo excluye a otros procesos del harness que usan el mismo directorio de datos; otros programas (el curador, Obsidian) no lo respetan, pero tampoco pueden hacer que se sobrescriba nada (paso 6). Entre la comprobación de `Decisiones/` del paso 4 y el `os.open` del paso 5, alguien con permiso de escritura en el vault podría cambiar `Decisiones/` por un enlace; el paso 6 comprueba después que el destino resuelto sigue en `raíz/Decisiones` y, si no, borra lo escrito y falla, pero durante esa ventana el temporal habría existido fuera. Tampoco se sincroniza el directorio (`fsync` de un directorio no tiene la misma llamada en Windows); tras un corte de luz justo después del enlace, la nota podría no estar y la reconciliación lo vería como `absent`. Todo ello se escribe en el README.
- **Impacto:** spec `decision-notes` (Escritura atómica que nunca sobrescribe, Escrituras serializadas, Solo los bytes aprobados, Escritura confinada a Decisiones); `skill-engine` gana `EffectRefused` y `Effect.exclusive` (D11); tarea 4.3.

### D7 · Reconciliar una escritura interrumpida

- **Qué:** `reconcile` (solo lectura, salvo el temporal propio): primero borra `Decisiones/.harness-<run_id>-<paso>.tmp` si existe y es un fichero regular (no un enlace simbólico ni un directorio); después busca en `Decisiones/` notas con `decision_id = effect_ref`. Ninguna → `absent` (el motor pide una aprobación nueva para los mismos bytes); una cuyo SHA-256 es `output_sha256` esperado → `applied` (paso `completed`); cualquier otro caso → `conflict`. **Revisada el 2026-11-24 (implementación):** el temporal se borra antes de buscar porque, si el proceso murió entre el enlace y el borrado del temporal (D6, paso 6), la nota tiene dos enlaces duros y la búsqueda (con las reglas de `walk_vault`) la saltaría. Y `conflict` deja el paso `uncertain` con `resume` negándose con código 1, que es lo que hace el motor mergeado de `skill-engine` (requisito «Un efecto interrumpido nunca se aplica dos veces»), en lugar de `failed`: así una persona mira el vault antes de cancelar. La spec `decision-notes` se ajustó en su sitio (requisito «Escritura interrumpida se reconcilia sin repetir», mismo escenario).
- **Por qué:** buscar por identificador y comparar hash funciona aunque SQLite no tenga la ruta ni el texto (proveedor real), y nunca escribe la nota: si no está, la escritura nueva pasa otra vez por una aprobación.
- **Alternativas rechazadas:** reescribir la nota si no está, reutilizando la aprobación consumida: sería un reintento automático de una escritura incierta y una aprobación usada dos veces.
- **Impacto:** spec `decision-notes` (Escritura interrumpida se reconcilia sin repetir); tarea 4.4.

### D8 · Deduplicación por identificador

- **Qué:** se comprueba dos veces: en `prepare`, antes de pedir la aprobación (si ya existe, la ejecución falla con `duplicate_decision` y la ruta existente, sin molestar a la persona), y en `apply`, con el bloqueo tomado. **Revisada el 2026-11-24 (implementación):** `prepare` no se queja si la nota existente tiene exactamente los bytes que prepararía (es la nota de esta misma ejecución, ya escrita, que el motor vuelve a preparar al reconciliar); `apply` sí rechaza cualquier nota existente con ese identificador. La búsqueda recorre solo los `.md` directos de `Decisiones/` con las reglas de `walk_vault` (sin enlaces, sin ocultos, ≤ 1 MiB, tope de 20 000 ficheros) y lee `decision_id` del frontmatter.
- **Por qué:** el identificador determinista (D4) solo sirve si alguien lo compara. Hacerlo antes de la aprobación evita aprobar algo que no se va a escribir.
- **Límite:** una decisión equivalente escrita a mano o por el curador sin `decision_id` no se detecta. Se escribe.
- **Impacto:** spec `architecture-memory` (Decisión ya registrada); tarea 4.1.

### D9 · El test de «memoria sin escrituras» con una excepción nombrada

- **Qué:** el código que escribe vive en `harness/memory/decisions.py` (junto a la lectura que reutiliza). `tests/security/test_memory_no_writes.py` exime **exactamente** ese fichero de su búsqueda de primitivas de escritura, y gana dos comprobaciones: que la lista de exenciones es esa y solo esa, y que ningún comando `memory …` importa `decisions.py` (los comandos de memoria siguen sin poder escribir). La huella del vault tras cada comando de memoria y `ask --project` sigue exigida sin cambios.
- **Revisada el 2026-11-24 (implementación):** la exención no es un cheque en blanco: `decisions.py` pasa por la misma lista blanca y lo único que se le permite además es una lista cerrada de hallazgos (`os.open` con `O_WRONLY|O_CREAT|O_EXCL`, `os.write`, `os.fsync`, `os.link`, `os.unlink`, `os.mkdir`); cualquier otra primitiva (por ejemplo `os.replace`, `shutil`, `write_text`) en ese fichero hace fallar el test. El bloqueo y la normalización de contenido, que necesitan módulos de fuera de la lista blanca, viven en el adaptador `harness/skills/decision_effect.py`, que no escribe nada por sí mismo. `default_effects()` importa ese adaptador dentro de la función, así que un comando `memory …` no carga `decisions.py`; un test lo comprueba en un subproceso mirando `sys.modules`.
- **Por qué:** mover la escritura fuera de `harness/memory/` para que el test siga pasando sin tocarlo sería esconderla del control que existe para encontrarla. Una exención con nombre se revisa en el diff.
- **Alternativas rechazadas:** `harness/skills/vault_write.py` fuera del paquete de memoria: el grep no la vería nunca.
- **Impacto:** tarea 4.5.

### D10 · Qué se prueba con el Mock y qué no

- **Qué:** respuestas guionizadas sintéticas para cada caso (revisión bien formada, sin un encabezado, JSON válido, con campo extra, con `path`, con título multilínea, con token ensamblado en tiempo de ejecución) y documentos sintéticos en `tests/fixtures/skill-inputs/`. Un proveedor de prueba que registra el texto recibido comprueba lo enviado; otro no sintético comprueba lo que se guarda con un proveedor real.
- **No se puede probar con el Mock, y no se afirma:** que Copilot devuelva las seis secciones o el JSON con esos campos; la calidad de la revisión o de la decisión; que un modelo real ignore órdenes del documento o de la memoria; los tiempos reales frente a los plazos. Eso se mide cuando `copilot-web-provider` esté mergeado, en local por Wilson, aportando solo cifras (tasa de `validation_failed` por Skill).
- **Impacto:** tareas 2.x, 3.x y 5.3.

### D11 · Lo que este change añade al motor de `skill-engine`

- **Qué (2026-11-24, implementación):** cuatro ampliaciones pequeñas del motor mergeado, sin cambiar su esquema SQLite:
  - `EffectContext` gana `project_slug`, `run_created_at`, `skill_version`, `skill_sha256`, `inputs` (el manifiesto: nombre, SHA-256 y bytes de cada entrada) y `memory_notes` (ruta y SHA-256 de las notas de `request_context` de las peticiones de la ejecución). Todo sale de SQLite y no cambia al reanudar.
  - `EffectRefused(code, message)`: lo que `prepare` o `apply` lanzan para rehusar de forma controlada. En `prepare`, el paso y la ejecución quedan `failed` con `code` sin crear aprobación; en `apply`, el paso queda `failed` con `code` (la aprobación ya está consumida y no vuelve a servir).
  - `Effect.exclusive(contexto)`: un gestor de contexto que el motor abre antes de consumir la aprobación y cierra después de `apply`; `NoEffect` devuelve uno vacío. Si lanza `EffectBusy`, nada se consume.
  - `Prepared.redactions` (número de credenciales enmascaradas, se muestra en la cabecera de la aprobación) y `RunOutcome.applied` (los destinos escritos en esta invocación, que el CLI imprime por stdout como `applied: <ruta relativa>`).
  - `FieldSpec.min_length` para el límite inferior del título (D2).
- **Por qué:** son las piezas mínimas para que un efecto con escritura real cumpla lo que exige la revisión: una sola preparación, la aprobación consumida con el bloqueo tomado y rehúses controlados antes de pedir nada.
- **Alternativas rechazadas:** que el efecto lea SQLite por su cuenta para conocer el proyecto o la procedencia: duplicaría consultas y daría al efecto una conexión que no necesita.
- **Impacto:** `harness/skills/effects.py`, `engine.py`, `approvals.py`, `definition.py`, `checks.py`, `commands.py`; los tests de `skill-engine` siguen pasando sin cambios de comportamiento.

## Risks / Trade-offs

- [`Decisiones/` es zona del curador en `claude-memory-system`] → nombre propio, `source: ai-harness`, nunca se edita ni borra nada ajeno; la carpeta solo se crea en la primera escritura aprobada (revisada el 2026-11-24, D3); el curador podría atribuirse la nota en su log si coincide en el tiempo (medido, D3). Lo confirma Wilson en la tarea 1.1.
- [Requisito vigente de `memory-vault` que dice que el harness no modifica el vault] → **Revisado el 2026-11-24:** con `project-memory` archivado, `specs/memory-vault/spec.md` lo modifica (MODIFIED con el bloque íntegro); tarea 1.2.
- [Sobrescritura por un tercero en la ventana entre la comprobación y el renombrado] → **Revisada el 2026-11-24:** eliminada; la publicación con `os.link` falla si el destino existe (D6).
- [Vault en un sistema de ficheros sin enlaces duros (FAT32, exFAT, algunas unidades de red)] → la escritura falla con `write_failed` sin escribir nada; escrito en el README (D6).
- [Corte de luz tras el renombrado sin sincronizar el directorio] → la reconciliación lo detectaría como `absent` y pediría aprobar de nuevo; aceptado y escrito.
- [Copilot no devuelve JSON estricto o las seis secciones] → `failed` controlado, sin escritura; se mide con el Corte 2 mergeado.
- [El vault vive en una carpeta sincronizada y el cliente de sincronización crea una copia en conflicto de la nota] → el harness no lo impide (D3 de `project-memory`, revisada); `memory maintain --dry-run` ya cuenta los conflictos de sincronización.
- [Una decisión equivalente sin `decision_id` no se deduplica] → límite escrito (D8).
- [Enlaces simbólicos en Windows sin privilegio] → los tests que crean enlaces se omiten con motivo visible; la validación pura no los necesita.

## Migration Plan

Sin migración de esquema. Añade dos carpetas a `skills/`, un módulo y un efecto. Sin `HARNESS_VAULT_ROOT`, `architecture-memory` y `hls-review` fallan de forma controlada antes de preguntar. Vuelta atrás: revertir el change; las notas ya escritas en `Decisiones/` siguen siendo notas válidas del vault y nadie las borra.

## Open Questions

Ninguna que cambie specs o tareas. Las decisiones que Wilson debe confirmar antes de implementar están como tareas 1.1 y 1.2, porque cambian lo que se construye.
