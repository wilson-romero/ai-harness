# Proposal

## Why

Hoy el harness tiene **1** proveedor registrado (`mock`, en `harness/providers/registry.py`), **0** caminos de código que escriban `sessions.remote_ref` y **0** que produzcan el estado `authentication_required` (medido el 2026-11-24 con `grep -rn` sobre `harness/` en `feature/session-core`, SHA `0c14f33`). Es decir: ninguna pregunta llega todavía a un modelo real, y nada sabe a qué conversación remota corresponde una sesión local. El Corte 2 es el primer valor real del producto y también su mayor riesgo técnico, porque depende de una interfaz web que nadie en esta sesión de planificación ha medido: no se conoce ni un selector, ni la forma de la URL de una conversación, ni la señal de fin de respuesta.

Corte **2 · Copilot** de `docs/plan/2026-11-24-ai-harness-cortes.md`. Riesgo **N2**. Cubre **SEC-06** (login o MFA vencido → intervención humana), **SEC-07** (timeout tras envío → `uncertain`, sin duplicación) y **SEC-10** (caída del navegador → recursos propios liberados). Se demuestra en **macOS**, con Edge y un perfil dedicado; Windows es una confirmación opcional de Wilson porque el diseño no tiene ningún camino de código distinto por plataforma (ver «Restricciones»).

## What Changes

- **Sonda** manual (`scripts/copilot_probe.py`) que Wilson ejecuta contra Copilot Web real, solo con prompts sintéticos fijos, y que mide: localizadores de los controles, forma de la referencia de una conversación, candidatos a señal de fin de respuesta, cómo se ve un login vencido, tamaño máximo de prompt aceptado y tiempos. Escribe su resultado **fuera del repo**, en `HARNESS_DATA_DIR`. Todo lo demás de este change va después de la sonda.
- Proveedor `copilot_web`: cada `ask` abre Edge con el perfil dedicado, recupera la conversación de la sesión (o abre una nueva la primera vez), envía el prompt, detecta la respuesta nueva y su final con las señales medidas, y cierra el navegador.
- Identidad remota: la sesión guarda la referencia de su conversación remota en cuanto se verifica; si tras un reinicio no se vuelve a encontrar, la sesión se cierra con un mensaje claro y nada se envía a otra conversación.
- Login vencido: la pregunta termina en `authentication_required` antes de enviar nada y se pide a Wilson que inicie sesión a mano con un comando nuevo `copilot login`. El harness nunca escribe en una página de login.
- Un solo navegador a la vez: las preguntas de sesiones distintas esperan su turno; dos procesos nunca abren el mismo perfil.
- Caída del navegador: antes del envío → `failed`; después → `uncertain`. Solo se cierra lo que el harness abrió.
- Retención: el contenido real **no** se guarda. `history` de una sesión de Copilot muestra estados, fechas y la referencia de la conversación, sin texto.
- Límites: tamaño máximo de prompt y plazo de respuesta, derivados de lo que mida la sonda.
- Pruebas automáticas contra páginas HTML sintéticas servidas en local; la aceptación real es una demo manual de Wilson con el marcador `copilot`.
- `README.md` y runbook del login manual y de la sonda.

**No entra**, aunque un lector lo supondría:

- Propuestas JSON de herramientas y tool calling (cortes 4 y 5), inyección de memoria (Corte 3), MCP en cualquier sentido.
- Persistir el texto real de prompts o respuestas, y cifrar SQLite: depende de la política corporativa de retención, que Wilson aún no ha aportado.
- Reconciliación automática del texto de una respuesta `uncertain`, reintentos o reenvíos de cualquier tipo.
- Navegador en segundo plano entre comandos, modo headless en real, varias cuentas, streaming de la respuesta a la terminal.
- Automatizar login o MFA, leer o exportar cookies, tokens, `storage_state`, endpoints privados o tráfico de red de Copilot.
- Usar el perfil personal o el de trabajo habitual de Edge, o cerrar procesos de Edge que el harness no lanzó.
- Instalar navegadores con `playwright install` (sobrescribe el Edge instalado en la ubicación global; documentado por Playwright).

## Restricciones

- **El repositorio es público.** No se versiona nada que identifique a la empresa o a su tenant: ni la URL real de Copilot, ni identificadores de tenant u organización, ni nombres de cuenta, ni localizadores capturados junto con atributos propios del tenant, ni capturas de pantalla, trazas de Playwright, ficheros HAR, vídeos o `storage_state`. La sonda escribe sus mediciones en `HARNESS_DATA_DIR` (ignorado por Git) y el proveedor las carga de ahí al ejecutarse. El repo solo contiene el código de la sonda, el **esquema** del fichero de medición y páginas de prueba sintéticas. El diseño no necesita ninguna excepción del guardián `scripts/check_public_safety.py` (llega en otra rama).
- **Sin caminos de código por plataforma.** Nada de ramas `sys.platform`, `os.name`, `msvcrt` o `fcntl` en el código de este change: solo `pathlib`, la API multiplataforma de Playwright y SQLite. Lo que pasa en el Mac es lo que corre en Windows. El bloqueo por sesión se usa como «existe un bloqueo por sesión», sin depender de cómo esté implementado (se está reescribiendo sobre SQLite en otra rama).

## Capabilities

### New Capabilities

- `copilot-ui-probe`: la sonda manual que mide la UI real de Copilot con contenido sintético, qué registra, qué no registra nunca y dónde deja el resultado.
- `copilot-web-provider`: preguntar a Copilot Web en una sesión: conversación remota por sesión y su recuperación tras reinicio, detección de respuesta completa, login vencido, `uncertain` tras envío sin reenvío, caída del navegador, retención sin contenido y límites.
- `dedicated-edge-browser`: el perfil dedicado de Edge y su protección, el login manual, un solo navegador a la vez entre procesos y la liberación de solo los recursos propios.

### Modified Capabilities

Ninguna. `openspec list --specs` devuelve «No specs found» y `ls openspec/specs` solo muestra `.gitkeep` (comprobado el 2026-11-24): no hay capacidad vigente que modificar.

**Dependencia declarada:** este change se apoya en las capacidades `llm-provider`, `session-management` y `request-recovery` del change `session-core`, que todavía no está archivado. No se escribe un delta `MODIFIED` contra ellas porque no existen en `openspec/specs/`. Todo lo que este change añade es aditivo y queda en sus propias specs: un proveedor nuevo seleccionable (no cambia «Proveedor seleccionable por configuración»), dos resultados nuevos propios de Copilot (`authentication_required` y `uncertain` por pérdida del navegador) y una sesión que pasa a `closed`, que `session-core` declara en su tipo pero no produce. La espera por el navegador es compatible con «Preguntas en sesiones distintas SHALL poder completarse»: se completan, una detrás de otra. Al archivar, si `session-core` ya está en `openspec/specs/`, se revisa que no haya contradicción; si la hubiera, se convierte en delta `MODIFIED` en ese momento.

## Impact

- Código nuevo: `harness/browser/` (perfil, lanzamiento, bloqueo del navegador), `harness/providers/copilot_web.py`, el esquema Pydantic del fichero de medición, `scripts/copilot_probe.py`, `tests/fixtures/copilot_ui/` (páginas sintéticas y su fichero de medición sintético), tests unitarios y de integración.
- Código tocado: `harness/providers/base.py` (el proveedor puede comunicar la referencia remota y la pérdida tras envío), `harness/core/service.py` (persistir `remote_ref`, estados `authentication_required` y `closed`), `harness/providers/registry.py`, `harness/config.py`, `harness/cli.py` (`copilot login`; `history` muestra la referencia remota). El Mock sigue igual en conducta.
- Dependencias: `playwright` (1.65.2, wheels `py3-none` para macOS y Windows, depende solo de `greenlet`, que publica wheels `cp314` para ambas; consultado en PyPI el 2026-11-24). Se añade en la tarea que lo usa, no en este change de planificación. Requisito de entorno: Microsoft Edge instalado; **en la Mac de desarrollo no está** (`/Applications`, `~/Applications` y Spotlight sin resultado, 2026-11-24).
- Configuración: `HARNESS_COPILOT_URL` y `HARNESS_EDGE_PROFILE` (ya en `.env.example`), más las que fije el diseño. Ninguna con valor real en el repo.
- Documentación: `README.md` (proveedor, retención, estados nuevos) y `docs/runbook/copilot.md` (login manual, sonda, demo).
