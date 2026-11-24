# Design

## Context

Parte de la punta de `feature/project-memory` (`032e989`), que contiene `session-core` (ya en `develop`) y `project-memory` (sin mergear). Lo que existe y sobre lo que se enchufa este change:

- `SessionService.ask(raw_session_id, prompt, context)` (`harness/core/service.py`): toma el `SessionLock` de la sesión, inserta la solicitud `pending` y el mensaje del usuario (texto solo si `provider.synthetic_content`), aplica el plazo con `asyncio.timeout` (vencido antes de `on_sent` → `timeout`, después → `uncertain`, excepción → `failed`) y registra `request_context` si hay contexto de memoria. `recover()` marca `uncertain` las solicitudes en curso cuyo bloqueo está libre.
- `SessionLock` (`harness/storage/locks.py`): transacción `BEGIN EXCLUSIVE` sobre `<data>/locks/<session_id>.lock`, no bloqueante. Un segundo `SessionLock` del **mismo** proceso sobre la misma sesión también falla (es otra conexión), así que el motor no puede llamar a `ask` mientras tiene el bloqueo.
- `LLMProvider` (`harness/providers/base.py`): `Protocol` con `name`, `synthetic_content` y `ask(request, on_sent)`. Hoy solo existe el Mock; Copilot Web (`copilot-web-provider`, Corte 2) no está mergeado y declara `synthetic_content = False` y ninguna migración.
- Memoria (`harness/memory/`): `build_context`/`compose_prompt` con aviso, nonce y neutralización de marcadores (D6 de `project-memory`); `parse_frontmatter` mínimo (`notes.py`); validación pura de nombres y recorrido confinado sin seguir enlaces (`paths.py`); `redact()`.
- **Revisada el 2026-11-24** tras mergear `develop` (`0319e4b`, PR #4 con las correcciones de una revisión independiente de `project-memory`): existe ahora `harness/memory/safe_text.py`, el saneado común (`strip_controls`/`terminal_safe` quitan caracteres de control `Cc`, de formato `Cf` —bidireccionales y de ancho cero incluidos— y separadores de línea, el tabulador pasa a espacio; `safe_text`/`safe_line` limpian y después redactan; `neutralise_delimiters` cambia todo `<<<` y `>>>` por equivalentes visuales). `paths.py` lee cada fichero con `read_vault_file` (`os.open` + `fstat`: mismo dispositivo e inodo que vio el recorrido, fichero regular, como mucho 1 MiB) y `is_within` rechaza rutas con `..`. Los errores de uso salen con código 2 (`UsageError`) y `cli.main` reconfigura stdout y stderr a UTF-8. El test `tests/security/test_memory_no_writes.py` es ahora una lista blanca sobre el árbol sintáctico de `harness/memory/`. Este diseño reutiliza esas piezas en lugar de duplicarlas (D3, D5, D6 y D12 revisadas).
- Migraciones `001_initial.sql` y `002_memory.sql`; la siguiente libre es la **003**. `audit_events` no tiene columnas para ejecución ni detalle.
- CLI con códigos 0 (hecho), 1 (error controlado), 2 (uso) y 130 (interrumpido), resultados por stdout y avisos por stderr.

Premisas medidas el 2026-11-24 en la Mac (arm64, CPython 3.14.8, con un script desechable fuera del repo):

- `json.loads` acepta claves duplicadas (se queda con la última: `{"a":1,"a":2}` → `{'a': 2}`) y `NaN`; `object_pairs_hook` permite rechazar duplicados; un anidamiento de 100 000 corchetes lanza `RecursionError`.
- `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` da `{"a":[1,2],"b":"ñ","v":1}`. `"é"` en NFC y en NFD no son los mismos bytes.
- `os.replace` sobrescribe el destino; `os.link` rechaza un destino existente con `FileExistsError`.
- Un directorio enlazado dentro de un Skill: `is_symlink()` es `True`, `is_junction()` `False` en macOS, y `os.walk(followlinks=False)` lo lista como nombre de directorio sin entrar.
- En un subproceso con stdin de `DEVNULL` y stdout capturado, `sys.stdin.isatty()` y `sys.stdout.isatty()` son `False`. `getpass.getuser()` devuelve un nombre no vacío.
- `re.sub` con una función de sustitución hace una sola pasada: el valor insertado `{{inputs.x}}` no se vuelve a sustituir.

## Goals / Non-Goals

**Goals:**

- Un motor que ejecute, persista y reanude secuencias lineales `llm`/`validate`/`approval`, y que `architecture-skills-llm` use sin tocar el motor: añade dos carpetas en `skills/` y un efecto.
- Que la aprobación sea el único camino a un efecto, ligada al contenido exacto, con caducidad y uso único, y que se pueda revisar por separado de cualquier escritura.
- Mismo código en macOS y Windows; ninguna dependencia nueva.

**Non-Goals:**

- Paralelismo, ramas, bucles o condiciones dentro de un Skill.
- Autenticar a la persona que aprueba: la identidad es el usuario local del sistema operativo (D12, límite escrito).
- Medir si un modelo real cumple los formatos de `validate` (no hay proveedor real mergeado).

## Decisions

### D1 · Dos changes, en este orden

- **Qué:** `skill-engine` (este) trae el formato, el motor, la persistencia, la aprobación, los límites, el Mock guionizado y Skills sintéticos de prueba; `architecture-skills-llm` trae `hls-review`, `architecture-memory` y el efecto `vault.save_decision`, la primera escritura del harness en el vault. El segundo depende del primero: usa su motor, su aprobación y su registro de efectos. Se implementan en `feature/skill-engine` y después en `feature/architecture-skills-llm` creada desde ella; los artefactos de ambos se planifican juntos en `feature/skill-engine`.
- **Por qué:** la aprobación es el control de seguridad más delicado del corte (SEC-12) y se revisa mejor sin una escritura real al lado; la escritura en el vault, en cambio, abre una cuestión de propiedad de carpetas y contradice un requisito vigente de `project-memory` (`memory-vault`: «el harness no modifica el vault»), que merece su propia revisión. Cada mitad se demuestra sola: este change con Skills sintéticos, el otro con los de producto.
- **Alternativas rechazadas:**
  - Un solo change: un PR que mezcla el motor genérico, la criptografía de la aprobación, dos plantillas de producto y la primera escritura en un vault ajeno; la revisión de SEC-12 se diluye.
  - Tres changes (aprobación aparte): la aprobación no tiene consumidor sin el motor y el motor no tiene sentido sin ella en este corte.
- **Impacto:** proposal de los dos changes; tareas 1.1 de cada uno; orden de archivo en `Workflow follow-up`.

### D2 · Formato en disco y raíz de Skills

- **Qué:** la raíz es `HARNESS_SKILLS_DIR` (absoluta) o, por defecto, la carpeta `skills/` del repositorio (resuelta desde la ubicación del paquete, no del directorio actual). Un Skill es `skills/<nombre>/` con:
  - `SKILL.md`: frontmatter con exactamente `name` y `description` (≤ 300 caracteres), leído con `parse_frontmatter` de `harness/memory/notes.py`; el cuerpo es documentación para la persona y nunca se envía al modelo.
  - `workflow.json` (esquema 1):

    ```json
    {
      "schema": 1,
      "version": "1.0.0",
      "inputs": {"document": {"description": "Texto a revisar", "required": true}},
      "steps": [
        {"id": "draft", "kind": "llm", "template": "templates/draft.md", "memory": "project", "timeout_s": 120},
        {"id": "check", "kind": "validate", "of": "draft", "format": "markdown",
         "required_headings": ["Resumen", "Preguntas pendientes"], "max_bytes": 32768},
        {"id": "confirm", "kind": "approval", "of": "check", "effect": "none"}
      ],
      "output": "check"
    }
    ```

  - `templates/*.md` (prompts de los pasos `llm`) y `references/*.md` (documentación opcional, no se envía).
- **Por qué:** es el formato del §8 del plan maestro (Agent Skills para la descripción, metadatos de ejecución propios en `workflow.json`), sin asumir compatibilidad con Claude Code. JSON y no YAML: la biblioteca estándar lo lee y no tiene etiquetas, anclas ni tipos implícitos. La raíz por defecto en el repo hace que `skill list` funcione recién clonado; la variable permite a los tests y a la demo usar Skills sintéticos.
- **Alternativas rechazadas:**
  - YAML para el workflow: dependencia nueva (`PyYAML`) y un lenguaje con construcciones que aquí sobran (D10 de `project-memory` ya lo descartó para el frontmatter).
  - Raíz relativa al directorio actual: el mismo comando lista Skills distintos según desde dónde se lance.
  - Varias raíces (repo + usuario): duplica la resolución de nombres sin consumidor.
- **Impacto:** spec `skill-definition` (Estructura de un Skill); tareas 2.x.

### D3 · Validación y SEC-14: deny-by-default con un solo camino de código

- **Qué:**
  - **Nombre** pedido en la CLI: `[a-z0-9][a-z0-9-]{0,63}`, comprobado antes de tocar el disco (rechaza `/`, `\`, `..` y unidades por construcción) y, además, rechazado si es un nombre reservado de Windows (`con`, `nul`, `com1`…) con la misma lista de `paths.py`; después debe aparecer **exactamente** en `os.listdir(raíz)` y ser un directorio real (no enlace ni unión), como `resolve_project` de `project-memory`. **Revisada el 2026-11-24:** la primera versión decía que la expresión ya excluía los nombres reservados «por construcción», y no es cierto (`con` la cumple); se añade la comprobación explícita.
  - **Lectura** de cada fichero aceptado con `read_vault_file` de `paths.py` (identidad comprobada sobre el descriptor abierto; **revisada el 2026-11-24**: reutiliza la corrección de la revisión de `project-memory` en lugar de un `read_bytes` propio), después de decidir el tamaño con el `lstat` del recorrido.
  - **Recorrido** de la carpeta con `os.walk(followlinks=False)`: cualquier enlace simbólico, unión (`is_junction()`) o fichero con `st_nlink > 1` invalida el Skill **entero** (en el vault se ignoraban; aquí un enlace es señal de Skill manipulado). Entradas que empiezan por punto: ignoradas, no leídas ni incluidas en el hash. Lista blanca: `SKILL.md`, `workflow.json`, `templates/*.md`, `references/*.md`, profundidad máxima 2; cualquier otro fichero o carpeta visible (`scripts/`, `*.py`, `*.sh`, `*.ps1`, `*.exe`, `schemas/`) → `unexpected file`. Cada fichero aceptado debe cumplir `resolve().is_relative_to(raíz_real)`.
  - **Rutas en `workflow.json`** (`template`): relativas POSIX, componentes `[a-z0-9][a-z0-9._-]*`, primer componente `templates`, sin `..`, y deben estar en la lista de ficheros aceptados por el recorrido (nunca se abre una ruta que el recorrido no vio).
  - **JSON estricto:** `object_pairs_hook` que rechaza claves duplicadas, `parse_constant` que rechaza `NaN`/`Infinity`, tamaño comprobado antes de parsear y `RecursionError` capturado (medido arriba).
  - **Esquema cerrado** con modelos Pydantic `extra="forbid"` y una unión discriminada por `kind` con `Literal["llm"]`, `Literal["validate"]`, `Literal["approval"]`: `tool`, `shell`, `script` o cualquier otro valor es «unknown step kind». `effect` es un `Literal` de los efectos registrados (D13).
  - `skill list` valida todos los Skills (está acotado por D14) y muestra los inválidos con sus motivos; un Skill inválido nunca hace fallar el listado de los demás.
- **Por qué:** lo que no está en la lista blanca no existe para el motor, así que un Skill no tiene forma de pedir que se ejecute algo: no hay ningún camino de código que lance un proceso a partir de un Skill. Validar el nombre como función pura permite probar entradas de Windows en la Mac (`..\otro`, `C:\x`) sin ramas por plataforma.
- **Alternativas rechazadas:**
  - Ignorar enlaces en lugar de invalidar el Skill (como en el vault): un Skill con un enlace se ejecutaría sin una plantilla que su autor creía presente; mejor rechazar entero y decir por qué.
  - Seguir enlaces que apunten dentro de la raíz: carrera entre comprobación y lectura y detección de ciclos para un caso que ningún Skill necesita.
  - Lista negra de extensiones peligrosas: siempre falta una.
- **Impacto:** spec `skill-definition` (Solo ficheros declarativos permitidos, Enlaces y traversal rechazados, Workflow declarativo y cerrado); tareas 2.x y 7.x.

### D4 · Hash y versión del Skill

- **Qué:** `version` es texto libre corto declarado en `workflow.json` (`[0-9A-Za-z.+-]{1,32}`). El hash es SHA-256 de `b"ai-harness/skill/v1\n"` seguido, por cada fichero aceptado en orden de ruta relativa POSIX, de `ruta + "\0" + sha256(contenido normalizado) + "\n"`; el contenido se normaliza decodificando UTF-8 estricto (un fichero no UTF-8 invalida el Skill), quitando el BOM y pasando `\r\n` y `\r` a `\n`. Se guarda en `skill_runs.skill_sha256` y entra en toda propuesta de aprobación (D12).
- **Por qué:** con `core.autocrlf` git puede sacar los ficheros con CRLF en Windows; sin normalizar, el mismo Skill tendría dos hashes y el vector de prueba fallaría en Windows. El prefijo de dominio evita confundir este hash con cualquier otro SHA-256 del sistema. La versión la escribe una persona; el hash no se puede olvidar de actualizar. Se elige hacer el hash robusto y **no** añadir una entrada en `.gitattributes`: el hash no depende de cómo git haya sacado los ficheros, y tampoco de un Skill copiado a mano desde otro sitio; los tests lo comprueban con copias CRLF y BOM creadas en tiempo de ejecución.
- **Alternativas rechazadas:**
  - Solo la versión: una plantilla editada sin cambiar la versión pasaría por el mismo Skill.
  - Hash del árbol de git: depende de que el Skill esté versionado y confirmado.
- **Impacto:** spec `skill-definition` (Hash y versión del Skill); D11; tarea 2.3.

### D5 · Referencias: sustitución literal de una gramática cerrada

- **Qué:** la única sintaxis es `{{` + espacios opcionales + una de `inputs.<nombre>`, `steps.<id>.output`, `steps.<id>.fields.<campo>` + espacios opcionales + `}}`, con nombres `[a-z][a-z0-9_-]{0,31}`. Al cargar el Skill, cualquier `{{` cuyo contenido no case con esa gramática invalida el Skill, y cada referencia debe resolver a una entrada declarada, a un paso **anterior** o a un campo declarado de un paso `validate` JSON anterior. Al ejecutar, una única llamada a `re.sub` con una función de búsqueda en un diccionario sustituye cada referencia; lo insertado no se vuelve a escanear (medido). `fields.<campo>` de tipo lista se inserta como líneas `- elemento`. Cada valor insertado va entre `<<<DATOS <nonce> <referencia>` y `DATOS <nonce>>>>`, con el nonce de 16 hexadecimales por paso y la misma neutralización de marcadores que el bloque de memoria de `project-memory` (D6 de ese change); la plantilla lleva delante un aviso fijo de que lo marcado son datos, no instrucciones. **Revisada el 2026-11-24:** el valor insertado pasa por `neutralise_delimiters` de `safe_text.py`, que sustituye **todo** `<<<` y `>>>` (no solo los que forman un marcador), y por `strip_controls`; así ningún valor puede cerrar su bloque ni el de memoria.
- **Por qué:** «no evaluar expresiones» se cumple por construcción: no hay intérprete, solo una tabla. Validar al cargar hace que un Skill con una referencia rota no llegue a gastar una pregunta. El marcado reutiliza una defensa ya medida y probada.
- **Alternativas rechazadas:**
  - `string.Template` o `str.format`: `format` accede a atributos e índices (`{0.__class__}`); `Template` no permite validar las referencias contra los pasos.
  - Jinja2 u otro motor: dependencia nueva y un lenguaje con expresiones, justo lo que el plan prohíbe.
  - Expresiones JSONPath para elegir partes de una salida: más gramática que validar; los campos de un `validate` JSON cubren el caso.
- **Impacto:** spec `skill-definition` (Referencias resueltas al cargar), `skill-execution` (Referencias sustituidas literalmente); tareas 3.1.

### D6 · `validate`: reglas cerradas y deterministas

- **Qué:** `of` nombra el paso anterior cuya salida se comprueba. Reglas por `format`:
  - Común: `min_bytes`, `max_bytes` (≤ 131 072). Normalización previa: `\r\n` → `\n` y fuera los caracteres de control salvo `\n` y `\t`. **Revisada el 2026-11-24:** la normalización es `safe_text` de `harness/memory/safe_text.py` (quita `Cc`, `Cf` y separadores de línea, el tabulador pasa a espacio, y después redacta credenciales de formato conocido), la misma que se aplica a todo texto del vault. La salida de un `validate` es por tanto texto ya saneado y redactado, que es lo que se guarda, se imprime y se aprueba.
  - `markdown`: `required_headings`, lista de títulos que deben aparecer como línea `#{1,6} <título>` (comparación con `casefold()` y espacios recortados), en cualquier orden.
  - `json`: si el texto contiene exactamente un bloque de código con la etiqueta `json`, se analiza su interior; si no, el texto entero. JSON estricto (D3). Debe ser un objeto cuyas claves sean exactamente las declaradas en `fields` (las `required: false` pueden faltar). Tipos: `string` (`max_length`, `single_line`, `enum`), `integer` (`min`, `max`), `boolean`, `string_list` (`max_items`, `max_length` por elemento). Formatos fijos opcionales para `string`: `slug` y `date` (`YYYY-MM-DD`); no se aceptan expresiones regulares escritas en el Skill.
  - Salida del paso: el texto normalizado (`markdown`/`text`) o el JSON canónico (`sort_keys`, `separators=(",", ":")`, `ensure_ascii=False`, cadenas en NFC).
  - Un fallo deja el paso y la ejecución en `failed` con `validation_failed:<regla>:<campo>`; nunca se repite el paso `llm` anterior de forma automática.
- **Por qué:** todo lo que se puede comprobar sin interpretar el texto y sin dependencias. El bloque `json` cubre la forma habitual en que un chat devuelve JSON; las expresiones regulares del Skill se excluyen porque una regex maliciosa puede tardar un tiempo exponencial. La salida canónica hace que el hash de la aprobación no dependa del orden de claves ni de la normalización Unicode que haya elegido el modelo.
- **Alternativas rechazadas:**
  - JSON Schema con `jsonschema`: dependencia nueva y un lenguaje mucho mayor que estas cuatro formas.
  - Repetir el paso `llm` hasta que pase: es reenviar a un proveedor sin decisión humana y multiplica el coste; se deja para una política explícita si hace falta.
- **Impacto:** spec `skill-execution` (Comprobaciones deterministas de validate); tareas 3.2.

### D7 · Paso `llm`: la sesión hace la pregunta, el motor sostiene el bloqueo

- **Qué:** `SessionService` gana un método para preguntar **con el bloqueo ya tomado**, que es el actual `_ask_locked` con dos parámetros nuevos: `stored_text` (lo que se guarda como mensaje del usuario cuando el proveedor es sintético) y `timeout_s` (el del paso). `ask` conserva exactamente su conducta y sus tests. El motor guarda como pregunta la marca `[skill <nombre>/<paso> intento <n>]`, nunca el prompt compuesto. Con `"memory": "project"` el motor exige que la sesión tenga proyecto, construye el contexto con `build_context` de `project-memory` justo antes de la pregunta y lo pasa como `context` (se registra `request_context`). El paso guarda su `request_id`. Tras la respuesta, si supera 128 KiB el paso queda `failed` (`limit:response_bytes`) sin guardar la salida.
- **Por qué:** reutilizar el servicio hereda gratis `timeout`/`uncertain`/no reenvío (SEC-07), el historial y la procedencia de la memoria, y el Corte 2 enchufa Copilot sin tocar el motor. Tomar el bloqueo en el motor y no en cada pregunta impide que un `ask` de otra terminal se cuele entre dos pasos de la misma ejecución.
- **Alternativas rechazadas:**
  - Llamar al proveedor directamente desde el motor: duplica la lógica de plazos y estados, y una corrección en uno no llegaría al otro.
  - Soltar y volver a tomar el bloqueo en cada paso: abre la ventana a otra pregunta o a otra ejecución entre pasos.
  - Guardar el prompt compuesto con el Mock: con el Mock y un documento real de Wilson, el documento acabaría en SQLite (mismo criterio que D7 de `project-memory` con el bloque de memoria).
- **Impacto:** spec `skill-execution` (Paso llm a través de la sesión); `harness/core/service.py`; tarea 4.1. No cambia ningún requisito de `session-core`.

### D8 · Persistencia: migración 003 y qué contenido se guarda

- **Qué:** `harness/storage/migrations/003_skills.sql`:
  - `skill_runs(run_id PK, session_id FK, skill_name, skill_version, skill_sha256 CHECK(length=64), status CHECK IN (pending, running, awaiting_approval, completed, failed, uncertain, cancelled), current_step, inputs_manifest, error_code, created_at, updated_at, finished_at)`. `inputs_manifest` es JSON canónico `{nombre: {sha256, bytes}}`: nunca el contenido.
  - `skill_steps(step_id PK, run_id FK, step_key, position, kind CHECK IN (llm, validate, approval), attempt CHECK(>=1), status CHECK IN (pending, running, awaiting_approval, applying, completed, failed, uncertain), request_id FK requests NULL, output_sha256, output_bytes, output_text NULL, prepared_at NULL, effect_ref NULL, error_code, started_at, finished_at, UNIQUE(run_id, step_key, attempt))`.
  - `approvals(approval_id PK, run_id FK, step_key, scope, proposal_hash CHECK(length=64), status CHECK IN (pending, granted, rejected, expired, consumed, revoked), identity NULL, channel NULL CHECK IN ('tty'), created_at, expires_at, decided_at, consumed_at)`.
  - Índices únicos parciales: una ejecución abierta por sesión (`skill_runs(session_id) WHERE status IN ('pending','running','awaiting_approval','uncertain')`) y una aprobación viva por paso (`approvals(run_id, step_key) WHERE status IN ('pending','granted')`).
  - `audit_events` gana `run_id` y `detail` (texto estructurado sin contenido: paso, intento, hash, límite) con `ALTER TABLE ... ADD COLUMN`.
  - **Contenido:** las entradas nunca se guardan. `output_text` solo si el proveedor de la sesión es sintético; `output_sha256` y `output_bytes` siempre. Ninguna columna guarda la propuesta; se recalcula (D12).
- **Por qué:** son las columnas mínimas de §6 del plan maestro más lo que exigen la reanudación (salida y su hash), la reconciliación (`request_id`, `effect_ref`, `applying`) y la aprobación (identidad, canal, tiempos). Las restricciones de unicidad hacen que «una ejecución abierta por sesión» y «una aprobación viva por paso» las garantice SQLite, como la clave compuesta de SEC-02 en `session-core`.
- **Alternativas rechazadas:**
  - Guardar las entradas con el Mock para poder reanudar sin volver a pasarlas: el Mock no hace sintético lo que escribe el usuario (D11).
  - Una tabla `skill_inputs` aparte: no hay consulta que la necesite; el manifiesto basta.
  - Guardar el texto de la propuesta en `approvals`: copia contenido y crea una segunda fuente que podría divergir de la que se aplica.
- **Impacto:** spec `skill-execution` (Entradas declaradas y acotadas, Estado consultable sin contenido), `human-approval` (Auditoría de aprobaciones sin contenido); tarea 1.3. `test_migrating_twice_changes_nothing` pasa a esperar las versiones `[1, 2, 3]`.

### D9 · Bloqueo con nombre y una ejecución abierta por sesión

- **Qué:** `SessionLock` se generaliza a `NamedLock(data_dir, name)` con la misma transacción exclusiva SQLite; `SessionLock` queda como el caso `name = <session_id>` y su conducta no cambia. `skill run` y `skill resume` toman el bloqueo de la sesión al empezar y lo sueltan al terminar, al quedar en `awaiting_approval` o ante cualquier error. Mientras una ejecución espera aprobación, la sesión admite `ask` (el bloqueo está libre) pero no otra ejecución (índice parcial de D8). `skill status` no toma bloqueos.
- **Por qué:** misma garantía que `session-core` D7, en macOS y Windows con el mismo código, y la base del bloqueo del vault que necesita `architecture-skills-llm`. La ejecución pausada no debe bloquear la sesión durante los 15 minutos que puede tardar una aprobación.
- **Alternativas rechazadas:**
  - Un bloqueo por ejecución además del de la sesión: dos bloqueos que adquirir en orden para nada, porque toda ejecución pertenece a una sesión.
  - Bloquear `ask` mientras una ejecución espera: protege poco (la conversación remota sigue siendo la misma) y obliga a cancelar para preguntar.
- **Impacto:** spec `skill-execution` (Una ejecución abierta por sesión); `harness/storage/locks.py`; tarea 1.2.

### D10 · Estados, recuperación y reconciliación

- **Qué:**
  - Ejecución: `pending` (lista para seguir), `running`, `awaiting_approval`, `completed`, `failed`, `uncertain`, `cancelled`. Terminales: `completed`, `failed`, `cancelled`.
  - Paso: `pending`, `running`, `awaiting_approval`, `applying` (efecto en curso), `completed`, `failed`, `uncertain`.
  - Un paso `llm` termina en el estado de su solicitud: `completed` → `completed`; `timeout` o `failed` → `failed` (la ejecución también, terminal); `uncertain` → `uncertain` (la ejecución también).
  - **Recuperación al arrancar**, tras `SessionService.recover()`: para cada ejecución `running` cuyo bloqueo de sesión se puede tomar, un paso `llm` `running` pasa a `uncertain`; un paso `validate` `running` vuelve a `pending`; un paso `applying` pasa a `uncertain`; la ejecución queda `uncertain` si tiene algún paso incierto y `pending` si no.
  - **Reconciliación de un paso `llm` incierto:** no hay forma automática de saber si el prompt llegó (con el Mock, ninguna; con Copilot, el Corte 2 no ofrece todavía lectura de la conversación). `skill resume` se niega y la persona decide: `--retry-step <id>` (crea el intento `n+1`, con aviso de que puede duplicar la pregunta en la conversación) o `skill cancel`. Máximo 3 intentos por paso. Queda auditado como `skill.step.reconciled` con actor `cli`.
  - **Reconciliación de un efecto incierto** (`applying` interrumpido): la hace el propio efecto leyendo el destino (`reconcile`, D13) sin escribir nada: `applied` → paso `completed`; `absent` → la aprobación ya se consumió, así que se pide una nueva; `conflict` → paso y ejecución `failed`.
- **Por qué:** es la regla del proyecto («tras un timeout posterior a un envío el estado es `uncertain` y no se reintenta solo; reconciliar antes de reanudar»). Un `validate` no tiene efectos fuera y se puede repetir; una pregunta o una escritura no.
- **Alternativas rechazadas:**
  - Reintentar automáticamente un `llm` incierto con el Mock porque «no hay efecto real»: el motor no distingue proveedores, y la conducta probada tiene que ser la de Copilot.
  - Hacer `failed` terminal también lo incierto: obligaría a repetir toda la ejecución, incluidas aprobaciones ya dadas.
- **Impacto:** spec `skill-execution` (Paso incierto nunca se repite solo, Recuperación de ejecuciones interrumpidas, Cancelar una ejecución); tareas 4.3 y 4.4.

### D11 · Reanudar: mismo Skill, mismas entradas, salidas disponibles

- **Qué:** `skill resume RUN_ID [--input …] [--input-file …] [--retry-step ID]` toma el bloqueo y comprueba, en este orden: (1) el hash actual del Skill es el de la ejecución; si no, se niega nombrando los dos hashes y no cambia nada (la persona puede cancelar); (2) si quedan pasos `llm` por ejecutar o la propuesta de aprobación las usa, las entradas pasadas tienen el SHA-256 del manifiesto; (3) las salidas de los pasos completados que se van a referenciar están en `output_text` (solo con proveedor sintético); si faltan, la ejecución pasa a `failed` (`outputs_not_retained`). Después sigue desde el primer paso no completado.
- **Por qué:** sin el contenido en SQLite, la única forma segura de reanudar es que la persona vuelva a dar las entradas y que su hash demuestre que son las mismas. Con un proveedor no sintético (Copilot) una ejecución tiene que terminar en el proceso que la empezó; por eso, antes de la primera pregunta, `skill run` con un proveedor no sintético y un paso `approval` exige terminal interactiva (no tiene sentido pausar algo que no se podrá reanudar).
- **Alternativas rechazadas:**
  - Reanudar con el Skill cambiado si la versión es la misma: la versión la escribe una persona (D4).
  - Guardar las salidas cifradas: no hay gestión de claves y el plan deja el cifrado para cuando haya autorización de retención.
- **Impacto:** spec `skill-execution` (Reanudar con el mismo Skill y las mismas entradas); tarea 4.4. Lo que pasa con Copilot solo se prueba con un proveedor de prueba que declara `synthetic_content = False`.

### D12 · Aprobación: qué se firma, cómo se concede, cuándo caduca, una sola vez

- **Qué:**
  - **Propuesta** (objeto): `{"format": "ai-harness/approval/1", "scope": <efecto>, "session_id", "run_id", "step": <id>, "skill": {"name", "version", "sha256"}, "target": <destino o null>, "content": {"sha256", "bytes"}}`. El contenido es la salida referenciada por `of` (efecto `none`) o lo que prepare el efecto (D13), normalizado: UTF-8, NFC, `\n`, sin caracteres de control salvo `\n` y `\t`, sin controles bidireccionales (U+202A–U+202E, U+2066–U+2069), ≤ 32 KiB. **Revisada el 2026-11-24:** la normalización es NFC y después `safe_text` (D6 revisada): también desaparecen los caracteres de formato de ancho cero y el tabulador pasa a espacio, y las credenciales de formato conocido salen redactadas; lo mostrado, lo hasheado y lo aplicado son esos bytes.
  - **Hash:** `sha256(b"ai-harness/approval/v1\n" + json.dumps(propuesta, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))`. Un vector de prueba fijo en los tests detecta cualquier cambio de serialización. `run_id` dentro hace que una aprobación no sirva para otra ejecución; `skill.sha256` dentro, que no sirva tras editar el Skill.
  - **Petición:** al llegar al paso se inserta `approvals` `pending` con `expires_at = ahora + HARNESS_APPROVAL_TTL_S` (900 por defecto, 60–3600) y la ejecución pasa a `awaiting_approval`.
  - **Concesión:** solo si `sys.stdin.isatty()` y `sys.stdout.isatty()`. Se imprime cabecera (Skill, versión, ejecución, paso, alcance, destino, bytes, hash completo, caducidad en UTC), el contenido íntegro entre dos reglas, y se pide «escribe los 8 primeros caracteres del hash para aprobar, o `n` para rechazar». Tres intentos fallidos o fin de entrada dejan la aprobación `pending`. Aprobar exige copiar del hash mostrado: no se puede aprobar sin haber tenido delante la pantalla con la propuesta. Se registra `identity = getpass.getuser()` y `channel = 'tty'`. Los tests inyectan un objeto de terminal falso; el de producción es el único que lee `stdin`.
  - **No interactivo:** `skill run`/`resume` sin terminal dejan `awaiting_approval` y terminan con código **3** y el comando a ejecutar en una terminal.
  - **Uso único:** el efecto empieza con una transacción que ejecuta `UPDATE approvals SET status='consumed', consumed_at=? WHERE approval_id=? AND status='granted' AND proposal_hash=? AND expires_at>?` y exige una fila; en la misma transacción el paso pasa a `applying`. Cero filas → denegado, evento `approval.denied`, nada se aplica.
  - **Alteración:** antes de esa transacción se recalcula la propuesta desde lo guardado (salidas, `prepared_at`, Skill en disco); si su hash no es el aprobado, la aprobación pasa a `revoked` y el paso a `failed`.
  - **Caducidad:** pendiente caducada al reanudar → `expired` y nueva petición (nuevo `approval_id`, mismo hash si nada cambió); concedida y caducada antes del efecto → denegada y `expired`.
  - **Rechazo:** `n` → `rejected`, ejecución `cancelled`.
- **Por qué:** es literalmente lo que piden §7 del plan maestro y SEC-12 (hash exacto, caducidad, uso único, el modelo nunca aprueba). Hashear el JSON canónico de una propuesta pequeña, y el contenido por su SHA-256, hace la serialización trivial de reproducir en un test. Mostrar el contenido limpio de controles evita que una secuencia de escape oculte en pantalla parte de lo que se aprueba.
- **Alternativas rechazadas:**
  - `skill approve RUN_ID --hash H` no interactivo: cualquier proceso que pueda ejecutar la CLI (incluido un agente) aprobaría; el plan pide la aprobación «fuera del modelo».
  - Confirmación `[s/N]`: se aprueba sin leer; copiar 8 caracteres del hash obliga a mirar la propuesta.
  - Firmas con clave (HMAC): no hay dónde guardar una clave que un proceso del mismo usuario no pueda leer; no añade nada frente a la amenaza real.
  - Hash del objeto Python con `repr` o `pickle`: no es estable entre versiones.
- **Límite que no se arregla:** un proceso del mismo usuario del sistema operativo con una pseudoterminal puede hacerse pasar por la persona. La identidad local no es autenticación; la protección es contra el modelo, contra reutilizar o alterar una aprobación y contra la aprobación por descuido, no contra un atacante con la cuenta del usuario. Se escribe en `SECURITY.md`.
- **Impacto:** spec `human-approval` completa; tareas 5.x.

### D13 · Efectos: protocolo y lista cerrada

- **Qué:** un efecto es una clase registrada en `harness/skills/effects.py` con `scope`, `prepare(run, salida_validada) -> Proposal` (contenido normalizado, destino y `effect_ref` sin contenido para reconciliar), `apply(proposal) -> EffectResult` (solo se llama tras consumir la aprobación) y `reconcile(run, step) -> applied | absent | conflict` (solo lectura). El registro es un diccionario literal en el código; `workflow.json` solo nombra la clave. Este change registra `none` (no aplica nada; consumir la aprobación deja seguir la ejecución). Los tests registran un efecto de prueba que escribe en un directorio temporal, por inyección en el constructor del motor, nunca desde un Skill.
- **Por qué:** separa «qué se aprueba» (motor) de «qué se hace» (efecto) y deja que `architecture-skills-llm` añada `vault.save_decision` sin tocar la aprobación. Las pruebas de uso único, alteración y reconciliación necesitan un efecto con consecuencias, y no puede ser el del vault porque llega en el otro change.
- **Alternativas rechazadas:**
  - Que un Skill declare un efecto por nombre de módulo o ruta: es cargar código desde un Skill (SEC-14).
  - Efecto como tipo de paso (`kind: write`): el plan fija los tipos `llm`/`validate`/`approval` para este corte; un efecto inseparable de su aprobación no se puede ejecutar sin ella por error de orden en un Skill.
- **Impacto:** spec `human-approval` (Efectos de una lista cerrada); tareas 5.4.

### D14 · Límites (SEC-15)

- **Qué:** constantes en código, no configurables en este corte salvo la caducidad:

  | Límite | Valor | Al superarse |
  |---|---|---|
  | Ficheros por Skill / bytes por fichero / total | 32 / 64 KiB / 512 KiB | Skill `invalid` |
  | Pasos / entradas declaradas | 12 / 8 | Skill `invalid` |
  | Plazo por paso | 1–600 s (por defecto `HARNESS_REQUEST_TIMEOUT_S`) | Skill `invalid` si fuera de rango; en ejecución, como `ask` |
  | Bytes por entrada / total de entradas | 64 KiB / 128 KiB | ejecución rechazada antes de crearse |
  | Prompt compuesto sin memoria | 64 KiB | paso `failed` sin preguntar |
  | Respuesta | 128 KiB | paso `failed`, salida no guardada |
  | Contenido de una propuesta | 32 KiB | paso `failed` sin pedir aprobación |
  | Tiempo por invocación de `run`/`resume` | 1800 s | se comprueba antes de cada paso y acota el plazo del paso; `failed` (`limit:run_time`) o `uncertain` si vence tras el envío |
  | Intentos por paso | 3 | `resume --retry-step` rechazado |
  | Fichero de respuestas del Mock | 1 MiB | error de configuración |

  Cada parada deja un evento `skill.limit` con el nombre del límite y no ejecuta ningún paso posterior.
- **Por qué:** con una secuencia lineal sin bucles, el número de preguntas está acotado por el número de pasos; los límites de tamaño protegen la terminal, SQLite y la ventana del proveedor; 32 KiB es lo que una persona puede leer antes de aprobar. Los valores son de partida: el límite real de entrada de Copilot Web lo mide la sonda del Corte 2.
- **Alternativas rechazadas:** hacerlos configurables por Skill: un Skill malicioso declararía límites enormes.
- **Impacto:** specs `skill-definition` (Límites de un Skill en disco) y `skill-execution` (Límites de ejecución); tarea 6.x.

### D15 · Mock con respuestas guionizadas

- **Qué:** `HARNESS_MOCK_RESPONSES` (ruta absoluta a un JSON local, objeto de cadena → cadena, ≤ 1 MiB, JSON estricto). Si está definida, el Mock busca, en orden alfabético de clave, la primera clave contenida en el prompt y devuelve su valor; si no hay ninguna, su respuesta determinista de siempre. Las plantillas sintéticas llevan una línea estable `tarea: <skill>/<paso>` que sirve de clave. Los comportamientos de fallo (`HARNESS_MOCK_BEHAVIOR`) siguen mandando sobre la respuesta. Sigue siendo `synthetic_content = True`.
- **Por qué:** la respuesta por defecto del Mock (`[mock …] Received N characters.`) nunca pasa un `validate`; sin guion no hay ejecución completa que probar ni demo. Elegir por un texto de la plantilla, no del usuario, no mezcla control con contenido del usuario, que es lo que D9 de `session-core` rechazó.
- **Alternativas rechazadas:**
  - Respuestas en orden de llamada: entre procesos (`run` y `resume`) habría que persistir un contador.
  - Por hash del prompt: el nonce de D5 cambia en cada pregunta.
- **Impacto:** spec `skill-execution` (Respuestas guionizadas del Mock); `harness/providers/mock.py`, `harness/config.py`; tarea 1.4. Amplía el Mock de `session-core` sin cambiar ninguno de sus escenarios.

### D16 · CLI, salidas y códigos

- **Qué:** `skill list`; `skill show NAME`; `skill run NAME --session ID [--input N=V]… [--input-file N=RUTA]…`; `skill status RUN_ID [--output]`; `skill resume RUN_ID [--input…] [--input-file…] [--retry-step ID]`; `skill cancel RUN_ID`. `RUN_ID` acepta solo el UUID completo (D4 de `session-core`). Por stdout, la salida final o el estado; por stderr, progreso por paso y avisos. Códigos: 0 `completed` (o comando de consulta correcto), 1 error controlado, `failed`, `uncertain` o `cancelled`, 2 uso, **3 `awaiting_approval`**, 130 interrumpido. `--input-file` lee como UTF-8 estricto, comprueba el tamaño con `stat` antes de leer y no sigue más allá de 64 KiB.
- **Por qué:** un script que lance un Skill tiene que distinguir «hecho» de «pausado esperando a una persona»; tratar `awaiting_approval` como éxito (0) haría que la demo o un agente siguieran como si el efecto hubiera ocurrido.
- **Alternativas rechazadas:** `awaiting_approval` con código 0 y el estado en stdout: obliga a cada llamador a analizar texto para algo que tiene consecuencias.
- **Impacto:** todos los escenarios de la CLI; README; tarea 4.2.

## Risks / Trade-offs

- [Un proceso del mismo usuario con una pseudoterminal aprueba en su lugar] → límite aceptado y escrito (D12); fuera del modelo de amenaza de SEC-12, que es reutilizar o alterar.
- [El Mock no dice nada de si Copilot devuelve JSON o Markdown válidos] → `validate` falla de forma controlada y la ejecución termina en `failed` sin efecto; cuánto falla con Copilot se mide con el Corte 2 mergeado. No se da por verificado con mocks.
- [Reanudar exige volver a pasar las entradas] → fricción aceptada para no guardar contenido real; el error nombra la entrada que falta o no coincide.
- [Con proveedor no sintético una ejecución no se puede reanudar en otro proceso] → `skill run` exige terminal interactiva antes de la primera pregunta si hay paso `approval` (D11); solo probado con un proveedor de prueba no sintético.
- [Un paso `llm` reintentado con `--retry-step` duplica la pregunta en la conversación remota] → solo ocurre con decisión explícita, auditada, máximo 3 veces; el aviso lo dice.
- [El hash del Skill depende de la normalización de finales de línea] → probado con un Skill guardado con CRLF (escenario «Finales de línea CRLF»).
- [Carrera entre comprobar un Skill y leer su plantilla] → la plantilla se lee de la lista del recorrido y el hash se recalcula sobre lo leído; un cambio entre medias cambia el hash y la propuesta, no se aplica nada con un hash no aprobado.
- [Migración 003 aditiva sobre `audit_events`] → `ADD COLUMN` sin `NOT NULL`; las filas anteriores quedan con `NULL`.
- [El harness no se ha ejecutado en Windows] → sin código condicionado (`tests/unit/test_portability.py`); `isatty`, `getpass.getuser` y la transacción exclusiva de SQLite son el mismo código en las dos; una ejecución en Windows es confirmación opcional.
- [Ejecuciones y pasos se acumulan en SQLite sin borrado] → sin política de retención en este corte; volumen pequeño (filas sin contenido real). Se decide en el Corte 8.

## Migration Plan

Migración 003 aditiva: tres tablas nuevas, dos índices parciales y dos columnas nulas en `audit_events`; no toca filas existentes. Sin `skills/` ni `HARNESS_SKILLS_DIR`, `skill list` muestra una lista vacía y todo lo anterior sigue igual. Vuelta atrás: revertir el change; las tablas quedan sin uso.

## Open Questions

- ¿`skill status --json`? No cambia specs ni tareas; se decide cuando la herramienta MCP del Corte 5 lo necesite.
