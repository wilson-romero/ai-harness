# Proposal

## Why

La matriz SEC-01..SEC-15 del plan maestro (§14) se prueba corte a corte, pero nadie puede contestar hoy, sin leer 6 `tasks.md` y 56 ficheros de test, qué SEC está cubierto, por qué test y con qué control negativo. Medido el 2026-11-25 sobre `develop` (`86f1079`): `grep -n "SEC-" README.md SECURITY.md` → 1 línea (SEC-09 en `SECURITY.md`); no existe `docs/security/`; `uv run pytest --collect-only -q` → 852 tests repartidos en 56 ficheros `.py` de `tests/`; y ningún script comprueba que un test citado en un recibo siga existiendo. Tampoco hay un runbook de instalación y uso para macOS y Windows/PowerShell (solo `docs/runbook/enterprise-architect.md`, en pausa), ni una guía para diagnosticar `uncertain`, `awaiting_approval`, `authentication_required`, una sesión ocupada o un bloqueo, ni una lista de la deuda conocida con su decisión.

Corte **8 · Cierre** de `docs/plan/2026-11-24-ai-harness-cortes.md`, en la parte que no depende de EA (revisión del 2026-11-25). Riesgo **N1**: no cambia conducta del producto. Afecta a **todas** las SEC en el sentido de documentarlas con recibos; **SEC-11** y la parte de COM de **SEC-10** quedan **BLOCKED** por la pausa de EA. Se demuestra en **macOS**; el runbook de Windows/PowerShell se escribe y su ejecución es confirmación opcional de Wilson.

**Proyecto educativo** (Wilson, 2026-11-25): se conserva lo que más enseña —la matriz con su comprobación, el runbook y la guía de diagnóstico— y se aplaza lo que solo sirve para operar en producción.

## What Changes

- **Matriz SEC viva** en `docs/security/sec-matrix.md`: por cada SEC-01..15, la capacidad y el requisito que lo cubren, los tests que lo prueban (por identificador de pytest), el control negativo (el recibo donde se vio fallar), el estado (`cubierto`, `parcial`, `pendiente de merge`, `no cubierto`, `BLOCKED`) y los límites escritos. Se rellena con lo que existe en `develop` el día que se implemente; lo de ramas sin mergear se marca `pendiente de merge`.
- **Comprobación de que la matriz no se pudre** en `scripts/verify.sh`: un script que exige las 15 filas, un estado de la lista cerrada, al menos un test en cada fila `cubierto` o `parcial`, y que cada test citado exista y lo recoja `pytest --collect-only`.
- **Runbook de instalación y uso** para macOS y Windows/PowerShell (`docs/runbook/install-and-use.md`).
- **Guía de diagnóstico** (`docs/runbook/diagnosis.md`): qué significa cada estado incierto o en espera, qué hacer, dónde están los bloqueos, la base de datos y los logs, y qué no se debe borrar a mano.
- **Lista de deuda conocida** (`docs/security/known-debt.md`) con dueño y decisión por cada punto.

**No entra**, aunque un lector lo asumiría:

- **Copia y restauración de `HARNESS_DATA_DIR`:** aplazada por decisión de Wilson del 2026-11-25. Es una tarea de operación en producción y este proyecto es educativo; los datos de un piloto con prompts sintéticos se pueden regenerar. La guía de diagnóstico sí dice qué contiene el directorio y qué no se debe copiar fuera (perfil de Edge, claves HMAC, logs).
- Retención o purga de filas de SQLite, rotación de logs entre ejecuciones, monitorización: operación en producción, aplazadas por el mismo motivo.
- Cualquier cambio de conducta del producto. Un hueco que la matriz descubra se apunta como `no cubierto` o `parcial` con una tarea en el change que corresponda; no se arregla aquí.
- Curador y Sueño asistidos (`memory-curation`), que siguen en el Corte 8 después del MVP.
- Lo que depende de EA: SEC-11 y la parte de COM de SEC-10 quedan BLOCKED en la matriz.
- Ejecutar el runbook de Windows como puerta: es confirmación opcional.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

Ninguna. Este change es documentación y una comprobación de desarrollo; no cambia ninguna conducta del harness, así que su `.openspec.yaml` lleva `skip_specs: true` en lugar de un requisito inventado. Comprobado el 2026-11-25: `openspec list --specs` devuelve 8 capacidades y ninguna se toca. La matriz cita requisitos de capacidades archivadas (`openspec/specs/`) y de changes mergeados sin archivar (`skill-engine`, `mcp-gateway`, nombrados por su ruta en `openspec/changes/`); al archivarlos, la comprobación de la matriz obliga a actualizar esas rutas (design D2).

## Impact

- Documentación nueva: `docs/security/sec-matrix.md`, `docs/security/known-debt.md`, `docs/runbook/install-and-use.md`, `docs/runbook/diagnosis.md`; enlaces desde `README.md` y `SECURITY.md`.
- Script nuevo: `scripts/check_sec_matrix.py` (biblioteca estándar; ejecuta `pytest --collect-only` como subproceso con plazo) y su llamada en `scripts/verify.sh`; tests del script en `tests/unit/`.
- Código de producto: ninguno. Dependencias: ninguna.
- Demo: `scripts/demo_hardening.py`.
