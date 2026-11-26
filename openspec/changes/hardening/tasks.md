# Tasks

Cada `[x]` lleva su recibo debajo (comando y salida relevante, o SHA). Los oráculos se nombran en cada tarea; cada comprobación lleva un control negativo aplicado en una copia desechable bajo `mktemp -d` y deshecho. Repo público y proyecto educativo: ningún dato del entorno de Wilson en los documentos.

**Antes de empezar:** Wilson confirma la decisión pendiente 1 de `design.md` (lista de lo aplazado). Las 2, 3 y 4 solo cambian la `Decisión` de su punto en la deuda conocida; no bloquean ninguna tarea.

## 1. Matriz SEC y su comprobación

- [ ] 1.1 Rama `feature/hardening` desde `develop`. Hecho: `git branch --show-current` la muestra y `uv run pytest` pasa entero antes de tocar nada.
- [ ] 1.2 `scripts/check_sec_matrix.py` con el formato de D2 y sus tests en `tests/unit/test_check_sec_matrix.py` sobre matrices sintéticas en `tmp_path`. Oráculo: una matriz válida da `sec-matrix: PASS`; cada una de estas da código 1 y nombra la fila: falta SEC-07, SEC-16 de más, filas fuera de orden, estado `casi`, fila `cubierto` sin tests, un test que no existe, un test renombrado (fichero existe, función no), una ruta de spec inexistente, un requisito que la spec no contiene, una fila `BLOCKED` sin motivo. El subproceso de `pytest --collect-only` tiene plazo y su fallo da código 1, no un PASS. Control negativo: comprobar solo el fichero (no la función) hace que el caso del test renombrado pase y el test falle.
- [ ] 1.3 `docs/security/sec-matrix.md` con la matriz de partida de D3, vuelta a comprobar contra el `develop` del día: cada identificador en `pytest --collect-only`, cada requisito citado en su spec, cada control negativo en el recibo que cita. Hecho: `uv run python scripts/check_sec_matrix.py` → `sec-matrix: PASS (15 rows, N tests)`; las filas `pendiente de merge` nombran su change y las `BLOCKED`, la pausa de EA.
- [ ] 1.4 Llamada en `scripts/verify.sh` después de `pytest`, con su código de salida respetado (`set -e` y sin tuberías que lo oculten). Oráculo: `verify: PASS on <SHA>`. Control negativo: en una copia desechable, renombrar `test_approval_reused` y hacer commit hace terminar `verify.sh` con distinto de 0 en el paso de la matriz.
- [ ] 1.5 Revisión independiente de la matriz contra los tests citados (que lo que dice cada fila lo pruebe de verdad el test, no solo que exista). Hecho: hallazgos anotados y corregidos en el documento; los que sean huecos de conducta, apuntados como `parcial` o `no cubierto` con el change que los resolverá.

## 2. Runbook y guía de diagnóstico

- [ ] 2.1 `docs/runbook/install-and-use.md` (D4) con comandos para macOS/zsh y Windows/PowerShell. Hecho: los comandos de macOS, copiados tal cual con un `HARNESS_DATA_DIR` y una copia del vault sintético temporales, terminan con el código que dice el documento; los de PowerShell quedan sin ejecutar hasta 4.2 y el documento lo dice.
- [ ] 2.2 `docs/runbook/diagnosis.md` (D4), organizado por síntoma, con el test que produce cada uno y qué no se debe copiar fuera de la máquina ni borrar a mano. Oráculo: cada test citado existe (lo comprueba un test pequeño que extrae los identificadores del documento con la misma función de 1.2). Control negativo: un identificador inventado en una copia hace fallar ese test.
- [ ] 2.3 Enlaces desde `README.md` (sección nueva «Seguridad y diagnóstico» o en las existentes) y desde `SECURITY.md`. Hecho: `uv run python scripts/check_public_safety.py` pasa; ningún enlace roto (comprobado con un test que resuelve las rutas relativas de los dos ficheros).

## 3. Deuda conocida

- [ ] 3.1 `docs/security/known-debt.md` con los puntos de D5, cada uno con `Qué`, `Riesgo`, `Decisión` y `Dueño`, y las respuestas de Wilson a las decisiones 2, 3 y 4 si las hay (si no, `pendiente de Wilson`). Hecho: ningún punto sin decisión ni dueño; el 10 dice «aplazado (proyecto educativo, 2026-11-25)»; `check_public_safety.py` pasa.

## 4. Portabilidad, verificación y demo

- [ ] 4.1 Portabilidad. Oráculo: `tests/unit/test_portability.py` pasa y `grep -nE "sys\.platform|os\.name|msvcrt|fcntl|platform\.system" scripts/check_sec_matrix.py scripts/demo_hardening.py` sin resultados. Control negativo: `X = sys.platform` en una copia desechable de `harness/core/service.py` hace fallar `test_portability.py`.
- [ ] 4.2 Confirmación opcional en Windows (no bloquea): `uv run python scripts/check_sec_matrix.py`, `uv run python scripts/demo_hardening.py` y los comandos de PowerShell del runbook. Oráculo: códigos de salida y `sec-matrix: PASS`, con la versión de Python. Estado: PASS, FAIL o NOT RUN.
- [ ] 4.3 `scripts/demo_hardening.py` (Python, con `scripts/demo_common.py`): ejecuta `check_sec_matrix.py` y muestra el recuento por estado; copia la matriz a un directorio temporal, renombra en la copia un test citado y comprueba que la comprobación lo rechaza; recorre el runbook de macOS con un `HARNESS_DATA_DIR` temporal y provoca un `uncertain` (Mock con `HARNESS_MOCK_BEHAVIOR`) para comprobar que la guía de diagnóstico describe lo que se ve. Hecho: exit 0 y `demo: PASS` en la Mac.
- [ ] 4.4 `scripts/verify.sh` sobre el árbol limpio. Oráculo: `verify: PASS on <SHA>` con el paso de la matriz incluido.
- [ ] 4.5 **Demo de `hardening`.** Wilson reproduce en macOS, con el SHA de 4.4: (a) `scripts/demo_hardening.py` → `demo: PASS`; (b) abre `docs/security/sec-matrix.md`, elige dos SEC y ejecuta los tests citados con `uv run pytest <id>`; (c) sigue la guía de diagnóstico ante el `uncertain` que provoca la demo; (d) lee la deuda conocida y confirma que cada decisión es la suya. Evidencia: log de la demo y salida de (b). Estado: PASS, FAIL, NOT RUN o BLOCKED.

## Workflow follow-up

- Abrir el PR de `feature/hardening` contra `develop` con descripción en español; el merge lo aprueba Wilson.
- Al mergear `copilot-web-provider`, `architecture-skills-llm` o `harness-mcp-server`, y al archivar `skill-engine` o `mcp-gateway`, actualizar las filas afectadas de la matriz en el mismo PR (la comprobación obliga en el caso de rutas).
- Cuando EA se retome, SEC-11 y la parte de COM de SEC-10 salen de `BLOCKED` con `ea-read`.
