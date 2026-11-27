# Proposal

## Why

`shell-appearance` (PR #25) dejó la conversación con colores, edición de línea y completado sobre una conversación que se desplaza. Wilson la probó el 2026-11-26 y respondió: «es muy sencilla, esperaba algo más como OpenCode». Ese mismo día eligió una **aplicación de pantalla completa construida con Textual**, con cuatro piezas y la maqueta que aprobó:

1. Pantalla completa con paneles: la conversación con su propio desplazamiento, la entrada fija abajo y una barra de pie.
2. Un panel lateral de contexto: nombre e id8 de la sesión, proyecto, proveedor, notas de memoria incluidas en la última pregunta (número y lista), envíos y estado de la última petición.
3. Una paleta de órdenes y selectores visuales: un atajo abre una lista filtrable de órdenes; con selectores se cambia de sesión, se elige una Skill y se adjunta un fichero, en lugar de escribir `/resume 2`.
4. Mensajes como bloques con estilo: el turno de la persona; la respuesta del proveedor con Markdown resaltado; la aprobación en su propia caja con destino y hash.

Referencia: la parte de interfaz de `docs/estudios/2026-11-25-arquitectura-opencode.md` (OpenCode separa el núcleo de sus clientes; la TUI es uno). Solo la idea: ni el nombre, ni el logo, ni el aspecto exacto de OpenCode.

Pertenece al **Corte 9 · Interfaz conversacional**, tercera entrega. Riesgo **N1**: no toca datos ni proveedores, pero sí la frontera entre texto ajeno y texto del harness y la vía por la que llega la aprobación. SEC que cubre: **SEC-02** (el panel y la barra describen solo la sesión tomada), **SEC-07** (Ctrl+C cancela la pregunta sin reenviarla), **SEC-12** (la aprobación sigue ligada al hash, y su código no se guarda ni se ofrece) y **SEC-15** (el texto ajeno sigue acotado, saneado e inerte). Se demuestra en **macOS**; Windows queda como ejecución pedida a Wilson (ver «Supuestos de Windows» en `design.md`).

## What Changes

- **Dependencia: `textual==8.2.8`** (MIT), que trae `rich`, `markdown-it-py`, `mdit-py-plugins`, `linkify-it-py`, `uc-micro-py`, `mdurl`, `platformdirs`, `pygments` y `typing-extensions`. **Se quita `prompt_toolkit`** y con él la terminal con estilo de `shell-appearance` (`harness/shell/styled.py`): quedan dos modos, pantalla completa y texto plano (D1).
- **Pantalla completa** (`harness/shell/tui.py`, el único módulo que importa Textual): conversación desplazable, panel lateral, entrada fija y pie con los atajos (`ctrl+p` órdenes, `ctrl+c` interrumpe, `ctrl+n` sesión nueva, `ctrl+q` sale).
- **Bloques**: el turno de la persona, las líneas del harness y el texto ajeno, este dentro de un bloque con borde y título del harness (el nombre del proveedor o «text from outside the harness»). El Markdown es el subconjunto de `render.py`, que solo colorea; **no se usa el widget `Markdown` de Textual** (D3).
- **Paleta y selectores**: la paleta lista solo órdenes del harness (ni tema, ni captura, ni las de sistema). Selectores de sesión (lista la misma que `/sessions` y envía `/resume N`), de Skill (rellena `/skill NOMBRE `) y de fichero (envía `/file RUTA`).
- **Caja de aprobación**: una pantalla modal con la cabecera del motor, el contenido propuesto en un área de texto ajeno y su propia entrada, que no guarda historial, no admite pegar y rechaza respuestas llegadas antes de `ARM_S` (0,5 s).
- **Núcleo sin bifurcar**: la pantalla completa y el texto plano conducen la misma `Conversation`. Se añaden dos lecturas a `ShellState` (`panel`, `sessions`), el protocolo `ApprovalTerminal` y la lista de notas de la última pregunta (D2, D4, D6).
- **Texto plano como respaldo**, el de hoy sin cambios: `--plain`, `HARNESS_PLAIN`, `NO_COLOR`, `TERM=dumb`, sin terminal, una variable de depuración de Textual puesta, o Textual que no carga. `scripts/verify.sh`, las demos y los tests de pseudoterminal del camino plano lo siguen usando.

**No entra:** texto que aparece poco a poco (streaming), ratón más allá de desplazar y elegir, temas, imágenes, enlaces pulsables, HTML, varias conversaciones a la vez, historial en disco, límite de envíos (no existe en esta rama: el panel muestra el número de envíos sin tope).

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `interactive-shell` (delta sobre la capacidad de los changes `interactive-shell` y `shell-appearance`, sin archivar): se **añaden** los requisitos de la pantalla completa. Este change **sustituye** a la terminal con estilo de `shell-appearance`: sus requisitos «Terminal con estilo y respaldo plano», «Edición e historial de entradas», «Indicador mientras el proveedor trabaja» e «Interrupción y aprobación en la terminal con estilo» describen `prompt_toolkit`, que se quita. Como ninguno de los dos está archivado, el delta va como requisitos añadidos; al archivar, `shell-appearance` se archiva primero y este delta se convierte en MODIFIED/REMOVED de esos cuatro (tarea 6.2). «Respuesta con formato y marca intacta», «Formato sin órdenes de terminal», «Línea de estado de la sesión tomada» y «Completado de comandos» siguen vigentes.

## Impact

- Código: `harness/shell/tui.py` (nuevo), `harness/shell/app.py` (elige y arranca la pantalla completa), `harness/shell/conversation.py` (panel, selector de sesiones, notas, caja de aprobación) y `harness/shell/terminal.py` (`PanelState`, `ApprovalTerminal`, dos campos de `ShellState`). Se borra `harness/shell/styled.py`.
- Fuera de `harness/shell/` y de sus tests: `pyproject.toml` y `uv.lock`, `README.md` y este change. Tests: `tests/tui_support.py` y `tests/unit/test_shell_tui.py` nuevos; `tests/integration/test_chat_styled_terminal.py` pasa a `test_chat_tui_terminal.py`; `tests/unit/test_shell_completion.py` pierde el adaptador de `prompt_toolkit`; se borra `tests/unit/test_shell_styled.py`.
- No toca `harness/cli.py`, `harness/core/service.py`, proveedores, cabeceras de memoria ni `tests/shell_support.py` (ramas `feature/copilot-web-provider` y `feature/prompt-economy`). Conflicto probable con `feature/prompt-economy` en los imports de `conversation.py`.
- Sin migración ni datos nuevos.
