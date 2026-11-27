# Estudio: ¿existen sistemas de diseño para interfaces de terminal y cuál adoptar?

Fecha de consulta: 2026-11-27. Repo leído en `origin/develop`: `harness/shell/tui.py`, `harness/shell/render.py` y `README.md` (sección «Aspecto»). Textual leído en el código instalado, la versión 8.2.8 que fija `uv.lock`. Las capturas son de la pantalla real con el Mock y una sesión sintética, tomadas con el `Pilot` de Textual. Este estudio no cambia código del producto.

Etiquetas: **[V]** verificado aquí, en el código instalado o ejecutando Textual 8.2.8 · **[C]** citado de la fuente primaria (enlace en §9) · **[I]** inferencia u observación de uso, sin fuente que lo confirme.

## Resumen

1. **[C]** No hay un sistema de diseño para terminal comparable a Material o Carbon. Hay tres cosas distintas: **sistemas de tokens de un framework** (Textual es el más completo: 11 colores base, 90 variables derivadas, 168 contando los tonos, claro/oscuro y ANSI), **guías de CLI** (clig.dev, Primer CLI, Heroku), que cubren la salida de órdenes y excluyen las pantallas completas, y **temas de aplicaciones** (Claude Code, Codex, OpenCode, Gemini CLI, lazygit, k9s, btop), que tienen roles de color propios sin escala de espaciado.
2. **[C]** La única «norma» con escala de espaciado en celdas que encontré es *Monospace Design TUI*: 0, 1, 2, 3, 4, 6 y 8 celdas, mínimo 80×24 y *breakpoints* por columnas. Es joven (repositorio creado en marzo de 2026, 11 estrellas) y no resuelve que la celda sea el doble de alta que de ancha. Sirve como inspiración, no como dependencia.
3. **[I]** El grid de 8 puntos encaja en la celda sin inventar nada: una columna mide unos 8 px y una fila unos 16 px. Por tanto, **1 fila ≈ 2 columnas**. Un relleno que se vea igual por los cuatro lados se escribe `padding: 1 2`. Es la proporción que ya usan OpenCode (mensaje del usuario: 1 fila y 2 columnas) y el `Input` de Textual (`padding: 0 2` dentro de un borde de media fila).
4. **[V]** Textual ya da todo lo necesario sin dependencias nuevas: variables de color de tema (`$panel`, `$text-muted`, `$text-error`…) que también funcionan **dentro de los estilos de `Content`** (`"bold $text-error"` se resuelve con el tema), variables CSS propias para el espaciado (`$gap: 1;`), alias que apuntan a variables del tema (`$you-bar: $accent;`), `HORIZONTAL_BREAKPOINTS`/`VERTICAL_BREAKPOINTS` y las pseudoclases `:ansi`, `:dark`, `:light` y `:nocolor`.
5. **[V]** Hallazgos en el CSS actual (`tui.py:770-793`): no hay escala (márgenes 0 o 1 sueltos), los colores de `STYLES` (`tui.py:92-108`) son hexadecimales fijos que ignoran el tema, y **`MD_CODE` tiene exactamente el color de `HARNESS_WARNING`** (`#e5c07b`, líneas 104 y 97). Un `` `warning: …` `` escrito por el modelo se pinta igual que un aviso del harness, aunque sea dentro del recuadro.
6. **[V]** En el tema por defecto (`textual-dark`), `$accent` y `$warning` son el mismo color (`#FEA62B`). La barra de «lo que escribes» (`.you`, línea 778) y el marco de la aprobación (línea 783) se distinguen solo por la forma. En los temas ANSI, `$panel`, `$surface` y `$boost` son `transparent`, así que **el fondo no puede ser la única marca de lo que es chrome**: hace falta la estructura (borde y título del harness, o el prefijo `|` en texto plano).
7. **[V]** A 80×24 el panel lateral ocupa 34 de 80 columnas (42 %), la conversación se queda en 46 y el identificador de sesión se corta a media palabra. La entrada, su margen y el pie se comen 5 de las 24 filas.
8. **Recomendación.** Adoptar tal cual los tokens de color de Textual (sin paleta propia) y añadir encima una capa pequeña de la casa: una escala de espaciado (columnas 0/1/2/4/8, filas 0/1/2, regla 1 fila = 2 columnas), alias semánticos de color hacia variables del tema, una lista cerrada de estilos para texto ajeno disjunta de los de chrome y dos *breakpoints*. No añadir ninguna dependencia ni adoptar una norma externa entera.
9. **Primer corte:** el CSS en tokens, `STYLES` sobre variables del tema (corrige la colisión del punto 5), un hueco uniforme de 1 fila entre bloques, el panel lateral oculto por debajo de 100 columnas y pruebas con `Pilot` a 80×24 y 120×40 más una prueba de que ningún estilo de texto ajeno usa fondo, `reverse` ni colores de estado.
10. **Fuera:** paleta hexadecimal propia, iconos Nerd Font o emoji, degradados y animaciones, trucos de media línea con `▀▄` fuera de los bordes de Textual y selector de temas mientras no haya decisión del dueño (§8).

## 1. Qué existe y qué especifica cada uno

| Sistema | Qué especifica de verdad | Espaciado | Madurez | ¿Usable desde Textual? |
|---|---|---|---|---|
| **Textual: temas y variables** [V][C] | `Theme(name, primary, secondary, warning, error, success, accent, foreground, background, surface, panel, boost, dark, luminosity_spread, text_alpha, variables, ansi)`. Solo `primary` es obligatorio y el resto se deriva: tonos `-lighten-1..3`/`-darken-1..3`, `*-muted` (mezcla al 70 % con el fondo), `$text`/`$text-muted`/`$text-disabled` (contraste automático: `auto 87 %/60 %/38 %`), `$text-primary`… `$text-error`, `$border`/`$border-blurred`, `$block-cursor-*`, `$input-*`, `$footer-*`, `$button-*`, `$scrollbar-*`, `$link-*`. 21 temas incluidos (`textual-dark`, `textual-light`, `nord`, `gruvbox`, `catppuccin-*`, `dracula`, `tokyo-night`, `monokai`, `flexoki`, `solarized-*`, `rose-pine-*`, `atom-one-*`, `ansi-dark`, `ansi-light`). | Ninguno. Hay unidades (celdas, `fr`, `%`, `w`, `h`, `vw`, `vh`, `auto`), pero no una escala. | Estable, es el núcleo del framework. | Es el framework. |
| **Textual: widgets** [V] | Convenciones implícitas en `DEFAULT_CSS`. `Input`: `padding: 0 2`, borde `tall` (media fila arriba y abajo), 3 filas, foco = el borde pasa de `$border-blurred` a `$border` más un tinte del 5 %, con variante `compact` de 1 fila. `Button`: `min-width: 16`, `line-pad: 1`, relieve con `border-top/bottom: tall` en un tono más claro u oscuro, foco `$button-focus-text-style` (`b reverse` en ANSI), variante `compact`. `Footer`: 1 fila, tecla en negrita `$footer-key-foreground` con `padding: 0 1`. `Collapsible`: fondo `$surface`, `padding-left: 1`, `padding-bottom: 1`, título con `$block-cursor-*` al enfocarlo. | Implícito: 1 columna alrededor de las teclas, 2 dentro de las entradas, media fila con bordes `tall`. | Estable. | Sí. |
| **Charm** (Lip Gloss, Bubbles, Huh) [C] | Lip Gloss da primitivas: *padding* y *margin* en celdas, bordes (normal, rounded, thick, double, markdown), `LightDark` según el fondo detectado y bajada automática de perfil de color (truecolor → 256 → 16 → sin color). Huh trae 5 temas y un **modo accesible** para lectores de pantalla que cambia la TUI por preguntas lineales. | Ninguno publicado. | Maduro como biblioteca, sin guía de estilo. | No (Go). Se puede copiar la idea del modo accesible. |
| **Ratatui** [C] | Disposición: restricciones `Length`, `Percentage`, `Ratio`, `Min`, `Max`, `Fill`, `spacing(n)` y `Flex`. No publica roles de color ni guía de estilo. | `spacing` entre elementos, sin escala. | Maduro. | No (Rust). |
| **Ink / Ink UI** [C] | `ThemeProvider` y `extendTheme`, con estilos por componente como funciones del estado. Por convención, éxito verde, error rojo, aviso amarillo e información azul. | Ninguno (el ejemplo usa `gap: 1`). | Medio. | No (React). |
| **OpenCode / OpenTUI** [C][V] | Tema JSON por grupos de tokens: `text`, `background` (con `raised.base/high/max`), `border`, `scrollbar`, `diff`, `syntax`, `markdown`. Estados `$hovered/$focused/$pressed/$selected/$disabled`, paleta de matices `gray…purple` en pasos 100–900 y modo `system/dark/light`. | En el código: mensaje del usuario con `paddingTop/Bottom 1`, `paddingLeft/Right 2` y `marginTop 1` entre filas. | Activo; el esquema cambió hace poco. | La idea de «superficie elevada» equivale a `$panel`/`$boost`. |
| **Primer CLI (GitHub)** [C] | Tipografía: jerarquía solo con peso y espacio; **la cursiva no se usa**. Espaciado con saltos de línea, tablas e indentación. Color: los 8 ANSI básicos son fiables y los brillantes menos; el color solo **refuerza** el significado, no lo comunica. Símbolos `✓ - ✗ + !`. Ramas en cian o entre corchetes; etiquetas en gris o entre paréntesis; repositorio en negrita. Para lectores de pantalla, `.`, `,` y `:` fuerzan pausas. | Cualitativo. | Estable, para órdenes y no para pantalla completa. La tabla de color por ANSI es una imagen que no pude leer. | Las reglas sí: sin cursiva estructural, el color como refuerzo y la puntuación como pausa. |
| **clig.dev** [C] | Color «con intención»; desactivarlo si no hay TTY, con `NO_COLOR`, con `TERM=dumb` o con `--no-color`; rojo con moderación; negrita en los encabezados. **Excluye expresamente las pantallas completas** («full-screen terminal programs like emacs and vim»). | Nada específico. | Referencia de facto para CLI. | El harness ya lo cumple con el modo plano. |
| **Heroku CLI style guide** [C] | Colores sugeridos: magenta, cian, azul, verde y gris. Amarillo y rojo se reservan para avisos y errores. Pocos colores, con dim y negrita para el contraste. Ancho de 80 columnas. | Nada. | Antiguo, estable. | Coincide con la regla de reservar los colores de estado. |
| **Monospace Design TUI** [C] | Celda como unidad; escala 0/1/2/3/4/6/8 (5 y 7 prohibidos); tres regiones (navegación, contenido y contexto); mínimo 80×24 y lienzo de 120×40; *breakpoints* 40–79/80–119/120–159/160+; pie de teclas siempre visible; estados: foco en `reverse` o con corchetes, deshabilitado en dim, error en rojo **con texto obligatorio**. | Sí, la única escala publicada que encontré. | Repo de un autor, creado el 2026-03-03, 11 estrellas, CC BY-SA. | Como inspiración. |
| **NO_COLOR** [C] | Si la variable está presente y no vacía, no se añade color ANSI por defecto. **No obliga a quitar negrita ni cursiva**. La configuración del usuario puede imponerse a la variable. | — | Estándar de facto. | El harness pasa a texto plano, que es más estricto que la norma. |
| **Carbon, GNOME** | No encontré guía para terminal de ninguno de los dos. `@carbon/cli` es una herramienta de tareas. Aparecieron un manual de CLI de PatternFly y unas guías CLI de Ubuntu que no llegué a leer (la página de PatternFly dio 404). | — | — | — |

**Accesibilidad.** Ninguna guía de CLI trata a fondo el contraste en paletas de 16/256 colores. Lo más concreto está en el código: Codex comprueba el contraste de cada color sobre el fondo real (`readable_color_on`) y deja el amarillo para fondos oscuros conocidos [V], y Textual calcula `$text*` por contraste automático [V]. Para lectores de pantalla, Claude Code tiene un modo que cambia la pantalla completa por texto lineal con etiquetas (`you:`, `claude:`, `tool:`, `error:`, `warning:`, `Permission Required:`), sin dibujo de cajas ni señales solo de color [C]. Huh ofrece lo mismo con `WithAccessible` [C]. Gemini CLI desactiva su relleno de fondo cuando hay lector de pantalla [V]. **El modo plano del harness ya es ese modo**: líneas lineales con prefijo `| ` para el texto ajeno y avisos que empiezan por `error:` o `warning:` (`render.py:50-53`).

## 2. Cómo lo hacen los agentes de referencia

| Agente | Usuario | Asistente | Herramienta | Aprobación | Espaciado y estado |
|---|---|---|---|---|---|
| **Claude Code** (código cerrado) | Fondo `userMessageBackground` [C]; además el texto va tras `>` [I]. | Etiqueta con el color `claude` [C]; viñeta `⏺` [I]. | Resultado indentado tras `⎿` [I]. | Bordes de diálogo con el token `permission` [C]. | Tokens `inactive` (pistas y deshabilitados) y `subtle` (divisores) [C]; temas `dark`, `light`, `*-daltonized` y `*-ansi` [C]; `maxProseWidth` limita el ancho de la prosa [C]. |
| **Codex CLI** (Ratatui) [V] | Bloque con fondo propio (`history_prompt_style`, una mezcla del primer plano sobre el fondo), una fila vacía con ese fondo arriba y otra abajo y el prefijo `› ` en negrita y dim. | `• ` en dim con sangría colgante de 2 columnas. | `  └ ` en dim delante de la salida. | `✔ ` verde o `✗ ` rojo delante del resumen. | Guía propia `styles.md`: encabezados en negrita, texto primario con el color por defecto, secundario con `secondary_text_style`, verde para éxito, rojo para error, magenta para Codex; **evitar azul, amarillo, negro y blanco** como primer plano; atajos `esc close` separados por `·`. |
| **OpenCode** (OpenTUI) [V] | Borde izquierdo `┃` del color del agente sobre `background.raised.base`, `padding` 1 fila y 2 columnas, `marginTop 1`. | Sangría de 3 columnas, sin borde. | Borde izquierdo `┃` en un tono apenas distinto del fondo. | Componente `permission.tsx` (no lo leí en detalle). | Tokens por grupo (§1); modo `system` que sigue a la terminal. |
| **Gemini CLI** (Ink) [V] | `> ` y fondo `background.message`, con **media fila de relleno** dibujada con `▄`/`▀` cuando hay truecolor y una fila entera si no. Sin fondo, `marginY 1`. | `✦ ` con sangría del ancho del prefijo. | — | — | Tema por roles `text.{primary, secondary, link, accent, response}`, `status.{success, warning, error}`, `ui.{active, focus}` y `border.default` [C]; temas `ANSI` y `ANSI Light` [C]. |
| **Toad** (Textual, AGPL) [V] | `UserInput`: `border-left: blank $secondary`, `background: $secondary 15%`, `padding: 1 1 1 0`, `margin: 1 1 1 0`. | `AgentResponse` sin borde; pensamiento con `background: $primary-muted 20%`. | `ToolCall` con `margin-left: 1` y cabecera en `$text-secondary`. | Avisos en `round $warning` y errores en `round $error`. | Bloques con `margin: 1 1 1 0`; modo columna con `max-width: 100`; entrada compacta opcional. Es lo más cercano al harness: **mismo framework, solo variables de tema**. Por la licencia AGPL, se toman ideas y no código. |
| **lazygit** [C] | — | — | — | — | Foco por **color y negrita del borde** (`activeBorderColor: [green, bold]`); línea seleccionada con fondo, o solo en negrita si se configura; bordes `rounded/single/double/hidden/bold`. |
| **k9s / btop** [V] | — | — | — | — | Temas por zona (`frame`, `dialog`, `prompt`, `menu`) o por caja (`cpu_box`, `mem_box`…) con colores literales. Sin escala. |
| **Posting** (Textual) [C] | — | — | — | — | Tema = campos de `Theme` de Textual. Deriva todo de los roles (GET con `primary`, POST con `success`, DELETE con `error`) y no define una paleta aparte. |

**Patrón común** [I]: (a) el mensaje del usuario lleva **fondo propio y una marca a la izquierda**; (b) el asistente va **sin caja**, con una sangría o viñeta; (c) **una fila** separa los bloques; (d) el relleno interior sigue la proporción **1 fila : 2 columnas** (OpenCode, Codex, Gemini); (e) el éxito y el error llevan **símbolo y color**, nunca solo color; (f) el pie usa `tecla acción` separados por `·` o por dos espacios. El harness difiere a propósito en (b): el texto ajeno **va siempre en recuadro**, porque esa contención es su garantía (D3 de `shell-tui`). Ninguno de ellos tiene esa restricción.

## 3. El grid de 8 puntos en celdas

- **[C]** No hay una convención publicada que traslade el grid de 8 puntos a celdas. Monospace Design TUI usa la celda como unidad, pero no compensa la proporción.
- **[I]** Una celda típica mide unos 8×16 px (Menlo 12 pt da unos 7×15; Cascadia Mono, la fuente por defecto de Windows Terminal, tiene una proporción parecida). Una columna equivale a 1 unidad de 8 px y una fila a 2. De ahí la regla: **el espaciado vertical en filas es la mitad del horizontal en columnas** para que se vea igual.
- **[V]** La media fila existe en Textual sin trucos: los bordes `tall` (`▔`/`▁`), `outer` (`▀`/`▄`) y `wide` ocupan una fila, pero se ven como media. El `Input` lo usa. Gemini CLI hace lo mismo a mano con `▄`/`▀` [V].
- **[I] Sin verificar en Windows:** que conhost con su fuente por defecto dibuje bien `▔ ▁ ▊ ▎` (no están en CP437) y las esquinas redondeadas `╭╮╰╯`. Windows Terminal con Cascadia sí debería. Hay que mirarlo en la máquina Windows de pruebas antes de depender de ellos para algo más que la entrada, que ya los usa.

**Escala propuesta (house scale).**

| Paso | Columnas (horizontal) | Filas (vertical) | Equivale a |
|---|---|---|---|
| 0 | 0 | 0 | 0 px |
| 1 | 1 | — | 8 px |
| 2 | 2 | 1 | 16 px |
| 4 | 4 | 2 | 32 px |
| 8 | 8 | — | 64 px (sangrías y anchos de columna, no rellenos) |

Reglas: (1) solo estos valores (ni 3, ni 5, ni 6 columnas); (2) un relleno «cuadrado» es `padding: 1 2`, o `0 1` en modo denso; (3) entre bloques del flujo, 1 fila; dentro de un bloque, 0; (4) las anchuras fijas (panel lateral, botones) en múltiplos de 2 columnas.

## 4. Lo que hay hoy (con líneas de `tui.py`)

Captura real a 80×24 con el Mock (sesión sintética):

```text
 ai-harness  -  mock  session 01a21d53        │ Session
 -------------------------------------        │  chat 2026-11-27 09:06
 Enter sends a question. /help lists the      │  01a21d53-f142-76aa-bd3b-d30475
 commands; Tab completes them.                │ dad9b8
 Ctrl+C interrupts a question (never resent). │ Project
 /exit or end of input leaves.                │  -
                                              │ Provider
 █ hola, revisa esto                          │  mock
                                              │ Sends
 ╭─ mock ───────────────────────────────────╮ │  1
 │ respuesta sintética                      │ │ Last request
 ╰──────────────────────────────────────────╯ │  completed
                                              │ Memory
                                              │  0 note(s) in the last question
(cinco filas vacías)
▊▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▎
▊  Type a question, or / for a command                                         ▎
▊▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▎
 ctrl+p commands  ctrl+c interrupts  ctrl+n new session  ctrl+q leaves
```

| Dónde | Qué hace hoy | Problema |
|---|---|---|
| `tui.py:83` `SIDE_COLUMNS = 34` y `:774` `#side` | Panel fijo de 34 columnas a cualquier ancho. | A 80 columnas se lleva el 42 % y corta el identificador (arriba). |
| `:773` `#log { padding: 0 1 }` | 1 columna de margen lateral. | Correcto para 80; en pantallas anchas la prosa ocupa todo el ancho. |
| `:775` `#prompt { margin: 0 0 1 0 }` + `Input` (3 filas) | Entrada `tall` y una fila de margen. | 4 filas de 24 solo para la entrada. |
| `:776` `#footer` con `$panel` | Pie de 1 fila. | Bien; en los temas ANSI `$panel` es transparente (sigue siendo legible). |
| `:778` `.you { margin: 1 0 0 0; padding: 0 1; border-left: thick $accent }` | Barra a la izquierda. | `$accent` = `$warning` en `textual-dark`. Sin fondo, a diferencia de todos los agentes de §2. |
| `:779` `.harness { color: $text-muted }` | Sin margen. | Las líneas del harness quedan pegadas al bloque anterior, mientras `.you` y `.foreign` dejan 1 fila: no hay una regla única. |
| `:780-781` `.foreign { margin: 1 0 0 0; padding: 0 1; border: round $secondary; … }` | Recuadro con título del harness. | Correcto. El color `$secondary` en `textual-dark` es `#004578`, poco visible sobre `#121212`; el marco se ve sobre todo por su forma. |
| `:783-785` `#approval-box { width: 90%; height: 90%; border: heavy $warning; padding: 0 1; background: $surface }` | Caja modal. | Sin relleno vertical: el título del motor queda pegado al borde. A 24 filas, 90 % deja 21. |
| `:787` `#approval-content { border: round $secondary }` | Contenido ajeno. | Correcto (contención). |
| `:788` `#approval-question { margin: 1 0 0 0 }` | 1 fila antes de la pregunta. | Es el único hueco interno de la caja. |
| `:792` `#picker-box { width: 80%; height: 70% … }` | Selector. | Porcentajes sin relación con la escala; sin relleno. |
| `:92-108` `STYLES` | Hexadecimales de la paleta Atom One Dark. | Ignoran el tema; `MD_CODE` (104) = `HARNESS_WARNING` (97). |
| `:457` `entry()` en `SidePanel` | Valor indentado 1 columna. | Indentación de 1 en el panel y de 2 en las notas (470): dos valores distintos para lo mismo. |
| `:825-827` `get_system_commands` vacío | Sin selector de tema. | El tema es siempre `textual-dark`, también en terminales claras. |

## 5. Propuesta concreta

### 5.1 Tokens (variables CSS de Textual al principio de `HarnessApp.CSS`)

Comprobado [V] que Textual 8.2.8 acepta variables propias con valores de espaciado (`$gap: 1;` … `margin: $gap 0 0 0`) y alias de variables de tema (`$you-bar: $accent;`), y que los estilos de `Content` aceptan `"bold $text-error"`, que se resuelve con el tema activo (`bold #d17e92` en `textual-dark`, `bold color(1)` en `ansi-dark`).

| Token | Valor | Dónde se usa | Sustituye a |
|---|---|---|---|
| `$edge` | `1` (col) | `#log` y `#footer`, relleno lateral | `:773`, `:776` `padding: 0 1` |
| `$gap` | `1` (fila) | `margin-top` de **todo** bloque del flujo (`.you`, `.harness`, `.foreign`) | `:778`, `:780`; añade a `:779` |
| `$inset` | `1` (col) | relleno lateral dentro de bloques del flujo | `:778`, `:780` `padding: 0 1` |
| `$indent` | `2` (col) | valores bajo su etiqueta en el panel y en las notas | `:457` (1), `:470` (2) |
| `$box-pad` | `1 2`; `0 1` en `-short` | relleno de las cajas modales | `:783` `padding: 0 1`, `:792` (nada) |
| `$box-gap` | `1` (fila) | separación entre las partes de la caja de aprobación | `:788` y nada en el resto |
| `$side-width` | `34` → **`32`** (múltiplo de 2; a decidir) | `#side` | `:83`, `:774` |
| `$you-bar` | `$primary` | `border-left` de `.you` (se distingue de `$warning` en todos los temas incluidos) | `:778` `$accent` |
| `$you-fill` | `$boost` | `background` de `.you` (en ANSI es transparente y queda la barra) | — (nuevo) |
| `$chrome-fill` | `$panel` | `#footer` y fondo de cajas modales | `:776`, `:785` y `:792` `$surface` |
| `$chrome-muted` | `$text-muted` | `.harness`, `#working`, texto del pie | `:776`, `:777`, `:779` |
| `$rule` | `$border-blurred` | separador del panel lateral | `:774` `$panel-lighten-2` |
| `$foreign-frame` | `$secondary` (hoy) u otro (decisión D3) | borde de `.foreign` y de `#approval-content` | `:780`, `:787` |
| `$approval-frame` | `$warning` + borde `heavy` | `#approval-box` | `:783` |
| `$picker-frame` | `$primary` + borde `round` | `#picker-box` | `:792` `$accent` |

### 5.2 Roles de color para los estilos de fila (`STYLES`)

| Estilo (`render.py`) | Hoy (`tui.py`) | Propuesto | Quién lo puede llevar |
|---|---|---|---|
| `HARNESS_ERROR` | `bold #e06c75` (96) | `bold $text-error` | solo chrome |
| `HARNESS_WARNING` | `#e5c07b` (97) | `$text-warning` | solo chrome |
| `STATUS` | `bold` (98) | `bold` | solo chrome |
| `GUTTER` | `dim` (93) | `dim` | marca, solo chrome |
| `MD_HEADING` | `bold #61afef` (99) | `bold $text-primary` | contenido |
| `MD_BULLET` | `#c678dd` (100) | `$text-secondary` | contenido |
| `MD_QUOTE` | `italic #98c379` (101) | `italic $text-muted` | contenido |
| `MD_RULE`, `MD_FENCE` | `dim` (102-103) | `$text-muted` | contenido |
| `MD_CODE` | `#e5c07b` (104) | `$text-secondary` o `bold` (sin color de estado) | contenido |
| `MD_STRONG`, `MD_EM` | `bold`, `italic` (105-106) | igual | contenido |
| `MD_LINK` | `underline #56b6c2` (107) | `underline` (o `underline $text-primary`) | contenido |

### 5.3 Qué variables son seguras para chrome y cuáles para contenido

El texto ajeno va siempre dentro de un contenedor del harness, que es la garantía. Las reglas siguientes evitan, además, que **dentro** del recuadro el modelo pueda parecer un aviso o un control del harness.

- **Solo chrome** (nunca en un estilo aplicado a texto ajeno): cualquier **fondo** (`$panel`, `$surface`, `$boost`, `$background`, `*-muted` como fondo, `$block-cursor-*`, `$input-*`, `$footer-*`), `reverse`, `blink`, los **colores de estado** como texto (`$text-error`, `$text-warning`, `$text-success`) y `$text-accent`, que en `textual-dark` es idéntico a `$text-warning` [V] y en `ansi-dark` a `$text-success` [V].
- **Permitido en contenido:** `$text`, `$text-muted`, `$text-primary`, `$text-secondary`, más `bold`, `italic`, `underline` y `dim`.
- **Comprobable con una prueba:** el conjunto de estilos que `markdown_styles` puede producir, pasado por `STYLES`, no contiene `on `, `reverse`, `$text-error`, `$text-warning`, `$text-success` ni `$text-accent`.
- **Ninguna identidad depende solo del fondo ni solo del color** [V]: en los temas ANSI los fondos de chrome son transparentes y `$accent`/`$warning`/`$success` coinciden según el tema. La marca es la forma: recuadro `round` con título del harness (ajeno), `heavy` (aprobación), barra a la izquierda (usuario) y prefijo de texto (`error:`, `warning:`).

### 5.4 Tipografía

| Atributo | Uso permitido | Nunca |
|---|---|---|
| **bold** | títulos de borde, etiquetas del panel, teclas del pie, `error:` del harness, encabezados y `**strong**` del contenido | párrafos enteros |
| **dim** / `$text-muted` | líneas del harness, pistas, identificadores, separadores, vallas de código | único indicador de un estado |
| *italic* | solo contenido (`*em*` y citas) | chrome: Primer no la usa y conhost probablemente no la muestra [I, sin verificar] |
| underline | enlaces del contenido (mostrados, nunca seguidos) | chrome |
| reverse | cursor y opción resaltada (lo pone Textual) | contenido |

### 5.5 Bordes por rol

| Rol | Borde | Color | Título |
|---|---|---|---|
| Texto ajeno en el flujo | `round` | `$foreign-frame` | del harness, `bold` |
| Contenido ajeno en la aprobación | `round` | `$foreign-frame` | «proposed content (from outside the harness)» |
| Caja de aprobación | `heavy` (la única gruesa) | `$approval-frame` | `bold` |
| Selector y paleta | `round` | `$picker-frame` | `bold` |
| Usuario | solo `border-left: thick` (o `tall`, D2) | `$you-bar` sobre `$you-fill` | — |
| Panel lateral | `border-left: solid` | `$rule` | — |
| Entrada | la de Textual (`tall`) o `compact` en `-short` | `$border` / `$border-blurred` | — |
| Botones (si llegan) | los de Textual; `compact` en `-short` | variantes `-primary`/`-error` de Textual | — |

**Botones.** Hoy no hay ninguno; la aprobación se responde escribiendo el código, y así debe seguir. Si se añaden: ancho = etiqueta + 2×2 columnas (escala 2), mínimo 12; 3 filas con el relieve de Textual a partir de 30 filas y `compact` (1 fila) por debajo. Separados por 2 columnas y alineados a la derecha de la caja.

### 5.6 Estados sin depender del color

| Estado | Señal no cromática | Color (refuerzo) |
|---|---|---|
| Enfocado | cursor `reverse` en la única entrada enfocada (Textual) | `$border` |
| Ocupado | placeholder `working: ctrl+c interrupts`, línea `mock: thinking (N s)`, panel «running» | `$chrome-muted` |
| Error | prefijo `error:` y negrita | `$text-error` |
| Aviso | prefijo `warning:` / `interrupted:` / `omitted:` | `$text-warning` |
| Aprobación pendiente | caja modal con borde `heavy` y título | `$approval-frame` |
| Deshabilitado | texto explícito («Busy: wait…», `tui.py:1000`) | `$text-disabled` |

### 5.7 Densidad y *breakpoints*

`HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]` y `VERTICAL_BREAKPOINTS = [(0, "-short"), (30, "-tall")]`, comprobado [V] que aplican las clases a la pantalla en 8.2.8.

| Clase | Regla |
|---|---|
| `-narrow` (<100 col) | `#side { display: none }`. El estado sigue en `/status` y en la paleta. Prosa a todo el ancho. |
| `-wide` (≥100) | Panel visible (`$side-width`). Opcional (D5): `max-width` de la prosa en 100 columnas, como Toad y `maxProseWidth` de Claude Code. |
| `-short` (<30 filas) | Entrada `compact` (1 fila) con una regla `hkey` encima; cajas modales al 100 % de alto con `$box-pad` `0 1`. |
| `-tall` (≥30) | Entrada `tall` (3 filas), cajas con `padding: 1 2`. |

Presupuesto a 80×24: hoy la conversación tiene 19 filas. Con `-short` serían 21 (pie 1, entrada 1 y regla 1).

**Mock-up 80×24 propuesto** (`#` = barra de `.you`, `:` = fondo `$you-fill`; borde ASCII por convención del estudio, en pantalla sería `round`):

```text
 ai-harness  -  mock  session 01a219d9
 Enter sends a question. /help lists the commands; Tab completes them.

 # revisa este requerimiento::::::::::::::::::::::::::::::::::::::::::::::::::

 context: demo-alpha, 7 note(s) included, 0 truncated, 1556 of 8192 bytes

 +- mock --------------------------------------------------------------------+
 | ## Resumen                                                                |
 | El requerimiento pide **avisar** de pedidos con `order.created`.          |
 |                                                                           |
 | ## Preguntas pendientes                                                   |
 | - Que pasa con un evento que no se publica?                               |
 +---------------------------------------------------------------------------+

 mock: thinking (3 s), ctrl+c interrupts





 ------------------------------------------------------------------------------
 Type a question, or / for a command
 ctrl+p commands  ctrl+c interrupts  ctrl+n new session  ctrl+q leaves
```

**Mock-up de la aprobación a 80×24** (`-short`: 100 % de alto, `padding: 0 1`, `$box-gap` entre partes):

```text
+=[ Approval requested ]=======================================================+
| target: notes/decision.md   hash: 3f9a1c   expires: 10 min                   |
|                                                                              |
| +- proposed content (from outside the harness) ----------------------------+ |
| | # Decision                                                               | |
| | Usar colas idempotentes para order.created.                              | |
| | ...                                                                      | |
| +--------------------------------------------------------------------------+ |
| 12 more line(s) below. The code is taken only once the end has been shown.   |
|                                                                              |
| Type the code to approve, n to reject:                                       |
| > ____                                                                       |
+==============================================================================+
```

**Mock-up 120×40** (`-wide -tall`): igual que arriba, más el panel a la derecha separado por `$rule` y cajas con `padding: 1 2`. No lo dibujo: solo cambian el panel (ya documentado en el README) y el relleno.

## 6. Qué adoptar tal cual de Textual y qué no inventar

- **Tal cual:** los 21 temas y todas las variables derivadas (sin hexadecimales en el harness); el contraste automático de `$text*`; `Input`, `OptionList` y la paleta con su CSS por defecto, incluido el foco; `compact` para alturas pequeñas; los bordes `round`, `heavy`, `tall` y `hkey`; `HORIZONTAL_BREAKPOINTS`/`VERTICAL_BREAKPOINTS`; las pseudoclases `:ansi` y `:light` si hace falta un ajuste por tema.
- **No inventar:** una paleta propia, un cálculo de contraste (Textual ya lo hace; Codex lo tiene que hacer a mano porque Ratatui no lo trae), un `Theme` propio mientras no se decida D6, ni un sistema de iconos.
- **Lo único de la casa:** la escala (§3), los alias semánticos (§5.1), la lista cerrada de estilos de contenido (§5.3) y los *breakpoints* (§5.7). Todo cabe en el CSS de `tui.py` y en `STYLES`, sin módulo ni dependencia nueva.

## 7. Recomendación y cortes

**Recomendación:** tokens de Textual + escala pequeña de la casa. Descartados: adoptar Monospace Design TUI entera (joven, de un solo autor y con reglas que no encajan, como un foco siempre visible en una app donde casi nada es enfocable); copiar el sistema de OpenCode (pensado para truecolor y otro motor); copiar Toad (AGPL); escribir una paleta propia (rompe los temas claros y ANSI).

| Corte | Contenido | Pruebas |
|---|---|---|
| **S1: tokens y estructura** (el más pequeño) | Variables de §5.1 al principio del CSS; `STYLES` → variables de tema (§5.2), que corrige la colisión código/aviso; `margin-top: $gap` también en `.harness`; `-narrow` oculta el panel; `$indent` en el panel. Sin cambios de comportamiento. | `Pilot` a 80×24 y 120×40 (texto de pantalla); estilos de contenido ⊆ permitidos (§5.3); `.you` y `#approval-box` con bordes de forma distinta; README («Aspecto») con la captura nueva. |
| **S2: densidad vertical** | `-short`/`-tall`: entrada `compact`, cajas modales con `$box-pad`, `$box-gap` en la aprobación. | Capturas a 80×24 y 100×30; la regla de «el final se ha visto» sigue pasando con la caja más baja. |
| **S3: fondo del usuario y marco ajeno** | `$you-fill`, decisión D2/D3. | Captura en `textual-dark`, `textual-light` y `ansi-dark` (se fuerza el tema en la prueba). |
| **S4 (opcional): temas** | Según D6: seguir el claro u oscuro de la terminal, permitir elegir o usar ANSI por defecto. | Persistencia y pruebas por tema. |
| **Windows** | En cada corte: mirar conhost y Windows Terminal en la máquina Windows de pruebas (bordes `tall`/`round`, cursiva). | Manual; no es una puerta. |

**Fuera de alcance:** iconos Nerd Font y emoji, degradados y *shimmer*, animaciones, estados `hover` de ratón, media línea con `▀▄` fuera de los bordes de Textual, colores por subagente y un modo para lector de pantalla distinto del modo plano (que ya cumple ese papel).

## 8. Decisiones abiertas para el dueño

| # | Decisión | Opciones | Recomiendo |
|---|---|---|---|
| D1 | Panel lateral en terminales estrechas | (a) ocultarlo por debajo de 100 columnas; (b) pasarlo a una línea de estado de 1 fila; (c) dejarlo como está | **(a)**, y (b) más adelante si se echa en falta |
| D2 | Marca del usuario | (a) barra `thick` + fondo `$boost`; (b) solo barra (hoy); (c) prefijo `> ` + fondo, como Codex y Gemini | **(a)** |
| D3 | Color del marco ajeno | (a) `$secondary` (hoy); (b) neutro (`$foreground-muted`), para que el color quede libre para los estados; (c) `$primary` | **(b)**: el marco es estructura y su forma ya basta |
| D4 | Entrada a 24 filas | (a) `compact` por debajo de 30 filas; (b) siempre `tall` | **(a)** |
| D5 | Ancho máximo de prosa | (a) sin límite; (b) 100 columnas en `-wide` | **(a)** en S1; revisar con uso real |
| D6 | Tema | (a) fijo `textual-dark` (hoy); (b) seguir la terminal (`textual-light` en fondo claro); (c) selector en la paleta; (d) `ansi-dark`/`ansi-light` por defecto, que respeta la paleta del usuario | **(a)** en S1-S3 y decidir (b) o (d) después; (c) exige persistir una preferencia |
| D7 | «El chrome se distingue por el fondo» | (a) el fondo es refuerzo y la forma es la marca; (b) el fondo como marca única | **(a)**: en los temas ANSI el fondo de chrome es transparente |

## 9. Verificado frente a supuesto

- **Verificado [V]:** variables, temas, CSS por defecto de `Button`, `Input`, `Footer` y `Collapsible`, caracteres de borde, pseudoclases, *breakpoints*, variables CSS de espaciado, alias y estilos de `Content` con `$variables`, todo en Textual 8.2.8 instalado; colores resueltos de `textual-dark`, `textual-light` y `ansi-dark` ejecutando Textual; la captura a 80×24; el código de Codex (`styles.md`, `style.rs`, `history_cell/*.rs`), OpenCode (`packages/tui/src/routes/session/index.tsx`, `ui/border.ts`), Gemini CLI (`UserMessage.tsx`, `GeminiMessage.tsx`, `HalfLinePaddedBox.tsx`), Toad (`toad.tcss`, `screens/main.tcss`), lazygit (`docs/Config.md`), btop (`themes/nord.theme`) y k9s (`skins/nord.yaml`) leídos en sus ramas principales.
- **Citado [C]:** páginas de documentación (§10).
- **Supuesto [I] o sin confirmar:** las viñetas `⏺`/`⎿` y el prefijo `>` de Claude Code (es código cerrado; los conozco por uso, no por documentación); el tamaño de celda en píxeles; que conhost no muestre la cursiva ni los bordes `tall`/`round` con su fuente por defecto; la tabla de colores ANSI de Primer (es una imagen); el contenido del manual de CLI de PatternFly (404); la madurez de Monospace Design TUI más allá de lo que muestra GitHub.

## 10. Fuentes

- Textual, temas y variables: <https://textual.textualize.io/guide/design/> · unidades: <https://textual.textualize.io/css_types/scalar/> · código: `textual/design.py`, `textual/theme.py`, `textual/_border.py`, `textual/app.py` (`HORIZONTAL_BREAKPOINTS`, `_PSEUDO_CLASSES`), `textual/widgets/_button.py`, `_input.py`, `_footer.py`, `_collapsible.py` (8.2.8).
- Lip Gloss: <https://github.com/charmbracelet/lipgloss> · Huh: <https://github.com/charmbracelet/huh>
- Ratatui, disposición: <https://ratatui.rs/concepts/layout/>
- Ink UI: <https://github.com/vadimdemedes/ink-ui>
- OpenCode, temas: <https://opencode.ai/docs/themes/> · código: <https://github.com/anomalyco/opencode/tree/dev/packages/tui/src>
- Primer CLI: <https://github.com/primer/design/blob/main/content/native/cli/foundations.mdx> y `components.mdx`
- clig.dev: <https://clig.dev/> · NO_COLOR: <https://no-color.org/> · Heroku: <https://devcenter.heroku.com/articles/cli-style-guide>
- Monospace Design TUI: <https://coreyt.github.io/monospace-design-tui/standard/layout/> y `/standard/state/`; repositorio <https://github.com/coreyt/monospace-design-tui>
- Claude Code, temas: <https://code.claude.com/docs/en/terminal-config> · accesibilidad: <https://code.claude.com/docs/en/accessibility>
- Codex CLI: <https://github.com/openai/codex/blob/main/codex-rs/tui/styles.md>, `codex-rs/tui/src/style.rs`, `codex-rs/tui/src/history_cell/`
- Gemini CLI, temas: <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/themes.md> · componentes en `packages/cli/src/ui/components/`
- Toad: <https://github.com/batrachianai/toad> (AGPL-3.0)
- Posting, temas: <https://posting.sh/guide/themes/>
- lazygit: <https://github.com/jesseduffield/lazygit/blob/master/docs/Config.md> · btop: <https://github.com/aristocratos/btop/tree/main/themes> · k9s: <https://github.com/derailed/k9s/tree/master/skins>
