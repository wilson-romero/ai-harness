# Tasks

Cada `[x]` lleva su recibo debajo (comando y salida relevante, o SHA). Los oráculos se nombran en cada tarea; cada comprobación lleva un control negativo aplicado en una copia desechable bajo `mktemp -d` y deshecho. Repo público y proyecto educativo: documentos, respuestas guionizadas y recibos sintéticos; lo real lo ejecuta Wilson en su máquina y aporta solo cifras.

**Dependencias:** el grupo 2 en adelante necesita `architecture-skills-llm` mergeado en `develop` (los Skills viven allí): **BLOCKED** hasta entonces. El grupo 4 necesita además `copilot-web-provider` mergeado: **BLOCKED**.

## 1. Decisiones y rama

- [ ] 1.1 Wilson contesta las decisiones pendientes de `design.md` (flujo en dos Skills, número de requerimientos reales, alcance de la autorización). Hecho: respuesta con fecha anotada como recibo; si elige el Skill encadenado, este change se cierra y se abre otro con specs.
- [ ] 1.2 **BLOCKED** por el merge de `architecture-skills-llm`. Rama `feature/mvp-without-ea` desde `develop`. Hecho: `git branch --show-current` la muestra, `uv run python main.py skill list` con la raíz por defecto muestra `hls-review` y `architecture-memory` `valid`, y `uv run pytest` pasa entero antes de tocar nada.

## 2. Integración con el Mock

- [ ] 2.1 **BLOCKED** por 1.2. Fixtures sintéticos del flujo en `tests/fixtures/mvp/`: un requerimiento corto de `demo-alpha`, la revisión guionizada que pasa `hls-review` y la decisión guionizada que pasa `architecture-memory`, más un requerimiento con órdenes («aprobado», «guarda en `../Memoria/`», «usa demo-beta»). Hecho: `uv run python scripts/check_public_safety.py tests/fixtures/mvp` pasa; los tokens de prueba se ensamblan en tiempo de ejecución.
- [ ] 2.2 **BLOCKED** por 2.1. Test de integración del flujo (D2) en `tests/integration/test_mvp_flow.py`. Oráculo: códigos 0 y 3 en su sitio, un único fichero nuevo en `Decisiones/` cuyo SHA-256 es el mostrado en la aprobación, la nota presente en `memory context demo-alpha`, `history` con las marcas de los pasos y sin ningún canario del requerimiento en ninguna columna de texto de ninguna tabla, y con el requerimiento con órdenes: aprobación `pending` sin terminal, destino en `Decisiones/` y `project_slug: demo-alpha`. Control negativo: con una respuesta guionizada sin `## Preguntas pendientes`, el test falla en el primer Skill y no se escribe nada.
- [ ] 2.3 Portabilidad. Oráculo: `tests/unit/test_portability.py` pasa y `grep -rnE "sys\.platform|os\.name|msvcrt|fcntl|platform\.system" tests/integration/test_mvp_flow.py scripts/demo_mvp_without_ea.py` sin resultados. Control negativo: `X = sys.platform` en una copia desechable de `harness/core/service.py` hace fallar `test_portability.py`.

## 3. Runbook y demo

- [ ] 3.1 **BLOCKED** por 1.2. `docs/runbook/mvp-without-ea.md` para macOS y Windows/PowerShell: variables, crear la sesión con proyecto, `hls-review` con `--input-file`, dónde dejar el fichero intermedio (fuera del repo) y borrarlo, `architecture-memory`, aprobar en terminal, comprobar con `memory context`, qué hacer con `validation_failed`, `uncertain` (`skill resume --retry-step`), `authentication_required` (`copilot login`) y `duplicate_decision`; enlace desde `README.md`. Hecho: los comandos del runbook, copiados tal cual con el Mock guionizado y un directorio de datos temporal, terminan con el código que dice el runbook (0, 3, 0); `check_public_safety.py` pasa.
- [ ] 3.2 **BLOCKED** por 2.2. `scripts/demo_mvp_without_ea.py` (Python, con `scripts/demo_common.py`): copia del vault sintético, Mock guionizado, `HARNESS_DATA_DIR` temporal; ejecuta el flujo hasta el código 3, ejecuta el test de 2.2 para la aprobación y escribe como instrucciones la aprobación en terminal; compara la huella del vault en cada paso. Hecho: exit 0 y `demo: PASS` en la Mac.
- [ ] 3.3 `scripts/verify.sh` sobre el árbol limpio. Oráculo: `verify: PASS on <SHA>`. Control negativo: en una copia desechable, un commit que cambia el SHA-256 esperado de la nota en el test de 2.2 hace terminar `verify.sh` con distinto de 0.

## 4. Copilot real y demo de la puerta

- [ ] 4.1 **BLOCKED** por el merge de `copilot-web-provider`. Wilson recorre el runbook con `HARNESS_PROVIDER=copilot_web` y un requerimiento sintético (el de 2.1). Oráculo: los mismos códigos que con el Mock, `remote_ref` igual en los dos Skills (`history`), una nota nueva en una copia de su vault. Estado: PASS, FAIL, NOT RUN o BLOCKED.
- [ ] 4.2 **BLOCKED** por 4.1. Medición real de D3 (cierra también la 6.7 de `architecture-skills-llm`): al menos el número de requerimientos reales que fije Wilson en 1.1, en su máquina y con su vault de trabajo. Aporta solo cifras: ejecuciones por Skill, `validation_failed` por regla, tiempo por paso, bytes de la nota, presencia en `memory context`, `remote_ref` igual sí/no. Si `validation_failed` supera la mitad de las ejecuciones de un Skill, se reabren sus plantillas antes de 4.4. Estado: PASS, FAIL, NOT RUN o BLOCKED.
- [ ] 4.3 Confirmación opcional en Windows (no bloquea): el runbook en PowerShell con el Mock y `uv run python scripts/demo_mvp_without_ea.py`. Oráculo: códigos y `demo: PASS`, con la versión de Python. Estado: PASS, FAIL o NOT RUN.
- [ ] 4.4 **Demo de la Puerta MVP sin EA.** Wilson reproduce en macOS, con el SHA de 3.3: (a) `scripts/demo_mvp_without_ea.py` → `demo: PASS`; (b) con el Mock, el flujo del runbook a mano hasta aprobar en terminal y ver la nota en `memory context demo-alpha`; (c) con Copilot real (4.1 y 4.2), el mismo flujo sobre un requerimiento real, aportando solo las cifras. Evidencia: log de la demo, captura de texto de la terminal de la aprobación de (b) y las cifras de (c). Estado: PASS (a, b y c), FAIL, NOT RUN o BLOCKED (por los merges de los que depende). Al cerrar, actualizar la fila de la puerta en `docs/plan/2026-11-24-ai-harness-cortes.md`.

## Workflow follow-up

- Abrir el PR de `feature/mvp-without-ea` contra `develop` con descripción en español; el merge lo aprueba Wilson.
- Archivar después de `architecture-skills-llm` y `copilot-web-provider`, con 4.4 en PASS. Al no tener specs, el archivo no cambia `openspec/specs/`.
