# Proposal

## Why

Wilson quiere dejar de escribir SQL a mano y usar el ORM SQLModel, porque el SQL a mano «no se siente seguro». Medido el 2026-11-27 sobre `origin/develop` (`5af28ed`), con un recorrido del AST de `harness/` (guion fuera del repositorio que lista cada llamada a `execute`, `executemany` y `executescript` con su primer argumento):

- **71 llamadas** a `execute`/`executescript` en **6 módulos**: `harness/skills/engine.py` 35, `harness/storage/repositories.py` 15, `harness/storage/database.py` 9, `harness/mcp/audit.py` 6, `harness/shell/conversation.py` 4, `harness/storage/locks.py` 2. `harness/core/service.py` y `harness/mcp/commands.py` reciben la conexión y abren transacciones (`transaction(...)`, 8 bloques en `service.py`), pero **no ejecutan SQL** (0 llamadas). La premisa recibida («también en `service.py` y `mcp/commands.py`, un solo f-string») era inexacta en esos dos puntos.
- **67 de 71** tienen como SQL un literal de cadena y pasan los valores con `?`. **3** son f-strings: `engine.py:1342` y `engine.py:1355` interpolan la constante de módulo `_HALF_DONE` (texto fijo); `conversation.py:393` genera `?, ?, ?, ?` a partir de la longitud de la tupla constante `OPEN_RUN_STATES`. **1** (`database.py:79`, `executescript`) ejecuta el texto de un fichero de migración del propio paquete.
- **Ningún valor que venga de fuera** (texto del LLM, de una herramienta, de la persona, de una nota) llega hoy al texto de una sentencia: el riesgo de inyección SQL medido hoy es **0 sitios**. El riesgo real es de **regresión**: nada impide que un cambio futuro meta un dato en un f-string, y ninguna prueba lo detectaría.

Un ORM hace que la forma segura sea la cómoda, pero **no elimina por sí solo** la vía insegura (`text()`, `exec_driver_sql`, f-strings dentro de `text()`, `literal_column` siguen existiendo) y añade riesgos propios que este change mide antes de diseñar (design, «Premisas medidas»). Por eso el change empieza por una guarda que sabe decir NO y luego migra por tramos pequeños, cada uno con `scripts/verify.sh` en verde.

**Corte y riesgo.** No está en la tabla de `docs/plan/2026-11-24-ai-harness-cortes.md`: es infraestructura transversal. Se propone colgarlo del **Corte 8 · Cierre** (endurecimiento que no depende de EA), como change propio en paralelo a `hardening`, y añadir su fila al plan cuando Wilson lo apruebe (pregunta abierta P1 en `design.md`). Riesgo **N1**: no abre superficie nueva ni toca proveedores, pero reescribe la persistencia de garantías vigentes; el tramo del motor de Skills (aprobaciones de un solo uso) se revisa con el rigor de un N2. SEC que **preserva y vuelve a demostrar** (no abre ninguno nuevo): **SEC-02** (aislamiento entre sesiones), **SEC-07** (`uncertain` sin duplicación), **SEC-08** (recuperación tras reinicio), **SEC-12** (aprobación de un solo uso ligada al hash). Se demuestra en **macOS**; Windows es confirmación opcional (mismo código, sin ramas por plataforma).

## What Changes

- **Tramo 0, guarda (entra primero y vale aunque se rechace el ORM):** una prueba que recorre el AST de `harness/` y rechaza toda sentencia SQL que no sea un literal (f-string, concatenación con variables, `%`, `.format`, `text()` con algo que no sea literal). Los 3 f-strings de hoy se reescriben como literales completos. Control negativo: un mutante con un dato interpolado hace fallar la prueba.
- **Dependencias nuevas** (si Wilson aprueba D1): `sqlmodel` y `sqlalchemy`, fijadas exactas. Medido el 2026-11-27 en un entorno desechable: solo añaden esas dos distribuciones (`typing-extensions`, `pydantic`, `pydantic-core`, `annotated-types` y `typing-inspection` ya están en `uv.lock`); sin `greenlet` porque no se usa la variante asíncrona.
- **Modelos de tabla** en `harness/storage/tables.py`, separados de los contratos de `harness/core/contracts.py`, que no cambian. Las columnas se declaran con el tipo **almacenado** (`str` para UUID y fechas ISO), no con `uuid.UUID` ni `datetime`.
- **Las migraciones numeradas `.sql` siguen siendo la única fuente del esquema.** Nunca `create_all` sobre una base real; sin Alembic. Una prueba compara el esquema de los modelos con el de una base migrada con 001..00N y falla si divergen.
- **Las transacciones siguen siendo de `transaction()`** (`BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` explícitos); SQLAlchemy ejecuta sobre la **misma conexión** `sqlite3` que hoy, con su reintento de apertura en Windows y sus pragmas.
- **Migración por tramos**: repositorios, auditoría MCP, motor de Skills (en dos tramos) y conversación. Se quedan como SQL explícito: pragmas, control de transacción, el ejecutor de migraciones y los bloqueos de `locks.py`.
- **Cierre:** la guarda se endurece para que SQL textual sobre la base principal solo exista en `harness/storage/database.py` y `locks.py`, más la documentación.

**No entra:** cambiar el esquema ni añadir migraciones; Alembic; `create_all`; sesiones asíncronas (`AsyncSession`, `aiosqlite`); otro motor que no sea SQLite; caché de objetos entre transacciones; cambiar las pruebas para que usen el ORM (las pruebas siguen leyendo con `sqlite3` crudo como oráculo independiente); retención o purga de filas; copia y restauración. No cambia ninguna salida de la CLI ni de la conversación.

## Capabilities

### New Capabilities

- `local-persistence`: garantías de la base de datos local que hoy no tienen requisito propio: una base creada por versiones anteriores abre y se usa sin cambios; ninguna sentencia SQL se construye con datos en tiempo de ejecución; una transacción que falla no deja nada escrito; el esquema que espera el código coincide con el que producen las migraciones.

### Modified Capabilities

(ninguna) Comprobado con `grep -rniE "sqlite|base de datos|migraci|transacci" openspec/specs/` el 2026-11-27: solo aparecen `session-management` («Esquema migrable y repetible», que sigue igual y se apoya en el mismo ejecutor de migraciones) y un escenario de `project-context` («Canario de nota fuera de SQLite», que no depende de cómo se escribe el SQL). Ningún requisito de `session-management`, `request-recovery` ni de los changes sin archivar (`skill-engine`, `mcp-gateway`) cambia: sus pruebas pasan sin tocar aserciones en cada tramo.

## Impact

- Código por tramo (design, «Plan de tramos»): `harness/storage/{database,repositories,tables}.py`, `harness/mcp/audit.py`, `harness/skills/engine.py`, `harness/shell/conversation.py`; firmas que hoy dicen `sqlite3.Connection` en 8 módulos (`service.py`, `conversation.py`, `database.py`, `audit.py`, `mcp/commands.py`, `repositories.py`, `locks.py`, `engine.py`).
- `pyproject.toml` y `uv.lock` (tramo 1). Pruebas: una nueva por la guarda y otra por la igualdad de esquema; 39 ficheros de prueba usan hoy `sqlite3`/`.execute(` (160 llamadas) y **no se reescriben**: son el oráculo.
- Conflicto probable con la rama que planifica una migración 008 (no encontrada en las ramas remotas el 2026-11-27): esa migración tendrá que actualizar `tables.py` a la vez, o la prueba de igualdad de esquema fallará, que es lo que se busca.
- Sin datos nuevos ni migración: una base existente abre igual.
