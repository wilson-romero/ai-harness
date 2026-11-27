# Proposal

## Why

La página de chat de Microsoft 365 Copilot Web tiene un selector del modo de respuesta (los nombres cambian: «Auto», «Quick response», «Think deeper»/«Deep», según lo que el dueño ve en su página). Hoy el harness no lo toca: cada pregunta sale en el modo en que esté la página, y nada en el registro dice cuál fue. Medido el 2026-11-27 sobre `develop` (`aa02081`):

- `grep -rn -i "mode" harness/providers/copilot_web.py harness/providers/copilot_ui.py` → **12** coincidencias y **ninguna** es un modo de respuesta (once son `model_validator(mode="after")`, `BaseModel` o `model_validate`; una, «model» en un comentario): el proveedor no conoce el selector.
- `ls harness/storage/migrations | wc -l` → **7** migraciones (001–007); `grep -rn -i "mode" harness/storage/migrations` → **1** coincidencia («model» en un comentario de la 006): **ninguna columna** guarda un modo.
- `grep -c -i "mode" tests/fixtures/copilot_ui/app.html` → **0**: la página sintética no tiene selector de modo y no hay dónde probarlo.

El dueño decidió el 2026-11-27: un comando de sesión `/mode auto|quick|deep`, visible en el panel lateral, recordado por sesión; el harness confirma en la página que el modo está puesto **antes** de enviar.

**Corte.** Nuevo **Corte 11 · Modo de respuesta** (2026-11-27), que este change añade a `docs/plan/2026-11-24-ai-harness-cortes.md`. Depende del Corte 2 (`copilot-web-provider`, en `develop`) y del Corte 9 (conversación). Riesgo **N2**: el harness hace clic en un control de la página real de Copilot, y un localizador equivocado podría tocar otro control. Cubre **SEC-02** (cambiar de modo no puede llevar la pregunta a otra conversación remota ni abrir una nueva) y **SEC-07** (un modo que no se confirma falla **antes** de enviar: ni `uncertain` ni reenvío; el plazo más largo de `deep` conserva `timeout` antes del envío y `uncertain` después). Se demuestra en **macOS** con el Mock y con la página sintética local; mismo código en Windows, cuya ejecución es confirmación opcional. **En esta rama no se abre la página real de Copilot.**

## What Changes

1. **Modo por sesión.** `sessions.response_mode` (`auto` por defecto) y, por solicitud, el modo pedido y el modo confirmado en la página (`requests.requested_mode`, `requests.confirmed_mode`), en la migración **008** (SQL literal).
2. **Comando y opción.** `/mode [auto|quick|deep]` en la conversación (pantalla completa y `--plain`) y `ask --mode auto|quick|deep` en la CLI. Cambiar de modo solo escribe en la base: no envía nada, no abre el navegador ni una conversación nueva.
3. **Interfaz mínima del proveedor.** `LLMRequest.mode` (por defecto `auto`); un método opcional `check_mode(mode)` con el que el proveedor dice si puede poner ese modo (sin él, solo `auto`); un argumento opcional `on_mode` con el que informa del modo que confirmó. El Mock admite los tres de forma determinista.
4. **Copilot Web.** Antes de escribir el prompt, el proveedor pone el modo con el control **medido** en `ui.json`, lo relee de la página y, si no puede confirmarlo, falla antes de escribir nada. Tras la respuesta lo relee otra vez: si la página cambió de modo sola, el registro dice el modo que realmente quedó. Sin medida del control, `quick` y `deep` se rechazan con un mensaje claro y `auto` deja la página como está.
5. **Sonda.** Un paso nuevo `scripts/copilot_probe.py response-mode` que, en la página real, registra la estructura del control (cómo se abre, los nombres accesibles y roles de las opciones, cómo se lee el modo actual) **sin enviar nada**, y la añade a `ui.json`.
6. **Plazo de `deep`.** `HARNESS_DEEP_REQUEST_TIMEOUT_S` (por defecto el triple de `HARNESS_REQUEST_TIMEOUT_S`) para las preguntas en `deep`.
7. **Visible.** El modo aparece en el panel lateral, en `/status`, en `/history` y en `history`.
8. **Página sintética.** `tests/fixtures/copilot_ui/app.html` gana un selector de modo opcional, en dos formas (menú con opciones marcadas; lista con la etiqueta en el botón) y con conductas de fallo (no cambia, cambia tarde, vuelve a otro modo tras la respuesta, abre otra conversación al elegir).

**No entra**, aunque un lector lo asumiría:

- Medir el control real ni dar por verificada la conducta en Copilot real: queda como tarea NOT RUN hasta que el coordinador ejecute la sonda con el dueño.
- Adivinar selectores, nombres de opciones o el mapeo de opciones a modos: vienen solo de la medida; el mapeo lo elige una persona al medir.
- Medir cuánto tarda una respuesta `deep` real (la sonda no envía): el plazo por defecto es una decisión justificada, no una medida.
- Cambiar el modo de los pasos de Skill con plazo propio: un paso con `timeout_s` declarado lo conserva aunque la sesión esté en `deep` (límite escrito en el diseño).
- Completar con Tab las palabras `auto|quick|deep` (otra rama cambia la tabla de completado).
- Cambiar las banderas de arranque de Edge o su sandbox.

## Capabilities

### New Capabilities

- `response-mode`: el modo de respuesta de una sesión, cómo se elige, cómo se pone y se confirma en el proveedor, qué se registra y se muestra, el plazo de `deep` y la medida del control.

### Modified Capabilities

Ninguna. Comprobado el 2026-11-27 con `grep -rn -i "modo\|mode\b\|HARNESS_REQUEST_TIMEOUT\|plazo" openspec/specs`: solo aparece la frase «de modo que» de `llm-provider`, el requisito «Solo modo de prueba» de `memory-maintenance` (otro sentido) y el requisito «Resultado distinto según el punto de fallo» de `llm-provider`, cuyos escenarios siguen ciertos con el plazo de `deep` (el plazo cambia de duración, no de semántica). «Mock determinista y sin red» sigue cierto: la misma pregunta en la misma sesión y el mismo modo da la misma respuesta. `copilot-ui-probe` y `copilot-web-provider` viven en un change sin archivar; lo nuevo de la sonda y del proveedor va en `response-mode`.

## Impact

- Código: `harness/core/contracts.py`, un módulo nuevo `harness/core/response_mode.py`, `harness/core/service.py`, `harness/config.py`, `harness/providers/base.py`, `harness/providers/mock.py`, `harness/providers/copilot_ui.py`, `harness/providers/copilot_web.py`, `harness/storage/repositories.py`, `harness/storage/migrations/008_response_mode.sql`, `harness/cli.py`, `harness/shell/app.py`, `harness/shell/conversation.py`, `harness/shell/parser.py` (una entrada de la tabla), `harness/shell/terminal.py` (un campo de `PanelState`), `harness/shell/tui.py` (una línea del panel), `scripts/copilot_probe.py`.
- Tests: página sintética y servidor (`tests/copilot_app.py`, que registra en qué modo estaba la página al recibir cada prompt), una medida sintética del control, pruebas del proveedor, del servicio, de la CLI, de la conversación, de la migración y de la sonda.
- Documentación: `README.md` (comando, opción y variable), `docs/runbook/copilot.md` (cómo medir el control), el plan de cortes (Corte 11).
- Sin dependencias nuevas. Migración 008.
- Conflictos esperados: `harness/shell/tui.py` y la tabla de comandos de `harness/shell/conversation.py`/`parser.py` (otras ramas en curso); los cambios ahí son mínimos y aditivos.
