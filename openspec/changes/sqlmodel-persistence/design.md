# Design

## Context

Motivación y cifras de partida: `proposal.md`, «Why». Hoy la persistencia es `sqlite3` de la biblioteca estándar:

- `harness/storage/database.py`: `connect()` abre con `autocommit=True` y `timeout=5.0`, pone `PRAGMA foreign_keys = ON` y `PRAGMA journal_mode = WAL`, y reintenta durante `OPEN_RETRY_S` (5 s) solo `SQLITE_IOERR_TRUNCATE` y `SQLITE_IOERR_SHMOPEN` (Windows, `-shm` mapeado por un proceso muerto). `transaction()` emite `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`. `migrate()` aplica `migrations/001..007` con `executescript`, cada una en su transacción, y apunta la versión en `schema_migrations`.
- `harness/storage/locks.py`: un bloqueo con nombre es una transacción `BEGIN EXCLUSIVE` sobre un fichero `locks/<name>.lock` aparte; el sistema operativo lo suelta al morir el proceso. No es la base principal.
- Las garantías que dependen de SQL concreto: tres índices únicos parciales (`idx_skill_runs_one_open_per_session`, `idx_approvals_one_live_per_step`, `idx_sessions_remote_ref`); actualizaciones de comparar y fijar cuyo `rowcount` decide (consumir una aprobación, `engine.py:817`, SEC-12; cerrar una llamada MCP `WHERE status = 'running'`, `audit.py:155/173/199`; ligar `remote_ref` `WHERE remote_ref IS NULL`, `repositories.py:167`); la recuperación de `uncertain` (`service.recover`, `recover_runs`, `audit.recover_stale`); `INSERT OR IGNORE` en `effect_sources` (`engine.py:1045`); comparaciones de fechas como **texto ISO** (`expires_at > ?`, `started_at >= ?`).
- Hilos: la conexión se abre, usa y cierra en el hilo que la abrió (`harness/shell/app.py:converse`); en la pantalla completa ese hilo es `conversation` (`shell-tui` D2). `cli.py`, `mcp/commands.py` y `skills/commands.py` abren la suya.

### Premisas medidas (2026-11-27, macOS arm64, Python 3.14.8, SQLite 3.53.1)

context7 no estaba disponible (el servidor pedía autenticación). Las versiones salen de la API JSON de PyPI y la conducta del dialecto, de la documentación de SQLAlchemy 2.1 (`docs.sqlalchemy.org/en/21/dialects/sqlite.html`), leídas el mismo día. Lo que importa se midió además con dos guiones fuera del repositorio, en un entorno desechable (`uv run --no-project --with sqlmodel==0.0.50 --with pydantic==2.14.4`), sin tocar `pyproject.toml` ni `uv.lock`, con datos sintéticos:

- **P1. Versiones.** `sqlmodel` 0.0.50 (2026-11-13, MIT, `requires_python >=3.11`, clasificadores 3.11–3.15) pide `SQLAlchemy>=2.0.14,<2.2.0`, `pydantic>=2.11.0` y `typing-extensions>=4.5.0`. `SQLAlchemy` 2.1.9 (2026-11-16, MIT, `>=3.11`, clasificadores hasta 3.15) pide solo `typing-extensions>=4.6.0`; publica ruedas `cp314` y `cp314t` para macOS arm64, Windows win32/amd64/arm64 y Linux, más una rueda pura `py3-none-any`. `pydantic` fijado en `uv.lock`: 2.14.4, compatible. Instalado en el entorno desechable: solo se añaden `sqlmodel` y `SQLAlchemy`; el resto ya está en `uv.lock`. Sin `greenlet` (solo lo pide el extra `asyncio`).
- **P2. `commit()` no hace nada con `autocommit=True`.** Con `sqlite3.connect(..., autocommit=True)`, `BEGIN IMMEDIATE`, un `INSERT` y `conn.commit()`: `in_transaction` sigue `True` y otra conexión ve 0 filas. Con el modo heredado (`isolation_level=None`) el mismo `commit()` sí cierra la transacción. Consecuencia: si SQLAlchemy (o `Session.commit()`) creyera que es dueño de la transacción sobre la conexión de hoy, **no escribiría nada y no daría error**.
- **P3. La misma conexión sirve a los dos mundos.** `create_engine("sqlite://", creator=lambda: owner, poolclass=StaticPool, isolation_level="AUTOCOMMIT")` sobre la conexión `owner` de hoy: con `BEGIN IMMEDIATE` explícito, `Session.add` + `flush` + `Session.commit()`, otra conexión ve **0** filas hasta el `COMMIT` explícito, y después **1**; con `ROLLBACK` explícito la fila desaparece. Es decir: `transaction()` sigue mandando y SQLAlchemy solo compone y ejecuta.
- **P4. Un modelo `table=True` no valida.** `Item(item_id=1, name=None, created_at=3)` se construye sin error.
- **P5. Tipos por defecto incompatibles con los datos guardados.** Un campo `uuid.UUID` genera `CHAR(32)` y liga `12345678123456781234567812345678` (sin guiones); las filas de hoy guardan `str(uuid)` (36 caracteres, con guiones). Un `datetime` genera `DATETIME` y liga `2026-01-01 00:00:00.000000` (sin `T` ni zona); hoy se guarda `isoformat()` con `+00:00`, y varias consultas comparan esas cadenas.
- **P6. `INSERT OR IGNORE` no es `ON CONFLICT DO NOTHING`.** Con una violación de `CHECK`, `insert().prefix_with("OR IGNORE")` (compila a `INSERT OR IGNORE INTO …`) la ignora; `sqlite.insert().on_conflict_do_nothing()` lanza `IntegrityError`.
- **P7. Comparar y fijar conserva su forma.** `update(Item).where(Item.item_id == …, Item.name == …).values(…)` compila a `UPDATE items SET name=? WHERE items.item_id = ? …` y devuelve `rowcount` 0 cuando no casa.
- **P8. La reflexión ve los índices parciales.** `inspect(engine).get_indexes("items")` devuelve el índice único con `dialect_options["sqlite_where"]`.
- **P9. El dialecto pysqlite** usa `QueuePool` y `check_same_thread=False` para ficheros desde 2.0 (documentación). Con `creator=` el dialecto no abre conexiones propias: la que se le da es la de `connect()`, con su `check_same_thread=True` por defecto. Pendiente de medir en el tramo 1 (tarea 2.3): que un uso desde otro hilo sigue dando `ProgrammingError`.

### Inventario de sentencias (AST de `harness/` sobre `5af28ed`)

Tipos: **A** = encaja tal cual en el ORM (`select(Modelo)`, proyecciones, `join`, `in_`, `order_by`, `limit`, `insert` de una fila); **B** = expresión de SQLAlchemy Core sobre los modelos (`update(...).where(...)` con `rowcount`, `CASE`, `COALESCE`, subconsultas, `count`, `EXISTS`, `OR IGNORE`, `rowid`); **C** = se queda como SQL explícito (pragmas, control de transacción, ejecutor de migraciones, bloqueos).

| Módulo | A | B | C | Total | Notas |
|---|---:|---:|---:|---:|---|
| `skills/engine.py` | 16 | 19 | 0 | 35 | 2 f-strings con `_HALF_DONE`; consumo de aprobación (SEC-12); `INSERT OR IGNORE`; 72 accesos `row["col"]` y 20 anotaciones `sqlite3.Row` |
| `storage/repositories.py` | 10 | 5 | 0 | 15 | `bind_remote_ref` captura `sqlite3.IntegrityError`; `history` con `JOIN`; dos `count` |
| `storage/database.py` | 0 | 0 | 9 | 9 | 2 pragmas, 3 de transacción, 3 de `schema_migrations`, 1 `executescript` |
| `mcp/audit.py` | 3 | 3 | 0 | 6 | 3 cierres `WHERE status = 'running'` |
| `shell/conversation.py` | 2 | 2 | 0 | 4 | 1 f-string de marcadores; `ORDER BY rowid`; `COUNT(*)` |
| `storage/locks.py` | 0 | 0 | 2 | 2 | `BEGIN EXCLUSIVE` / `ROLLBACK` sobre el fichero del bloqueo |
| **Total** | **31** | **29** | **11** | **71** | |

Riesgo de seguridad medido hoy (proposal): 0 sitios donde un dato llegue al texto de la sentencia; 3 f-strings con texto fijo; 1 `executescript` de un fichero del paquete. **Lo que el ORM quita:** la necesidad de escribir el texto de 60 de las 71 sentencias (A + B), las erratas en nombres de columna (fallan al importar o al compilar, no en producción) y la tentación de interpolar. **Lo que no quita:** las 11 de tipo C; `text()`, `exec_driver_sql`, `literal_column` y `prefix_with` siguen aceptando texto; la conversión de tipos mal elegida (P5) es un fallo de datos nuevo que hoy no existe. Por eso la guarda (D9) es el control de seguridad y el ORM es comodidad y forma.

## Goals / Non-Goals

**Goals:** que las sentencias A y B se escriban con SQLModel/SQLAlchemy sin cambiar ni una fila ni una garantía; que una prueba diga NO a todo SQL construido con datos; que cada tramo se pueda mergear solo con `scripts/verify.sh` en verde.

**Non-Goals:** reescribir las pruebas con el ORM; cambiar la forma de las filas `row["col"]` del motor en el mismo tramo que cambia sus sentencias; rendimiento (no se mide ni se promete); `AsyncSession`.

## Decisions

### D1 · SQLModel sobre SQLAlchemy 2.1, con la guarda como control de seguridad

- **Qué:** SQLModel para declarar las tablas y componer consultas; SQLAlchemy Core (que viene con él) para lo de tipo B. La guarda del tramo 0 (D9) entra antes y es independiente.
- **Por qué:** es lo que Wilson pidió, y es un proyecto para aprender: declarar tablas como clases tipadas y componer consultas con expresiones es la forma habitual en Python. Pero el inventario dice que el riesgo de inyección medido es 0 y que el riesgo real es la regresión; eso lo cierra la guarda, no el ORM. Se dice así para no vender seguridad que no da.
- **Alternativas consideradas y rechazadas:**
  - *Solo SQLAlchemy Core (sin SQLModel):* una dependencia menos y sin la ambigüedad de un modelo que parece pydantic y no valida (P4). Se rechaza porque no da lo que Wilson nombró (SQLModel) y la diferencia real es pequeña: las 29 de tipo B son Core en las dos opciones. Era la opción (b) de la pregunta Q2; Wilson eligió SQLModel completo (2026-11-27).
  - *Quedarse con `sqlite3` y añadir solo la guarda:* elimina el mismo riesgo medido, sin dependencias ni migración de 60 sentencias. Se rechaza solo porque no cumple el objetivo de Wilson de no escribir SQL a mano; era la opción más barata, la (c) de Q2; Wilson eligió SQLModel completo (2026-11-27).
  - *Otro ORM (Peewee, Pony):* sin ventaja sobre SQLAlchemy y sin la integración con pydantic que Wilson busca.
- **Impacto:** `pyproject.toml`, `uv.lock` (tramo 1); spec «Ninguna sentencia SQL se construye con datos».

### D2 · Modelos de tabla aparte de los contratos, con el tipo guardado

- **Qué:** `harness/storage/tables.py` declara las 10 tablas de dominio (`sessions`, `requests`, `messages`, `audit_events`, `request_context`, `skill_runs`, `skill_steps`, `approvals`, `tool_calls`, `effect_sources`) como `SQLModel, table=True`. Cada columna lleva el tipo **tal como se guarda**: `str` para UUID y fechas ISO, `int` para enteros y banderas 0/1. Los contratos de `harness/core/contracts.py` (`frozen=True`, `extra="forbid"`) no cambian, y los repositorios convierten fila → contrato, como hoy. `schema_migrations` no se modela: es del ejecutor de migraciones.
- **Por qué:** P4 (un modelo de tabla no valida: usarlo como contrato quitaría la validación que hoy da `Session(**dict(row))`); los contratos son inmutables y el ORM muta; P5 (los tipos por defecto cambian la forma de UUID y fechas y romperían igualdades y comparaciones de texto sobre filas existentes).
- **Alternativas consideradas y rechazadas:**
  - *Reusar los contratos como tablas (`Session(SQLModel, table=True)`):* pierde validación (P4) y la inmutabilidad, y mezcla la frontera de datos no confiables con la de almacenamiento.
  - *Columnas `uuid.UUID`/`datetime` con un `TypeDecorator` que guarde la forma de hoy:* posible, pero es código de conversión propio que tiene que acertar a la primera con filas reales; se deja como mejora posterior, ya con la prueba de compatibilidad (tarea 2.4) para cubrirla.
- **Impacto:** spec «Identificadores y fechas conservan su forma»; tareas 2.2 y 2.4.

### D3 · Las migraciones `.sql` son la única fuente del esquema

- **Qué:** se conservan `migrations/001..007` y el ejecutor de hoy. Nunca `SQLModel.metadata.create_all` sobre una base real; sin Alembic. Una prueba (`tests/unit/test_schema_matches_migrations.py`) migra una base vacía, crea en otra base temporal el esquema de `tables.py` y compara, tabla a tabla, `PRAGMA table_info` (nombre, tipo declarado, `notnull`, `pk`), `PRAGMA foreign_key_list` e índices (`index_list`, `index_info`, únicos y texto del `WHERE` de los parciales, P8). Los `CHECK` no se modelan: los impone la base y sigue mandando la migración (límite escrito en Riesgos).
- **Por qué:** las migraciones son texto revisable, ya probado (`test_migration_007_…`), y conocen cosas que un modelo no expresa bien (`CHECK`, índices parciales, la limpieza de datos de 007). Alembic añade otra dependencia, otra tabla de versiones y un segundo dueño del esquema. La prueba de igualdad convierte «dos descripciones del mismo esquema» de riesgo en comprobación.
- **Alternativas consideradas y rechazadas:**
  - *Alembic con autogeneración:* dos historias de versiones (`schema_migrations` y `alembic_version`) o una migración de la tabla de versiones en bases existentes; la autogeneración no ve `CHECK` ni todos los índices parciales.
  - *`create_all` en el primer arranque:* crearía un esquema distinto del migrado (sin `CHECK`, tipos de P5) en bases nuevas, y dos poblaciones de bases.
  - *Generar `tables.py` por reflexión al arrancar:* sin tipos estáticos y sin la comprobación que da sentido al modelo.
- **Impacto:** spec «El esquema esperado coincide con el migrado»; la rama que planifica la migración 008 tendrá que tocar `tables.py` en el mismo commit (proposal, Impacto).

### D4 · `transaction()` sigue siendo el único dueño de la transacción

- **Qué:** SQLAlchemy ejecuta sobre la **misma** conexión `sqlite3` que devuelve `connect()`: un `Engine` por conexión, `creator=lambda: conn`, `poolclass=StaticPool`, `isolation_level="AUTOCOMMIT"`. `transaction(conn)` sigue emitiendo `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`. En el código del harness no hay `Session.commit()`, `Session.rollback()`, `Connection.begin()` ni `engine.begin()`; la guarda lo comprueba. Las sentencias SQLAlchemy y las `conn.execute` que queden conviven dentro del mismo `BEGIN IMMEDIATE` durante la migración.
- **Por qué:** P2 y P3. Con `autocommit=True`, un `commit()` del lado de SQLAlchemy no escribe nada y no avisa: sería una pérdida de datos silenciosa. Con una sola conexión y un solo dueño, la migración por tramos no cambia ninguna frontera de transacción, y el reintento de apertura de Windows y los pragmas siguen en `connect()`, sin duplicarse en eventos del `Engine`.
- **Alternativas consideradas y rechazadas:**
  - *Transacciones de SQLAlchemy con la receta del dialecto* (`isolation_level=None` al conectar y un evento `begin` que emita `BEGIN IMMEDIATE`): habría que pasar la conexión al modo heredado, que Python retira en 3.16 (documentación de SQLAlchemy), y durante la migración convivirían dos dueños de la transacción en la misma conexión.
  - *`create_engine("sqlite:///…")` con su propio `QueuePool`:* conexiones abiertas por SQLAlchemy, sin el reintento de `connect()`, con `check_same_thread=False` (P9) y con más de una conexión por proceso; rompe la frontera de hilos de D7.
- **Impacto:** `database.py` (una función que da el `Engine` o la `Session` de una conexión); spec «Una transacción fallida no deja nada escrito»; tareas 2.3 y 2.5 con su control negativo (un `Session.commit()` en lugar del `COMMIT` explícito deja 0 filas visibles).

### D5 · Lecturas con `select`, escrituras como sentencias, sin objetos entre transacciones

- **Qué:** las lecturas usan `select(...)` sobre los modelos; las escrituras, `insert(...)`/`update(...)` ejecutadas en el acto y, cuando el resultado decide (comparar y fijar), comprobando `rowcount` como hoy. `Session.add` solo dentro de un `transaction()` y con `flush()` antes de salir. Ningún objeto del ORM sale de una función de repositorio: se devuelven contratos, tuplas o `RowMapping`. Las filas del motor de Skills se leen con `.mappings()`, que admite `row["col"]`, para no tocar sus 72 accesos en el mismo tramo.
- **Por qué:** otros procesos escriben la misma base (CLI, servidor MCP del harness, otra conversación) y un mapa de identidad que viva más que una transacción devolvería datos viejos. Las tres garantías de comparar y fijar (SEC-12, cierre de llamadas MCP, `remote_ref`) son un solo `UPDATE … WHERE` atómico; cargar, modificar y hacer `flush` las partiría en dos sentencias con una ventana entre ellas.
- **Alternativas consideradas y rechazadas:**
  - *Unidad de trabajo completa (cargar, mutar, `flush` al final):* parte cada comparar y fijar y retrasa las escrituras a un momento que el código no ve.
  - *Pasar el motor a atributos (`row.status`) a la vez:* duplica el tamaño del tramo más delicado; queda como mejora sin prisa.
- **Impacto:** tramos 2 a 5; las pruebas de SEC-12 (`test_skill_approval.py`) y de recuperación no cambian.

### D6 · Lo específico de SQLite se conserva tal cual

- **Qué:** `INSERT OR IGNORE` → `insert(...).prefix_with("OR IGNORE")` (P6), no `on_conflict_do_nothing`. `ORDER BY rowid` → `literal_column("rowid")` con literal. Los índices únicos parciales siguen en las migraciones y se declaran en `tables.py` con `sqlite_where` solo para la prueba de igualdad. `sqlite3.IntegrityError` capturado hoy (`repositories.py:172`, `engine.py:269`) pasa a `sqlalchemy.exc.IntegrityError` en las sentencias migradas. `_HALF_DONE` se convierte en una expresión `exists()` reutilizable. Los pragmas, `transaction()`, el ejecutor de migraciones y `locks.py` se quedan en `sqlite3` crudo.
- **Por qué:** cada uno es una garantía que hoy funciona; traducirlo a la forma «portable» cambiaría la conducta (P6) o haría depender una prueba de seguridad de cómo envuelve SQLAlchemy las excepciones. `locks.py` no es la base principal y su `BEGIN EXCLUSIVE` es el bloqueo.
- **Alternativas consideradas y rechazadas:** `on_conflict_do_nothing` (cambia la conducta con `CHECK`); ordenar por `started_at, request_id` en lugar de `rowid` (otra conducta con fechas iguales); pasar los bloqueos a SQLAlchemy (ninguna ganancia, más superficie en una pieza que hoy es pequeña y probada en las dos plataformas).
- **Impacto:** tramos 2, 4 y 5; cada traducción con su prueba que falla si se usa la forma rechazada (tareas 3.2, 5.2, 6.2, 7.1).

### D7 · Una conexión por hilo dueño, sin cambios

- **Qué:** el `Engine` de D4 se crea junto a la conexión, en el hilo que la abre, y muere con ella. No hay `Engine` global ni de módulo. El hilo `conversation` de la pantalla completa sigue abriendo, usando y cerrando la suya.
- **Por qué:** es la frontera que hoy garantiza Python (`check_same_thread=True`) y que `shell-tui` D2 documenta; un `Engine` global con su piscina la borraría sin que ninguna prueba lo notara.
- **Alternativas consideradas y rechazadas:** un `Engine` global con `QueuePool` (P9, D4); `scoped_session` por hilo (resuelve un problema que aquí no existe: cada hilo ya tiene su conexión).
- **Impacto:** tarea 2.3 (control: usar la conexión desde otro hilo sigue fallando).

### D8 · Dependencias fijadas exactas y con antigüedad

- **Qué:** `sqlmodel` y `sqlalchemy` fijadas con `==` en `pyproject.toml`, con versiones publicadas hace al menos 14 días el día del tramo 1 (el 2026-11-27, `sqlmodel` 0.0.50 tiene 14 días y `SQLAlchemy` 2.1.9, 11). Se anota en `tasks.md` versión, licencia, fecha y ruedas `cp314` de cada una.
- **Por qué:** el proyecto era biblioteca estándar más pydantic; esto suma dos paquetes, uno con extensiones compiladas (SQLAlchemy) y otro anterior a 1.0 con cinco versiones entre el 2026-09-22 y el 2026-11-13 (P1), es decir, con cambios frecuentes que pueden romper. Fijar exacto y esperar unos días reduce el riesgo de una versión retirada o comprometida.
- **Alternativas consideradas y rechazadas:** rangos (`>=`), como `pydantic` hoy (una actualización de `sqlmodel` 0.0.x podría cambiar la conducta sin que nadie la pida); vendorizar (mantenimiento propio de 2 bibliotecas).
- **Impacto:** `pyproject.toml`, `uv.lock`; decisión Q4.

### D9 · La guarda: el texto de una sentencia es un literal

- **Qué:** `tests/unit/test_sql_literals.py` recorre el AST de `harness/` y de `main.py`. Regla exacta del tramo 0 (2026-11-27):
  - Se examina toda llamada `<cualquier objeto>.execute|executemany|executescript|exec_driver_sql(...)`. Su sentencia es el primer argumento posicional o la palabra clave `sql`/`sql_script`/`statement`; una llamada sin sentencia o con `*args` se rechaza.
  - La sentencia tiene que ser **SQL literal**: un literal `str` (los literales adyacentes ya son uno para Python); `a + b` con `a` y `b` SQL literal; o un nombre ligado **una sola vez** en el mismo módulo, a nivel de módulo, a SQL literal, y no ligado en ningún otro sitio del módulo (ni en una función, bucle, `with`, `import`, `except`, `match`, ni declarado `global`/`nonlocal`). La resolución es transitiva y sin ciclos.
  - Se rechaza todo lo demás: f-strings (aunque solo interpolen constantes), `%`, `.format`, `str.join`, llamadas, atributos, subíndices, variables locales y parámetros, `bytes`.
  - Un método SQL no se puede **nombrar sin llamarlo** (`run = conn.execute`, `self._run = conn.execute`, `partial(conn.execute)`), ni pedir con `getattr(obj, "execute")`: así un alias no puede esquivar la regla.
  - Única excepción, con su motivo en la prueba: `executescript` dentro de `migrate()` en `harness/storage/database.py` (ficheros de migración del paquete).
  - Límites conocidos, escritos en la prueba: otro módulo puede reasignar una constante (`engine._HALF_DONE = …`); `getattr` con un nombre calculado y `operator.methodcaller` no se siguen; no se revisan `scripts/` ni `tests/` (`scripts/demo_architecture_skills.py` tiene un `execute(sql)` de ayuda); lo que haga una biblioteca o una extensión en C queda fuera.
  - En el tramo 1, con la dependencia ya dentro, se añaden `text`, `literal_column` y `prefix_with`, y el rechazo de `.commit(`, `.rollback(` y `.begin(` de SQLAlchemy (D4). En el tramo 6, que `execute` sobre la base principal solo aparezca en `database.py` y `locks.py`.
  - Los 3 f-strings de hoy pasan a formas aceptadas sin cambiar el texto de la sentencia: `"… AND " + _HALF_DONE` y `"… WHERE " + _HALF_DONE` en `engine.py`; `IN (?, ?, ?, ?)` literal en `conversation.py`, como ya hace `engine.py:243` (si `OPEN_RUN_STATES` cambia de longitud, SQLite rechaza la llamada por número de parámetros: falla en voz alta, no en silencio).
- **Por qué:** es el único control que cubre el riesgo medido (la regresión), con o sin ORM, y se puede demostrar que dice NO.
- **Alternativas consideradas y rechazadas:** `grep` por `execute(f"` (no ve sentencias de varias líneas ni variables intermedias); la regla S608 de Ruff (Ruff no es dependencia; solo marca algunos patrones y se silencia con `noqa`, como ya pasa en `engine.py:1343`); `sqlite3.Connection.set_authorizer` (autoriza operaciones, no distingue texto construido de literal).
- **Impacto:** spec «La comprobación rechaza una sentencia construida»; tramo 0 y 6.

### D10 · El mismo código en macOS y Windows

- **Qué:** ni una rama por plataforma. El reintento de Windows sigue en `connect()`, que es lo que recibe el `Engine` (D4). SQLAlchemy publica ruedas `cp314` para Windows amd64/arm64 (P1), y su rueda pura sirve si una plataforma no tuviera la compilada.
- **Por qué:** regla del proyecto (`tests/unit/test_portability.py`).
- **Alternativas consideradas y rechazadas:** forzar la rueda pura de SQLAlchemy para no cargar código compilado (más lenta y sin ganancia de seguridad medible; queda como opción si la compilada diera problemas en Windows).
- **Impacto:** tareas 2.6 y 8.2 (Windows, confirmación opcional en la máquina de pruebas de Wilson).

## Risks / Trade-offs

- [Una conversión de tipo cambia la forma de UUID o fechas y las consultas dejan de casar con filas antiguas] → D2 (tipo guardado) y la base de la versión anterior de la tarea 2.4, con control negativo (un UUID sin guiones hace fallar la prueba).
- [Una escritura del ORM se queda sin confirmar en silencio (P2)] → D4, la guarda rechaza `commit`/`rollback`/`begin` de SQLAlchemy y la tarea 2.5 lo demuestra con otra conexión.
- [La traducción de una comparar y fijar se parte en dos sentencias] → D5; las pruebas de SEC-12 y de cierre de llamadas MCP no cambian ni una aserción, y la revisión del tramo 5 es independiente.
- [`sqlalchemy.exc.IntegrityError` en vez de `sqlite3.IntegrityError` hace que un `except` deje de capturar] → D6; prueba de dos sesiones con la misma referencia remota y de dos ejecuciones abiertas a la vez en cada tramo que lo toque.
- [`tables.py` y las migraciones divergen] → la prueba de igualdad de D3, con su control negativo.
- [`sqlmodel` 0.0.x rompe en una versión nueva] → D8, fijada exacta; subir de versión es un cambio propio con `scripts/verify.sh`.
- [Dos dependencias más y código compilado] → D8; Wilson aceptó el coste al elegir SQLModel completo (Q2, 2026-11-27).
- **Límite que no se arregla:** los `CHECK` no se modelan en `tables.py`; un valor fuera de rango se descubre al escribir (`IntegrityError`), como hoy, no al construir el objeto.
- **Límite que no se arregla:** la guarda revisa el código del repositorio, no lo que haga una biblioteca por dentro.
- **Límite que no se arregla:** el motor de Skills seguirá leyendo filas como `row["col"]` tras este change (D5).

## Plan de tramos

Cada tramo es una rama `feature/sqlmodel-persistence-<n>` desde `develop`, un PR, y deja `scripts/verify.sh` en verde. El tramo 0 se puede mergear aunque Wilson decida no adoptar el ORM. Tamaños aproximados, medidos sobre `5af28ed`:

| Tramo | Contenido | Ficheros de producto | Sentencias | Pruebas afectadas |
|---|---|---|---:|---|
| 0 · Guarda | D9 y los 3 f-strings a literales | `engine.py`, `conversation.py` | 3 | 1 nueva; ninguna aserción cambia |
| 1 · Fontanería | Dependencias, `tables.py`, `Engine` por conexión (D4), prueba de igualdad de esquema, base de la versión anterior, guarda de `commit` | `pyproject.toml`, `uv.lock`, `database.py`, `tables.py` (nuevo, ~200 líneas) | 0 | 3 nuevas (esquema, compatibilidad, frontera de transacción) |
| 2 · Repositorios | `repositories.py` | 1 | 15 (10 A, 5 B) | `test_storage.py` y las que pasan por `SessionService` (~12 ficheros), sin cambiar aserciones |
| 3 · Auditoría MCP | `audit.py` | 1 | 6 (3 A, 3 B) | `test_mcp_*`, `test_mcp_cli.py` |
| 4 · Motor, lecturas e inserciones | `engine.py`, tipo A | 1 | 16 | `test_skill_*` (5 ficheros), `test_skill_crash.py`, `test_hls_review.py`, `test_architecture_memory.py` |
| 5 · Motor, actualizaciones y recuperación | `engine.py`, tipo B, consumo de aprobación, `recover_runs` | 1 | 19 | las mismas; revisión independiente obligatoria (SEC-12) |
| 6 · Conversación y cierre | `conversation.py`; guarda endurecida; documentación | `conversation.py`, `docs/runbook/` | 4 | `test_shell_*`, `test_chat_*` |

**Vuelta atrás:** cada tramo se revierte con su PR; como no hay migración ni cambio de datos, una base escrita por un tramo la lee el anterior (lo comprueba la tarea 2.4 en sentido inverso: filas escritas por la versión con ORM, leídas con SQL crudo de pruebas).

## Decisiones de Wilson (2026-11-27)

Sustituyen a las preguntas abiertas de la primera versión de este diseño (allí P1–P5; aquí Q1–Q5, para no confundirlas con las premisas medidas P1–P9).

- **Q2 · Alcance: SQLModel completo** (decidido por Wilson). Se hacen los tramos 0 a 6 tal como están en «Plan de tramos».
- **Orden:** el tramo 0 entra ya, en paralelo con las ramas abiertas. Los tramos 1 a 6 empiezan solo cuando estén mergeadas `feature/prompt-economy`, `feature/approval-buttons` y `feature/collapsible-blocks` (decidido por Wilson).
- **Q1 · Corte:** Corte 8, como change propio junto a `hardening`. *Por defecto; Wilson puede revisarlo.*
- **Q3 · Tipos:** columnas con el tipo guardado (`str`) y conversión en los repositorios (D2); los `TypeDecorator` quedan como mejora posterior. *Por defecto; Wilson puede revisarlo.*
- **Q4 · Versiones:** las más nuevas con al menos 14 días el día del tramo 1 (D8). *Por defecto; Wilson puede revisarlo.*
- **Q5 · Migración 008:** se mergea antes del tramo 1 y `tables.py` nace con ella. *Por defecto; Wilson puede revisarlo.*
