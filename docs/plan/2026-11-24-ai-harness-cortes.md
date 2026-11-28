# Plan de entregas por cortes (2026-11-24)

Aprobado por Wilson el 2026-11-24. Parte de `AI-HARNESS-PLAN.md` v0.4 (copiado en esta carpeta como referencia). Este fichero manda sobre las fases F00–F09 del plan maestro hasta la Puerta MVP.

**Desde el 2026-11-27, el orden de trabajo lo da [`2026-11-27-plan-por-hitos.md`](2026-11-27-plan-por-hitos.md).** Este fichero sigue siendo el registro de los cortes: su change, dónde se demuestra, sus SEC, su riesgo y su estado. Las listas «Orden de lo que queda» y «Orden nuevo de lo que queda» de las revisiones de abajo se conservan como historia, pero ya no mandan. El estado de cada corte y los cortes nuevos están en la tabla y en la sección [Revisado el 2026-11-27: plan por hitos](#revisado-el-2026-11-27-plan-por-hitos).

**Revisado el 2026-11-25 (Wilson):** Enterprise Architect queda en pausa y se añade una puerta intermedia, la **Puerta MVP sin EA**. El estado real de cada corte, la puerta nueva y el orden de lo que queda están en la sección [Revisado el 2026-11-25 (Wilson)](#revisado-el-2026-11-25-wilson). La tabla de cortes conserva los cortes de EA, marcados en pausa, para que retomarlos no exija arqueología.

## Norte

El **MVP de punta a punta**: Wilson da un requerimiento, el harness recupera el contexto del proyecto en la memoria, lee el modelo de Enterprise Architect, pide una propuesta a Copilot Web, Wilson la aprueba, el harness crea el diagrama editable en el repositorio de pruebas, lo verifica releyéndolo y registra la decisión.

*Revisado el 2026-11-25:* el Norte no cambia, pero hasta que Wilson tenga EA instalado el objetivo intermedio es la **Puerta MVP sin EA**: requerimiento → memoria del proyecto → Copilot real → revisión HLS → decisión aprobada y guardada en el vault.

## Decisiones de partida

- Todo funciona en macOS y en Windows salvo Enterprise Architect, que usa COM y vive en un servidor MCP separado, solo Windows. Fuera de EA no hay código condicionado por plataforma: lo que pasa los tests en la Mac es lo que corre en Windows, y una ejecución en Windows es una confirmación opcional, no la puerta de un corte (Wilson, 2026-11-24).
- El repositorio es público: nada real ni identificable entra en él (`SECURITY.md`); lo medido sobre sistemas reales vive en `HARNESS_DATA_DIR`.
- Wilson tiene Windows + Edge + Copilot corporativo y permiso para automatizar Copilot Web (declarado el 2026-11-24). De EA tiene una versión demo: que permita Automation se mide con una sonda al abrir el Corte 5. *Revisado el 2026-11-25:* Wilson no tiene EA instalado; la sonda no se ha ejecutado (ver la revisión).
- El primer valor real es Copilot en varias conversaciones (Corte 2). Es también el riesgo técnico mayor y por eso va antes que MCP y Skills.
- Cada pieza de infraestructura nace en el corte que la usa: aprobaciones con la primera escritura (Corte 4), cliente MCP y políticas con EA (Corte 5). Los Skills se ejecutan en secuencia lineal, sin DAG.
- La seguridad no es una fase: cada SEC-xx del plan maestro se prueba en el corte que abre esa superficie.
- Solo datos sintéticos en el repo y en los agentes. Wilson prueba con lo real en local.
- No hay `docs/progress.md`: el estado vive en `tasks.md` de cada change. `docs/adr/` queda para decisiones transversales.

## Cortes

Cada corte es demostrable por separado. Hecho = Wilson lo reproduce con el SHA indicado. Entre paréntesis, la fase del plan maestro. La columna «Estado» se añadió el 2026-11-25 y se revisó el 2026-11-27 sobre `develop` = `a9c51fe`; las demás columnas son las aprobadas el 2026-11-24, salvo las filas marcadas como nuevas. «Cerrado» quiere decir archivado con su demo; un change en `develop` con la demo pendiente está «en `develop`, sin cerrar».

| Corte | Lo que Wilson ve y reproduce | Change(s) | Dónde | SEC | Riesgo | Estado (2026-11-27) |
|---|---|---|---|---|---|---|
| 0 · Base (F00) | Repo con uv + Python 3.14, OpenSpec personalizado, este plan y `scripts/verify.sh` | — | Mac | — | N0 | Cerrado, publicado en `v0.1.0` |
| 1 · Esqueleto (F01) | `session create/list`, `ask`, `history` con mock: tres sesiones aisladas, historial tras reinicio, solicitud interrumpida → `uncertain` | `session-core` | Mac y Windows | 02, 07, 08 | N1 | Cerrado, archivado, publicado en `v0.1.0` |
| 2 · Copilot (F04) | `ask` contra Copilot Web real en tres conversaciones, reinicio y recuperación de identidad, login vencido pide intervención, timeout tras envío → `uncertain` sin reenvío. Empieza con una sonda que mide selectores y señal de fin de respuesta en la UI real | `copilot-web-provider` | Mac y Windows, Edge con perfil dedicado | 06, 07, 10 | N2 | En `develop`, sin cerrar: probado en macOS contra la página real con cuenta de prueba; abiertas 5.4 (tests reales), 7.3, 7.4 (Windows, opcional) y 7.5 (demo) |
| 3 · Memoria (F05) | `memory search`, `memory context`, `ask --project` con contexto acotado, `memory maintain --dry-run`; vault sintético compatible con `claude-memory-system` | `project-memory` | Mac y Windows | 01, 03, 04, 13 | N1 | Cerrado, archivado, publicado en `v0.1.0` (medición sobre el vault real: NOT RUN) |
| 4 · Skills sin herramientas (F03, parte de F07) | `skill list/show/run/status/resume`; `hls-review` y `architecture-memory` con pasos llm / validate / approval. Aprobaciones por hash exacto, con expiración y uso único | `skill-engine`, `architecture-skills-llm` | Mac y Windows | 12, 14, 15 | N1 | En `develop`, sin cerrar: `skill-engine` (demo 7.7 pendiente) y `architecture-skills-llm` (abiertas 6.7, medición con Copilot real, y 6.8, demo) |
| 5 · EA lectura (F02 mínima, F06.1–2) | Sonda COM sobre el modelo demo; cliente MCP y políticas deny-by-default; `ea_list_packages`, `ea_list_diagrams`, `ea_get_diagram`, `ea_get_element` desde la CLI | `mcp-gateway`, `ea-read` | Solo Windows | 05, 09, 10 | N2 | `mcp-gateway` en `develop`, sin cerrar (demo 5.4 pendiente). `ea-read` **EN PAUSA** (sin EA) |
| 6 · EA escritura en pruebas (F06.3–4) | `ea_preview_diagram` y `ea_create_test_diagram`: cuatro componentes y tres relaciones, verificados releyendo el modelo; la escritura al target productivo se deniega | `ea-test-write` | Solo Windows | 11, 12 | N2 | **EN PAUSA** (sin EA) |
| **9 · Interfaz conversacional** (nuevo, 2026-11-25) | `main.py` o `main.py chat`: se entra una vez y se conversa; preguntas, comandos con barra (`/new`, `/resume`, `/history`, `/context`, `/skill`, `/file`…), aprobación dentro de la conversación, Ctrl+C interrumpe la pregunta sin reenviar y sin cerrar | `interactive-shell`, `shell-appearance`, `shell-tui`, `collapsible-blocks`, `approval-buttons`, `command-completion`, `tui-spacing`, `reply-rendering`, `code-mode` | Mac; Windows como confirmación opcional | 02, 07, 12, 15 | N1 | En `develop`, sin cerrar: la conversación a pantalla completa y, de `code-mode` (el «experimento de agente»), los tramos 1 y 2 (`/plan` de solo lectura). Las lecturas por regla y el lazo con vueltas (A2 y A3) están en curso, sin fusionar. Demos pendientes (`interactive-shell` 7.6 y las de cada change) |
| **10 · Economía del prompt** (nuevo, 2026-11-26) | `memory context` con cabeceras de nota cortas y el aviso de respuesta concisa; `architecture-memory` pide el JSON en una sola línea; diseño de la memoria por deltas dentro de una conversación remota | `prompt-economy` | Mac; Windows como confirmación opcional | 03, 15 | N1 | En `develop`, sin cerrar: puntos 1–3 implementados; el 4 (deltas, tareas 5.x) solo diseñado; el Corte 2 ya está en `develop` |
| **11 · Modo de respuesta** (nuevo, 2026-11-27) | `/mode auto\|quick\|deep` y `ask --mode`: el modo se recuerda por sesión, se pone y se confirma en la página antes de enviar, se ve en el panel y en el historial; la sonda mide el selector sin enviar | `response-mode` | Mac; Windows como confirmación opcional | 02, 07 | N2 | En `develop`, sin cerrar: implementado contra la página sintética; abiertas 8.1 (medida del selector real con el dueño) y 8.2 (demo) |
| **12 · Herramientas de la carpeta de trabajo** (nuevo, 2026-11-27) | `/workspace <ruta>` elige la carpeta; `read`, `list`, `glob` y `grep` confinados a ella; `write` y `edit` con el diff exacto y una aprobación por hash; `/undo` del último cambio | `workspace-tools` | Mac; Windows como confirmación opcional | 01, 03, 04, 05, 07, 08, 12, 15 y una fila nueva | N1 (lecturas) y N2 (escrituras) | En curso, sin fusionar: propuesta y primer tramo (carpeta, confinamiento, `read` y `list` por la CLI) en `feature/workspace-tools`. Hito 2 del plan por hitos |
| **13 · Ejecución de código aprobada** (nuevo, 2026-11-27; su propuesta lo llama «Corte 11», ver la revisión del 2026-11-27) | `/run [n]` toma un bloque de código de la última respuesta y lo ejecuta tras una aprobación ligada al hash exacto, con plazo y tope de salida; la salida se muestra como texto ajeno y no vuelve al modelo | `code-run` | Mac; Windows como confirmación opcional | 01, 03, 04, 07, 08, 12, 15 y la nueva 16 | N2 | Solo la propuesta y las decisiones del dueño, en `feature/code-run`, sin fusionar. Hito 2 del plan por hitos |
| **Puerta MVP sin EA** (nueva, 2026-11-25) | Requerimiento → memoria del proyecto → Copilot real → revisión HLS → decisión aprobada y guardada en `Decisiones/` del vault; demo con el Mock y demo manual con Copilot real | `mvp-without-ea` | Mac; Windows como confirmación opcional | 01, 03, 06, 07, 12, 13 | N2 | En `develop`, sin cerrar: la demo con el Mock pasa; abiertas 4.1–4.4 (la medición con Copilot real y la demo), ya sin bloqueo |
| **7 · Puerta MVP** (F07) | `architecture-diagram` de punta a punta y `architecture-impact` | `architecture-skills-ea` | Windows | 03 | N2 | **EN PAUSA** (sin EA) |
| 8 · Cierre (F09 y resto) | Matriz SEC-01..15 completa con recibos, runbook, backup y restauración, curador y Sueño asistidos, MCP Server propio del harness | `hardening`, `memory-curation`, `harness-mcp-server` | Mac y Windows | todas | N1 | Revisado el 2026-11-25: `harness-mcp-server` y la parte de `hardening` que no depende de EA (sin copia y restauración, aplazada por ser un proyecto educativo) se adelantan y van en paralelo a la Puerta MVP sin EA; `memory-curation` sigue después del MVP. *Revisado el 2026-11-27:* `hardening` en `develop`, sin cerrar (demo 7.5 pendiente); `harness-mcp-server` sin empezar (0 de 34 tareas), como deuda transversal; `memory-curation` pasa al Hito 3 del plan por hitos |

Los cortes 3–4 no dependen de 5–6: si EA bloquea, se sigue por memoria y Skills.

## Fuera del alcance hasta después del MVP

- Computer Use (F08).
- Sugerencia de Skill por IA y scripts externos dentro de un Skill.
- Ejecución nocturna del Sueño.
- Escritura en cualquier repositorio de EA que no sea el de pruebas.
- Interfaz gráfica, despliegue multiusuario, extracción de tokens o APIs privadas.

## Dependencias externas

- Licencia de EA con Automation Interface y un modelo local de pruebas. Bloquea los cortes 5–7. *Revisado el 2026-11-25:* Wilson no tiene EA instalado; los cortes 5 (segunda mitad), 6 y 7 quedan en pausa hasta que lo tenga.
- Tipo de conexión y credenciales de solo lectura del repositorio corporativo de EA. Bloquea la lectura real del Corte 5, no su desarrollo contra el modelo demo.
- Política corporativa de retención: decide si el contenido real de las conversaciones se persiste en SQLite. Se resuelve en el Corte 2. *Revisado el 2026-11-25:* el Corte 2 la resolvió tomando la opción que no necesita la política: el contenido real no se guarda.
- *Añadida el 2026-11-25:* alcance de la autorización para automatizar Copilot Web. Las condiciones de los Online Services de Microsoft para empresas prohíben usar «scraping or other data extraction methods» sobre el servicio; Wilson declara estar autorizado y se le ha pedido que confirme el alcance. Bloquea exponer Copilot a través del servidor MCP propio (`harness-mcp-server`), no su desarrollo con el Mock.

## Reglas del plan

- Si un corte falla: 4 h de diagnóstico y después se replantea el alcance con Wilson.
- Un corte con integración real no se cierra si solo pasó con mocks.
- No hay fechas: se estima al abrir cada corte y se reestima tras el Corte 2, que es el riesgo técnico mayor.

## Revisado el 2026-11-25 (Wilson)

### Decisiones de Wilson

1. **Enterprise Architect en pausa** hasta que lo tenga instalado. `ea-read` (segunda mitad del Corte 5), el Corte 6 y el Corte 7 original quedan **bloqueados, no cancelados**. Nada se borra: los artefactos de `ea-read` siguen en `openspec/changes/ea-read/` con una nota de pausa, y las filas de la tabla siguen ahí.
2. **Objetivo intermedio: Puerta MVP sin EA**, un flujo completo que no depende de EA y que se demuestra en macOS (Windows, confirmación opcional). Usa los cortes 2 y 4.
3. **En paralelo:** el servidor MCP propio del harness (`harness-mcp-server`) y el cierre y endurecimiento que no depende de EA (`hardening`). Ninguno de los dos espera ya a EA.
4. La integración con OpenCode se estudió y Wilson la descartó el 2026-11-25: sigue con el piloto del harness.
5. **El proyecto es educativo:** sirve para aprender a construir un harness, no para producción. Desde el 2026-11-25 guía el alcance: se conserva lo que más enseña (las propiedades de seguridad nunca se aplazan) y se aplaza lo que solo tiene sentido en producción, como la copia y restauración de `HARNESS_DATA_DIR`.

Decisiones vigentes que no cambian: repo público; sin código por plataforma fuera del paquete de EA; Windows no es puerta; sin perfiles; demos en Python; solo biblioteca estándar, pydantic y las dependencias ya aprobadas (`mcp==2.3.0`, `playwright`); la aprobación conserva su límite documentado (no prueba que haya una persona delante); git flow.

### Estado real de cada corte (sobre `develop` = `86f1079`)

- **Cortes 0, 1 y 3:** cerrados, con `session-core` y `project-memory` archivados en `openspec/specs/`, y publicados en `v0.1.0` (`main` = `d368143`). Queda abierta, aplazada y NOT RUN, la medición sobre el vault real de Wilson (Workflow follow-up de `project-memory`).
- **Corte 2:** en curso en `feature/copilot-web-provider`, sin mergear. La sonda se midió en macOS (forma de la referencia de conversación, reapertura 3/3, tiempos). Falta el `ask` del proveedor (grupos 4–7 de sus tareas). Un navegador a la vez tras un bloqueo con nombre, lanzado por pregunta; el contenido real no se guarda.
- **Corte 4:** `skill-engine` mergeado en `develop` y sin archivar (abiertas 7.6, Windows opcional, y 7.7, demo de Wilson). `architecture-skills-llm` en curso en su rama: tareas de implementación hechas, revisión independiente en marcha, abiertas 6.6 (Windows), 6.7 (medición con Copilot real, BLOCKED por el Corte 2) y 6.8 (demo).
- **Corte 5:** `mcp-gateway` mergeado en `develop` y sin archivar (abiertas 5.3, Windows opcional, y 5.4, demo de Wilson). `ea-read`: solo la sonda escrita; **EN PAUSA**.
- **Cortes 6 y 7:** sin empezar; **EN PAUSA**.
- **Corte 8:** se parte en dos. Lo que no depende de EA (`hardening` sin SEC-11 ni la parte de COM de SEC-10, y `harness-mcp-server`) se planifica ya. `memory-curation` (curador y Sueño asistidos) sigue después del MVP.

### Puerta MVP sin EA

- **Lo que Wilson ve y reproduce:** en una sesión con proyecto, `hls-review` sobre un documento de requerimiento con el contexto del proyecto, contra Copilot real; después `architecture-memory` extrae la decisión, Wilson la aprueba en terminal y la nota queda en `Decisiones/` del vault, visible en `memory context` del proyecto. Primero con el Mock (demo en Python, sin persona salvo la aprobación) y después a mano con Copilot real sobre contenido real, aportando solo cifras.
- **Evidencia:** log de `scripts/demo_mvp_without_ea.py` con `demo: PASS` y el SHA; captura de texto de la terminal de la aprobación; las cifras de la ejecución real (ejecuciones, `validation_failed` por regla, tiempos por paso, bytes de la nota) sin contenido.
- **SEC que cubre de punta a punta:** 01, 03, 06, 07, 12 y 13, ya probados por separado en sus cortes; la puerta comprueba que siguen valiendo encadenados y con el proveedor real.
- **Dependencias:** merge de `copilot-web-provider` (Corte 2) y de `architecture-skills-llm` (segunda mitad del Corte 4). Change: `mvp-without-ea`.
- **Plataformas:** macOS es la puerta; Windows, confirmación opcional.

### Orden de lo que queda

1. Terminar y mergear `copilot-web-provider` y `architecture-skills-llm` (en curso).
2. En paralelo, sin esperar a 1: `harness-mcp-server` con el Mock (las herramientas que preguntan a Copilot real quedan BLOCKED por el merge del Corte 2 y por la confirmación de Wilson del alcance de la autorización) y `hardening` (matriz SEC viva, runbook de instalación y uso, guía de diagnóstico, deuda conocida).
3. `mvp-without-ea`: la integración, la demo con el Mock y la demo manual con Copilot real, cuando 1 esté mergeado.
4. Archivar los changes mergeados con su demo en PASS (`skill-engine`, `mcp-gateway`, después `architecture-skills-llm` y `copilot-web-provider`).
5. EA (cortes 5 segunda mitad, 6 y 7) cuando Wilson lo tenga instalado.

### Qué queda fuera ahora

- Todo lo que necesita EA: `ea-read`, `ea-test-write`, `architecture-skills-ea` (`architecture-diagram`, `architecture-impact`), SEC-11 y la parte de COM de SEC-10.
- `memory-curation` (curador y Sueño asistidos), Computer Use, sugerencia de Skill por IA.
- Copia y restauración de `HARNESS_DATA_DIR` y cualquier tarea que solo sirva para operar en producción (proyecto educativo).
- Guardar contenido real de Copilot y cifrar SQLite.
- Escribir en el vault desde el servidor MCP (`memory_save_decision`): no entra en la primera versión de `harness-mcp-server` (ver su design).

### Cómo retomar EA

Cuando Wilson tenga EA instalado: ejecutar la tarea 1.2 de `ea-read` (la sonda, siguiendo `docs/runbook/enterprise-architect.md`), retirar la nota de pausa de su `tasks.md` y su `proposal.md`, y seguir sus tareas tal como están. `mcp-gateway`, del que depende, ya está en `develop`. Después, los cortes 6 y 7 en el orden de la tabla; la Puerta MVP original sigue siendo la del Norte.

## Revisado el 2026-11-25 (Wilson): Corte 9 · Interfaz conversacional

Wilson decidió el 2026-11-25 que el harness se use como una conversación, al estilo de Codex, Claude Code y OpenCode: se entra una vez, se escriben preguntas y comandos con barra y las aprobaciones se piden ahí mismo. Es el **Corte 9** (`interactive-shell`, riesgo N1, SEC-02, 07, 12 y 15; macOS como puerta y Windows como confirmación opcional) y va **antes** de la Puerta MVP sin EA, para que la demo de esa puerta sea ya una conversación. Su alcance es solo el bucle conversacional sobre lo que existe: sin paneles ni colores, sin texto que aparezca poco a poco, sin bucle de agente y sin llamadas MCP desde la conversación.

### Orden nuevo de lo que queda

1. **Interfaz conversacional** (`interactive-shell`, Corte 9), en curso. En paralelo siguen `copilot-web-provider` y `architecture-skills-llm` hasta su merge.
2. **Puerta MVP sin EA** (`mvp-without-ea`), con su demo manual dentro de la conversación.
3. **Apariencia** (change posterior): paneles, colores, barra de estado, edición de línea; decide si se añade una librería de terminal.
4. **Experimento de agente:** que el modelo proponga y ejecute herramientas (bucle de agente), con las mismas aprobaciones.
5. **Endurecimiento** (`hardening`): sus guías de uso esperaban a esta interfaz.

Este orden sustituye a los puntos 2 y 3 de «Orden de lo que queda» de la revisión anterior en lo que se refiere a `hardening` y `mvp-without-ea`; `harness-mcp-server` y EA no cambian de sitio. Mantener Edge abierto durante una conversación se hace en `copilot-web-provider` (su D3), con el contrato de apertura y cierre que define `interactive-shell`.

## Revisado el 2026-11-26 (Wilson): Corte 10 · Economía del prompt

El estudio `docs/estudios/2026-11-26-formato-compacto-para-copilot.md` midió que ningún formato más corto que JSON compensa y que el ahorro está en otra parte. Wilson decidió el 2026-11-26 guardar el estudio y aplicar cuatro ahorros, que forman el **Corte 10** (`prompt-economy`, riesgo N1, SEC-03 y SEC-15; macOS como puerta y Windows como confirmación opcional): JSON de `extract` en una sola línea, cabeceras de nota cortas, aviso de respuesta concisa en las preguntas sueltas y, solo diseñada, la memoria por deltas dentro de una misma conversación remota. Las tres primeras van en paralelo a lo que queda; la cuarta se implementa después del merge de `copilot-web-provider` (Corte 2), que cambia los mismos puntos de `harness/core/service.py`. No cambia el orden de la revisión anterior.

## Revisado el 2026-11-27 (Wilson): Corte 11 · Modo de respuesta

Wilson decidió el 2026-11-27 que el modo de respuesta de Copilot (automático, rápido, profundo) se elige desde el harness con un comando de sesión, `/mode auto|quick|deep`, visible en el panel lateral y recordado por sesión, y que el harness confirma en la página que el modo está puesto antes de enviar. Forma el **Corte 11** (`response-mode`, riesgo N2 porque el harness hace clic en un control de la página real, SEC-02 y SEC-07; macOS como puerta y Windows como confirmación opcional). Se implementa contra la página sintética; el selector real lo mide la sonda (`copilot_probe.py response-mode`, sin enviar nada) con el dueño, y la demo con Copilot real queda pendiente de esa medida. No cambia el orden de la revisión anterior.

## Revisado el 2026-11-27: plan por hitos

El dueño aprobó el 2026-11-27 un plan nuevo, [`2026-11-27-plan-por-hitos.md`](2026-11-27-plan-por-hitos.md), con cuatro hitos: un lazo que funciona con Copilot real y no desespera, el agente de código, que aprenda en la segunda memoria y la rutina diaria. Desde esa fecha, **el orden lo da ese documento**. Este fichero conserva la tabla de cortes y su estado.

### Qué cambia aquí

- La columna «Estado» se revisó sobre `develop` = `a9c51fe`. Siguen cerrados solo los cortes 0, 1 y 3. Los cortes 2, 4, 9, 10 y 11, la primera mitad del 5, `hardening` y la Puerta MVP sin EA están en `develop` y no se cierran hasta que pase su demo.
- El Corte 9 recoge todos los changes de la conversación, también `code-mode`, que es la forma que tomó el «experimento de agente» (punto 4 de su orden).
- **Corte 12 · Herramientas de la carpeta de trabajo** (`workspace-tools`) y **Corte 13 · Ejecución de código aprobada** (`code-run`) entran en la tabla. Los dos son del Hito 2.
- `memory-curation` deja de esperar al MVP y entra en el Hito 3.

### La numeración del Corte 13

La propuesta de `code-run`, escrita en su rama, se llama a sí misma «Corte 11 · Ejecución de código aprobada». Ese número ya lo tenía `response-mode` (Corte 11 · Modo de respuesta), que está en `develop`. La propuesta de `workspace-tools` señala el choque y deja la numeración final al dueño.

En esta tabla, `code-run` es el **Corte 13**: `response-mode` conserva el 11 porque ya está fusionado y su tarea 8.2 lo cita, y `workspace-tools` conserva el 12 que ya se da. Cuando la rama de `code-run` se retome, su `proposal.md` (sección «Corte, riesgo, SEC y plataformas») y su tarea 1.3 deben decir «Corte 13»; hasta entonces, manda esta tabla.
