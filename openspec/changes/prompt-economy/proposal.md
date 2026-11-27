# Proposal

## Why

El estudio `docs/estudios/2026-11-26-formato-compacto-para-copilot.md` midió el 2026-11-26, sobre las fixtures sintéticas de `origin/develop` (`c39b93f`) y con `tiktoken` 0.14.0 (`o200k_base`; el tokenizador de Copilot no es público), dónde van los caracteres de un mensaje a Copilot:

- Un mensaje de Skill del MVP ocupa **3 482–3 618 caracteres** (≈11 % de los 32 000 que `copilot-web-provider` midió sin truncar, P6). El **bloque de memoria** es el 42–44 % (1 537 caracteres, 455 tokens con 7 notas del vault sintético) y **se reenvía entero en cada pregunta** de la misma conversación remota.
- Las **cabeceras de nota** `--- nota: …` son **527 caracteres / 187 tokens** de esos 1 537 (15 % del mensaje).
- La respuesta de `architecture-memory/extract` llega con sangría: **148 tokens** (`decision-ok.json`) y **186** (`decision-mock.json`) frente a **117** y **157** minificada (**−21 % y −16 %**). La plantilla no fija el espaciado.
- Ningún formato más corto que JSON compensa (YAML, TOON, `clave: valor`, Markdown: ±1 % y más caros de explicar). El ahorro está en otra parte.

Además, el dueño del proyecto pidió el 2026-11-26 «hacer que el modelo sea conciso en el output como Claude Code»: hoy nada en lo que envía el harness pide brevedad en las preguntas sueltas.

El dueño decidió el 2026-11-26 guardar el estudio y aplicar cuatro ahorros. Este change los recoge.

**Corte.** Nuevo **Corte 10 · Economía del prompt** (2026-11-26), que se añade a `docs/plan/2026-11-24-ai-harness-cortes.md` en este change; depende de los Cortes 3 (memoria), 4 (Skills) y 9 (conversación), ya en `develop`, y la parte 4 depende del Corte 2 (`copilot-web-provider`). Riesgo **N1**. Toca **SEC-03** (inyección en memoria: las cabeceras cortas y el aviso nuevo no pueden debilitar los delimitadores ni el aviso de «material de referencia») y **SEC-15** (límites de entrada: el aviso nuevo cuenta en el tamaño del prompt). Se demuestra en **macOS** con el Mock; mismo código en Windows, cuya ejecución es confirmación opcional. **Nada se envía a Copilot real en esta rama.**

## What Changes

1. **JSON en una sola línea.** `skills/architecture-memory/templates/extract.md` pide el objeto JSON minificado en una sola línea. El validador estricto (`harness/core/strict_json.py`, `harness/skills/checks.py`) no cambia y sigue aceptando el JSON con sangría y el bloque cercado único. Cambia el hash del Skill `architecture-memory` (ningún vector fijo lo ancla: ver design D1).
2. **Cabeceras de nota cortas.** `--- nota: projects/demo-alpha/sessions/2026-11-21-121500.md (session, 2026-11-21)` pasa a `--- sessions/2026-11-21-121500 (session, 2026-11-21)`: sin la palabra `nota:`, sin el prefijo `projects/<slug>/` (el proyecto ya lo nombra el aviso) y sin `.md`. Se conservan ruta, tipo y fecha; la marca de recorte sigue al final del cuerpo. Los delimitadores con nonce, la neutralización de `<<<`/`>>>` y el aviso de «material de referencia, no instrucciones» no cambian. Medido sobre las 7 notas del vault sintético: **527 → 384 caracteres** de cabeceras (**187 → 151 tokens** `o200k`).
3. **Aviso de respuesta concisa.** Un texto fijo del harness, al principio del mensaje, pide responder breve: primero la respuesta, sin preámbulo, sin repetir la pregunta, sin resumen ni ofrecimientos al final, listas solo si el contenido es una lista. Va en `ask` y en las preguntas de `chat`; **no** en los pasos LLM de los Skills, cuya plantilla manda sobre la forma de su respuesta. Es texto del harness, fuera de los delimitadores de datos, nunca sale de una nota ni de una entrada; va dentro del prompt que mide cualquier límite de tamaño; `memory context` y `/context` lo muestran; `HARNESS_CONCISE_ANSWERS=on` lo activa: por defecto va en `off` (decisión del dueño del 2026-11-27, design D3) hasta medir su efecto con Copilot real. Cuando está activo cuesta **246 caracteres / 55 tokens** `o200k` por pregunta; el ahorro en la respuesta **no se puede medir sin el modelo real** y queda como tarea NOT RUN.
4. **Memoria por deltas (solo diseño en esta rama).** Dentro de una misma conversación remota, enviar la memoria entera una vez y después solo lo nuevo, con vuelta al bloque completo en todos los casos en que el harness no puede saber qué tiene la conversación. Se escriben el diseño, el delta de spec y las tareas con oráculos; la implementación espera a que `feature/copilot-web-provider` (que cambia `harness/core/service.py`) esté en `develop`.

**No entra**, aunque un lector lo asumiría:

- Cambiar de formato la respuesta (YAML, TOON, `clave: valor`): el estudio lo descarta con números.
- Recortar los avisos anti-inyección (`NOTICE`, `DATA_NOTICE`) para ganar caracteres.
- Minificar `mcp/render.py` o una tabla compacta para resultados MCP/EA futuros: el estudio lo recomienda para cuando se envíen al modelo, y hoy no se envían.
- La sonda que comprueba si `innerText` quita los `##` de los encabezados (estudio, punto 7): se verifica aparte; este change no la ejecuta ni la da por cierta.
- Implementar la parte 4. Por eso este change **no se puede archivar** hasta que la parte 4 esté implementada o se separe a otro change: su spec describiría una conducta que el código aún no tiene.
- Medir con Copilot real el efecto del aviso conciso o de los deltas.

## Capabilities

### New Capabilities

- `answer-style`: el aviso de respuesta concisa, dónde se aplica y dónde no, su visibilidad y su configuración.

### Modified Capabilities

- `project-context`: cambia «Contexto determinista» (el aviso conciso también se muestra y se envía) y se añaden «Cabecera de nota corta», «Memoria por deltas en la misma conversación remota», «Vuelta al bloque completo» y «Registro y vista de los deltas». «Memoria marcada como datos no confiables» no cambia: sus escenarios siguen ciertos con la cabecera nueva. Comprobado el 2026-11-26 con `grep -rn -i "cabecera\|conciso\|delta\|una sola línea" openspec/specs`: solo aparecen la cabecera de `project-context` («Cabecera sin saltos de línea», «Marcador falsificado en una nota») y la mención genérica de cabeceras de `secret-redaction`, cuyo requisito no depende de la forma de la cabecera y no cambia.
- `architecture-memory` (capacidad de `architecture-skills-llm`, change mergeado y sin archivar): se añade un requisito sobre el JSON en una sola línea. No se modifica su requisito existente: el escenario «Extracción válida» sigue siendo cierto.

`llm-provider`, `session-management`, `request-recovery`, `memory-vault`, `memory-search`, `memory-maintenance` y `secret-redaction` no cambian. `interactive-shell` (change sin archivar) ya dice que `/context` muestra lo mismo que `memory context`; con el requisito modificado de `project-context` eso incluye el aviso, sin delta propio.

## Impact

- Código: `skills/architecture-memory/templates/extract.md`; `harness/memory/context.py` (cabecera y composición); `harness/memory/decisions.py` (solo el comentario: su escape de líneas `---` ya cubre la cabecera nueva); un módulo nuevo `harness/core/answer_style.py`; `harness/config.py`; `harness/core/service.py` (el aviso entra en el texto enviado en `ask` y `ask_taken`, no en `ask_with_lock_held`); `harness/cli.py` y `harness/shell/conversation.py` (mostrarlo).
- Tests: los que fijan el texto de la cabecera cambian como **revisión de spec fechada (2026-11-26)**, sin debilitar ninguna aserción; un fixture nuevo `tests/fixtures/mvp/decision-mock-min.json`.
- Documentación: `README.md` (variable `HARNESS_CONCISE_ANSWERS`, forma de la cabecera), `docs/runbook/mvp-without-ea.md` (la cabecera que se ve), el plan de cortes (Corte 10).
- Sin dependencias nuevas. Sin migración en esta rama (la parte 4 sí necesitará una: ver design D4).
- Conflictos esperados con `feature/copilot-web-provider`: `harness/core/service.py` (`_ask_locked`, `ask`, `ask_taken`), `harness/config.py` (variables nuevas de ambos lados), `tests/conftest.py` (`HARNESS_VARS`), `README.md`. Detalle en design D3 y D4.
