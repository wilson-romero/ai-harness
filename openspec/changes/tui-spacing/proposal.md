# Proposal

## Why

Wilson ve la pantalla completa «sin espaciado»: todo pegado de borde a borde. Medido el 2026-11-27 con Pilot y el Mock, sobre `481ad2e`:

- **Márgenes sueltos:** 1 columna al borde de la pantalla (`#log`, `#footer`), 1 dentro de los bloques y 0 delante de las líneas del harness. El texto de la persona, el del harness, el ajeno y el de la entrada empiezan en tres columnas distintas (3, 1 y 3).
- **Panel lateral fijo:** 34 columnas a cualquier ancho. A 80 columnas se lleva el 42 %: la conversación queda en 46 y el identificador de sesión se corta a media palabra.
- **Colores de la casa:** 10 colores hexadecimales en `harness/shell/tui.py`, fuera del tema, para los estilos de las filas, el chrome de los bloques plegados y el subtítulo del recuadro ajeno.
- **La marca de la persona:** una barra `thick $accent`. En el tema por defecto `$accent` es el mismo color que `$warning`, el del marco de la aprobación.

**Filas de conversación visibles hoy** (dos turnos con el Mock):

| Tamaño | Filas |
|---|---|
| 80×24 | 20 |
| 100×30 | 26 |
| 120×40 | 36 |

El estudio `docs/estudios/2026-11-27-sistema-de-diseno-tui.md` propone la escala y los alias. Wilson decidió el 2026-11-27 (§8):

1. **Colores y escala.** Variables de tema de Textual para todo color, con alias semánticos. La escala de la casa: columnas 0/1/2/4/8, filas 0/1/2, y 1 fila = 2 columnas.
2. **Panel lateral (D1).** Oculto por debajo de 100 columnas, con sus datos en `/status`.
3. **Mensajes de la persona (D2).** Barra, fondo suave propio y una fila de separación. Tiene que seguir distinguiéndose en los temas ANSI, donde el fondo es transparente: la barra lo lleva.
4. **Lo demás (D3–D6).** Según la recomendación del estudio.

La caja de aprobación ya está sobre la escala desde `feature/tui-8pt-grid` (`approval-buttons` D7).

Pertenece al **Corte 9 · Interfaz conversacional**, tras `collapsible-blocks`. Riesgo **N1**: no cambia qué se escribe ni qué se aprueba, pero sí cómo se ve el texto ajeno junto al chrome del harness. SEC que cubre:

- **SEC-15:** el texto ajeno no puede tomar el aspecto del chrome. Ningún estilo de texto ajeno usa el color de un estado del harness, un fondo ni `reverse`, y el chrome se reconoce por su forma.

Se demuestra en **macOS**. Windows (conhost y Windows Terminal, sobre todo los bordes `hkey` y `tall`) queda como comprobación opcional en la máquina de pruebas; no es una puerta.

## What Changes

- **Colores (D1):** `harness/shell/palette.py` nombra cada rol y lo apunta a una variable del tema. El CSS de la pantalla los declara como variables, y `STYLES` y el chrome de los bloques plegados los toman. No queda ningún hexadecimal en `tui.py`.
- **Panel lateral (D2):** se oculta por debajo de 100 columnas. Pasa de 34 a 32 columnas, con relleno de 2. `/status` añade lo que solo daba el panel: `sends: N` y `memory: N note(s) in the last question`, con los nombres de las notas.
- **Mensajes de la persona (D3):** barra `thick` en `$you-bar` (`$primary`), fondo `$you-fill` (`$boost`) y una fila encima.
- **Una sola columna para el texto (D4):**
  - 2 columnas al borde de la pantalla, en la conversación, la entrada y el pie;
  - 1 columna dentro de la barra o del marco de un bloque, y 2 delante de las líneas del harness.

  Todo el texto empieza en la columna 4.
- **Huecos verticales según el alto (D5):**
  - desde 30 filas, una fila entre bloques, también delante de las líneas del harness, salvo encima del primer bloque del panel;
  - por debajo de 30, sin esas filas, y la entrada pasa a una fila de texto bajo una raya `hkey`, de 2 filas en lugar de 3. Solo es CSS: el widget de la entrada no cambia.
- **Marco del texto ajeno neutro (D6, la D3 del estudio):** `$foreground-muted`, ni `$secondary` ni un color de estado.
- **Lo que no cambia (D7, D4–D6 del estudio):**
  - el tema sigue fijo en `textual-dark`;
  - sin ancho máximo de la prosa;
  - el fondo es refuerzo y la forma es la marca.

**No entra:**
- un selector de tema y los temas claros;
- iconos;
- reordenar ni rehacer la entrada (`feature/command-completion` añade un desplegable debajo; este change solo toca su CSS);
- la sangría de los valores del panel lateral (las pruebas de `shell-tui` la fijan en 1 columna);
- cambiar el texto de los bloques;
- cualquier cosa del modo plano salvo las dos líneas nuevas de `/status`.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

- `interactive-shell`: delta sobre los changes `shell-tui`, `collapsible-blocks` y `approval-buttons`, sin archivar. Se añaden los requisitos de la escala y del tema de la pantalla completa. Un `grep` en `openspec/specs/` confirma que `interactive-shell` aún no está en las specs vigentes. El delta va como ADDED y se convierte al archivar (tarea 5.1).

## Impact

- **Código:**
  - `harness/shell/palette.py` (nuevo);
  - `harness/shell/spacing.py` (borde, sangría, ancho del panel, *breakpoints*);
  - `harness/shell/tui.py` (CSS, `STYLES`, `CHROME`, `Turn.add`);
  - `harness/shell/conversation.py` (`/status`).
- **Pruebas:**
  - `tests/unit/test_shell_tui_spacing.py` (nuevo);
  - `tests/unit/test_shell_tui_blocks.py`: el ayudante que localiza el fondo del chrome lo lee del tema en vez de un hexadecimal. Ninguna aserción cambia.
- **Documentación:**
  - `README.md` («Conversación › Aspecto»);
  - el estudio no se toca.
- **Dependencias:** ninguna nueva.
