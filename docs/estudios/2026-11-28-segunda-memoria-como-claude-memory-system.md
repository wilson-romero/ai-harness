# Estudio: la segunda memoria como `claude-memory-system`

Fecha: 2026-11-28. Paso 3.1 del [plan por hitos](../plan/2026-11-27-plan-por-hitos.md) (Hito 3, «Que aprenda y se adapte»). Leído:

- `claude-memory-system` en el commit `92b19ea` (`92b19ea59716fc811f02b4a59fbc0daeb30aa7d0`, 2026-09-30, `VERSION` 2.1.2), clonado en un directorio temporal. Se leyó como datos: no se ejecutó ningún script ni el instalador. Los enlaces de este estudio apuntan a ese commit.
- `ai-harness` en `origin/develop` (`8a8afbd`). Las líneas `fichero:línea` del harness son de ese commit.

No se leyó ningún vault real ni configuración local. No se envió nada a Copilot y no se escribió código de producto.

Etiquetas: **[R]** leído en uno de los dos repositorios, con fichero y línea · **[I]** inferencia o propuesta, no medida · **(no verificado)** lo que el repositorio leído no permite confirmar.

## Resumen (12 líneas)

1. **[R]** `claude-memory-system` es un conjunto de scripts de Bash y Python para Claude Code. Usa dos hooks, `SessionStart` y `Stop`, y un temporizador nocturno. Todo lo que guarda es Markdown en una carpeta de un vault de Obsidian. Licencia MIT.
2. **[R]** El ciclo tiene cuatro piezas con dueños disjuntos. La **captura** es determinista y escribe `projects/`, `daily/`, `agents/` y `_index.md`. El **curador** es un `claude -p` sin supervisión que escribe `Memoria/`, `Lecciones/` y `Memoria-CC/`. El **Sueño** consolida y archiva cada noche a las 03:30. La **carga** inyecta unos 6 KB al empezar la sesión.
3. **[R]** Todo es automático y sin aprobación: el curador se rige por «si hay duda, guarda» y el Sueño mueve ficheros. Las dos llamadas al modelo son procesos aparte con herramientas limitadas al vault.
4. **[R]** El lector actual del harness acierta en la estructura y en el aviso «datos, no instrucciones». Falla en varios detalles del formato real: tipos de nota, dónde viven los agentes, `_project.md` sin `created`, slugs sacados de la ruta y enlaces `../Lecciones/` en el índice. La fixture sintética reproduce los errores en lugar de detectarlos (§2.3).
5. **[R]** El fallo con más consecuencias: el curador real escribe `tags: []` y no pone `project_slug`. Por eso `memory context` **nunca** incluye una lección ni una nota de `Memoria-CC/` real de un proyecto. Solo entran las que la fixture inventa.
6. **[R]** `Decisiones/` no tiene formato en el repositorio público: no hay plantilla, no existe el tipo `decision` y el curador no tiene permiso para escribir allí. El formato de decisión es un invento del harness.
7. **[I]** No se copia nada de lo que escribe o llama al modelo solo: ni la escritura automática, ni el `claude -p` en segundo plano (aquí cada llamada sería un envío visible a Copilot), ni ningún código o hook que venga del vault.
8. **[I]** Primer tramo recomendado: `/remember <texto>`. Escribe una nota **nueva** `Memoria-CC/feedback_<slug>.md` con el frontmatter del curador. No hace ningún envío y reutiliza la caja de aprobación y el escritor por enlace duro de las decisiones. Tamaño M.
9. **[I]** Segundo tramo: al cerrar la sesión, si la persona lo pide, el harness hace **una** pregunta para que el modelo proponga notas en un bloque JSON con nonce y esquema cerrado, igual que el lector de planes. Cada candidata se aprueba o se rechaza por separado. Cuesta un envío. El harness no tiene el texto de la sesión con Copilot: solo lo tiene la conversación remota.
10. **[I]** Tercer tramo: las notas globales aprobadas entran en `memory context` como una sección propia, primera y con tope de bytes. Cuarto tramo, para más adelante: un Sueño asistido que propone fusionar o sustituir notas, sin borrar nunca y con aprobación por propuesta.
11. **[I]** Riesgos principales: envenenamiento de la memoria (el bloque marcado impide falsificar los delimitadores, pero no que el modelo obedezca), datos de terceros en las notas, que el formato original cambie (MIT permite copiar las plantillas como fixture de referencia) y la convivencia con el curador original en el mismo vault.
12. Decisiones abiertas para el dueño en §6, con opciones, recomendación y tamaño.

---

## 1. Qué es `claude-memory-system`

### 1.1 Las piezas

| Pieza | Fichero | Cuándo corre | Quién decide qué escribe |
|---|---|---|---|
| Carga | [`scripts/memoria-load.sh`][load] | Hook `SessionStart`, síncrono, 15 s | Script determinista |
| Captura | [`scripts/memoria-capture.sh`][capture] | Hook `Stop`, `"async": true`, 30 s, **en cada turno** | Script determinista |
| Curador | [`scripts/memoria-curator.sh`][curator] + [`templates/curator-prompt.md.tmpl`][curprompt] | Hook `Stop`, `"asyncRewake": true`, 900 s, con topes de frecuencia | Un `claude -p` sin supervisión |
| Sueño | [`scripts/memoria-dream.sh`][dream] + [`templates/dream-prompt.md.tmpl`][dreamprompt] | Temporizador de systemd a las 03:30 ([`memoria-dream.timer`][timer]). Si no corrió hoy, lo lanza `SessionStart` | Fase 1: script. Fase 2: `claude -p` sin supervisión |
| Comandos | [`skills/memory-*.md`][skills] | Los pide la persona (`/memory-save`, `/memory-load`, `/memory-promote`, `/memory-maintenance`, `/memory-update`) | Claude Code con los permisos de la persona |
| Redacción | [`scripts/lib/redact.py`][redact] | Antes de que el texto de la sesión llegue al vault | Patrones por prefijo de proveedor |
| Sincronización | [`scripts/sync-obsidian.sh`][syncobs], [`scripts/sync-knowledge.sh`][syncknow] | Temporizadores, solo si están configurados | `rclone` |

El instalador ([`install.sh`][install], líneas 172–193) añade los dos hooks a `~/.claude/settings.json`, enlaza los comandos y renderiza los dos prompts con el nombre de la persona, la máquina y el perfil (`personal` o `work`). Necesita Linux o WSL: usa `flock`, `find -printf`, `sed -i` y systemd. El design de `project-memory` ya midió que no corre en Windows ([design](../../openspec/changes/archive/2026-11-24-project-memory/design.md), «Risks»).

### 1.2 La vida de un recuerdo

```
 sesión de Claude Code
 ─────────────────────
  SessionStart ──► memoria-load.sh ──► systemMessage (~6 KB, marcado como datos)
                                       _project.md (3000 B) · última sección de
                                       contexto-reciente (1500 B) · índice de
                                       agentes (1000 B) · INDEX compartido (800 B)
        │
        ▼
  ... turnos ...
        │
  Stop (cada turno)
   ├─► memoria-capture.sh  (determinista, async)
   │     lee el transcript JSONL ──► redact ──►
   │       projects/<vault_slug>/sessions/YYYY-MM-DD-HHMMSS.md   (nota de sesión)
   │       projects/<vault_slug>/_project.md                     (reescrita)
   │       daily/YYYY-MM-DD.md   agents/skills/<tipo>.md   _index.md
   │
   └─► memoria-curator.sh  (asyncRewake; como mucho 1 cada 10 min por sesión
         │                  y 1 cada 30 min por máquina; flock)
         │  copia redactada del transcript + nota de sesión
         ▼
       claude -p (Read/Edit/Write/Glob/Grep, solo dentro del vault)
         ──► Memoria/contexto-reciente.md   (## YYYY-MM-DD, añade bullets)
         ──► Memoria/proyectos-activos.md · personas.md · preferencias.md · perfil.md
         ──► Lecciones/YYYY-MM-DD-<slug>.md                (nueva)
         ──► Memoria-CC/feedback_|project_|reference_<slug>.md + línea en MEMORY.md
         comprueba el trabajo por mtime; si no escribió nada, exit 2 despierta la sesión

 cada noche 03:30 (o al abrir sesión si no corrió hoy)
 ───────────────────────────────────────────────────────
  memoria-dream.sh
   Fase 1 (sin modelo): cuarentena de conflictos de sync, reparación de [[enlaces]]
                        únicos, huérfanos y entradas colgantes del índice,
                        pares de nombres parecidos (> 0,72)
   Fase 2 (claude -p):  fusiona duplicados, compacta contexto-reciente > 30 días
                        en Memoria/Archivo/contexto-YYYY-MM.md, archiva lo obsoleto,
                        repara y ramifica MEMORY.md (< 17 KB), máx. 10 ficheros
                        los movimientos los PIDE en Memoria/Archivo/_mover.txt
                        y el script solo aplica zona curada ──► Memoria/Archivo/
   Reporte: Memoria/Suenos/YYYY-MM-DD.md            (nunca borra)

 recuerdo
 ────────
  siguiente SessionStart (inyección) · Read/Grep de Claude sobre el vault ·
  /memory-load (lee perfil, preferencias, proyectos, contexto, MEMORY.md) ·
  MEMORY.md, que carga la auto-memoria nativa de Claude Code (enlace no visible en el repo)
```

### 1.3 Capas y dueños

[`docs/arquitectura.md`][arq] (líneas 5–37) divide el vault en dos zonas. El **conocimiento** (`Memoria-CC/`, `Lecciones/`, `Decisiones/`) se une entre máquinas personales con `rclone copy --ignore-existing`, que solo añade, y los índices `MEMORY*.md` y `_INDEX.md` quedan fuera de esa unión. La **sesión** (`Memoria/`, `projects/`, `daily/`, `agents/`, `_index.md`) es de cada máquina. La regla de oro es el «ownership disjunto»: captura y curador nunca escriben en la misma ruta, y el Sueño no toca los datos crudos. Una máquina `work` no se une a nada; a ella se le lleva una lección a mano con `/memory-promote`, que la limpia y pide aprobación ([`skills/memory-promote.md`][promote]).

---

## 2. Correspondencia pieza a pieza

### 2.1 Tabla

«Aquí» es el harness. La última columna dice qué cambia porque aquí **toda escritura necesita aprobación** y el modelo es **una página de chat con presupuesto de envíos** (cada pregunta cuesta segundos y cuenta contra el presupuesto; no hay llamadas de fondo).

| Pieza allí | Qué hace | Fichero(s) allí | Equivalente en ai-harness hoy | Qué falta | Qué cambia aquí |
|---|---|---|---|---|---|
| **Raíz y estructura del vault** | Carpeta dentro de un vault de Obsidian. La crea la migración 001: `Memoria/{Archivo/conflictos,Suenos}`, `Memoria-CC`, `Lecciones`, `projects`, `daily`, `agents/skills`. **`Decisiones/` no se crea** | [`migrations/001-vault-skeleton.sh`][m001] 9–16; [`docs/arquitectura.md`][arq] 5–27 | `HARNESS_VAULT_ROOT` (`harness/memory/config.py:20`, `:30-41`); recorrido confinado (`harness/memory/paths.py:197-252`); `Memoria/Archivo` no se lee (`paths.py:24`, `:260`) | Nada para leer. El harness no crea la estructura, y está bien así | Ninguna carpeta se crea sin una escritura aprobada (como hoy `Decisiones/`, `decisions.py:343-352`) |
| **`projects/<slug>/_project.md`** | La captura la **reescribe** en cada turno: `type: project`, `machine`, `project`, `project_slug`, `updated`, `tags: [claude-code, proyecto]`, **sin `created`**. El cuerpo lleva `Path`, `Última sesión`, `## Memoria de Claude Code` (copia de la auto-memoria nativa del proyecto) y `## Historial de sesiones` (10 enlaces) | [`memoria-capture.sh`][capture] 197–208, 277–299 | Sección `project`, primera del contexto (`harness/memory/notes.py:188-204`, `context.py:231`) | Leerla tal cual sirve. `memory maintain` la marca como frontmatter no válido (§2.3, fallo 5) | El harness nunca la escribe: es de la captura. No hay que replicar la captura, porque aquí no hay transcript (§4.2) |
| **Notas de sesión** | `sessions/YYYY-MM-DD-HHMMSS.md`, una por turno de `Stop`. Frontmatter: `type: session`, `machine`, `session_id` (UUID de Claude Code), `project`, `project_slug`, `created`, `updated`, `tags` en bloque (`claude-code`, `<slug>`). Cuerpo: objetivo (primer mensaje, 300 caracteres), ficheros tocados, herramientas, fragmento del último mensaje (600), «Aprendizajes» (líneas con palabras clave como «importante», «clave», «lección»), estado git, ruta del transcript | [`memoria-capture.sh`][capture] 76–170, 221–269 | Las 3 sesiones más recientes entran al final del contexto (`context.py:37`, `:236-237`) | Sin cambio para leer | El harness no tiene transcript con Copilot (`README.md:712`). Una «nota de sesión» propia tendría solo metadatos. Ver §6, decisión 5 |
| **Slugs** | `vault_slug`: la ruta del cwd sin la `/` inicial, con `/` → `-` (incluye el nombre de usuario de la ruta). `cc_slug`: `/`, `.` y `_` → `-`, con guion inicial, para `~/.claude/projects/` | [`scripts/lib/common.sh`][common] 28–39; [`docs/convenciones.md`][conv] 33–37 | El proyecto es el nombre exacto de una carpeta de `projects/` que cumpla `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` (`paths.py:26`, `:63-69`) | Un `vault_slug` real con espacios o letras no ASCII se **rechaza**, y uno de una ruta profunda puede pasar de 128 caracteres (§2.3, fallo 7) | Aquí no hay cwd: el proyecto lo elige la persona con `--project`. Una nota escrita por el harness declara el `project_slug` de la sesión, como hoy la decisión |
| **Tipos de nota** | `type: feedback \| project \| reference \| lesson \| session \| daily \| curated \| user`. No existen `decision`, `index`, `agent` ni `memoria` | [`docs/convenciones.md`][conv] 3–13; [`scripts/migrate/add-frontmatter.py`][addfm] 13–36 | El harness no valida el valor de `type`: solo exige que exista (`notes.py:163-177`) y lo muestra en la cabecera de cada nota (`context.py:252-256`) | Una lista cerrada para lo que **escribe** el harness | El harness escribe solo tipos de la lista original, más `decision`, que ya usa y que §6, decisión 6, pide declarar |
| **Frontmatter estándar** | `type`, `machine` (por defecto el hostname), `created`, `updated` (`YYYY-MM-DD`), `tags: []`. El curador lo pone en todo fichero nuevo y actualiza `updated`. El Sueño exige que toda `description:` vaya **entre comillas**, porque `: ` sin comillas rompe el YAML | [`docs/convenciones.md`][conv] 3–16; [`curator-prompt.md.tmpl`][curprompt] 33–41; [`dream-prompt.md.tmpl`][dreamprompt] 31 | Parser mínimo, solo con las formas medidas (`notes.py:86-135`). `frontmatter_problem` exige `type`, `created` y `updated` (`notes.py:163-177`) | `machine:` en lo que escribe el harness (la nota de decisión no lo lleva: `decisions.py:203-215`); `description:` entre comillas | `machine:` necesita un nombre configurado, no el hostname sin más (§6, decisión 3) |
| **`Memoria-CC/` y prefijos** | `feedback_` (corrección de conducta o lección de depuración: problema → causa → solución), `project_`, `reference_`, `user_`. Índice `MEMORY.md`, una línea por fichero (`- [Título](archivo.md) — resumen`), ramificado en `MEMORY-<tema>.md`, por debajo de 17 KB, porque la auto-memoria nativa lo corta en unos 24 KB | [`docs/convenciones.md`][conv] 18–31; [`dream-prompt.md.tmpl`][dreamprompt] 25–29; [`skills/memory-maintenance.md`][maint] 36–75 | Se lee como sección `Memoria-CC` solo si la nota declara proyecto (`notes.py:183-204`). `memory maintain` audita `MEMORY*.md` (`maintenance.py:252-267`) | Una nota sin proyecto (casi todas las reales) no entra nunca en el contexto. El harness no puede añadir la línea a `MEMORY.md` sin **modificar** un fichero | Sería el primer destino del aprendizaje: una nota **nueva** por fichero. El índice se queda sin la línea y el Sueño original la añade como «huérfano» (tarea 4 del prompt) |
| **`Lecciones/`** | `YYYY-MM-DD-<slug>.md`, slug de 3–5 palabras con guiones, `type: lesson`. Para «algo técnico concreto (bug resuelto, patrón, configuración que falló)» | [`curator-prompt.md.tmpl`][curprompt] 29 | Sección `Lecciones`, también solo si declara proyecto (`notes.py:20`) | Nada para leer, salvo el fallo de `tags: []` | Segundo destino posible (`type: lesson`) |
| **`Memoria/` (curados de la máquina)** | `contexto-reciente.md` (secciones `## YYYY-MM-DD`, compactadas a 30 días), `proyectos-activos.md`, `personas.md`, `preferencias.md` y `perfil.md`, todos `type: curated`. El curador los **edita** | [`templates/memoria-curada/`][tpl]; [`curator-prompt.md.tmpl`][curprompt] 19–27 | No entran en el contexto por diseño (`README.md:291`). `memory search` sí los lee | `preferencias.md` es donde el original guarda las preferencias. El harness no la lee en el contexto ni puede añadirle una línea (sería editar) | Editar un fichero existente queda fuera del modelo de escritura actual (enlace duro, nunca sustituir). Las preferencias del harness van como notas nuevas `feedback_`/`user_` (§4.1) |
| **`Decisiones/`** | El repositorio público no tiene plantilla ni tipo para ellas. Lo nombra como zona del curador y se une entre máquinas, pero el prompt **no** le deja escribir ahí (zona permitida: `Memoria/`, `Lecciones/`, `Memoria-CC/`). Sí cuenta sus `mtime` como trabajo del curador | [`docs/arquitectura.md`][arq] 14; [`curator-prompt.md.tmpl`][curprompt] 9–13; [`memoria-curator.sh`][curator] 253–256 | Única escritura del harness hoy: `Decisiones/YYYY-MM-DD-<slug>-<id8>.md`, `type: decision` (`decisions.py:196-247`, `README.md:431-457`) | Que el formato quede declarado como **propio** del harness | Ninguno: ya pasa por aprobación |
| **Agentes** | `agents/skills/<subagent_type>.md` (`type: reference`, `agent_type`), con un historial por fecha que se añade al final, y `agents/_skills-index.md` (tabla). La captura los saca de las llamadas a `Agent`/`Task` | [`memoria-capture.sh`][capture] 354–427 | No se leen en el contexto (`README.md:291`) | Nada | No aplica: el harness no tiene subagentes |
| **`daily/` e `_index.md`** | `daily/YYYY-MM-DD.md` con «Sesiones del día» y «Aprendizajes del día». `_index.md` se regenera con las sesiones, proyectos y diarios recientes; `type: reference`, sin `created` | [`memoria-capture.sh`][capture] 301–352, 429–466 | Solo `memory search` | Nada | No se escriben: son de la captura |
| **Disparadores de captura** | `Stop` en **cada turno**. El curador tiene guardas: su propio despertar, recursión, cwd dentro del vault, 600 s por sesión, 1800 s por máquina, `flock` | [`install.sh`][install] 187–193; [`memoria-curator.sh`][curator] 66–171 | No existe. Los hooks del harness (estudio, §10) solo **observan y bloquean** y son órdenes externas | Un disparador que **proponga** y nunca escriba | El disparador es la persona: `/remember` y, al cerrar, una oferta que hay que aceptar. El fin de la conversación (`conversation.end`) no puede bloquear (estudio de hooks, §3.2), así que no puede esperar una aprobación |
| **Contenido de una captura** | Del **transcript JSONL** de Claude Code, redactado. La captura extrae prompts (300 caracteres), ficheros, herramientas y fragmentos. El curador recibe una **copia** redactada del transcript completo y la nota de sesión, y escribe lo que el modelo resume | [`memoria-capture.sh`][capture] 76–170; [`memoria-curator.sh`][curator] 193–232 | Con un proveedor real, SQLite guarda la solicitud sin texto (`README.md:712`, `harness/core/service.py:548`). La conversación vive en Copilot | Una fuente para «lo que pasó en la sesión» | El único que tiene la sesión es el modelo remoto: la propuesta es **una pregunta** en la misma conversación (§4.2) |
| **Curación** | `claude -p` con Sonnet, sin hooks, sin Bash, sin MCP, `--restricted`, `dontAsk`, solo `Edit(/<vault>/**)`. Verifica el trabajo por `mtime` y la línea de contrato `CURATOR: WROTE/SKIPPED` | [`scripts/lib/common.sh`][common] 70–103; [`memoria-curator.sh`][curator] 234–283 | No existe (D11 de `project-memory` dejó fuera `capture`, `curator` y `dream`; plan maestro §10) | Todo | Ningún modelo escribe: propone JSON, Python valida y la persona aprueba cada nota. Cada curación es un envío visible, nunca de fondo |
| **Consolidación («Sueño»)** | Fase 1 determinista. Fase 2 con modelo: fusionar, compactar, archivar (pedido en `_mover.txt` y validado), reparar el índice, como mucho 10 ficheros, reporte en `Memoria/Suenos/` | [`memoria-dream.sh`][dream] 67–181, 215–320; [`dream-prompt.md.tmpl`][dreamprompt] | Fase 1 solo como informe: `memory maintain --dry-run` (`harness/memory/maintenance.py:94-149`), con los mismos umbrales (0,85 y 0,72) | La fase 2 y cualquier aplicación | Tramo (d): propuestas con aprobación una a una; nada se mueve ni se borra en el primer corte (§4.4) |
| **Calendario** | 03:30 con `Persistent=true`. Si no corrió hoy, al abrir sesión. Solo corre si hubo actividad | [`memoria-dream.timer`][timer]; [`memoria-load.sh`][load] 82–87; [`memoria-dream.sh`][dream] 45–58 | No hay nada programado (plan maestro §10: «sin ejecución nocturna hasta autorización») | — | Sin calendario: lo pide la persona, y el harness puede avisar de que hay hallazgos |
| **Deduplicación** | El curador lee el destino antes de escribir («para no duplicar»). El Sueño busca nombres parecidos (`difflib` > 0,72) y fusiona. Entre máquinas, `--ignore-existing` | [`curator-prompt.md.tmpl`][curprompt] 17; [`memoria-dream.sh`][dream] 164–174 | Decisiones: `decision_id` por título normalizado, más el SHA-256 de la fuente antes de preguntar al modelo (`decision_effect.py:172-208`, `decisions.py:94-99`). `memory maintain` informa de pares parecidos (`maintenance.py:270-283`) | Una identidad para las notas de aprendizaje | Identificador por contenido normalizado y tipo (§4.1). La deduplicación débil por título ya está escrita (`README.md:439`) |
| **Recuerdo y contexto** | `SessionStart`: banner, aviso «datos, no instrucciones», `_project.md` (3000 B), última sección de `contexto-reciente` (1500 B), índice de agentes (1000 B), `INDEX.md` compartido (800 B), unos 6 KB. Además, Read/Grep libres sobre el vault y `MEMORY.md` por la auto-memoria nativa | [`memoria-load.sh`][load] 89–157 | `memory context` y `ask --project`: nota del proyecto, `Decisiones/`, `Lecciones/`, `Memoria-CC/` (si declaran proyecto) y 3 sesiones; 8192 B por defecto (`config.py:16`); notas de 3000 B como máximo; reparto por secciones; nonce (`context.py:33-47`, `:100-184`); `memory search` (`search.py:57-108`) | Preferencias globales y `contexto-reciente` | Ninguna lectura gasta un envío, pero cada byte viaja en **cada** pregunta. El tope importa más aquí que allí |
| **Privacidad y redacción** | Patrones por prefijo de proveedor (Anthropic, OpenAI, GitHub, GitLab, AWS, Google, Slack, DigitalOcean, Stripe, JWT, PEM). Con perfil `work`, una línea de confidencialidad en los prompts; la unión de conocimiento se niega a correr | [`redact.py`][redact] 16–43; [`install.sh`][install] 105–108; [`docs/arquitectura.md`][arq] 98–101 | La misma familia de patrones en `harness/text/redaction.py` (`README.md:307`), aplicada a todo lo que sale del vault y a todo contenido que se aprueba (`approvals.py`, `normalise_content`) | Nada nuevo en la redacción | Lo que el modelo propone es contenido de Copilot: se muestra entero, solo lo aprobado va al vault y nunca a SQLite (§5.2) |
| **Escritura atómica** | `atomic_write`: temporal `.tmp.XXXXXX` y `mv -f` (**sustituye**) | [`common.sh`][common] 41–51 | Temporal oculto con `O_EXCL` y publicación por enlace duro, que **falla** si el nombre existe (`decisions.py:330-372`) | — | Se conserva la del harness: nunca sustituir |
| **Aviso «datos, no instrucciones»** | Un párrafo antes del bloque inyectado | [`memoria-load.sh`][load] 116–126 | El mismo aviso, más delimitadores con nonce que una nota no puede falsificar (`context.py:41-47`) | — | — |

### 2.2 Lo que el propio original no cumple (útil para no copiarlo)

- **[R]** El README dice que la carga inyecta «el índice de lecciones» ([README][readme], línea 32). El script inyecta `_project.md`, `contexto-reciente`, el índice de **agentes** y el `INDEX.md` compartido ([`memoria-load.sh`][load] 104–107). `MEMORY.md` llega por la auto-memoria nativa de Claude Code, y el repositorio no muestra cómo queda `Memoria-CC/` enlazada a ella **(no verificado)**.
- **[R]** `Decisiones/` está en la arquitectura y en la comprobación por `mtime`, pero ni se crea ni el curador puede escribir allí (tabla de §2.1).
- **[R]** La convención no incluye `description:`, pero `/memory-maintenance` marca como defecto una nota de `Memoria-CC/` sin `description` ([`skills/memory-maintenance.md`][maint] 57). El formato real de esas notas mezcla el del curador y el de la auto-memoria nativa **(no verificado)**: el repositorio no trae ninguna nota de ejemplo de `Memoria-CC/`.

### 2.3 Lo que el lector y la fixture del harness hacen mal

Se comparó cada fichero de `tests/fixtures/vault-synthetic/` con las plantillas y los scripts del commit leído.

| # | Diferencia | Real (fuente) | Fixture / harness | Efecto |
|---|---|---|---|---|
| 1 | Tipo de lección | `type: lesson` ([`curator-prompt`][curprompt] 35; [`add-frontmatter.py`][addfm] 20) | `type: leccion` (`Lecciones/*.md`) | Ninguno en el código, que no mira el valor. La fixture enseña un tipo inexistente y lo mostraría en la cabecera |
| 2 | Tipo de los curados de `Memoria/` | `type: curated`, `tags: [memoria, <tema>]` ([`templates/memoria-curada/`][tpl]) | `type: memoria`, `tags: []` | Igual que el 1 |
| 3 | `_index.md` | `type: reference`, sin `created`, cuerpo regenerado ([`capture`][capture] 430–466) | `type: index`, con `created` | Con el real, `memory maintain` informa `invalid_frontmatter (created is not YYYY-MM-DD)` |
| 4 | Agentes | `agents/skills/<tipo>.md` con `type: reference` y `agent_type`, más `agents/_skills-index.md` sin `created` ([`capture`][capture] 354–427) | `agents/revisor.md` con `type: agent` | Ruta y tipo inventados. `_skills-index.md` real también sale como frontmatter no válido |
| 5 | `_project.md` sin `created` | La captura no escribe `created` ([`capture`][capture] 277–287) | La fixture lo lleva | **Cada `_project.md` real** sale en `invalid_frontmatter` de `memory maintain` (`notes.py:171-174`). Falso positivo sistemático |
| 6 | Cuerpo y etiquetas de `_project.md` y de las sesiones | `project:` = las dos últimas partes de la ruta; secciones `Memoria de Claude Code` e `Historial de sesiones`; sesiones con `tags: [claude-code, <slug>]` y secciones fijas | `project: Demo Alpha`, `tags: [sesion, …]`, una frase | El contexto real lleva mucho más ruido (rutas de ficheros, estado git, ruta del transcript). La fixture no mide cuánto ocupa una sesión real dentro de los 8 KB |
| 7 | Forma del slug | `vault_slug` de la ruta completa, con el nombre de usuario dentro y los espacios y acentos conservados ([`common.sh`][common] 30–32) | `demo-alpha` | `validate_project_slug` (`paths.py:26`) **rechaza** un proyecto real cuya ruta tenga espacios, acentos u otros caracteres fuera de `[A-Za-z0-9._-]`, o más de 128 caracteres. No medido sobre un vault real |
| 8 | Pertenencia al proyecto de las notas curadas | El curador escribe `tags: []` y nunca `project_slug` ([`curator-prompt`][curprompt] 33–40) | `project_slug` y etiqueta del proyecto en `Lecciones/` y `Memoria-CC/` | **Las lecciones y notas `Memoria-CC/` reales no entran nunca** en `memory context` (`notes.py:183-204`). El design de `project-memory` ya lo temía («Pocas notas curadas declaran proyecto»), y aquí se confirma desde el prompt |
| 9 | `Decisiones/` | Sin formato en el repositorio público | `type: decision` con `project_slug` | Formato propio del harness, presentado en la fixture como si fuera del sistema original |
| 10 | `machine:` en lo que escribe el harness | «`machine:` siempre indica dónde se originó» ([`convenciones`][conv] 16) | La nota de decisión no lo lleva (`decisions.py:203-215`) | Una nota del harness no dice de qué máquina viene, y en un vault unido entre máquinas eso se pierde |
| 11 | `contexto-reciente.md` | Secciones `## YYYY-MM-DD`; la carga inyecta la última | Una frase sin secciones | El harness no lo lee en el contexto (decisión de diseño). La fixture no sirve para probar una lectura futura |
| 12 | Índice con enlaces fuera de `Memoria-CC/` | `MEMORY.md` enlaza `../Lecciones/…`, que son válidos; el Sueño resuelve la ruta con `os.path.exists` ([`dream`][dream] 141–162; commit `7fc9037` del original) | `_index_audit` antepone `Memoria-CC/` sin normalizar (`maintenance.py:262-265`) | Cada enlace `../Lecciones/x.md` sale como **`index_dangling`**: el falso positivo que el original corrigió porque «invita al modelo a borrarlos» |
| 13 | `description:` sin comillas con `: ` | Rompe el YAML; el original lo trata como defecto ([`dream-prompt`][dreamprompt] 31; [`memory-maintenance`][maint] 40–58) | El parser parte por el primer `:` y lo acepta (`notes.py:117-134`) | `memory maintain` da por válida una nota que Obsidian y el original no indexan |
| 14 | Ámbito de huérfanos | Solo el primer nivel de `Memoria-CC/` (`os.listdir`) | Toda nota bajo `Memoria-CC/`, también en subcarpetas (`maintenance.py:186-187`) | Diferencia menor de recuento |
| 15 | Ficheros que la fixture no tiene | `Memoria/preferencias.md`, `proyectos-activos.md`, `perfil.md`, `Memoria/Suenos/`, `agents/_skills-index.md`, `MEMORY-<tema>.md`, `Lecciones/_INDEX.md`, `Decisiones/_INDEX.md` | Ausentes | Ningún test cubre su lectura ni su auditoría |

Lo que sí coincide **[R]**: nombres de las sesiones `YYYY-MM-DD-HHMMSS.md`, frontmatter de sesión, listas en línea y en bloque, `Memoria/Archivo/` fuera de la lectura, temporales ocultos ignorados (`.tmp.XXXXXX`), umbrales de la fase 1 y el aviso del bloque.

---

## 3. Dónde el harness no debe copiar el original

1. **Escrituras automáticas.** El curador escribe sin que nadie lo vea, con la regla «si hay duda, guarda» ([`curator-prompt`][curprompt] 5). Aquí toda escritura en el vault es una nota nueva aprobada por su hash. Una nota mala afecta a **todas** las sesiones futuras (plan por hitos, «Riesgos que el plan no quita»). La regla se invierte: si hay duda, se propone y la persona decide.
2. **Llamadas al modelo en segundo plano.** El curador y la fase 2 son `claude -p` que el usuario no ve. Hubo días con seis curadores en doce minutos y el 20 % de la cuota gastada ([`memoria-curator.sh`][curator] 109–145), y cuatro Sueños a la vez con el 49 % ([`memoria-dream.sh`][dream] 31–43). Aquí cada llamada es un **envío visible a Copilot** desde la ventana de Edge, con su presupuesto. No existe el «de fondo»: o lo pide la persona o no ocurre. Tampoco tiene sentido el `exit 2` que despierta la sesión, ni el contador de sesiones sin curar.
3. **Editar y sustituir ficheros.** `atomic_write` hace `mv -f`, el curador edita `MEMORY.md` y los curados de `Memoria/`, y el Sueño fusiona y reescribe. El harness solo crea, con enlace duro, y nunca sustituye (`decisions.py:435-456`). Editar un fichero existente con aprobación sería otra capacidad, con su propio diff exacto (como el paso 2.2 del plan para la carpeta de trabajo), y no entra en estos tramos.
4. **Ejecutar algo que venga del vault.** El original hace `source` de `memoria.env`, renderiza nombres de fichero del vault dentro del prompt (y tuvo que blindar la migración 006 contra un nombre como `preferencias$(cmd).md`: commit `78d075b`) y enlaza `skills/*.md` como comandos. El harness nunca carga un Skill, un hook ni una configuración desde el vault (estudio de hooks, §6.3). Una nota es dato, también la que escribió el propio harness.
5. **Mover ficheros por manifiesto.** `_mover.txt` es una buena idea para un proceso sin Bash: el modelo pide y el script valida. Aquí el modelo tampoco mueve nada, y la persona aprueba cada propuesta. Archivar sería un efecto propio, para más tarde (§4.4).
6. **Unión entre máquinas y sincronización.** El harness no copia ni sube el vault (`README.md:311`) y no tiene perfil `work` ni `personal`. No se copia `sync-knowledge.sh`. Lo que el harness escriba en `Memoria-CC/` viajará con la unión del original si esa máquina la tiene: es un efecto del original, no del harness, y se documenta.
7. **Extraer «aprendizajes» por palabras clave.** La captura toma como aprendizaje cualquier línea con «importante», «clave» o «considerar» ([`capture`][capture] 158–167). En español eso marca casi cualquier respuesta. No se copia: los candidatos los propone el modelo y los filtra la persona.

---

## 4. Diseño del aprendizaje en el harness, por tramos

Todo lo de esta sección es **[I]**: una propuesta, no medida.

### 4.1 Tramo (a): `/remember <texto>`, sin envíos

**Qué hace.** En `chat`, `/remember [--kind feedback|user|reference|project|lesson] <texto>` convierte el texto de la persona en una nota con el formato del curador, la muestra entera en la caja de aprobación y, si se aprueba, la escribe como fichero **nuevo**. No pregunta al modelo: el texto ya es de la persona y el formato es determinista.

**Destino y tipo por defecto.** `--kind feedback` (el defecto), `user`, `reference` y `project` escriben `Memoria-CC/<kind>_<slug>.md`. `lesson` escribe `Lecciones/YYYY-MM-DD-<slug>.md`. El defecto es `feedback` porque la convención lo define como «corrección de comportamiento» ([`convenciones`][conv] 22), que es lo que el dueño pide aprender: sus preferencias y las correcciones que hizo.

**Nombre.** `<kind>_<slug>-<id8>.md`, con el `slug_for` actual (`decisions.py:107-125`): ASCII, `[a-z0-9-]`, 48 caracteres como máximo. El slug sale del título, y el título es la primera línea del texto cortada a 80 caracteres. El sufijo `-<id8>` evita choques sin leer el índice. El Sueño original compara nombres con un umbral de 0,72, y dos notas del mismo tema con sufijos distintos le saldrán como «duplicados candidatos». Eso es correcto: lo son.

**Frontmatter exacto** (orden fijo; ningún valor sale del texto de la persona salvo `description`):

```yaml
---
type: feedback
machine: <HARNESS_MEMORY_MACHINE>
created: 2026-11-28
updated: 2026-11-28
tags: [<project_slug>]
description: "<primera línea, una línea, comillas escapadas, ≤ 150 caracteres>"
memory_id: mem-<16 hex>
source: ai-harness
run_id: <run>
---
```

- Los cinco primeros campos son el frontmatter estándar del original. `description` va entre comillas, como exige su Sueño. `memory_id`, `source` y `run_id` son del harness: Obsidian y el original los ignoran, igual que ignoran hoy los de la nota de decisión.
- `tags` lleva el proyecto de la sesión si lo hay, y queda `[]` si no. Es la forma nativa en que el original liga una nota a un proyecto (sus sesiones llevan `<slug>` en `tags`), y la que `declares_project` ya entiende (`notes.py:183-185`). No se usa `project_slug` porque el curador original no lo escribe en `Memoria-CC/`.
- `memory_id = mem-` + 16 hex del SHA-256 de `ai-harness/memory/v1\n<kind>\n<project o ->\n<texto normalizado>` (NFKC, `casefold`, espacios colapsados, como `normalise_title`). Es la deduplicación: el mismo texto del mismo tipo y proyecto da el mismo identificador, y el harness se niega con `duplicate_memory` antes de pedir la aprobación.

**Cuerpo:**

```
# <título>

<texto de la persona, saneado, redactado e inerte (make_inert, _escape_line)>

## Procedencia

- /remember en la sesión <id corto>, ejecución <run>.
- Credenciales enmascaradas: <n>.
```

**Cómo se reutiliza lo que hay.**

- El escritor: `write_decision` (`decisions.py:330-372`) se generaliza a `write_new_note(root, folder, name, data, temp_name, ident, id_field)` con una lista cerrada de carpetas (`Decisiones`, `Memoria-CC`, `Lecciones`). Conserva la creación exclusiva, el enlace duro, la retirada si la carpeta cambió y `reconcile` por identificador y SHA-256. El test de lista blanca (`tests/security/test_memory_no_writes.py:31`, `:227`) sigue con **una** excepción, el módulo escritor, ahora con nombre genérico.
- El efecto: `vault.save_memory`, hermano de `vault.save_decision` (`decision_effect.py:63-249`), con `bind` (vault y día), `prepare` (render, confinamiento, deduplicación), `exclusive` (el mismo bloqueo `vault-decisions`, que pasa a llamarse `vault-notes`), `apply`, `reconcile`, `source_key` (SHA-256 del texto) y `early_refusal`.
- El motor: hoy un paso `validate` solo puede leer la salida de otro paso (`harness/skills/definition.py:101`, `ValidateStep.of`). `/remember` sería un Skill interno de dos pasos, `validate` (de la **entrada** `text`) y `approval` (efecto `vault.save_memory`), y para eso `of` tiene que poder nombrar una entrada. Es un cambio pequeño del motor y deja gratis la persistencia del paso, `skill resume`, `skill cancel` y la reconciliación. La alternativa (llamar al efecto desde la conversación sin ejecución de Skill) perdería `uncertain` y `resume`.
- La caja de aprobación con botones (`approval-buttons`) y el hash de la propuesta (`approvals.py:24-28`) sin cambios. Como mucho 32 KiB de contenido.

**Coste:** cero envíos. **Tamaño:** M. **Demo:** con la fixture corregida, `/remember` → caja → nota en `Memoria-CC/` → `memory context` la muestra (con el tramo (c)), y un segundo `/remember` igual termina en `duplicate_memory`.

### 4.2 Tramo (b): propuesta al cerrar la sesión, un envío

**Qué tiene el harness y qué no.** Con Copilot, SQLite guarda las solicitudes con estado y fechas, pero **sin texto** (`README.md:712`, `service.py:548`). Guarda también la procedencia de las notas de memoria enviadas (`request_context`: ruta, SHA-256, bytes). El texto de la sesión solo lo tienen la conversación remota de Copilot y, mientras dura el proceso, la pantalla. Consecuencias:

- No hay transcript que dar a un curador. El único que «recuerda» la sesión es el propio modelo en esa conversación, así que la propuesta se pide **en la misma conversación**, como una pregunta más.
- La persona no puede comparar un candidato con una fuente local: lo comprueba con su propia memoria de la sesión. Por eso cada candidato lleva un campo `evidence` con lo que la persona dijo, según el modelo, y la caja dice que lo escribió el modelo.
- Una conversación larga puede haber salido ya del contexto del modelo. Copilot puede olvidar o inventar **(no medido)**.
- Con el Mock, que sí guarda el texto, la demo es reproducible.

**Cuándo.** Al cerrar (`/exit` o fin de entrada), si la sesión tuvo al menos una pregunta completada, el harness **ofrece** una sola vez: «¿Proponer notas de esta sesión? Cuesta 1 envío». También se puede pedir en cualquier momento con `/remember` sin texto. Sin un «sí», no se envía nada. El evento `conversation.end` del estudio de hooks no sirve como disparador, porque no puede esperar una respuesta. Esto es código propio del harness, no un hook.

**La pregunta.** Texto fijo del harness, fuera de los delimitadores, con un nonce nuevo. Pide un único bloque `json`:

```json
{"format": "ai-harness/memory-candidates/1", "nonce": "<16 hex>",
 "candidates": [
   {"kind": "feedback", "scope": "global",
    "title": "Respuestas en español y código en inglés",
    "description": "Idioma de las respuestas y del código",
    "body": "…", "evidence": "…"}
 ]}
```

- Campos cerrados. `kind` ∈ {`feedback`, `user`, `reference`, `project`, `lesson`}: **no** existen `persona` ni `perfil`, porque no se proponen datos de terceros. `scope` ∈ {`global`, `project`}. `title`: una línea de 8 a 120 caracteres. `description`: una línea de hasta 150. `body`: hasta 1500. `evidence`: hasta 300. Como mucho 5 candidatos, y `[]` es una respuesta válida («nada que recordar»).
- Se lee con el lector de planes (`harness/mcp/plan.py:1-40`, `:247-287`): `split_fences` (`harness/skills/checks.py:123`), un solo bloque, nonce en su sitio y en ningún otro, `loads_strict` con tope de tamaño y profundidad, invisibles, NFC, `credential_in_*` y esquema cerrado con Pydantic. El primer fallo gana y se nombra. Una respuesta `uncertain` o truncada no se lee.
- Cada candidato válido pasa por el mismo render y el mismo efecto que `/remember`, y por **su propia** caja de aprobación. La persona aprueba o rechaza uno a uno, en orden. Rechazar uno no afecta a los demás. Los rechazados no se guardan en ningún sitio, porque con Copilot no se guarda texto.
- Un candidato con el mismo `memory_id` que una nota existente se descarta antes de la caja, y se dice cuál.

**Qué recibe el modelo.** Solo la pregunta fija y el nonce. La memoria del proyecto no se reenvía, porque ya está en la conversación. Tampoco va la lista de notas existentes: la deduplicación es local, por identificador.

**Coste:** un envío por propuesta, cero por aprobación. **Tamaño:** M–L (el lector se reutiliza, pero hay que medir con Copilot real si escribe el bloque bien, igual que en el tramo 3 de `code-mode`).

### 4.3 Tramo (c): que lo aprobado vuelva al contexto

Hoy una nota de `Memoria-CC/` sin proyecto no entra en ningún contexto (`notes.py:202-203`), y las preferencias son justo eso: globales.

- **Sección nueva `preferencias`**, **primera** del bloque, antes de `_project.md`. Lleva las notas de `Memoria-CC/` con `type` ∈ {`feedback`, `user`} que no declaran proyecto, ordenadas por `updated` descendente y después por ruta.
- **Tope propio:** como mucho 1500 bytes o una sexta parte del límite, lo que sea menor, fuera del reparto por partes iguales (`context.py:116-133`). Una preferencia no debe comerse la nota del proyecto. Con el límite por defecto de 8192 B quedan unos 6,6 KB para las otras cinco secciones. El original inyecta unos 6 KB en total ([`memoria-load.sh`][load] 104–107).
- **Qué notas** (§6, decisión 2): solo las que escribió el harness (`source: ai-harness`) o todas las globales del vault. Si entran todas, también entran las del curador original, escritas por un modelo sin supervisión a partir de transcripts que citan páginas web.
- Cada nota con la cabecera de siempre (`--- Memoria-CC/feedback_… (feedback, 2026-11-28)`) y dentro del mismo bloque con nonce. `request_context` registra su procedencia como hoy.
- `/context` y `memory context` las muestran. Una spec nueva en `project-context` («Preferencias globales en el contexto») con su escenario de tope.

**Coste:** cero envíos, pero hasta 1,5 KB más en cada pregunta con proyecto. **Tamaño:** S.

### 4.4 Tramo (d): Sueño asistido, más adelante

- **Fase 1:** ya existe como informe (`memory maintain --dry-run`), después de corregir los fallos 5, 12 y 13 de §2.3.
- **Fase 2 asistida:** la persona la pide (`memory dream`, sin calendario). Por cada par de `duplicate_candidates`, como mucho 10 por ejecución como en el original, el harness hace **un** envío con las dos notas marcadas como datos y pide un JSON cerrado: `{"action": "merge" | "keep_both", "title", "body", "supersedes": [ruta, ruta]}`.
- **Qué se aplica:** una nota **nueva** con `supersedes:` en el frontmatter, aprobada como cualquier otra. Las notas sustituidas **no se tocan**: el contexto deja de incluir una nota que otra sustituye. No se borra nada, nunca. Mover a `Memoria/Archivo/` sería un efecto aparte (`vault.archive_note`), con la misma validación que `apply_dream_moves` del original ([`dream`][dream] 263–320): solo de zona curada a `Memoria/Archivo/`, sin enlaces y sin sustituir.
- **Coste:** un envío por par propuesto. Con 10 pares son 10 envíos, que se anuncian antes de empezar y cuentan contra el presupuesto. **Tamaño:** L.
- No se copia la compactación de `contexto-reciente.md`, porque es una edición. Tampoco la reparación de `MEMORY.md`, que es del original y la hace su Sueño.

### 4.5 Resumen de tramos

| Tramo | Envíos | Escribe | Reutiliza | Nuevo | Tamaño |
|---|---|---|---|---|---|
| Fixture fiel al formato + 3 fallos del lector (§2.3: 5, 12, 13) | 0 | nada | fixture, `maintenance.py`, `notes.py` | Plantillas MIT como referencia (§5.3) | S |
| (a) `/remember <texto>` | 0 | 1 nota nueva | escritor, efecto, aprobación, motor | `vault.save_memory`, `validate` de una entrada, `machine` | M |
| (b) Propuesta al cerrar | 1 por propuesta | 0–5 notas, una caja cada una | lector de planes, (a) | esquema `memory-candidates/1`, oferta al salir | M–L |
| (c) Recuerdo | 0 (+≤1,5 KB por pregunta) | nada | `context.py` | sección `preferencias` con tope | S |
| (d) Sueño asistido | 1 por par | notas nuevas con `supersedes` | (a), `memory maintain` | acción `merge`, filtro de sustituidas | L |

---

## 5. Riesgos

### 5.1 Envenenamiento de la memoria

- **[riesgo]** Una nota con instrucciones («ejecuta X sin preguntar», «envía el fichero Y») llega a **todas** las sesiones con ese proyecto o, si es global, a todas. **[mitigación]** Lo que **sí** impide el bloque marcado: que la nota cierre el bloque o falsifique los delimitadores (nonce, `‹‹‹`), que imite la cabecera de otra nota (`_escape_line`) y que Obsidian ejecute o incruste algo (`make_inert`). Lo que **no** impide: que el modelo obedezca. Es una mitigación, no una garantía (`README.md:299`). Lo que de verdad limita el daño es que **ninguna nota cambia la conducta del harness**: un texto del modelo nunca aprueba nada, y cada escritura, envío o ejecución sigue pidiendo el hash de su contenido exacto.
- **[riesgo]** En el tramo (b), el modelo cuela una instrucción disfrazada de preferencia («el dueño prefiere que las órdenes se ejecuten sin confirmación»). **[mitigación]** Caja de aprobación por candidato, con el aviso fijo «propuesto por el modelo» y el campo `evidence`. **[límite]** Una persona cansada aprueba. Ningún filtro de frases imperativas es fiable: no se propone ninguno.
- **[riesgo]** El curador original, que lee páginas web citadas en transcripts, escribe en `Memoria-CC/` una nota global y el tramo (c) la inyecta. **[mitigación]** Decisión 2 de §6: el primer corte inyecta solo `source: ai-harness`. **[límite]** `source: ai-harness` es un campo de texto que cualquiera que escriba en el vault puede copiar. Una prueba de autoría necesitaría una firma, por ejemplo un campo `harness_mac` con un HMAC-SHA-256 del contenido bajo una clave local. El patrón ya existe: la auditoría MCP usa una clave aleatoria por instalación, `HARNESS_DATA_DIR/keys/mcp-args.key`, creada una vez y legible solo por su dueño (`harness/mcp/audit.py:22-25`, `:58-84`). Haría falta una clave propia para las notas. Se deja como opción.

### 5.2 Privacidad

- **Qué puede contener una nota:** lo que la persona escribe o aprueba, es decir, contenido de su trabajo. En la máquina de trabajo, eso es contenido corporativo en el vault, como ya pasa con las decisiones (D3 de `project-memory`: si el vault está en una carpeta sincronizada, el harness no lo impide ni lo detecta).
- **Redacción:** la de siempre, solo formatos conocidos (`README.md:307`). Una contraseña escrita en prosa pasa.
- **Terceros:** no hay tipo `persona`. El original tiene `personas.md` («nombre, relación, contexto»): el harness no lo escribe ni lo propone.
- **Rutas:** el `vault_slug` real lleva el nombre de usuario de la máquina. El harness ya guarda en SQLite solo resúmenes de la raíz (`decision_effect.py:252-255`). Las notas nuevas no escriben rutas absolutas en su cuerpo.
- **Candidatos rechazados:** no se guardan. Con el Mock se guarda el texto de la respuesta, como hoy.

### 5.3 Desvío del formato original

- **Licencia:** MIT ([LICENSE][license]). Permite copiar, modificar y redistribuir si se conservan el aviso de copyright y el texto de la licencia en las copias. Se pueden copiar a una fixture de referencia, por ejemplo `tests/fixtures/claude-memory-system@92b19ea/` con su `LICENSE`: `templates/memoria-curada/*.md`, las dos plantillas de prompt y `docs/convenciones.md`. **Choque a decidir:** el aviso de copyright lleva el nombre del autor, y el repositorio público del harness evita nombres de personas (guarda de `scripts/check_public_safety.py`). Conservar el aviso es obligatorio si se copia. La alternativa es no copiar nada y probar contra una **descripción** escrita a mano del formato, citando el commit (§6, decisión 4).
- **Test de formato:** con las plantillas copiadas, un test comprueba que lo que escribe el harness usa solo claves y tipos de la convención copiada (más las claves propias declaradas), fechas `YYYY-MM-DD` y `description` entre comillas. Otro test fija el commit copiado. Para detectar el desvío, un script manual (no en CI, necesita red) compara las plantillas y la lista de tipos de `docs/convenciones.md` del `HEAD` público con las copiadas. Un cambio es una tarea, no un fallo silencioso.
- **[riesgo]** El original cambia algo que no está en una plantilla (los campos de `_project.md` o de las sesiones viven dentro de `memoria-capture.sh`). **[mitigación]** El script manual compara también los bloques de frontmatter de `memoria-capture.sh` (líneas 221–233 y 277–287). **[límite]** Es una comparación de texto: puede saltar por un comentario.

### 5.4 Convivencia con el curador y el Sueño originales en el mismo vault

- **Atribución:** el curador cuenta como suyo todo `.md` de `Memoria/`, `Lecciones/`, `Memoria-CC/` y `Decisiones/` con `mtime` posterior a su arranque ([`curator`][curator] 253–256). El riesgo que el README ya anota para `Decisiones/` (`README.md:457`) se **amplía** a `Memoria-CC/` y `Lecciones/`. No se pierde nada, pero el log del curador queda mal.
- **Choque de nombres:** el curador puede crear `feedback_<slug>.md` con el mismo nombre en el mismo instante. El sufijo `-<id8>` lo hace improbable, y el enlace duro falla con `conflict` en vez de sustituir.
- **El Sueño original edita lo que escribe el harness:** puede fusionar una nota del harness con otra, cambiarle `updated` o el cuerpo, o archivarla en `Memoria/Archivo/`, que el harness no lee. Consecuencias: una ejecución en curso que se reconcilia por SHA-256 da `conflict` (raro, y queda `uncertain` para la persona), y un `/remember` igual a una nota archivada **no** se detecta como duplicado. Se acepta y se documenta: el vault es de la persona, y su Sueño tiene la última palabra.
- **Índice:** el harness no añade la línea a `MEMORY.md`. El Sueño original lo hará en la tarea 4 («huérfanos → agrega su línea»). Hasta entonces, `/memory-maintenance` y `memory maintain` la listan como huérfana. Es el comportamiento esperado y se escribe en el README.
- **Máquina sin el original:** en Windows el original no corre. Allí el harness será el único escritor, nadie indexará sus notas en `MEMORY.md` y no hay Sueño. Por eso el tramo (c) no depende del índice: lee las notas directamente.

---

## 6. Decisiones abiertas para el dueño

1. **Destino de `/remember` por defecto.** (a) `Memoria-CC/feedback_<slug>-<id8>.md`, `type: feedback`. (b) `Lecciones/YYYY-MM-DD-<slug>.md`, `type: lesson`. (c) Una línea añadida a `Memoria/preferencias.md`, que exige editar un fichero existente con diff aprobado. **Recomiendo (a):** es lo que el original define como corrección de conducta, es un fichero nuevo y entra en la unión de conocimiento. (c) es lo más fiel al sitio de las preferencias, pero abre la edición del vault, que es otra capacidad.
2. **Qué notas globales vuelven al contexto (tramo c).** (a) Solo `source: ai-harness`. (b) Todas las `feedback`/`user` globales del vault. (c) (a) más una firma HMAC local. **Recomiendo (a)** en el primer corte y (c) si el vault lo comparten otros escritores. (b) mete en cada pregunta texto escrito por un modelo sin supervisión.
3. **`machine:`.** (a) Una variable obligatoria, `HARNESS_MEMORY_MACHINE`, sin la cual `/remember` se niega. (b) El hostname, como el original. (c) Un valor fijo (`ai-harness`). **Recomiendo (a):** el hostname de un equipo corporativo puede identificar a la empresa, y (c) rompe el sentido del campo en un vault unido.
4. **Referencia del formato.** (a) Copiar las plantillas y `convenciones.md` con su `LICENSE` como fixture de referencia, aceptando el aviso de copyright con el nombre del autor (excepción revisada para la guarda). (b) Una descripción propia del formato, citando el commit, sin copiar nada. **Recomiendo (a) si el dueño acepta la excepción, y si no, (b).** Con (a) el test compara contra el original byte a byte; con (b), contra lo que alguien leyó.
5. **Nota de sesión propia.** (a) Ninguna: el harness no escribe en `projects/`, que es de la captura. (b) Una nota de sesión del harness solo con metadatos (número de preguntas, estados, notas de memoria usadas). **Recomiendo (a):** respeta el «ownership disjunto», y (b) aportaría poco sin el texto.
6. **Declarar el formato de decisión como propio.** (a) Escribir en el README y en la fixture que `type: decision` y su frontmatter son del harness, y añadir `machine:` a la nota de decisión. (b) Dejarlo como está. **Recomiendo (a):** es el fallo 10 de §2.3, y la fixture no debe enseñar como original lo que no lo es.
7. **Oferta al cerrar.** (a) Ofrecer una vez al salir, si hubo preguntas completadas. (b) Solo con `/remember` sin texto, sin ofrecer nada. **Recomiendo (a):** el plan pide «captura al cerrar la sesión», y la oferta no envía nada sin un «sí».
8. **Orden de los tramos.** (a) Fixture y fallos del lector, después (a), (c), (b) y (d). (b) Lo mismo con (b) antes que (c). **Recomiendo (a):** con (a)+(c) ya hay un ciclo completo de punta a punta sin gastar envíos, y (b) depende de medir Copilot real.

Tamaños (S ≈ un tramo de un día, M ≈ dos o tres, L ≈ una semana; **[I]**, no medidos): fixture y fallos del lector **S**; (a) **M**; (c) **S**; (b) **M–L**; (d) **L**.

---

## Verificado frente a supuesto

**Leído en `claude-memory-system` `92b19ea`:** `README.md`, `LICENSE`, `VERSION`, `docs/arquitectura.md`, `docs/convenciones.md`, `docs/runbook-uso.md`, `docs/runbook-admin.md`, `config/memoria.env.example`, `install.sh`, `scripts/memoria-load.sh`, `memoria-capture.sh`, `memoria-curator.sh`, `memoria-dream.sh`, `scripts/lib/common.sh`, `scripts/lib/redact.py`, `scripts/migrate/add-frontmatter.py`, las cabeceras de `scripts/sync-knowledge.sh`, `scripts/systemd/memoria-dream.timer`, las seis migraciones, los cinco `skills/memory-*.md`, las cuatro plantillas de `templates/memoria-curada/` y las dos de prompt, y el historial de commits. No se leyeron en detalle `sync-obsidian.sh`, `resolve-`/`triage-knowledge-divergence.sh` ni los dos `selftest-*`, porque no tocan el formato de las notas.

**Leído en `ai-harness` `8a8afbd`:** `openspec/config.yaml`, `README.md` (memoria, Skills de arquitectura, qué se guarda), `harness/memory/*.py`, `harness/skills/decision_effect.py`, `effects.py`, las cabeceras de `approvals.py`, `definition.py` (`ValidateStep`), `skills/architecture-memory/workflow.json`, la cabecera de `harness/mcp/plan.py`, `tests/fixtures/vault-synthetic/` completo, el design y la propuesta archivados de `project-memory`, el plan maestro v0.4 §10, el plan por hitos y el estudio de hooks.

**No verificado:** cómo queda `Memoria-CC/` enlazada a la auto-memoria nativa de Claude Code (no está en el repositorio); el formato real de una nota de `Memoria-CC/` (no hay ejemplo en el repositorio); que un vault real tenga slugs con espacios o de más de 128 caracteres (fallo 7: deducido de `vault_slug`, no medido); que Copilot escriba un bloque `memory-candidates/1` válido y recuerde una sesión larga; los tamaños de los tramos.

---

## Fuentes

Repositorio `wilson-romero/claude-memory-system`, commit `92b19ea59716fc811f02b4a59fbc0daeb30aa7d0`:

[readme]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/README.md
[license]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/LICENSE
[arq]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/docs/arquitectura.md
[conv]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/docs/convenciones.md
[install]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/install.sh
[load]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/memoria-load.sh
[capture]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/memoria-capture.sh
[curator]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/memoria-curator.sh
[dream]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/memoria-dream.sh
[common]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/lib/common.sh
[redact]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/lib/redact.py
[addfm]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/migrate/add-frontmatter.py
[syncobs]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/sync-obsidian.sh
[syncknow]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/sync-knowledge.sh
[timer]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/scripts/systemd/memoria-dream.timer
[m001]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/migrations/001-vault-skeleton.sh
[curprompt]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/templates/curator-prompt.md.tmpl
[dreamprompt]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/templates/dream-prompt.md.tmpl
[tpl]: https://github.com/wilson-romero/claude-memory-system/tree/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/templates/memoria-curada
[skills]: https://github.com/wilson-romero/claude-memory-system/tree/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/skills
[maint]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/skills/memory-maintenance.md
[promote]: https://github.com/wilson-romero/claude-memory-system/blob/92b19ea59716fc811f02b4a59fbc0daeb30aa7d0/skills/memory-promote.md

- README, LICENSE, `docs/arquitectura.md`, `docs/convenciones.md`: [README][readme], [LICENSE][license], [arquitectura][arq], [convenciones][conv].
- Scripts: [install.sh][install], [memoria-load.sh][load], [memoria-capture.sh][capture], [memoria-curator.sh][curator], [memoria-dream.sh][dream], [common.sh][common], [redact.py][redact], [add-frontmatter.py][addfm], [sync-obsidian.sh][syncobs], [sync-knowledge.sh][syncknow], [memoria-dream.timer][timer], [migración 001][m001].
- Plantillas y comandos: [curator-prompt.md.tmpl][curprompt], [dream-prompt.md.tmpl][dreamprompt], [memoria-curada/][tpl], [skills/][skills], [memory-maintenance.md][maint], [memory-promote.md][promote].
