# Tasks

Cada `[x]` lleva su recibo debajo (comando y salida relevante, o SHA). Los oráculos se nombran en cada tarea.

## 1. Estructura y contratos

- [x] 1.1 Crear rama `feature/session-core` desde `develop` (git flow). Hecho: `git branch --show-current` la muestra.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `git branch --show-current` → `feature/session-core` (creada sobre `feature/bootstrap`, que sale de `develop`, porque el PR #1 aún no está mergeado).
- [x] 1.2 Crear `main.py`, `harness/cli.py`, `harness/core/`, `harness/storage/`, `harness/providers/` (D1). Hecho: `uv run python main.py --help` lista `session`, `ask` e `history` y termina con 0.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `uv run python main.py --help` lista `{session,ask,history}`, exit 0.
- [x] 1.3 Definir los contratos Pydantic `Session`, `LLMRequest`, `LLMResponse` y los tres enumerados de estado (sesión, solicitud). Oráculo: test que construye cada modelo y rechaza un estado fuera del enumerado y una fecha sin zona horaria.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `tests/unit/test_contracts.py`, 4 pasados.

## 2. Almacenamiento y migraciones

- [x] 2.1 Escribir `migrations/001_initial.sql` con `sessions`, `requests`, `messages`, `audit_events` e índices (D2). Oráculo: `SELECT name FROM sqlite_master WHERE type='table'` devuelve esas cuatro más `schema_migrations`.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_first_run_creates_the_schema` compara el conjunto exacto de cinco tablas.
- [x] 2.2 Implementar el migrador y la apertura de conexión con `foreign_keys=ON` y WAL (D3). Oráculo: test que migra dos veces y comprueba `SELECT count(*) FROM schema_migrations` = 1 y datos intactos.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_migrating_twice_changes_nothing`: segunda `migrate()` devuelve `[]`, `count(*)` = 1.
- [x] 2.3 Implementar los repositorios de sesiones, solicitudes, mensajes y auditoría con consultas parametrizadas. Oráculo: tests de ida y vuelta por repositorio contra un SQLite temporal.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `tests/unit/test_storage.py`, 5 pasados.
- [x] 2.4 Control negativo de SEC-02 en almacenamiento: test que inserta un mensaje con `request_id` de otra sesión y espera `IntegrityError`. Antes de darlo por bueno, quitar temporalmente la clave compuesta y confirmar que el test falla; anotar ese fallo como recibo.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): Con la clave compuesta quitada de `001_initial.sql`: `Failed: DID NOT RAISE IntegrityError` en `test_cross_session_message_is_rejected_by_storage` (1 failed, 2 passed). Restaurada: pasa.

## 3. Sesiones e historial en la CLI

- [x] 3.1 Implementar `session create` y `session list` con validación de nombre. Oráculo: tests de los escenarios «Sesión creada con nombre», «Nombre vacío rechazado», «Tres sesiones listadas» y «Lista vacía».
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `tests/unit/test_cli_sessions.py`: `test_session_created_with_name`, `test_empty_name_is_rejected`, `test_three_sessions_listed`, `test_empty_list`.
- [x] 3.2 Implementar `history SESSION_ID` con validación de UUID completo (D4, D10). Oráculo: tests de «Identificador mal formado» y «Sesión inexistente» que comprueban código 1, mensaje en stderr y ausencia de `Traceback` en la salida.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_malformed_identifier` (tres formas, incluida la de llaves) y `test_missing_session`: código 1, sin `Traceback`, `count(*) FROM requests` = 0.
- [x] 3.3 Registrar auditoría en creación de sesión y en cada cambio de estado. Oráculo: test que pregunta con la cadena `ZZ-CANARY-7731` y ejecuta `SELECT count(*) FROM audit_events WHERE ... LIKE '%ZZ-CANARY-7731%'` = 0 sobre todas las columnas de texto, con al menos un evento de esa solicitud.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_audit_never_stores_the_prompt`: el canario no aparece en ninguna fila de `audit_events` y sí aparece 1 vez en `messages` (control de que la búsqueda distingue).

## 4. Proveedor y `ask`

- [x] 4.1 Definir la interfaz `LLMProvider` con `synthetic_content` y `on_sent` (D5, D6) y el registro de proveedores por nombre. Oráculo: tests de «Mock por defecto» y «Proveedor desconocido» (este último comprueba `SELECT count(*) FROM requests` = 0).
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_mock_is_the_default_provider`, `test_unknown_provider` (`requests` = 0 y `session create` tampoco crea sesión).
- [x] 4.2 Implementar el Mock determinista con los cuatro comportamientos y el retardo (D9). Oráculo: test «Misma pregunta, misma respuesta»; test que ejecuta el Mock con `socket.socket.connect`, `socket.getaddrinfo` y `socket.create_connection` parcheados para lanzar excepción y pasa (parchear `socket.socket` entero rompe el bucle de asyncio, que usa un socketpair local).
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_same_question_same_answer`, `test_mock_works_without_network`.
- [x] 4.3 Implementar `ask`: insertar la solicitud `pending`, llamar al proveedor con plazo, registrar `completed`/`failed`/`timeout`/`uncertain`, duración y estado de sesión (D6, D8). Oráculo: un test por escenario de «Resultado distinto según el punto de fallo» y «Pregunta completada», cada uno con `SELECT status FROM requests`.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_question_completed` y `test_result_depends_on_where_it_failed` con sus tres casos (`failed`, `timeout`, `uncertain`), más `test_failure_states_exit_non_zero_and_name_the_state`.
- [x] 4.4 Guardar contenido solo si el proveedor es sintético (D5). Oráculo: test con un proveedor de prueba no sintético que comprueba `SELECT count(*) FROM messages WHERE content IS NOT NULL` = 0; control negativo: el mismo test con el Mock da > 0.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_content_is_stored_only_for_synthetic_providers`: 0 mensajes con contenido con el proveedor no sintético; 2 con el Mock.
- [x] 4.5 Tests de «Historial tras dos preguntas», «Solicitud sin respuesta visible en el historial», «El historial no mezcla sesiones» y «Historial disponible en un proceso nuevo» (este último lanza dos subprocesos reales de `main.py` sobre el mismo `HARNESS_DATA_DIR`).
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_history_after_two_questions`, `test_result_depends_on_where_it_failed` (historial sin respuesta inventada), `test_history_does_not_mix_sessions`, `test_history_survives_a_new_process` (tres subprocesos).

## 5. Bloqueo y recuperación

- [x] 5.1 Implementar el bloqueo por sesión con una transacción exclusiva de SQLite, sin código condicionado por plataforma (D7 revisada). Oráculo: test que toma el bloqueo en un subproceso y comprueba que un segundo intento falla y que tras matar el subproceso se obtiene.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `tests/unit/test_locks.py`, 2 pasados con la versión SQLite. La primera versión (`fcntl`/`msvcrt`) quedó revertida.
- [x] 5.2 Implementar la recuperación al arrancar. Oráculo: test que lanza `ask` en un subproceso con `HARNESS_MOCK_DELAY_MS` alto, lo mata con `kill`, ejecuta `session list` y comprueba `SELECT status FROM requests` = `uncertain` y sesión `uncertain`; el Mock registra cero llamadas durante la recuperación («La recuperación no reenvía»).
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `test_killed_process_leaves_the_request_uncertain` (subproceso matado con `kill`) y `test_recovery_does_not_resend` (`provider.calls == 0`).
- [x] 5.3 Tests de «Listar mientras otra pregunta sigue en curso», «Segunda pregunta en la misma sesión», «Preguntas en sesiones distintas», «Interrupción con Ctrl+C» (cancelación de la pregunta en curso, que es como llega Ctrl+C, más el código 130 de la CLI), «Repetir es una solicitud nueva» y «Aviso y vuelta a activa». Control negativo: desactivar la comprobación del bloqueo en la recuperación y confirmar que «Listar mientras otra pregunta sigue en curso» falla; anotar el recibo.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): siete tests en `tests/integration/test_recovery.py`, ninguno omitido en ninguna plataforma. Control negativo: con `recover()` ignorando el bloqueo, `test_live_request_is_not_touched_by_another_process` falla (1 failed, 8 passed); restaurado, pasa.
- [x] 5.4 Demostrar que el producto no tiene código condicionado por plataforma, de modo que lo probado en la Mac es lo que corre en Windows. Oráculo: `tests/unit/test_portability.py` y `grep -rnE "sys\.platform|os\.name|msvcrt|fcntl" harness main.py` sin resultados. Control negativo: el test debe fallar contra la versión `fcntl`/`msvcrt` del bloqueo.
  - Recibo (2026-11-24): contra el bloqueo antiguo, `test_product_code_has_no_platform_branches` falló citando `harness/storage/locks.py:14: if sys.platform == "win32":`; con el bloqueo SQLite pasa y el grep no devuelve nada. Sustituye a la tarea original «ejecutar la suite en Windows» por decisión de Wilson del 2026-11-24: Windows no es puerta del corte.

## 6. Documentación

- [x] 6.1 Escribir `README.md`: instalación con uv, variables de `.env.example` que este corte usa, los cuatro comandos de la CLI, qué significa `uncertain` y la advertencia de disco local para `HARNESS_DATA_DIR`. Hecho: los comandos del README, copiados tal cual, funcionan sobre un directorio de datos vacío.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): Comandos del README ejecutados sobre un directorio vacío: crean sesión, responden y muestran historial.
- [x] 6.2 Añadir `scripts/demo_session_core.py` que reproduce la demo de 7.2 sobre un `HARNESS_DATA_DIR` temporal. Hecho: termina con 0 y deja el log en stdout.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): `scripts/demo_session_core.py` → `demo: PASS` en macOS.

## 7. Integración y demo

- [x] 7.1 `scripts/verify.sh` sobre el árbol limpio. Oráculo: línea `verify: PASS on <SHA>`. Control negativo: romper un escenario a propósito en una copia de trabajo y confirmar que `verify.sh` termina distinto de 0.
  - Recibo (2026-11-24, macOS arm64, Python 3.14.8): ver el SHA de `verify: PASS` en la descripción del PR #2 (se vuelve a ejecutar tras cada commit). Control negativo en un worktree desechable con `uncertain` cambiado por `timeout`: 3 FAILED y sin línea `verify: PASS`.
- [x] 7.2 Demo del Corte 1. Wilson reproduce con el SHA del PR: (a) crear tres sesiones; (b) una pregunta en cada una; (c) cerrar la terminal, abrir otra y ver `history` de las tres sin mezcla; (d) `ask` con `HARNESS_MOCK_DELAY_MS=60000`, matar el proceso, y ver la solicitud y la sesión en `uncertain`; (e) `history` con un identificador mal formado. Evidencia: log de `scripts/demo_session_core.py`. Estado: PASS, FAIL, NOT RUN o BLOCKED. Una ejecución en Windows es una confirmación opcional.
  - Recibo (2026-11-24): **PASS**. Wilson ejecutó `uv run python scripts/demo_session_core.py` en Windows AMD64, Python 3.14.10, PowerShell, sobre `459b401` (rama que contiene este corte): tres sesiones, historial sin mezcla, la pregunta matada a mitad quedó `uncertain` y el identificador mal formado dio error controlado; terminó en `demo: PASS`.
  - macOS: **PASS** ejecutado por el agente (`scripts/demo_session_core.py` → `demo: PASS`, 2026-11-24); falta que Wilson lo reproduzca.

## Workflow follow-up

- Abrir el PR de `feature/session-core` contra `develop` con descripción en español; el merge lo aprueba Wilson.
- Archivar el change cuando la demo esté en PASS en las dos plataformas.
