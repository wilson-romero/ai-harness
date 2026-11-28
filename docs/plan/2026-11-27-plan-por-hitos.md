# Plan por hitos (2026-11-27)

Aprobado por el dueño del proyecto el 2026-11-27. Desde esta fecha, **este documento da el orden de trabajo**. El plan por cortes ([`2026-11-24-ai-harness-cortes.md`](2026-11-24-ai-harness-cortes.md)) sigue siendo el registro de cada corte: su change, su riesgo, sus SEC y su estado. Cuando un change nombra su corte, lo busca allí; cuando alguien pregunta «¿qué va ahora?», la respuesta está aquí.

## Qué se construye

Un asistente personal sobre Copilot Web. Hace tres cosas, que se entregan en este orden:

1. **Agente de código en una carpeta de trabajo**, al estilo de OpenCode: lee los ficheros, propone cambios, los aplica con aprobación, ejecuta y corrige.
2. **Aprende en la segunda memoria**, siguiendo el modelo del repositorio público `claude-memory-system`: la misma estructura, los mismos formatos de nota y el mismo ciclo de captura y curación.
3. **Rutina diaria**: Outlook, Teams y Planner por la web, borradores de respuesta en el tono del dueño y diagramas en Enterprise Architect.

## Reglas que valen para todo

- **El modelo propone y el harness ejecuta.** Un texto del modelo nunca es una orden ni una aprobación.
- **Leer puede ir solo** cuando una regla de la lista local lo permite. **Escribir, enviar o ejecutar, nunca** sin la aprobación del contenido exacto, ligada a su hash.
- **Nunca se reenvía.** Lo que queda `uncertain` se queda así; repetir es una decisión de la persona y crea otra solicitud.
- **El mismo código en macOS y en Windows**, salvo el paquete de Enterprise Architect.
- **El harness no dice que aísle nada.** Lo aprobado corre con la cuenta de la persona, sin sandbox del sistema.
- Solo datos sintéticos en el repo (`SECURITY.md`).

## Dónde estamos (sobre `develop` = `a9c51fe`)

**En `develop`:**

- La conversación a pantalla completa (`main.py chat`): botones de aprobación con guarda, bloques plegables, espaciado, tablas y respuestas enteras, autocompletado y comandos cortos.
- El proveedor de Copilot Web, probado en macOS contra la página real con una cuenta de prueba. La demo del Corte 2 (`copilot-web-provider` 7.5) sigue abierta.
- `/mode auto|quick|deep` (`response-mode`), implementado contra la página sintética. El selector de la página real está sin medir (tarea 8.1).
- La memoria del proyecto y los Skills con aprobación (`hls-review`, `architecture-memory`), y la Puerta MVP sin EA con el Mock.
- La pasarela MCP de solo lectura (`mcp call`).
- El lector de planes y `/plan` de solo lectura (`code-mode`, tramos 1 y 2): el modelo propone un plan JSON de lecturas, la persona lo aprueba por su hash y el harness lo ejecuta por la pasarela. El resultado se muestra solo a la persona.
- El endurecimiento que no depende de EA (`hardening`), la guía de fundamentos ([`docs/aprendizaje/fundamentos-de-un-harness.md`](../aprendizaje/fundamentos-de-un-harness.md)) y el runbook de niveles ([`docs/runbook/harness-funcional.md`](../runbook/harness-funcional.md)).
- Los estudios de code mode, hooks y sistema de diseño de la terminal ([`docs/estudios/`](../estudios/)).

**En curso, sin fusionar:**

- **Lecturas por regla** (`code-mode`, A2 de su design): una herramienta marcada `auto_read` en la lista local se ejecuta sin la caja de aprobación. Está en una rama, sin revisión independiente.
- **El lazo con vueltas** (`code-mode`, A3): el resultado vuelve al modelo con tope de vueltas y turno de cierre. Está a medio escribir.
- **Herramientas de la carpeta de trabajo** (`workspace-tools`): la propuesta y el primer tramo (carpeta, confinamiento de rutas, `read` y `list` por la CLI) están en una rama.
- **Ejecutar código con aprobación** (`code-run`): solo la propuesta y las decisiones del dueño, en una rama.
- Las decisiones del dueño sobre los estudios de hooks y de sistema de diseño están anotadas en ramas sin fusionar; en `develop` los dos estudios tienen sus decisiones abiertas.

**Sin implementar:** los tramos de `sqlmodel-persistence` que faltan (5 de 34 tareas hechas), la memoria por deltas de `prompt-economy` (tareas 5.x), el servidor MCP propio (`harness-mcp-server`, 0 de 34) y todo lo de Enterprise Architect (`ea-read`, en pausa).

**Sin medir:**

- si Copilot real escribe planes válidos (`code-mode`, tramo 3);
- `/mode quick` y `deep` en la página real;
- el `develop` actual en Windows.

## El problema de la velocidad

Una pregunta de una palabra, dentro de una conversación, tarda **unos 11 s**. Medido el 2026-11-26 en la página real, en macOS, con tres preguntas trazadas (`openspec/changes/copilot-web-provider/design.md`, D3, «Coste medido por pregunta»). Así se reparte:

| Tramo | Tiempo | De quién es |
|---|---:|---|
| Cargar la dirección y esperar el chat | 1,0–1,4 s | harness |
| Esperar a que la página deje de cambiar | 3,6–4,1 s | harness |
| Escribir y enviar | 0,25 s | harness |
| Esperar el final de la respuesta | 6,1 s, de ellos 4 s de ventana fija «sin cambios» | unos 2 s Copilot, 4 s harness |

La primera pregunta tardó 14,2 s y las siguientes, 11,1 y 11,0 s. De esos 11 s, **unos 9 son espera del propio harness** y unos 2 son Copilot contestando. Ese es el margen. Un lazo de tres vueltas a este ritmo pasa del medio minuto.

Las medidas, en cuatro grupos y por orden:

**V1 · Quitar la espera propia.** Es lo que más rinde y va primero.

1. No recargar la página cuando la pestaña es de confianza y ya muestra la conversación de la sesión. Es la propuesta sin implementar del mismo D3: ahorraría unos 4–5 s por pregunta.
2. Detectar el final de la respuesta por una señal positiva de la página: desaparece el botón de parar, vuelve el de enviar, se va el indicador de escritura. La ventana de estabilidad queda como respaldo corto. Ahorraría hasta 3 s.
3. Medir antes y después con la sonda, unos 10 envíos. El objetivo es bajar de 11 s a 3–4 s por vuelta en preguntas cortas. El riesgo es cortar una respuesta antes de tiempo; por eso se mide, y la comprobación de respuesta truncada se conserva.

**V2 · Menos vueltas por tarea.**

4. Planes de varias acciones (ya en `develop`) y, después, referencias entre pasos (una versión 2 del formato del plan), para que una vuelta haga lo que hoy harían tres.
5. Leer en bloque: una herramienta que devuelve varios ficheros, o varios correos, de una vez.
6. `/mode quick` para las vueltas mecánicas del lazo, y `deep` solo cuando la persona lo pida.
7. Memoria por deltas (diseñada en `prompt-economy`): no reenviar el contexto que Copilot ya tiene en la conversación.

**V3 · Que se sienta rápido.**

8. Mostrar la respuesta mientras llega, no entera al final.
9. Mostrar en qué va cada vuelta (enviando, esperando, ejecutando el paso 2 de 3), con su tiempo.

**V4 · Un segundo modelo para lo mecánico. Es una decisión del dueño, no está planificada.** La interfaz de proveedor ya admite otro modelo. Uno con API y llamadas a herramientas nativas haría las vueltas mecánicas en 1–2 s y dejaría Copilot para razonar. Pero cambia la premisa del proyecto («el modelo es Copilot Web») y depende de lo que el dueño tenga permitido usar. Solo se estudia si V1 a V3 no bastan.

**Lo que no se hará:** varias pestañas en paralelo contra Copilot. Arriesga el bloqueo de la cuenta y la mezcla de conversaciones.

## Orden de trabajo

Cada hito termina en algo que el dueño puede usar. Dentro de un hito, los pasos van en orden.

### Hito 1 · Un lazo que funciona con Copilot real y no desespera

| Paso | Qué | Estado |
|---|---|---|
| 1.1 | Lecturas por regla, sin caja (`code-mode` A2) | En curso, sin fusionar; falta la revisión independiente |
| 1.2 | Lazo con vueltas, tope y turno de cierre (`code-mode` A3) | En curso, sin fusionar |
| 1.3 | Velocidad V1: sin recarga y fin de respuesta por señal | Por empezar |
| 1.4 | Sonda de `/mode` en la página real, con el dueño (`response-mode` 8.1) | Pendiente del dueño |
| 1.5 | Medición con Copilot real (`code-mode` A4, tramo 3): ¿escribe planes válidos?, ¿cuánto tarda una tarea de tres vueltas? | Por empezar |

**Punto de control tras 1.5.** Si Copilot no escribe planes fiables, se cambia a una acción por turno (el mismo código, con más vueltas) o se abre V4. La decisión se toma **antes** de invertir en los hitos 2 a 4.

### Hito 2 · Agente de código

| Paso | Qué |
|---|---|
| 2.1 | Carpeta de trabajo y lectura de ficheros (`workspace-tools`, primer tramo, en una rama), y esas lecturas en el catálogo del lazo |
| 2.2 | Crear y editar con el diff exacto y aprobación; leer antes de editar; sin borrar ni mover |
| 2.3 | `/undo` de un nivel; buscar (`grep`, `glob`) |
| 2.4 | Ejecutar: `/run` y órdenes de una tabla fija (`code-run`) |
| 2.5 | Velocidad V2 (leer en bloque, referencias entre pasos) y V3 (respuesta en vivo, progreso) |

### Hito 3 · Que aprenda y se adapte

| Paso | Qué |
|---|---|
| 3.1 | Estudio de `claude-memory-system`: correspondencia pieza a pieza (estructura, formatos, captura, curación) |
| 3.2 | Hooks: observar y bloquear, como programas externos ([estudio de hooks](../estudios/2026-11-27-hooks.md)) |
| 3.3 | `/remember` y captura al cerrar la sesión: el harness propone notas, el dueño las aprueba y se escriben con el formato de su sistema |
| 3.4 | Curación asistida («Sueño»), con aprobación |
| 3.5 | `AGENTS.md` de la carpeta como datos; modos plan y build |

### Hito 4 · Rutina diaria

| Paso | Qué |
|---|---|
| 4.1 | Estudio: Playwright frente a Microsoft Graph; el permiso corporativo; qué se puede medir sin datos reales |
| 4.2 | Outlook de solo lectura: resumir y clasificar lo no leído, en bloque |
| 4.3 | Borradores en el tono del dueño (guía de voz y ejemplos), enviados solo con aprobación |
| 4.4 | Planner y Teams |
| 4.5 | Enterprise Architect (cortes 5 a 7 del plan por cortes; en pausa hasta que esté instalado) |

### Trabajo transversal

No bloquea ningún hito.

- **Windows.** Una corrida tras cada tanda de merges. Nunca es condición de merge.
- **Base de datos.** Los tramos de `sqlmodel-persistence`, entre hitos y cuando ninguna rama abierta toque el almacenamiento.
- **Deuda conocida:**
  - estado por pasos para reanudar un lazo tras un corte;
  - códigos de error cerrados por proveedor;
  - el servidor MCP propio (`harness-mcp-server`);
  - la medición formal de la Puerta MVP sin EA con tres requerimientos (`mvp-without-ea` 4.1–4.4).
- **Forma de trabajar.** Merges por tandas, cada uno con una revisión independiente y la aprobación del dueño. La puerta de tests tiene dos niveles (ver «Cómo se verifica»).

## Riesgos que el plan no quita

- Copilot puede no escribir planes fiables. Lo dirá el paso 1.5.
- Aun con V1, cada vuelta costará varios segundos. Nunca será tan rápido como un modelo con API.
- Outlook, Teams y Planner cambian su interfaz. Lo que se construya sobre ellos habrá que volver a medirlo.
- Lo aprobado corre con la cuenta de la persona, sin aislamiento del sistema.
- Una nota mala en la memoria afecta a todas las sesiones futuras. Por eso cada nota se aprueba.

## Cómo se verifica

- **Cada paso:**
  - tests que se vieron fallar antes de la implementación;
  - controles negativos por mutación;
  - la tanda sin Edge en PASS sobre el SHA (`caffeinate -i uv run pytest -m "not edge and not copilot"`);
  - la demo en `demo: PASS`;
  - una revisión independiente.
- **La tanda con Edge** (`-m edge`) corre en cada merge que toca el código del proveedor o del navegador, y una vez por tanda de merges sobre `develop`. Esa misma tanda lleva la corrida en Windows.
- **Velocidad.** Tiempos por tramo antes y después, medidos con la sonda en la página real y guardados como recibo en `HARNESS_DATA_DIR`. En el repo entran solo las cifras.
- **Hito 1.** Una tarea de tres vueltas con Copilot real, con sus tiempos y su número de envíos, dentro del presupuesto de 100 envíos automáticos.

## Qué cambió respecto al plan anterior

- La **velocidad** entra en el Hito 1; antes no estaba en ningún plan. Sin ella, el lazo existe pero no se usa.
- La **medición con Copilot real** va antes de los ficheros y de la ejecución, como punto de control.
- **Aprender en la segunda memoria** y la **rutina diaria** dejan de ser añadidos sueltos y pasan a ser los hitos 3 y 4. El curador y el Sueño (`memory-curation`), que el plan por cortes dejaba para después del MVP, quedan dentro del Hito 3.
- Los **hooks** suben al Hito 3, porque la captura al cerrar la sesión los necesita.
- El orden ya no lo da la lista «Orden de lo que queda» del plan por cortes, sino los hitos de este documento.
