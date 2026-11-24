# Tasks

Cada `[x]` lleva su recibo debajo (comando y salida relevante, o SHA). Los oráculos se nombran en cada tarea.

## 1. Estructura y contratos

- [ ] 1.1 Crear rama `feature/session-core` desde `develop` (git flow). Hecho: `git branch --show-current` la muestra.
- [ ] 1.2 Crear `main.py`, `harness/cli.py`, `harness/core/`, `harness/storage/`, `harness/providers/` (D1). Hecho: `uv run python main.py --help` lista `session`, `ask` e `history` y termina con 0.
- [ ] 1.3 Definir los contratos Pydantic `Session`, `LLMRequest`, `LLMResponse` y los tres enumerados de estado (sesión, solicitud). Oráculo: test que construye cada modelo y rechaza un estado fuera del enumerado y una fecha sin zona horaria.

## 2. Almacenamiento y migraciones

- [ ] 2.1 Escribir `migrations/001_initial.sql` con `sessions`, `requests`, `messages`, `audit_events` e índices (D2). Oráculo: `SELECT name FROM sqlite_master WHERE type='table'` devuelve esas cuatro más `schema_migrations`.
- [ ] 2.2 Implementar el migrador y la apertura de conexión con `foreign_keys=ON` y WAL (D3). Oráculo: test que migra dos veces y comprueba `SELECT count(*) FROM schema_migrations` = 1 y datos intactos.
- [ ] 2.3 Implementar los repositorios de sesiones, solicitudes, mensajes y auditoría con consultas parametrizadas. Oráculo: tests de ida y vuelta por repositorio contra un SQLite temporal.
- [ ] 2.4 Control negativo de SEC-02 en almacenamiento: test que inserta un mensaje con `request_id` de otra sesión y espera `IntegrityError`. Antes de darlo por bueno, quitar temporalmente la clave compuesta y confirmar que el test falla; anotar ese fallo como recibo.

## 3. Sesiones e historial en la CLI

- [ ] 3.1 Implementar `session create` y `session list` con validación de nombre. Oráculo: tests de los escenarios «Sesión creada con nombre», «Nombre vacío rechazado», «Tres sesiones listadas» y «Lista vacía».
- [ ] 3.2 Implementar `history SESSION_ID` con validación de UUID completo (D4, D10). Oráculo: tests de «Identificador mal formado» y «Sesión inexistente» que comprueban código 1, mensaje en stderr y ausencia de `Traceback` en la salida.
- [ ] 3.3 Registrar auditoría en creación de sesión y en cada cambio de estado. Oráculo: test que pregunta con la cadena `ZZ-CANARY-7731` y ejecuta `SELECT count(*) FROM audit_events WHERE ... LIKE '%ZZ-CANARY-7731%'` = 0 sobre todas las columnas de texto, con al menos un evento de esa solicitud.

## 4. Proveedor y `ask`

- [ ] 4.1 Definir la interfaz `LLMProvider` con `synthetic_content` y `on_sent` (D5, D6) y el registro de proveedores por nombre. Oráculo: tests de «Mock por defecto» y «Proveedor desconocido» (este último comprueba `SELECT count(*) FROM requests` = 0).
- [ ] 4.2 Implementar el Mock determinista con los cuatro comportamientos y el retardo (D9). Oráculo: test «Misma pregunta, misma respuesta»; test que ejecuta el Mock con `socket.socket` parcheado para lanzar excepción y pasa.
- [ ] 4.3 Implementar `ask`: insertar la solicitud `pending`, llamar al proveedor con plazo, registrar `completed`/`failed`/`timeout`/`uncertain`, duración y estado de sesión (D6, D8). Oráculo: un test por escenario de «Resultado distinto según el punto de fallo» y «Pregunta completada», cada uno con `SELECT status FROM requests`.
- [ ] 4.4 Guardar contenido solo si el proveedor es sintético (D5). Oráculo: test con un proveedor de prueba no sintético que comprueba `SELECT count(*) FROM messages WHERE content IS NOT NULL` = 0; control negativo: el mismo test con el Mock da > 0.
- [ ] 4.5 Tests de «Historial tras dos preguntas», «Solicitud sin respuesta visible en el historial», «El historial no mezcla sesiones» y «Historial disponible en un proceso nuevo» (este último lanza dos subprocesos reales de `main.py` sobre el mismo `HARNESS_DATA_DIR`).

## 5. Bloqueo y recuperación

- [ ] 5.1 Implementar el bloqueo de fichero por sesión para macOS/Linux y Windows (D7). Oráculo: test que toma el bloqueo en un subproceso y comprueba que un segundo intento falla y que tras matar el subproceso se obtiene.
- [ ] 5.2 Implementar la recuperación al arrancar. Oráculo: test que lanza `ask` en un subproceso con `HARNESS_MOCK_DELAY_MS` alto, lo mata con `kill`, ejecuta `session list` y comprueba `SELECT status FROM requests` = `uncertain` y sesión `uncertain`; el Mock registra cero llamadas durante la recuperación («La recuperación no reenvía»).
- [ ] 5.3 Tests de «Listar mientras otra pregunta sigue en curso», «Segunda pregunta en la misma sesión», «Preguntas en sesiones distintas», «Interrupción con Ctrl+C» (señal SIGINT al subproceso), «Repetir es una solicitud nueva» y «Aviso y vuelta a activa». Control negativo: desactivar la comprobación del bloqueo en la recuperación y confirmar que «Listar mientras otra pregunta sigue en curso» falla; anotar el recibo.
- [ ] 5.4 Ejecutar la suite completa en Windows (segunda plataforma) y medir `msvcrt.locking`. Oráculo: salida de `uv run pytest` en Windows con el recuento de pasados/fallados/omitidos y la versión de Python. Estado: PASS, FAIL, NOT RUN o BLOCKED. Si falla el bloqueo, reabrir D7 antes de seguir.

## 6. Documentación

- [ ] 6.1 Escribir `README.md`: instalación con uv, variables de `.env.example` que este corte usa, los cuatro comandos de la CLI, qué significa `uncertain` y la advertencia de disco local para `HARNESS_DATA_DIR`. Hecho: los comandos del README, copiados tal cual, funcionan sobre un directorio de datos vacío.
- [ ] 6.2 Añadir `scripts/demo-session-core.sh` que reproduce la demo de 7.2 sobre un `HARNESS_DATA_DIR` temporal. Hecho: termina con 0 y deja el log en stdout.

## 7. Integración y demo

- [ ] 7.1 `scripts/verify.sh` sobre el árbol limpio. Oráculo: línea `verify: PASS on <SHA>`. Control negativo: romper un escenario a propósito en una copia de trabajo y confirmar que `verify.sh` termina distinto de 0.
- [ ] 7.2 Demo del Corte 1. Wilson reproduce, con el SHA de 7.1, en macOS y en Windows: (a) crear tres sesiones; (b) una pregunta en cada una; (c) cerrar la terminal, abrir otra y ver `history` de las tres sin mezcla; (d) `ask` con `HARNESS_MOCK_DELAY_MS=60000`, matar el proceso, y ver la solicitud y la sesión en `uncertain`; (e) `history` con un identificador mal formado. Evidencia: log de `scripts/demo-session-core.sh` en cada plataforma. Estado por plataforma: PASS, FAIL, NOT RUN o BLOCKED.

## Workflow follow-up

- Abrir el PR de `feature/session-core` contra `develop` con descripción en español; el merge lo aprueba Wilson.
- Archivar el change cuando la demo esté en PASS en las dos plataformas.
