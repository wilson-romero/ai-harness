# Design

## Context

Ver `proposal.md` para el porqué. Piezas que el flujo usa, todas sin cambiar:

- `session create --project`, `ask`, `history`, recuperación y `uncertain` (`develop`).
- `memory context` y el contexto del proyecto en los pasos `llm` con `"memory": "project"` (`develop`).
- Motor de Skills, aprobación en terminal, código 3, `skill resume` y reconciliación (`skill-engine`, en `develop`). Con un proveedor no sintético (Copilot), `skill run` con un paso `approval` exige terminal interactiva antes de la primera pregunta, y las salidas de los pasos no se guardan (D11 de `skill-engine`).
- `hls-review` (`llm` → `validate` markdown con seis encabezados) y `architecture-memory` (`llm` → `validate` JSON → `approval` con el efecto `vault.save_decision`), en `feature/architecture-skills-llm`.
- Proveedor `copilot_web` en `feature/copilot-web-provider`: un Edge por pregunta (mediana de arranque 4356 ms, n = 7), una conversación por sesión, contenido real nunca guardado, `HARNESS_REQUEST_TIMEOUT_S` recomendado 21 s por su sonda (macOS, 2026-11-24). Los pasos `llm` de los dos Skills declaran `timeout_s: 300`.

### Premisas sin medir (las mide una tarea)

- Que Copilot devuelva una revisión con los seis encabezados exactos y un JSON de decisión que pase el `validate` (tarea 4.2; es la 6.7 de `architecture-skills-llm`).
- Que dos Skills seguidos en la misma sesión de Copilot reutilicen la misma conversación remota (tarea 4.2: `remote_ref` igual antes y después; lo garantiza el diseño del Corte 2, no se ha ejecutado encadenado).
- Que el flujo funcione igual en PowerShell (tarea 4.3, opcional).

## Goals / Non-Goals

**Goals:** que Wilson pueda recorrer el flujo entero siguiendo un runbook, primero con el Mock y después con Copilot real, y que una demo y un test lo protejan de regresiones.

**Non-Goals:** conducta nueva; un Skill encadenado; automatizar la parte humana (leer la revisión, decidir, aprobar).

## Decisions

### D1 · Dos Skills en una sesión y una persona entre medias, no un Skill encadenado

- **Qué:** el flujo son dos ejecuciones en la misma sesión. La salida de `hls-review` sale por stdout; Wilson la lee, escribe la decisión que toma (o guarda la revisión en un fichero fuera del repo) y se la pasa a `architecture-memory` con `--input-file source=<fichero>`. El runbook dice dónde dejar ese fichero (fuera del repo, por ejemplo en `HARNESS_DATA_DIR/tmp/`) y que lo borre al terminar.
- **Por qué:** el plan maestro separa los dos Skills (revisión → preguntas pendientes; decisión → revisión humana → persistir), y decidir qué se registra es justo el juicio humano que el flujo quiere conservar. Con Copilot, `skill-engine` no guarda la salida de un paso, así que un Skill encadenado tendría que hacer las dos preguntas y la aprobación en un mismo proceso y en terminal: es posible con el motor actual (secuencia lineal de cinco pasos), pero convierte cualquier ajuste de una plantilla en un cambio de los dos flujos y no enseña nada que los dos Skills por separado no enseñen ya.
- **Alternativas rechazadas:**
  - Skill `mvp-decision` con `review` → `check` → `extract` → `check-json` → `save`: conducta nueva (spec, tests, hash, límites) para ahorrar un comando; la persona dejaría de decidir qué decisión sale de la revisión, porque el modelo extraería directamente.
  - Pasar la salida por una tubería (`hls-review | architecture-memory`): `architecture-memory` necesita la terminal para aprobar y el texto del modelo entraría sin que nadie lo leyera.
- **Impacto:** ninguna spec; runbook; tareas 2.1 y 3.1. Si Wilson prefiere el Skill encadenado, es un change propio con specs (decisión abierta 1).

### D2 · Qué prueba el test de integración y qué no

- **Qué:** un test por subprocesos (como `tests/integration/test_skill_cli_run.py`) con el Mock guionizado por `HARNESS_MOCK_RESPONSES`, una copia temporal del vault sintético y la terminal de prueba de `skill-engine` inyectada en la fase de aprobación (la parte en proceso que ya usan los tests de `architecture-skills-llm`): `session create --project demo-alpha` → `skill run hls-review` (código 0, seis encabezados) → `skill run architecture-memory` sin terminal (código 3) → aprobación → un fichero nuevo en `Decisiones/` con el SHA-256 mostrado → `memory context demo-alpha` lo incluye → `history` tiene las marcas de los pasos y ningún texto del documento.
- **Por qué:** fija que las piezas encajan (la nota que escribe uno la lee el otro; la sesión con proyecto sirve a los dos Skills) sin probar nada de Copilot.
- **Alternativas rechazadas:** un test con el proveedor de Copilot sobre la app sintética: los Skills ya lo cubren por separado en su rama y el flujo no añade conducta del proveedor.
- **Límite escrito:** el test no dice nada de si Copilot real cumple los formatos.
- **Impacto:** tarea 2.2.

### D3 · Medición real: solo cifras, regla de reapertura heredada

- **Qué:** Wilson ejecuta el flujo con Copilot real sobre al menos 3 requerimientos de su trabajo y aporta: ejecuciones de cada Skill, cuántas terminaron en `validation_failed` y en qué regla, tiempo por paso, bytes de la nota preparada, si la nota aparece en `memory context`, y si `remote_ref` fue el mismo en los dos Skills de cada sesión. Si `validation_failed` supera la mitad de las ejecuciones de un Skill, se reabren sus plantillas o reglas en `architecture-skills-llm` antes de cerrar la puerta (regla de su tarea 6.7).
- **Por qué:** «una integración real no se da por verificada con mocks»; el contenido real no sale de la máquina de Wilson.
- **Impacto:** tarea 4.2; cierra también la 6.7 de `architecture-skills-llm` (se anota el recibo en las dos).

## Risks / Trade-offs

- [Copilot no respeta los encabezados o el JSON] → `validate` falla de forma controlada sin escribir nada; la regla de D3 decide si se reabren las plantillas.
- [El fichero intermedio con contenido real queda en disco] → el runbook lo pone fuera del repo y pide borrarlo; el guard del repo público lo rechazaría si acabara dentro. No se automatiza.
- [Un login vencido a mitad del flujo] → `authentication_required` antes de enviar; el runbook dice que `copilot login` y repetir el paso no duplica nada.
- [Merge tardío de los dos changes de los que depende] → las tareas BLOCKED lo dicen; la parte con el Mock no avanza tampoco sin `architecture-skills-llm`, porque los Skills viven allí.

## Migration Plan

Sin migración: documentación, un test y una demo.

## Decisiones pendientes de Wilson (antes de implementar)

1. ¿Flujo en dos Skills con tu decisión entre medias (D1, propuesto) o un Skill encadenado (sería un change con specs)?
2. ¿Con cuántos requerimientos reales haces la medición de D3 (propuesta: al menos 3) y aceptas la regla de reapertura de la mitad?
3. ¿Confirmas el alcance de tu autorización para automatizar Copilot Web también para este flujo (dos preguntas por requerimiento en la misma conversación)?
