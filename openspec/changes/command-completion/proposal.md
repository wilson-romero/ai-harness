# Proposal

## Why

Wilson, el 2026-11-27, sobre la pantalla completa: «los comandos son demasiado verbosos y no se autocompletan». Las dos líneas que escribe hoy en la demo del Corte 9 y su longitud (contada sobre el texto, 2026-11-27):

| Línea de hoy | Caracteres |
|---|---|
| `/new --project demo-alpha` | 25 |
| `/skill architecture-memory --file source=tests/fixtures/skill-inputs/fuente-decision.md` | 87 |

Leído en `develop` `1611064` (2026-11-27): escribir `/` no muestra nada, porque no hay lista; Tab solo completa el nombre del comando y el primer argumento de algunos (`harness/shell/completion.py` anterior): no completa `--project` ni sus valores, ni las entradas de un Skill (`source=`), ni una ruta tras `--file NOMBRE=`. La única forma de ver los comandos es `/help`, que es otro texto distinto del analizador (dos listas que mantener a mano).

Con este change, las mismas dos órdenes se escriben así (contado con `Pilot` el 2026-11-27, tarea 4.9): `/new demo-a` y Tab, 12 teclas en vez de 25; `/sk` Tab `arch` Tab `tests/fi` Tab `sk` Tab `fu` Tab, 24 teclas en vez de 87. Lo que se ejecuta se ve entero antes de Intro.

Pertenece al **Corte 9 · Interfaz conversacional**, quinta entrega (tras `interactive-shell`, `shell-appearance`, `shell-tui` y `collapsible-blocks`). Riesgo **N1**: no toca datos, proveedores ni la aprobación, pero pone nombres que vienen de fuera del harness (ficheros, títulos de sesión, descripciones de Skills) en una lista de la pantalla, y añade formas cortas que se convierten en un comando distinto del escrito. SEC que cubre: **SEC-15** (lo ajeno que se ofrece se dibuja literal, acotado e inerte: no imita el cromo, no inyecta texto ni ejecuta nada) y **SEC-02** (las sesiones que se ofrecen y el proyecto de `/new` salen del estado del harness). No toca SEC-07 ni SEC-12; sus pruebas siguen igual. Se demuestra en **macOS**. Windows queda como ejecución opcional: el código no tiene ramas por plataforma (`tests/unit/test_portability.py`).

## What Changes

- **Una sola tabla de comandos** (`harness/shell/commands.py`): nombre, argumentos, uso, resumen, qué completa cada posición y sus opciones. De ella salen el analizador, `/help` y la lista de completado; ya no hay dos listas.
- **Lista de completado bajo la entrada** (pantalla completa):
  - `/` muestra los comandos con su resumen; al escribir se filtra, primero por principio y después por letras en orden (*fuzzy*).
  - Después del comando: sus opciones (`--project`, `--file`), los proyectos del vault, los Skills válidos con su descripción, las entradas que declara el Skill (`source=`), las sesiones (identificador, proyecto y título) para `/resume` y rutas para `/file`, `--file NOMBRE=` y la ruta corta de un Skill de una entrada.
  - Rutas relativas a la carpeta de trabajo, carpetas primero; `~/` lista la carpeta personal y se queda escrito `~/`; los nombres ocultos solo si lo escrito empieza por `.`; un enlace sale como nombre y nunca se sigue. El listado va en otro hilo, acotado a 100 000 entradas y medio segundo, y calla los errores.
  - Ninguna fila está elegida al abrirse (como Claude Code): Intro envía lo escrito; Tab pone la fila elegida o la primera; flechas eligen; Intro sobre una fila elegida la pone y no envía; Esc cierra. La lista nunca se queda con una tecla escrita ni envía nada.
- **Formas cortas** (las largas no cambian; las pruebas del analizador no cambian):
  - Nombre cortado: basta el principio de un comando si solo uno empieza así (`/sk` → `/skill`); si hay varios, es un error que los nombra y no se ejecuta nada.
  - `/new SLUG` → `/new --project SLUG` cuando `SLUG` es una carpeta de `projects/`; si no, sigue siendo el nombre de la sesión.
  - `/skill NOMBRE RUTA` → `/skill NOMBRE --file ENTRADA=RUTA` cuando el Skill declara exactamente una entrada y no se ha dado ya.
  - `/resume ID`: además del número de `/sessions`, el identificador entero o sus primeros 8 caracteres o más si solo una sesión empieza así.
  - `~/` en `/file` y `--file` es la carpeta personal.
  - Lo que se ejecuta se ve entero antes: el núcleo escribe `running: <comando entero>` antes de ejecutar una forma corta (también en `--plain`), y la pantalla completa lo enseña además en el borde de la entrada mientras se escribe.
- **Texto plano** (`--plain`): las mismas formas cortas, sin lista ni Tab. `readline` no entra (D5).

**No entra:**

- Menciones con `@` (adjuntar un fichero desde cualquier punto de una pregunta, como Codex y OpenCode). Hoy está `/file`.
- Que `/new` herede el proyecto de la sesión actual. Cambiaría lo que hace hoy `/new` sin argumentos y una prueba existente; queda como decisión abierta para Wilson.
- Texto fantasma (el resto del candidato en gris tras el cursor).
- Tab en el texto plano con `readline` (D5).
- Derivar de la tabla las entradas de la paleta (`ctrl+p`): siguen escritas a mano en `tui.py`.
- Nombres con espacios o comillas en la lista (no se ofrecen; se pueden escribir entre comillas como hasta ahora).

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `interactive-shell`, sin archivar, como en `shell-tui` y `collapsible-blocks`: se **añaden** los requisitos de la lista de completado, las formas cortas y la tabla única. Este change **sustituye** el requisito «Completado de comandos» de `shell-appearance`: aquel completaba el *número* de `/resume`; ahora se ofrece la sesión (identificador, proyecto y título) y se inserta su identificador entero, y `/resume N` sigue aceptando el número. Como `shell-appearance` no está archivado, el delta va como requisito añadido («Lista de completado bajo la entrada»); al archivar, pasa a MODIFIED de aquel (tarea 7.2).
- Comprobado con `grep -rn "complet\|/resume\|/new\|/skill\|Tab" openspec/specs/` (2026-11-27): las coincidencias son de `session-management`, `request-recovery`, `project-context`, `llm-provider` y `secret-redaction`, y hablan de solicitudes completadas (`completed`) o de las órdenes sueltas (`skill run`, `ask --project`), no de la conversación. Ninguna capacidad de `openspec/specs/` cambia.

## Impact

- **Código:** `harness/shell/commands.py` (nuevo, la tabla), `harness/shell/shortforms.py` (nuevo, formas cortas), `harness/shell/completion.py` (reescrito: motor de candidatos, orden, listado de carpetas), `harness/shell/parser.py` (lee la tabla; `parse_short`), `harness/shell/conversation.py` (`/help` de la tabla, eco `running:`, `/resume ID`, `~/`, datos para completar), `harness/shell/terminal.py` (`ShellState.completion`) y `harness/shell/tui.py` (la lista, la vista previa en el borde, las teclas). No cambian el motor de Skills, los proveedores, la base de datos ni la caja de aprobación. Sin SQL nuevo. Sin dependencias nuevas.
- **Fuera del código:** `README.md` («Conversación»: tabla de comandos, formas cortas, «Completar» y el paso a paso con el Mock en formas cortas) y este change.
- **Tests:** `tests/unit/test_shell_completion.py` reescrito (las pruebas del `complete()` anterior se van con él), `tests/unit/test_shell_shortforms.py` y `tests/unit/test_shell_tui_completion.py` nuevos, una prueba PTY más en `tests/integration/test_chat_tui_terminal.py`. Una línea de `tests/unit/test_shell_skills.py` cambia: `/skill demo-echo texto` era un error de forma y ahora es la forma corta de un Skill de una entrada; la prueba pasa a `texto otro`, que sigue siendo un error (tarea 3.3). Ninguna prueba del analizador cambia.
- **Ramas posteriores** que tocan `tui.py` (espaciado de la caja de aprobación y de toda la pantalla): el estilo de la lista vive en `SuggestionList.DEFAULT_CSS`, aparte del CSS de la aplicación, con cuentas de celdas sencillas.
- Sin migración ni datos nuevos.
