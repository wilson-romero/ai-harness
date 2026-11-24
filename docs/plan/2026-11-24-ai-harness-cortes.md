# Plan de entregas por cortes (2026-11-24)

Aprobado por Wilson el 2026-11-24. Parte de `AI-HARNESS-PLAN.md` v0.4 (copiado en esta carpeta como referencia). Este fichero manda sobre las fases F00–F09 del plan maestro hasta la Puerta MVP.

## Norte

El **MVP de punta a punta**: Wilson da un requerimiento, el harness recupera el contexto del proyecto en la memoria, lee el modelo de Enterprise Architect, pide una propuesta a Copilot Web, Wilson la aprueba, el harness crea el diagrama editable en el repositorio de pruebas, lo verifica releyéndolo y registra la decisión.

## Decisiones de partida

- Todo funciona en macOS y en Windows salvo Enterprise Architect, que usa COM y vive en un servidor MCP separado, solo Windows. Fuera de EA no hay código condicionado por plataforma: lo que pasa los tests en la Mac es lo que corre en Windows, y una ejecución en Windows es una confirmación opcional, no la puerta de un corte (Wilson, 2026-11-24).
- El repositorio es público: nada real ni identificable entra en él (`SECURITY.md`); lo medido sobre sistemas reales vive en `HARNESS_DATA_DIR`.
- Wilson tiene Windows + Edge + Copilot corporativo y permiso para automatizar Copilot Web (declarado el 2026-11-24). De EA tiene una versión demo: que permita Automation se mide con una sonda al abrir el Corte 5.
- El primer valor real es Copilot en varias conversaciones (Corte 2). Es también el riesgo técnico mayor y por eso va antes que MCP y Skills.
- Cada pieza de infraestructura nace en el corte que la usa: aprobaciones con la primera escritura (Corte 4), cliente MCP y políticas con EA (Corte 5). Los Skills se ejecutan en secuencia lineal, sin DAG.
- La seguridad no es una fase: cada SEC-xx del plan maestro se prueba en el corte que abre esa superficie.
- Solo datos sintéticos en el repo y en los agentes. Wilson prueba con lo real en local.
- No hay `docs/progress.md`: el estado vive en `tasks.md` de cada change. `docs/adr/` queda para decisiones transversales.

## Cortes

Cada corte es demostrable por separado. Hecho = Wilson lo reproduce con el SHA indicado. Entre paréntesis, la fase del plan maestro.

| Corte | Lo que Wilson ve y reproduce | Change(s) | Dónde | SEC | Riesgo |
|---|---|---|---|---|---|
| 0 · Base (F00) | Repo con uv + Python 3.14, OpenSpec personalizado, este plan y `scripts/verify.sh` | — | Mac | — | N0 |
| 1 · Esqueleto (F01) | `session create/list`, `ask`, `history` con mock: tres sesiones aisladas, historial tras reinicio, solicitud interrumpida → `uncertain` | `session-core` | Mac y Windows | 02, 07, 08 | N1 |
| 2 · Copilot (F04) | `ask` contra Copilot Web real en tres conversaciones, reinicio y recuperación de identidad, login vencido pide intervención, timeout tras envío → `uncertain` sin reenvío. Empieza con una sonda que mide selectores y señal de fin de respuesta en la UI real | `copilot-web-provider` | Mac y Windows, Edge con perfil dedicado | 06, 07, 10 | N2 |
| 3 · Memoria (F05) | `memory search`, `memory context`, `ask --project` con contexto acotado, `memory maintain --dry-run`; vault sintético compatible con `claude-memory-system` | `project-memory` | Mac y Windows | 01, 03, 04, 13 | N1 |
| 4 · Skills sin herramientas (F03, parte de F07) | `skill list/show/run/status/resume`; `hls-review` y `architecture-memory` con pasos llm / validate / approval. Aprobaciones por hash exacto, con expiración y uso único | `skill-engine`, `architecture-skills-llm` | Mac y Windows | 12, 14, 15 | N1 |
| 5 · EA lectura (F02 mínima, F06.1–2) | Sonda COM sobre el modelo demo; cliente MCP y políticas deny-by-default; `ea_list_packages`, `ea_list_diagrams`, `ea_get_diagram`, `ea_get_element` desde la CLI | `mcp-gateway`, `ea-read` | Solo Windows | 05, 09, 10 | N2 |
| 6 · EA escritura en pruebas (F06.3–4) | `ea_preview_diagram` y `ea_create_test_diagram`: cuatro componentes y tres relaciones, verificados releyendo el modelo; la escritura al target productivo se deniega | `ea-test-write` | Solo Windows | 11, 12 | N2 |
| **7 · Puerta MVP** (F07) | `architecture-diagram` de punta a punta y `architecture-impact` | `architecture-skills-ea` | Windows | 03 | N2 |
| 8 · Cierre (F09 y resto) | Matriz SEC-01..15 completa con recibos, runbook, backup y restauración, curador y Sueño asistidos, MCP Server propio del harness | `hardening`, `memory-curation`, `harness-mcp-server` | Mac y Windows | todas | N1 |

Los cortes 3–4 no dependen de 5–6: si EA bloquea, se sigue por memoria y Skills.

## Fuera del alcance hasta después del MVP

- Computer Use (F08).
- Sugerencia de Skill por IA y scripts externos dentro de un Skill.
- Ejecución nocturna del Sueño.
- Escritura en cualquier repositorio de EA que no sea el de pruebas.
- Interfaz gráfica, despliegue multiusuario, extracción de tokens o APIs privadas.

## Dependencias externas

- Licencia de EA con Automation Interface y un modelo local de pruebas. Bloquea los cortes 5–7.
- Tipo de conexión y credenciales de solo lectura del repositorio corporativo de EA. Bloquea la lectura real del Corte 5, no su desarrollo contra el modelo demo.
- Política corporativa de retención: decide si el contenido real de las conversaciones se persiste en SQLite. Se resuelve en el Corte 2.

## Reglas del plan

- Si un corte falla: 4 h de diagnóstico y después se replantea el alcance con Wilson.
- Un corte con integración real no se cierra si solo pasó con mocks.
- No hay fechas: se estima al abrir cada corte y se reestima tras el Corte 2, que es el riesgo técnico mayor.
