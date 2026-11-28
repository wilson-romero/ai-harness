# Proposal

## Why

Una pregunta a Copilot Web dentro de una conversación ya abierta tarda unos **11 s**, y casi todo es espera del harness, no de Copilot. Medido el 2026-11-26 en la página real, conversación trazada, tres preguntas de una palabra (`copilot-web-provider`, design D3, «Coste medido por pregunta»): por pregunta, cargar la dirección 0,4–0,8 s, esperar el chat listo 0,6 s, esperar a que la página deje de cambiar **3,6–4,1 s**, escribir y enviar 0,25 s, esperar el final de la respuesta **6,1 s**, que incluye la ventana de estabilidad medida de **4 s** (P4, 2026-11-24, macOS arm64: `stop_hidden` válida 12/12 con retraso medio 1217 ms; `text_stable_1000` no válida, 7 adelantos). Total 14,2 s la primera, 11,1 s y 11,0 s las siguientes.

Dos esperas se pueden quitar sin aflojar ninguna garantía:

- **Recargar y esperar 2 s sin cambios** antes de cada pregunta, aunque la pestaña retenida ya muestre la conversación de la sesión que acaba de responder.
- **La ventana de 4 s sin cambios** tras la señal de fin, que se eligió porque las ventanas cortas solas se adelantan. Una ventana corta **tras una señal estructural medida** es otra regla y hay que medirla.

Además hoy nadie ve en qué se va el tiempo de una pregunta: no hay desglose por fases.

**Corte.** Pertenece al **Corte 2** (`copilot-web-provider`, el proveedor de Copilot Web; ya en `develop`) como mejora suya; no abre un corte nuevo (el último número libre lo toma otra rama). Riesgo **N2**: cambia cuándo el harness confía en una pestaña de la página real y cuándo da una respuesta por terminada. Cubre **SEC-02** (una pestaña reutilizada nunca lleva la pregunta a otra conversación remota; toda guarda del camino lento sigue en el rápido), **SEC-06** (una pestaña que pasó a pedir inicio de sesión, o una página que sin ventana pide verificarse, se detiene sin escribir; el inicio de sesión siempre con ventana) y **SEC-07** (una sola pulsación por pregunta, sin reenvío; `uncertain` tras enviar igual que antes; nunca `completed` con una respuesta que aún crece). Se demuestra en **macOS** con la página sintética local; mismo código en Windows, confirmación opcional. **En esta rama no se abre la página real de Copilot ni el perfil real de Edge.**

## What Changes

1. **Tiempos por fases.** Cada pregunta registra la duración de cada fase (comprobación de la pestaña, navegar, chat listo, asentarse, historial, guarda, modo, escribir, enviar, inicio y fin de la respuesta, lectura, identificador, comprobaciones finales), el camino (recarga o pestaña reutilizada, y por qué se rechazó reutilizar), cómo terminó (ventana o señal) y el resultado. Solo duraciones y palabras fijas, nunca texto. Se guardan en `HARNESS_DATA_DIR/copilot/timings.jsonl` (sin migración), se ven con `history SESSION_ID --timings` y, con `HARNESS_COPILOT_TIMINGS=on`, como un aviso más de cada pregunta. El proveedor deja el último desglose en `last_timings` para la barra de progreso de otra rama.
2. **Sin recarga cuando es seguro.** Si la pestaña retenida es **de confianza** (definición exacta en el diseño, D2) se pregunta en ella sin navegar ni esperar los 2 s. Ante cualquier duda, el camino de siempre.
3. **Fin de la respuesta por señal positiva.** Con una regla medida en `ui.json` (`fast_end`: señal estructural + ventana corta de confirmación), la respuesta termina cuando la señal se vio ocupada tras enviar, luego libre sin interrupción, y el texto (leído como lo devuelve el proveedor) no cambió durante la ventana corta. Sin regla medida, o si no se cumple, decide la ventana larga de siempre. La regla solo actúa en los modos en que se midió, y tras cada fin por señal se vuelve a leer la respuesta: si creció o la señal volvió a ocupada, no se devuelve el texto corto, se sigue esperando y se cuenta como fin temprano (D7, tras la revisión independiente del 2026-11-28).
4. **Interruptores.** `HARNESS_COPILOT_FAST_END` (`on` por defecto, solo actúa si la sonda lo midió), `HARNESS_COPILOT_REUSE_TAB` (`off` por defecto aunque esté medida, porque sin recargar no ve una conversación borrada en otro sitio; D8) y `HARNESS_COPILOT_TIMINGS` (`off`). Sin medida nueva en `ui.json`, la conducta es exactamente la de hoy.
5. **Sin ventana, solo si se pide.** `HARNESS_COPILOT_HEADLESS=on` hace las preguntas sin ventana; apagado por defecto. El inicio de sesión y los pasos de descubrimiento de la sonda usan siempre ventana. Si sin ventana la página se comporta distinto, las guardas existentes lo rechazan (`authentication_required` o no lista) sin escribir nada.
6. **Un solo comando de medida.** `scripts/copilot_probe.py speed [--questions N] [--rounds 1|2] [--skip-headless]`: dice cuántos envíos hará y espera Enter; mide las reglas de fin rápido con seis prompts fijos (2 conversaciones × 6 = **12 envíos**, más 2 en `deep` si el modo está medido), cada respuesta leída otra vez 5 s después, y luego N preguntas fijas (N = 5 por defecto, 2 a 5) con las optimizaciones apagadas, N encendidas y N encendidas sin ventana (**3N envíos**): **27 envíos** por defecto (29 con `deep`); el mínimo que aún escribe las reglas son 10 (12 con `deep`). Imprime la tabla por fases de las tres variantes y escribe en `ui.json` solo lo que la medida confirmó.

**No entra**, aunque un lector lo asumiría:

- Medir la página real ni dar por verificadas las mejoras en Copilot real: la tarea de medida queda NOT RUN hasta que el coordinador ejecute `speed` con el dueño. Las cifras de esta rama son de la página sintética.
- Activar algo sin medida: un `ui.json` sin `fast_end` ni `tab_reuse` deja el comportamiento como hoy.
- Ver un cambio hecho en otro dispositivo que la pestaña abierta no muestra (una conversación borrada o un turno añadido que la página no pinta): el límite está escrito en el diseño y en el runbook, acotado por la inactividad máxima (120 s), y por eso la reutilización está apagada por defecto.
- Tocar `/status` de la conversación (`harness/shell/`): lo muestra otra rama con `last_timings`.
- Cambiar las banderas de arranque de Edge o su sandbox. Sin ventana, Playwright añade sus propias banderas de modo sin ventana (D5); ninguna más.
- Una migración: los tiempos van a un fichero aparte.

## Capabilities

### New Capabilities

- `copilot-turn-speed`: los tiempos por fases de una pregunta a Copilot Web, cuándo se pregunta en la pestaña retenida sin recargar, cuándo una respuesta termina por señal positiva, los interruptores, el modo sin ventana y el paso de medida `speed` de la sonda.

### Modified Capabilities

Ninguna. Comprobado el 2026-11-27 con `grep -rn -i "copilot\|pestaña\|ventana\|estabilidad\|headless\|recarg" openspec/specs`: **ninguna** coincidencia. El contrato del proveedor de `llm-provider` y `request-recovery` (estados `uncertain` y `timeout`, sin reenvío) sigue cierto sin cambios: este change no cambia qué estado resulta de cada fallo, solo cuánto se espera en el camino feliz. `copilot-ui-probe` y `copilot-web-provider` viven en un change sin archivar; lo nuevo del proveedor y de la sonda va en `copilot-turn-speed`, como hizo `response-mode`.

## Impact

- Código: `harness/providers/copilot_web.py`, `harness/providers/copilot_ui.py` (dos entradas opcionales de `ui.json`), un módulo nuevo `harness/providers/copilot_timings.py`, `harness/config.py`, `harness/browser/edge.py` (`from_settings(..., window=)`), `harness/browser/login.py` (una línea: siempre ventana), `harness/cli.py` (`history --timings`), `scripts/copilot_probe.py` (paso `speed`).
- Tests: página y servidor sintéticos (pausas con señal parpadeante, sin botón de parar, bloque tardío, seguimiento en vivo de la conversación, página distinta sin ventana), `tests/browser/test_copilot_turn_speed.py`, `tests/browser/test_copilot_speed_probe.py`, `tests/unit/test_turn_speed.py`.
- Documentación: `docs/runbook/copilot.md` (paso `speed`, variables), `.env.example`.
- Sin dependencias nuevas, sin migración.
- Ficheros compartidos con otras ramas: ninguno de `harness/core/service.py`, `harness/mcp/plan*.py` ni `harness/shell/`. `harness/cli.py`: solo el subcomando `history` (detalle en tasks).
