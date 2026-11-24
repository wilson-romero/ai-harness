# Design

## Context

Repo recién creado (Corte 0): `pyproject.toml` con Python `>=3.14,<3.15`, `pydantic`, `pytest`, `pytest-asyncio`; un test de entorno; `scripts/verify.sh`. No hay código de producto. La motivación está en `proposal.md`; los contratos y el esquema de partida, en §6 de `docs/plan/AI-HARNESS-PLAN-v0.4.md`.

Premisas medidas el 2026-11-24 en la Mac con `uv run python` (CPython 3.14.8):

- `uuid.uuid7()` existe en la biblioteca estándar.
- SQLite enlazado: 3.53.1.
- Una clave foránea compuesta `(request_id, session_id)` rechaza un mensaje de otra sesión (`FOREIGN KEY constraint failed`) y acepta el de la propia, con `PRAGMA foreign_keys=ON`.
- Dos conexiones SQLite sobre el mismo fichero: la segunda falla en `BEGIN EXCLUSIVE` con `timeout=0`, y lo obtiene cuando el proceso de la primera muere por `kill` (medido con `tests/unit/test_locks.py`).

## Goals / Non-Goals

**Goals:**

- Que el Corte 2 pueda añadir el proveedor de Copilot Web implementando una interfaz, sin tocar sesiones, almacenamiento ni CLI.
- Que el estado `uncertain` y el no reenvío queden resueltos una vez, aquí, para todos los proveedores.
- Mismo comportamiento en macOS y Windows usando solo la biblioteca estándar y `pydantic`.

**Non-Goals:**

- Cifrado de SQLite. El contenido real no se guarda (D5); el cifrado se decide cuando haya autorización para persistirlo.
- Concurrencia dentro de un proceso. La CLI ejecuta un comando por proceso.
- Streaming de respuestas, cancelación remota y reintentos.

## Decisions

### D1 · Estructura mínima de paquetes

- **Qué:** `main.py` solo llama a `harness.cli.main()`. `harness/core/` (contratos Pydantic, estados, servicio de sesiones), `harness/storage/` (conexión, migraciones, repositorios), `harness/providers/` (interfaz y Mock). Nada más.
- **Por qué:** es el subconjunto de §4 del plan maestro que este corte usa. El plan pide no crear módulos vacíos.
- **Alternativas rechazadas:**
  - Crear ya toda la estructura de §4 (`browser/`, `mcp/`, `skills/`...): carpetas sin código que invitan a rellenarlas antes de tiempo.
  - Puertos y adaptadores con capa de dominio separada: el plan maestro lo excluye de forma explícita.
- **Impacto:** `tasks.md` grupo 1. Los cortes siguientes añaden paquetes, no reorganizan estos.

### D2 · Esquema 001 con solo cuatro tablas

- **Qué:** la migración 001 crea `sessions`, `requests`, `messages` y `audit_events`. Respecto a §6 del plan maestro: `requests` añade `error_code`, `duration_ms` y `UNIQUE(request_id, session_id)`; `messages` referencia `(request_id, session_id)` con clave foránea compuesta; `audit_events` añade `session_id` y `actor`. Fechas en UTC ISO 8601. Índices por `(session_id, created_at)`.
- **Por qué:** la clave compuesta hace que SEC-02 lo garantice la base de datos y no una comprobación en Python que alguien pueda saltarse. `session_id` en auditoría permite auditar la creación de una sesión, que no tiene solicitud.
- **Alternativas rechazadas:**
  - Crear ya `tool_calls`, `approvals`, `skill_runs`: columnas diseñadas sin consumidor, que habría que migrar cuando se conozca el uso real.
  - Validar la pertenencia sesión–solicitud solo en el repositorio: una escritura futura por otra vía la rompería sin que nada lo detecte.
- **Impacto:** spec `session-management` (Aislamiento entre sesiones, Auditoría sin contenido). Los cortes 4 y 5 añaden las migraciones 002 y siguientes.

### D3 · Migraciones: ficheros SQL numerados y tabla de versión

- **Qué:** `harness/storage/migrations/NNN_nombre.sql`, aplicados en orden dentro de una transacción cada uno, con registro en `schema_migrations(version, applied_at)`. Se ejecutan al abrir el almacenamiento. Cada conexión activa `foreign_keys=ON` y `journal_mode=WAL`.
- **Por qué:** una sola persona, un solo fichero SQLite local; no hace falta más.
- **Alternativas rechazadas:**
  - Alembic: trae SQLAlchemy, que este proyecto no usa.
  - `CREATE TABLE IF NOT EXISTS` sin versión: no sabe evolucionar una tabla existente, y la migración 002 llega en el Corte 4.
- **Impacto:** spec `session-management` (Esquema migrable y repetible); tareas 2.x.

### D4 · Identificadores UUIDv7 de la biblioteca estándar

- **Qué:** `session_id`, `request_id`, `message_id` y `event_id` son `uuid.uuid7()`. La CLI solo acepta el UUID completo.
- **Por qué:** ordenables por tiempo, lo que ayuda a los índices y a leer un log; sin dependencia nueva (medido arriba).
- **Alternativas rechazadas:**
  - UUIDv4: válido, pero sin orden temporal y sin ventaja a cambio.
  - Aceptar prefijos abreviados en la CLI: cómodo, pero un prefijo ambiguo es una vía para preguntar en la sesión equivocada (SEC-02).
- **Impacto:** spec `session-management` (Identificadores validados).

### D5 · El proveedor declara si su contenido es sintético

- **Qué:** la interfaz de proveedor expone `synthetic_content: bool`. Solo si es `True` se guarda el texto en `messages.content`; si no, se guarda la fila con `content = NULL`. El Mock lo declara `True`.
- **Por qué:** §6 del plan maestro prohíbe persistir contenido real hasta que haya autorización, pero el historial sintético debe persistir. Ponerlo en el contrato del proveedor impide que el Corte 2 lo persista por descuido.
- **Alternativas rechazadas:**
  - Una variable de entorno `HARNESS_PERSIST_CONTENT`: un valor mal puesto en `.env` guardaría contenido corporativo sin cifrar.
  - No guardar contenido nunca: `history` no serviría ni para la demo de este corte.
- **Impacto:** spec `llm-provider` (El contenido solo se guarda si es sintético). El Corte 2 decide, con la política de retención, si añade una autorización explícita; hasta entonces `history` con Copilot mostrará estados sin texto.

### D6 · Interfaz de proveedor con señal de «prompt enviado»

- **Qué:** `LLMProvider` es un `Protocol` asíncrono con `ask(request, on_sent)`; el proveedor llama a `on_sent()` en el momento en que el prompt sale. El orquestador aplica el plazo con `asyncio.timeout`: si vence antes de `on_sent` → `timeout`; después → `uncertain`. Una excepción del proveedor → `failed`. `KeyboardInterrupt` y cancelación siguen la misma regla. `create_session`, `recover` y `close` de §9 del plan maestro no se definen todavía.
- **Por qué:** la diferencia entre `timeout` y `uncertain` es si hubo efecto fuera. Solo el proveedor sabe cuándo ocurre, así que tiene que decirlo.
- **Alternativas rechazadas:**
  - Todo plazo vencido es `uncertain`: seguro, pero marca como dudosas preguntas que nunca salieron y entrena a ignorar el estado.
  - Definir ya `create_session/recover/close`: su forma depende de cómo Copilot Web identifica una conversación, que se mide en la sonda del Corte 2.
- **Impacto:** spec `llm-provider` (Resultado distinto según el punto de fallo). El Corte 2 amplía la interfaz y lo declara en su propio design.

### D7 · Bloqueo por sesión con una transacción exclusiva de SQLite

**Revisada el 2026-11-24.** La primera versión usaba `fcntl.flock` en macOS/Linux y `msvcrt.locking` en Windows: queda **revertida**. Dejaba una rama de código que en la Mac no se ejecuta nunca, y Wilson fijó ese día la regla de que lo probado en una plataforma tiene que ser el mismo código que corre en la otra. Specs releídas tras el cambio: `request-recovery` describe la conducta (sesión ocupada, solicitud viva, huérfana) y no el mecanismo; no cambia ningún requisito ni escenario.

- **Qué:** `ask` abre una base SQLite propia de la sesión, `<data>/locks/<session_id>.lock`, con `timeout=0` y ejecuta `BEGIN EXCLUSIVE`; mantiene la transacción hasta registrar el resultado. Si `BEGIN EXCLUSIVE` falla con «database is locked», rechaza la pregunta. La recuperación al arrancar intenta lo mismo en cada sesión con solicitudes `pending`/`running`: si obtiene el bloqueo, el proceso dueño ya no existe y las marca `uncertain`; si no, las deja.
- **Por qué:** SQLite ya resuelve el bloqueo de ficheros en cada sistema operativo, así que el código del harness es idéntico en macOS y Windows y no hay rama sin probar. El sistema operativo libera el bloqueo cuando el proceso muere, también con `kill -9` o un corte de luz: es una señal de «sigue vivo» que no puede quedarse mintiendo. Esto define además el «bloqueo por sesión» que el plan maestro nombra sin concretar: protege de dos procesos de CLI en la misma sesión.
- **Alternativas rechazadas:**
  - `fcntl.flock` + `msvcrt.locking` (la versión revertida): dos implementaciones, y la de Windows solo se podía probar en Windows.
  - Guardar el PID en la solicitud y comprobar si existe: los PID se reutilizan y la comprobación es distinta en cada plataforma.
  - Latido periódico en la base principal: exige una tarea de fondo y un umbral de caducidad que siempre es demasiado corto o demasiado largo.
  - Marcar `uncertain` todo lo que esté en curso al arrancar: `session list` en otra terminal rompería una pregunta viva.
  - Dependencia `filelock`: por dentro también ramifica por plataforma, y añade un paquete para lo que la biblioteca estándar ya da.
- **Impacto:** spec `request-recovery` completa; tareas 5.x. `tests/unit/test_portability.py` impide que vuelva a entrar código condicionado por plataforma. El Corte 2 reutiliza el mismo bloqueo para serializar el navegador por sesión.

### D8 · Estado de sesión derivado de su última solicitud

- **Qué:** `created` → `active` al completarse la primera pregunta; pasa a `uncertain` cuando una solicitud suya queda `uncertain`; vuelve a `active` con la siguiente pregunta completada, con aviso por stderr. No hay comando para «resolver» una solicitud incierta. `authentication_required` y `closed` existen en el tipo pero ningún camino de este corte los produce.
- **Por qué:** el plan maestro pide no reenviar, no bloquear al usuario. La solicitud incierta queda visible para siempre en el historial; la sesión solo indica si lo último que pasó fue dudoso.
- **Alternativas rechazadas:**
  - Bloquear la sesión hasta un `session resolve`: un comando más y una fricción que con el Mock no protege de nada. Si Copilot lo necesita, se añade en el Corte 2 con datos reales.
- **Impacto:** spec `request-recovery` (La sesión vuelve a activa con una pregunta completada).

### D9 · Mock con comportamiento elegido por configuración

- **Qué:** la respuesta del Mock se deriva del hash de `(session_id, prompt)`. `HARNESS_MOCK_BEHAVIOR` admite `ok` (por defecto), `fail`, `timeout_before_send` y `timeout_after_send`; `HARNESS_MOCK_DELAY_MS` añade una espera tras el envío. Los tests inyectan el comportamiento por constructor, no por entorno.
- **Por qué:** la demo necesita que Wilson pueda matar un `ask` a mitad y provocar cada estado sin tocar código.
- **Alternativas rechazadas:**
  - Prefijos mágicos en el prompt (`!fail ...`): mezcla control con contenido, justo lo que el resto del sistema debe evitar.
- **Impacto:** spec `llm-provider` (Mock determinista y sin red); tareas 4.x y la demo.

### D10 · Salida de la CLI y códigos de retorno

- **Qué:** resultados por stdout, avisos y errores por stderr. Código 0 = hecho; 1 = error controlado (incluye `failed`, `timeout`, `uncertain`, sesión ocupada); 2 = uso incorrecto (argparse). Ningún error esperado muestra traza.
- **Por qué:** stdout limpio permite encadenar comandos y, más adelante, reservarlo al protocolo MCP.
- **Alternativas rechazadas:**
  - Un código distinto por cada estado: nadie lo consume todavía; el estado ya va en el mensaje y en `history`.
- **Impacto:** todos los escenarios que dicen «código distinto de 0».

## Risks / Trade-offs

- [El harness no se ha ejecutado en Windows] → el producto no tiene código condicionado por plataforma (`test_portability`), así que lo que corre en Windows es lo mismo que pasa los tests en la Mac; las diferencias quedan dentro de SQLite y de CPython. Una ejecución en Windows es una confirmación opcional, no una puerta del corte.
- [Un sistema de ficheros en red no garantiza los bloqueos] → `HARNESS_DATA_DIR` debe ser un disco local; se documenta en el README. No se va a arreglar.
- [Una solicitud `uncertain` puede haber llegado al proveedor y haber sido respondida; el harness no lo sabrá] → es el significado del estado. La reconciliación con la conversación remota es trabajo del Corte 2.
- [SQLite sin cifrar] → en este corte solo guarda contenido sintético (D5). Límite conocido, no se arregla aquí.
- [Entre `on_sent` y el registro del estado `running` puede morir el proceso] → la solicitud se inserta como `pending` antes de llamar al proveedor, así que la recuperación la encuentra siempre; el peor caso es un `uncertain` de algo que no salió, nunca un envío sin rastro.
- [`scripts/verify.sh` y la demo son bash] → son herramientas de desarrollo, no producto; en Windows se ejecutan desde Git Bash.

## Open Questions

- ¿`history` debe ofrecer salida JSON? No cambia specs ni tareas de este corte; se decide cuando un Skill lo necesite (Corte 4).
