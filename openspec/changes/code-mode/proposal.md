# Proposal

## Why

Copilot Web no tiene llamadas a herramientas nativas: cada vuelta del bucle «una herramienta por turno» es un envío. Las cifras, con su origen:

- Un envío dentro de `main.py chat` cuesta **11,0–14,2 s** (`copilot-web-provider/design.md` D3, medido el 2026-11-26, macOS, página real, 3 preguntas).
- Una llamada MCP al servidor sintético cuesta **519 ms** dentro del harness (`docs/estudios/2026-11-27-code-mode.md` §2.1, medido el 2026-11-27, macOS arm64).
- Los envíos reales autorizados son **100** en total (`docs/runbook/mvp-without-ea.md`, `mvp-without-ea/tasks.md` 4.1).

Con N lecturas encadenadas, ese bucle gasta N + 1 envíos; un plan gasta 1. Para N = 5 son 6 envíos frente a 1 (cálculo del estudio, §2.2, sobre esas cifras; no es una medida). Además, los resultados intermedios no salen hacia Copilot.

El dueño decidió el 2026-11-27 (estudio, §10.1) que la forma sea un **plan JSON interpretado por el harness** (Monty no se adopta). Un plan de solo lectura se confirma con el **botón de aprobación** en la pantalla completa, ligado al hash exacto del plan, y con el código tecleado en el modo plano y en la CLI. En el primer corte, el resultado se muestra solo a la persona y **no** vuelve a Copilot. Es el «hueco central» de `docs/aprendizaje/fundamentos-de-un-harness.md` §14 y el nivel 5 de `docs/runbook/harness-funcional.md`.

**Corte.** Pertenece al **Corte 9 · Interfaz conversacional** de `docs/plan/2026-11-24-ai-harness-cortes.md`, punto 4 del orden, «Experimento de agente». Es la forma que toma ese experimento (decisión 6 del estudio, abierta, con (a) como opción de trabajo).

**Riesgo.**
- **N0** en el tramo 1 (este commit): una función pura, sin E/S, sin nada conectado.
- **N1** en el tramo 2: el harness ejecuta lecturas que propuso el modelo, con aprobación.
- **N2** en el tramo 5: escrituras.

**SEC que cubre:**
- **SEC-03:** un resultado no cambia lo que se llama;
- **SEC-05:** herramienta o argumentos fuera de la lista;
- **SEC-07:** `uncertain` nunca se analiza ni se reenvía;
- **SEC-12:** la aprobación está ligada al hash del plan;
- **SEC-14:** no se ejecuta código escrito por el modelo;
- **SEC-15:** tope de pasos, de tamaño y de profundidad.

**Plataformas.** Se demuestra en **macOS**. Windows queda como confirmación opcional; el código no tiene ramas por plataforma.

## What Changes

El change describe el code mode entero y lo entrega en **cinco tramos**. «Tramo» numera las entregas de este change; «corte» se reserva para `docs/plan/`.

1. **Lector del plan (este commit).** `harness/mcp/plan.py`: una función pura. Recibe el texto de la respuesta, el nonce de la pregunta y la lista local, y devuelve una de tres cosas:
   - un `Plan` validado y canónico, con sus bytes y su SHA-256;
   - un rechazo con un motivo de una lista cerrada;
   - «sin plan».

   `loads_strict` gana un `kind` por motivo y un `max_depth` más estricto. `checks.py` expone su lectura de vallas (`split_fences`). Nada se conecta a la conversación ni al servicio.
2. **`/plan` de solo lectura** con el Mock y el servidor MCP sintético:
   - el catálogo, generado desde la lista local;
   - el nonce por pregunta;
   - la aprobación con botón o con código;
   - la ejecución por la pasarela, con `plan_id` en `tool_calls` (migración numerada);
   - el resultado como texto ajeno, plegable y solo para la persona;
   - `scripts/demo_code_mode.py`.
3. **Sonda y medición con Copilot real:** unos 12 envíos del presupuesto de 100. Primero 1–2 de sonda de un bloque `json` largo; después 10 tareas sintéticas.
4. **El resultado vuelve al modelo** solo con una orden explícita (`/send`), con el presupuesto de envíos a la vista.
5. **Escrituras:** vista previa, lista exacta de efectos, hash y `Effect`. Solo cuando la pasarela acepte escrituras con aprobación.

**No entra en este change, aunque un lector lo supondría:**
- **Python, TypeScript, Monty ni WASM.** No se ejecuta código del modelo en ningún tramo.
- **Referencias entre pasos** (`$ref`), `for_each`, `select` ni `return`. El plan de la versión 1 es una lista de llamadas con argumentos literales (design D2). El estudio los esbozaba; aquí se aplazan hasta que la lista local declare la forma de cada resultado.
- **Reparación automática** de un plan mal formado, ni una segunda pregunta oculta al modelo.
- **Llamadas en paralelo**, bucles o un plan que pide otro plan.
- **Descripciones del servidor en el prompt.**
- **Escrituras antes del tramo 5**, y nada de EA.
- **En el tramo 1, nada visible para la persona:** ni `/plan`, ni prompt, ni migración.

## Capabilities

### New Capabilities

- `code-mode`: cómo se lee un plan de llamadas en la respuesta del modelo, qué se rechaza y por qué, qué se aprueba y cómo se ejecuta y se muestra. El tramo 1 implementa los requisitos de lectura; los de aprobación, ejecución y resultado son del tramo 2.

### Modified Capabilities

Ninguna capacidad de `openspec/specs/` cambia. Comprobado el 2026-11-27:
- `openspec list --specs` da solo `llm-provider`, `memory-*`, `project-context`, `request-recovery`, `secret-redaction` y `session-management`;
- `grep -rn "plan" openspec/specs` no encuentra ningún requisito sobre planes.

`tool-policy` (de `mcp-gateway`, sin archivar) dice que «la única forma de pedir una llamada es la CLI, ejecutada por la persona». El tramo 2 añade una segunda forma, un plan aprobado. Por eso este change lleva un delta **ADDED** en `tool-policy`, como hizo `approval-buttons` con `human-approval`. Al archivar, pasa a MODIFIED sobre «Ninguna superficie de entrada en este corte» y «Sin bucles ni recursión» (tarea de archivo).

## Impact

- **Código del tramo 1:**
  - `harness/mcp/plan.py`, nuevo;
  - `harness/core/strict_json.py`: `StrictJsonError.kind` y `max_depth`, sin cambiar ningún mensaje;
  - `harness/skills/checks.py`: `split_fences`, el mismo analizador con nombre público.
- **Tests del tramo 1:** `tests/unit/test_mcp_plan.py`, nuevo; `tests/unit/test_strict_json.py`, ampliado.
- **Tramo 2:**
  - `harness/mcp/commands.py`: la ejecución de una llamada, extraída para reutilizarla;
  - `harness/mcp/audit.py` y una migración (`plan_id`, posición, fila del plan);
  - `harness/shell/conversation.py` y `tui.py`: `/plan` y la caja de aprobación;
  - `scripts/demo_code_mode.py`;
  - `README.md`, `SECURITY.md`, `docs/runbook/harness-funcional.md` (nivel 5) y `docs/security/sec-matrix.md`.
- **Se apoya en ramas de interfaz en curso** (design, «Dependencias del tramo 2»): la tabla declarativa de órdenes `harness/shell/commands.py` con autocompletado, el espaciado de toda la interfaz, el pintado de respuestas y `/mode`. El tramo 1 no depende de ninguna.
- **Sin dependencias nuevas.** Sin SQL en el tramo 1.
