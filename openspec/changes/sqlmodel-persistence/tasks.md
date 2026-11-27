# Tasks

Cada `[x]` lleva su recibo debajo, con fecha y plataforma. Cada grupo es un tramo de `design.md` («Plan de tramos»): su propia rama desde `develop`, su PR y `scripts/verify.sh` en verde. Los controles negativos se aplican con un guion fuera del repositorio (mutación, prueba, restauración) y su recibo es `1 failed` o más. Los grupos 2 a 8 dependen de las respuestas de Wilson a P2 (alcance) y P4 (versiones) de `design.md`; el grupo 1 no.

## 1. Tramo 0 · Guarda contra SQL construido

- [ ] 1.1 Rama `feature/sqlmodel-persistence-0` desde `develop`. Hecho: `git rev-parse --abbrev-ref HEAD` da ese nombre y su base es `origin/develop`.
- [ ] 1.2 `tests/unit/test_sql_literals.py` (D9): recorre el AST de `harness/` y rechaza, con fichero y línea, todo primer argumento de `execute`, `executemany`, `executescript`, `exec_driver_sql`, `text`, `literal_column` y `prefix_with` que no sea literal o nombre ligado a literal; única excepción, con su motivo, `executescript` en `migrate()`. Oráculo: sobre `develop` sin el 1.3 la prueba falla y nombra exactamente `engine.py:1342`, `engine.py:1355` y `conversation.py:393`.
- [ ] 1.3 Reescribir esos 3 f-strings como literales completos (las dos consultas de `_HALF_DONE` enteras; `IN (?, ?, ?, ?)` como en `engine.py:243`) y quitar el `noqa: S608`. Oráculo: la prueba del 1.2 pasa, y el inventario del guion AST da 0 f-strings y 0 concatenaciones en sentencias.
- [ ] 1.4 Controles negativos de la guarda: (a) `conn.execute(f"SELECT * FROM sessions WHERE name = '{name}'")`; (b) `"… WHERE name = '" + name + "'"`; (c) `sql = "…%s" % name; conn.execute(sql)`; (d) `text(f"…{x}")`. Oráculo: cada mutante → `1 failed` con su línea.
- [ ] 1.5 Escenario «Valor hostil como dato» de la spec: sesión llamada `x'); DROP TABLE sessions; --` en `tests/security/`. Oráculo: el nombre literal en `session list` y `SELECT name FROM sqlite_master WHERE type = 'table'` con las 11 tablas.
- [ ] 1.6 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y `verify: PASS on <sha>`; `tests/unit/test_portability.py` en verde (sin ramas por plataforma).

## 2. Tramo 1 · Dependencias, modelos y fontanería, sin cambiar conducta

- [ ] 2.1 `sqlmodel` y `sqlalchemy` fijadas con `==` (D8, P4). Recibo: versión, licencia, fecha de publicación (≥ 14 días) y ruedas `cp314` para macOS arm64 y Windows amd64 de cada una, leídas de PyPI ese día; `uv lock --check` pasa; la diferencia de `uv.lock` añade solo esas dos distribuciones.
- [ ] 2.2 `harness/storage/tables.py` con las 10 tablas de dominio y el tipo guardado (D2), y `tests/unit/test_schema_matches_migrations.py` (D3). Oráculo: la prueba pasa comparando `table_info`, `foreign_key_list` e índices (con el `WHERE` de los parciales). Controles negativos: quitar una columna del modelo, cambiar su nulabilidad, quitar el `sqlite_where` de `idx_approvals_one_live_per_step` y añadir una migración `008` de prueba con una columna → cada uno `1 failed` que nombra tabla y columna o índice.
- [ ] 2.3 `Engine` por conexión sobre la conexión de `connect()` (D4, D7): `creator`, `StaticPool`, `AUTOCOMMIT`; ningún sitio de producto lo usa todavía. Oráculo: prueba de que `engine.raw_connection()` es la misma conexión, que los dos pragmas siguen activos y que usarla desde otro hilo da `ProgrammingError` (premisa P9). Control negativo: un `Engine` con `sqlite:///` propio → la prueba de identidad falla.
- [ ] 2.4 Base de la versión anterior (spec «Una base existente abre sin cambios»): un constructor en `tests/` que crea y puebla, con SQL crudo y literal, una base sintética con la forma de filas de hoy (UUID con guiones, fechas `isoformat()` con `+00:00`, una ejecución de Skill con aprobación, una llamada MCP). Oráculo: `iterdump()` idéntico antes y después de abrirla, listar sesiones e historial; lo mismo en sentido inverso (filas escritas por el código nuevo, leídas con SQL crudo). Control negativo: escribir un UUID sin guiones en el código nuevo → `1 failed`.
- [ ] 2.5 Frontera de transacción (spec «Una transacción fallida no deja nada escrito», D4): con una sentencia SQLAlchemy y una `sqlite3` dentro del mismo `transaction()`, otra conexión ve 0 filas antes del `COMMIT` y 2 después; con una excepción entre las dos, 0. La guarda del 1.2 rechaza además `.commit(`, `.rollback(` y `.begin(` de SQLAlchemy en `harness/`. Controles negativos: sustituir el `COMMIT` explícito por `Session.commit()` → la prueba ve 0 filas y falla; añadir un `session.commit()` en `harness/` → la guarda falla.
- [ ] 2.6 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0, `verify: PASS on <sha>` y el mismo número de pruebas que antes más las nuevas, sin ninguna aserción cambiada (`git diff --stat develop -- tests/` solo con ficheros nuevos).

## 3. Tramo 2 · `storage/repositories.py`

- [ ] 3.1 Las 15 sentencias con `select`/`insert`/`update` (10 A, 5 B), devolviendo contratos como hoy (D5). Oráculo: `test_storage.py`, `test_recovery.py`, `test_session_isolation.py` y las pruebas de `SessionService` pasan sin cambiar aserciones; el guion AST da 0 `execute(` en `repositories.py`.
- [ ] 3.2 `bind_remote_ref` captura el `IntegrityError` de SQLAlchemy (D6). Oráculo: `test_a_remote_reference_belongs_to_one_session` pasa. Control negativo: capturar solo `sqlite3.IntegrityError` → `1 failed`.
- [ ] 3.3 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y `verify: PASS on <sha>`.

## 4. Tramo 3 · `mcp/audit.py`

- [ ] 4.1 Las 6 sentencias (3 A, 3 B); los tres cierres siguen siendo un solo `UPDATE … WHERE status = 'running'` con `rowcount` (D5). Oráculo: pruebas de MCP y `test_mcp_cli.py` sin cambiar aserciones. Control negativo: quitar `status == 'running'` del `where` → la prueba de cierre doble falla.
- [ ] 4.2 `recover_stale` marca `failed/interrupted` solo las llamadas sin dueño vivo (SEC-08). Oráculo: las pruebas de recuperación de MCP pasan.
- [ ] 4.3 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y `verify: PASS on <sha>`.

## 5. Tramo 4 · Motor de Skills, lecturas e inserciones

- [ ] 5.1 Las 16 sentencias de tipo A de `engine.py` leídas con `.mappings()` para conservar `row["col"]` (D5). Oráculo: `test_skill_*.py`, `test_skill_crash.py`, `test_hls_review.py` y `test_architecture_memory.py` sin cambiar aserciones.
- [ ] 5.2 La inserción de `skill_runs` sigue rechazando una segunda ejecución abierta por sesión (índice parcial, `engine.py:269`), capturando el `IntegrityError` de SQLAlchemy. Oráculo: `test_one_open_run_per_session` y la prueba del motor equivalente. Control negativo: capturar solo `sqlite3.IntegrityError` → `1 failed`.
- [ ] 5.3 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y `verify: PASS on <sha>`.

## 6. Tramo 5 · Motor de Skills, actualizaciones, aprobaciones y recuperación

- [ ] 6.1 Las 19 sentencias de tipo B, con `_HALF_DONE` como una expresión `exists()` y `CASE`/`COALESCE` de Core. Oráculo: las mismas pruebas del 5.1 sin cambiar aserciones; el guion AST da 0 `execute(` en `engine.py`.
- [ ] 6.2 `effect_sources` sigue con `INSERT OR IGNORE` (`prefix_with`, D6, premisa P6). Oráculo: prueba que inserta dos veces la misma fuente y una fila que viola un `CHECK`, y no lanza. Control negativo: `on_conflict_do_nothing()` → `1 failed`.
- [ ] 6.3 SEC-12: consumir una aprobación sigue siendo un solo `UPDATE … WHERE status = 'granted' AND proposal_hash = ? AND expires_at > ?` con `rowcount`. Oráculo: `test_skill_approval.py` (reutilizada, hash alterado, caducada) pasa. Controles negativos: quitar `proposal_hash` del `where`; comparar `expires_at` como `DATETIME` en lugar de texto → cada uno `1 failed`.
- [ ] 6.4 Recuperación (SEC-07, SEC-08): `recover_runs` deja `uncertain` lo que estaba a medias y no reintenta. Oráculo: `test_skill_crash.py` y `test_decision_crash.py` pasan.
- [ ] 6.5 Revisión independiente del tramo, centrada en SEC-12 y en la frontera de transacción; los hallazgos se corrigen o se escriben en `design.md` como límites. Oráculo: el informe de la revisión enlazado aquí.
- [ ] 6.6 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y `verify: PASS on <sha>`.

## 7. Tramo 6 · Conversación, guarda endurecida y documentación

- [ ] 7.1 Las 4 sentencias de `conversation.py`; `ORDER BY rowid` con `literal_column("rowid")` (D6). Oráculo: `test_shell_*.py` y `test_chat_*.py` sin cambiar aserciones. Control negativo: ordenar por `started_at` → la prueba de dos solicitudes con la misma fecha falla.
- [ ] 7.2 La guarda del 1.2 exige que `execute`/`executescript` sobre la base principal solo aparezcan en `storage/database.py` y `storage/locks.py` (D9). Control negativo: un `conn.execute("SELECT 1")` literal en `harness/core/service.py` → `1 failed`.
- [ ] 7.3 Documentar en `docs/runbook/` (o en el README, sección de desarrollo) cómo se escribe una consulta nueva, por qué no hay `create_all` ni `Session.commit()`, y que una migración nueva actualiza `tables.py` en el mismo commit. Oráculo: el ejemplo del documento se ejecuta tal cual contra una base sintética.
- [ ] 7.4 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y `verify: PASS on <sha>`.

## 8. Cierre del change

- [ ] 8.1 Nuevo inventario con el guion AST sobre el último tramo. Oráculo: quedan exactamente las 11 sentencias de tipo C, todas en `database.py` (9) y `locks.py` (2); 0 f-strings.
- [ ] 8.2 Windows (confirmación opcional, máquina de pruebas de Wilson): `uv sync`, `scripts/verify.sh` y el escenario de la base de la versión anterior (2.4). Resultado: PASS, FAIL o NOT RUN con lo que se vio.
- [ ] 8.3 Demo (Wilson, macOS): con un `HARNESS_DATA_DIR` sintético creado con `v0.2.1` (sesiones, una pregunta con el Mock, `/skill` con aprobación), cambiar al SHA del último tramo y repetir `main.py chat`: el historial sigue, la aprobación vieja no se puede reutilizar y una pregunta nueva queda guardada. Evidencia: SHA y log de la sesión. Estado: **NOT RUN**.

## Workflow follow-up

- Añadir la fila del change al plan de `docs/plan/` en el corte que Wilson elija (P1).
- Archivar el change cuando los tramos estén mergeados y la demo 8.3 tenga estado.
