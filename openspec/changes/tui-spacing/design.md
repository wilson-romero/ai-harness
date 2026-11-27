# Design

## Context

La pantalla completa (`shell-tui`, `collapsible-blocks`) sale de un solo bloque de CSS en `HarnessApp.CSS`, escrito en `ac57cff` con márgenes de 0 o 1 sueltos. Ni el diseño de `shell-tui` ni el de `collapsible-blocks` dicen nada de espaciado ni de densidad. «Temas» figura como fuera de alcance. Es una omisión, no una decisión.

La caja de aprobación ya está sobre la escala desde `approval-buttons` D7, con `harness/shell/spacing.py` y sus variables CSS. Este change lleva esa misma escala y unos alias de color al resto de la pantalla.

Premisas medidas aquí (2026-11-27, Textual 8.2.8 instalado):

- **Breakpoints.** `App.HORIZONTAL_BREAKPOINTS`/`VERTICAL_BREAKPOINTS` ponen las clases en cada pantalla. Una pantalla que define los suyos, como `ApprovalScreen`, sustituye los de la aplicación.
- **Estilos de `Content`.** Aceptan variables del tema y las resuelven al dibujar:
  - en `textual-dark`, `"$text-secondary"` → `#5684a5`;
  - en `ansi-dark`, `ansi_cyan`.

  `"$text-muted"` (`auto 60%`) se dibuja **blanco**. Por eso las filas atenuadas siguen con `dim` y no con `$text-muted`.
- **En `ansi-dark`:**
  - `$panel-lighten-1` y `$boost` resuelven a transparente;
  - `$text-error`, `$text-warning`, `$text-primary` y `$text-secondary` son rojo, amarillo, azul y cian ANSI.
- **El pie y la entrada se acoplan los dos abajo.** El `margin-bottom: 1` de la entrada es la fila del pie, no un hueco. Si se quita, la entrada tapa el pie.

## Goals / Non-Goals

**Goals:**
- ningún color de la casa;
- la escala en todos los contenedores;
- el panel solo donde cabe;
- la persona marcada por la forma;
- una columna de texto;
- huecos verticales solo donde sobran filas.

**Non-Goals:**
- temas y selector;
- ancho máximo de prosa;
- rehacer la entrada;
- iconos;
- la sangría interna del panel lateral.

## Decisions

### D1 · Colores solo por roles con nombre, sobre variables del tema

- **Qué:** `harness/shell/palette.py` define `ROLES`: rol → variable del tema. Ejemplos:
  - `approval-frame` → `$warning`;
  - `foreign-frame` → `$foreground-muted`;
  - `you-bar` → `$primary`;
  - `you-fill` → `$boost`;
  - `fold-fill` → `$panel-lighten-1`;
  - `error-text` → `$text-error`;
  - `code-text` → `$text-secondary`.

  El CSS declara los roles como variables (`$you-bar: $primary;`) y las reglas solo nombran roles o la escala. `STYLES` y `CHROME` toman el valor del rol. Se quitan los 10 hexadecimales de `tui.py`:
  - `MD_HEADING` → negrita `$text-primary`;
  - `MD_BULLET` → `$text-primary`;
  - `MD_QUOTE` → `italic dim`;
  - `MD_LINK` → `underline`;
  - `HARNESS_ERROR` y `HARNESS_WARNING` → `$text-error` y `$text-warning`;
  - `CHROME` → `bold $foreground on $panel-lighten-1`.
- **Por qué:**
  - Decisión del dueño (§8.1).
  - Los hexadecimales ignoran el tema.
  - Con roles, «qué colores puede llevar el texto ajeno» es una lista que se prueba: nunca `error-text` ni `warning-text`, nunca un fondo, nunca `reverse`.
  - El fondo del chrome sigue siendo el único fondo de un estilo de fila, como pide `collapsible-blocks` D4.
- **Alternativas rechazadas:**
  - **`$text-muted` para lo atenuado:** se dibuja blanco, medido arriba.
  - **Un `Theme` propio de la casa:** es la D6 del estudio, abierta.
  - **El chrome sobre `$panel`:** es el fondo del pie, y entonces el chrome de un bloque y el pie no se distinguirían.
- **Impacto:**
  - spec `interactive-shell`, requisito «Colores del tema con nombre»;
  - `palette.py` y `tui.py`;
  - prueba: ningún hexadecimal en `tui.py`, `blocks.py` ni `palette.py`, y todos los roles resuelven en `textual-dark` y en `ansi-dark`;
  - el ayudante `_chrome_cells` de `test_shell_tui_blocks.py` lee el fondo del tema.

### D2 · El panel lateral solo desde 100 columnas

- **Qué:**
  - `HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]`;
  - `Screen.-narrow #side { display: none; }`;
  - el panel mide 32 columnas (antes 34) con 2 de relleno;
  - `/status` añade `sends: N`, `memory: N note(s) in the last question` y los nombres de esas notas.

  Lo demás del panel (sesión, proyecto, proveedor y última petición) ya estaba en `/status`.
- **Por qué:**
  - Decisión del dueño (D1 del estudio). A 80 columnas el panel se llevaba el 42 % de la pantalla.
  - 32 es par, de modo que la escala de columnas sigue cuadrando.
- **Alternativas rechazadas:**
  - **Una línea de estado de una fila:** ocupa una fila a todos los tamaños. El estudio la deja para más adelante.
  - **Dejarlo fijo:** es el problema de partida.
- **Impacto:**
  - spec, requisito «Panel lateral solo donde cabe»;
  - `tui.py`, `spacing.py` y `conversation.py` (`_cmd_status`);
  - pruebas a 80, 99, 100 y 120 columnas y de `/status`.

### D3 · Los mensajes de la persona: barra, fondo suave y una fila

- **Qué:** `.you` lleva:
  - `border-left: thick $you-bar` (`$primary`);
  - `background: $you-fill` (`$boost`);
  - `margin-top: 1` y `padding: 0 1`.

  En un tema ANSI el fondo es transparente y queda la barra. La prueba lo comprueba en `ansi-dark`: la celda de la barra no está vacía, y una línea del harness no tiene borde izquierdo.
- **Por qué:**
  - Decisión del dueño (D2 del estudio).
  - `$accent` es igual que `$warning` en `textual-dark`. Con `$primary`, la barra ya no tiene el color del marco de la aprobación.
  - El fondo refuerza; la forma (la barra) es la marca (D7).
- **Alternativas rechazadas:**
  - **Prefijo `> ` y fondo, como Codex y Gemini:** cambia el texto del bloque y su prueba.
  - **Solo la barra:** es lo que había.
- **Impacto:** spec, requisito «Mensajes de la persona marcados por la forma»; CSS; dos pruebas.

### D4 · Una columna para todo el texto

- **Qué:**
  - `EDGE = 2` columnas al borde, en `#log`, la entrada (como margen) y `#footer`;
  - `BLOCK_INSET = 1` dentro de la barra o del marco de un bloque;
  - 2 delante de las líneas del harness y del resumen de un turno.

  Todo empieza en `TEXT_COLUMN = 4`: lo que escribe la persona, el harness, el texto ajeno y la entrada.
- **Por qué:** alinear el texto a una rejilla es la mitad de lo que pide el dueño; la otra mitad son los huecos (D5). Con una sola columna, la vista distingue lo que es de quién por la forma, no por un desplazamiento.
- **Alternativas rechazadas:**
  - **`padding: 0 2` dentro de los bloques:** la columna sería la 5 y las líneas del harness necesitarían 3, que no está en la escala.
  - **Borde de 1:** deja el texto pegado al borde del terminal.
- **Impacto:** spec, requisito «Una columna para el texto»; prueba a los tres tamaños.

### D5 · Huecos verticales solo donde sobran filas

- **Qué:** `VERTICAL_BREAKPOINTS = [(0, "-short"), (30, "-tall")]`.
  - **Desde 30 filas:** una fila delante de cada bloque, también de las líneas del harness, que antes iban pegadas. El primer bloque del panel no la lleva (`-lead`, puesto por `Turn.add`), así que el panel empieza arriba.
  - **Por debajo de 30:**
    - las líneas del harness van sin hueco;
    - la entrada pasa a 2 filas, una raya `hkey` y la línea de texto, en lugar de 3 con borde `tall`;
    - la fila del pie sigue siendo suya.

  Solo es CSS. El modo de navegación pinta la raya en `$browse-frame`.
- **Por qué:** cada fila en blanco se gasta en filas enteras. A 80×24 la conversación gana una fila (de 20 a 21) aunque haya huecos entre bloques. A 100×30 y a 120×40 conserva las mismas filas visibles y gana aire entre bloques.
- **Alternativas rechazadas:**
  - **Huecos a cualquier altura:** a 80×24 costarían filas de conversación.
  - **`Input(compact=True)`:** cambia el widget, y `feature/command-completion` trabaja en esa zona.
- **Impacto:** spec, requisito «Huecos verticales según el alto»; pruebas a los tres tamaños, incluida la de que el pie siempre se ve.

### D6 · El marco del texto ajeno, neutro

- **Qué:** `foreign-frame` → `$foreground-muted`, en `.foreign` y en `#approval-content`.
- **Por qué:**
  - Es la recomendación del estudio (D3), que el dueño adopta para D3–D6.
  - El marco es estructura, no un estado. Así el color queda libre para los estados, y el marco no coincide con ningún estado, ni con la aprobación ni con la barra de la persona.
- **Alternativas rechazadas:**
  - **`$secondary` (lo que había):** casi invisible sobre el fondo, `#004578` sobre `#121212`.
  - **`$primary`:** es la barra de la persona.
- **Impacto:** spec, el requisito de colores; prueba del marco.

### D7 · Lo que no cambia

- **Qué:**
  - el tema sigue fijo en `textual-dark` (D6 del estudio: (a) por ahora);
  - sin ancho máximo de la prosa (D5 (a));
  - el fondo es refuerzo y la forma es la marca (D7 (a)).

  La sangría de los valores del panel lateral se queda en 1 columna: la fijan las pruebas de `shell-tui`.
- **Por qué:** es la recomendación del estudio para lo que el dueño no decidió explícitamente. Lo del panel, para no tocar aserciones de otro change por un detalle.
- **Alternativas rechazadas:** cambiar la sangría a 2 con sus pruebas; queda anotado como posible ajuste.
- **Impacto:** ninguno.

## Risks / Trade-offs

- [`$boost` es muy suave en `textual-dark` (blanco al 4 %)] → es lo pedido («fondo suave»); la barra lleva la marca. Si se ve poco, el rol `you-fill` se cambia en un solo sitio.
- [El chrome de un bloque plegado pierde el fondo en los temas ANSI] → sigue el glifo `▸` y la negrita, y el extracto va detrás de su marca (`| ` o `› `). Es la D7 del estudio. El tema por defecto no es ANSI.
- [Las rayas `hkey` y los bordes `tall` en conhost sin verificar] → comprobación opcional en Windows; no es una puerta.
- [`feature/command-completion` cambia la zona de la entrada] → aquí solo hay CSS de `#prompt`. Si su desplegable necesita altura, que cuente con las 2 filas de `-short`.
- [Más filas de contenido a 100×30 (los huecos)] → las filas visibles no cambian; el contenido pide 2 filas más de desplazamiento.

## Open Questions

(ninguna; D5–D7 del estudio siguen abiertas para el dueño)
