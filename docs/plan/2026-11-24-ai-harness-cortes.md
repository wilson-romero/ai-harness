# Plan de entregas por cortes (2026-11-24)

Aprobado por Wilson el 2026-11-24. Parte de `AI-HARNESS-PLAN.md` v0.4 (copiado en esta carpeta como referencia). Este fichero manda sobre las fases F00–F09 del plan maestro hasta la Puerta MVP.

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

Cada corte es demostrable por separado. Hecho = Wilson lo reproduce con el SHA indicado. Entre paréntesis, la fase del plan maestro. La columna «Estado» se añadió el 2026-11-25; las demás columnas son las aprobadas el 2026-11-24, salvo las filas marcadas como nuevas.

| Corte | Lo que Wilson ve y reproduce | Change(s) | Dónde | SEC | Riesgo | Estado (2026-11-25) |
|---|---|---|---|---|---|---|
| 0 · Base (F00) | Repo con uv + Python 3.14, OpenSpec personalizado, este plan y `scripts/verify.sh` | — | Mac | — | N0 | Cerrado, publicado en `v0.1.0` |
| 1 · Esqueleto (F01) | `session create/list`, `ask`, `history` con mock: tres sesiones aisladas, historial tras reinicio, solicitud interrumpida → `uncertain` | `session-core` | Mac y Windows | 02, 07, 08 | N1 | Cerrado, archivado, publicado en `v0.1.0` |
| 2 · Copilot (F04) | `ask` contra Copilot Web real en tres conversaciones, reinicio y recuperación de identidad, login vencido pide intervención, timeout tras envío → `uncertain` sin reenvío. Empieza con una sonda que mide selectores y señal de fin de respuesta en la UI real | `copilot-web-provider` | Mac y Windows, Edge con perfil dedicado | 06, 07, 10 | N2 | En curso en `feature/copilot-web-provider`: sonda medida en macOS; el `ask` del proveedor se está implementando |
| 3 · Memoria (F05) | `memory search`, `memory context`, `ask --project` con contexto acotado, `memory maintain --dry-run`; vault sintético compatible con `claude-memory-system` | `project-memory` | Mac y Windows | 01, 03, 04, 13 | N1 | Cerrado, archivado, publicado en `v0.1.0` (medición sobre el vault real: NOT RUN) |
| 4 · Skills sin herramientas (F03, parte de F07) | `skill list/show/run/status/resume`; `hls-review` y `architecture-memory` con pasos llm / validate / approval. Aprobaciones por hash exacto, con expiración y uso único | `skill-engine`, `architecture-skills-llm` | Mac y Windows | 12, 14, 15 | N1 | `skill-engine` mergeado en `develop` (sin archivar; demo 7.7 pendiente). `architecture-skills-llm` en curso en su rama, con correcciones de una revisión en marcha |
| 5 · EA lectura (F02 mínima, F06.1–2) | Sonda COM sobre el modelo demo; cliente MCP y políticas deny-by-default; `ea_list_packages`, `ea_list_diagrams`, `ea_get_diagram`, `ea_get_element` desde la CLI | `mcp-gateway`, `ea-read` | Solo Windows | 05, 09, 10 | N2 | `mcp-gateway` mergeado en `develop` (sin archivar; demo 5.4 pendiente). `ea-read` **EN PAUSA** (sin EA) |
| 6 · EA escritura en pruebas (F06.3–4) | `ea_preview_diagram` y `ea_create_test_diagram`: cuatro componentes y tres relaciones, verificados releyendo el modelo; la escritura al target productivo se deniega | `ea-test-write` | Solo Windows | 11, 12 | N2 | **EN PAUSA** (sin EA) |
| **Puerta MVP sin EA** (nueva, 2026-11-25) | Requerimiento → memoria del proyecto → Copilot real → revisión HLS → decisión aprobada y guardada en `Decisiones/` del vault; demo con el Mock y demo manual con Copilot real | `mvp-without-ea` | Mac; Windows como confirmación opcional | 01, 03, 06, 07, 12, 13 | N2 | Planificada; bloqueada por el merge del Corte 2 y de la segunda mitad del Corte 4 |
| **7 · Puerta MVP** (F07) | `architecture-diagram` de punta a punta y `architecture-impact` | `architecture-skills-ea` | Windows | 03 | N2 | **EN PAUSA** (sin EA) |
| 8 · Cierre (F09 y resto) | Matriz SEC-01..15 completa con recibos, runbook, backup y restauración, curador y Sueño asistidos, MCP Server propio del harness | `hardening`, `memory-curation`, `harness-mcp-server` | Mac y Windows | todas | N1 | Revisado el 2026-11-25: `harness-mcp-server` y la parte de `hardening` que no depende de EA se adelantan y van en paralelo a la Puerta MVP sin EA; `memory-curation` sigue después del MVP |

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
2. En paralelo, sin esperar a 1: `harness-mcp-server` con el Mock (las herramientas que preguntan a Copilot real quedan BLOCKED por el merge del Corte 2 y por la confirmación de Wilson del alcance de la autorización) y `hardening` (matriz SEC viva, runbook, copia y restauración, diagnóstico, deuda conocida).
3. `mvp-without-ea`: la integración, la demo con el Mock y la demo manual con Copilot real, cuando 1 esté mergeado.
4. Archivar los changes mergeados con su demo en PASS (`skill-engine`, `mcp-gateway`, después `architecture-skills-llm` y `copilot-web-provider`).
5. EA (cortes 5 segunda mitad, 6 y 7) cuando Wilson lo tenga instalado.

### Qué queda fuera ahora

- Todo lo que necesita EA: `ea-read`, `ea-test-write`, `architecture-skills-ea` (`architecture-diagram`, `architecture-impact`), SEC-11 y la parte de COM de SEC-10.
- `memory-curation` (curador y Sueño asistidos), Computer Use, sugerencia de Skill por IA.
- Guardar contenido real de Copilot y cifrar SQLite.
- Escribir en el vault desde el servidor MCP (`memory_save_decision`): no entra en la primera versión de `harness-mcp-server` (ver su design).

### Cómo retomar EA

Cuando Wilson tenga EA instalado: ejecutar la tarea 1.2 de `ea-read` (la sonda, siguiendo `docs/runbook/enterprise-architect.md`), retirar la nota de pausa de su `tasks.md` y su `proposal.md`, y seguir sus tareas tal como están. `mcp-gateway`, del que depende, ya está en `develop`. Después, los cortes 6 y 7 en el orden de la tabla; la Puerta MVP original sigue siendo la del Norte.
