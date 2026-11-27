# Design

## Context

Lo que existe, medido en `develop` (`5af28ed`) el 2026-11-27:

- `decide()` (`harness/skills/approvals.py`):
  - muestra el aviso y pregunta con `terminal.ask` hasta 3 veces;
  - concede si la respuesta es `approval_hash[:8]`;
  - con `confirm_rejection`, `n` seguido de `reject` rechaza.
- El motor (`harness/skills/engine.py`, paso `approval`):
  - registra `granted` o `rejected` con la identidad local;
  - comprueba la caducidad después de la respuesta;
  - antes del efecto, consume en una transacción la fila `granted` con el mismo `proposal_hash`, una sola vez.
- `skill-engine` D12 deja escrito lo que la aprobación no garantiza: «que haya una persona delante». Wilson lo aceptó el 2026-11-24 (opción 3 de «Canal de aprobación más fuerte»).
- La pantalla completa (`shell-tui` D6 y la revisión del 2026-11-26):
  - la caja dibuja la cabecera del motor y el contenido en un área ajena;
  - pide el código en una `CodeInput` sin pegado, que no lo toma antes de 0,5 s ni sin haber visto el final;
  - una sola respuesta por pregunta (`_take`).
- Textual 8.2.8:
  - un `Button` deshabilitado no recibe foco ni clics;
  - un `Button` con foco se pulsa con Enter o con Espacio;
  - el orden de Tab es el del árbol de widgets, y se salta lo deshabilitado;
  - un `VerticalScroll` con foco se desplaza con flechas, AvPág, RePág, Inicio y Fin, y no tiene acción para Enter.

## Goals / Non-Goals

**Goals:**
- en la pantalla completa, aprobar con un botón;
- que nada apruebe por accidente ni por texto automático;
- que el motor siga ligando la decisión al hash, con caducidad y uso único;
- que la auditoría diga cómo se decidió.

**Non-Goals:**
- probar que hay una persona;
- botones fuera de la pantalla completa;
- cambiar lo que se firma.

## Decisions

### D1 · Lo que envía el botón: una pulsación ligada al hash, que solo la pantalla completa devuelve

- **Qué:** `approvals.py` define cuatro piezas.
  - `ButtonPress(choice, approval_hash)`: un objeto inmutable, no un texto.
  - `ButtonApprovalTerminal`: un protocolo con `ask_buttons(question, approval_hash) -> ButtonPress | None`.
  - `Verdict(decision, means)`.
  - `decide()`:
    - si la terminal tiene `ask_buttons`, muestra el aviso, pregunta una vez y solo acepta un `ButtonPress` cuyo `approval_hash` sea el de esa pregunta. `approve` → `granted`; `reject` (ya confirmado en la caja) → `rejected`; cualquier otra cosa → `undecided`;
    - si no lo tiene, sigue el camino del código, que no cambia (`decide_by_code`). Una respuesta que no sea texto ahí es `undecided`.

  El motor no cambia nada más: misma fila de `approvals`, misma comprobación de caducidad tras la respuesta, mismo consumo único por `proposal_hash`. La auditoría añade `;means=button` o `;means=code` al detalle de `approval.granted` y `approval.rejected`. `channel` sigue siendo `tty`, así que no hace falta migración.

  En la pantalla completa (`TuiTerminal`):
  - `ask_buttons` vacía primero las pulsaciones viejas;
  - solo abre la caja si el aviso que el motor acaba de mostrar contiene ese hash, y si no, devuelve `None`;
  - devuelve solo la pulsación de esa caja.

  `TuiTerminal.ask` devuelve `None`: en la pantalla completa no hay respuesta escrita.
- **Por qué:** el botón responde a la misma pregunta del motor y queda ligado a la misma fila y al mismo hash. No hay una segunda vía más débil:
  - un texto, venga de una persona, de un modelo, de un fichero o de un pegado, nunca es un `ButtonPress`;
  - `ConsoleTerminal` (texto plano) y `TtyTerminal` (CLI) no tienen `ask_buttons`, así que `decide` les pide el código **por construcción**, no por una opción que se pueda activar;
  - una pulsación de una caja anterior (otro hash) no decide.

  El hash que lleva la pulsación es el de la caja que se abrió, y la caja muestra la cabecera del motor con ese hash. Así, lo mostrado es lo concedido, y el destino mostrado es el aplicado, igual que con el código.
- **Alternativas rechazadas:**
  - Que la interfaz rellene el código (`hash[:8]`) y lo mande por `ask`. Funciona, pero hace del código un dato que la interfaz conoce y envía. Cualquier camino que llegue a `ask` con ese texto aprobaría, y en la auditoría no se distinguiría de un código escrito.
  - Una respuesta especial en texto (`"__button__"`). Es una cadena que se puede escribir, pegar o generar.
  - Un comando `/approve` en la conversación. Ya se rechazó en `interactive-shell`: una línea de la conversación nunca es una aprobación.
- **Impacto:** spec `human-approval` (concesión por botón, modo en la auditoría); `approvals.py`, `engine.py` y `tui.py`; pruebas en `tests/unit/test_skill_approval_buttons.py`.

### D2 · Las protecciones que sustituyen a lo que daba el código

- **Qué:** la caja (`ApprovalScreen`), de arriba abajo:
  - la cabecera del motor;
  - el área ajena con la propuesta (`ProposalArea`, un `VerticalScroll` enfocable que solo se desplaza);
  - una línea del harness con el estado de la lectura: «N more line(s) below: Approve is enabled once the end has been shown» o «The whole proposal has been shown»;
  - la pregunta del motor;
  - **una fila de botones fija abajo** (`dock: bottom`), fuera del área ajena: [Approve] y [Reject].

  Las reglas:
  - **Foco al abrir:** en la propuesta, nunca en un botón. Enter y Espacio sobre la propuesta no hacen nada.
  - **Armado:** durante `ARM_S` (0,5 s) los dos botones están deshabilitados. Una tecla, un Tab, un clic o una pulsación que llegue antes no encuentra ningún botón, y el manejador lo comprueba otra vez por el reloj. Esto cubre lo escrito por adelantado, que llega mientras la caja se arma.
    - **Revisado el 2026-11-27 (D9):** el plazo solo por reloj caducaba en una máquina cargada; ahora la caja se arma tras `ARM_S` sin entrada contados desde que se pinta, y una entrada leída antes del armado nunca actúa.
  - **El final mostrado:** «Approve» sigue deshabilitado hasta que el final de la propuesta ha estado en pantalla. Cuenta igual llegar con teclas, con la rueda o con la barra: se mira la posición del área cada 0,1 s. Si la propuesta cabe, se habilita al armarse.
  - **Orden de Tab:** propuesta → Approve → Reject. Con «Approve» deshabilitado, el primer Tab lleva a «Reject», que no decide sin su pregunta (D3).
  - **Una pulsación:** tras la primera, todos los botones se deshabilitan, y `TuiTerminal.press` toma la espera y la cierra en el mismo paso (`_take`). Un doble clic, o Enter mantenido, decide una vez.
  - **Pegado:** en la caja no hay ninguna entrada de texto. Un pegado, entre corchetes o de varias líneas, o un `ctrl+v` no llegan a nada que decida.
  - **Atajos de la aplicación:**
    - ninguno pulsa un botón;
    - `ctrl+p` no se abre sobre la caja;
    - `ctrl+n` manda una línea que se rechaza porque el núcleo no espera una;
    - **`ctrl+c` y `ctrl+q` dejan la aprobación pendiente** y cierran la caja; `ctrl+q`, además, sale.
    - **Escape no decide:** en la caja no hace nada, y en la pregunta de Reject es «Back».
  - **Ratón:** solo cuenta un clic sobre el propio botón. Un clic sobre la propuesta no hace nada.
  - **Texto ajeno:** el área es `Static(markup=False)` dentro de un borde titulado «proposed content (from outside the harness)». Una respuesta que dibuje «[ Approve ] [ Reject ]» es texto dentro de ese borde, encima de la fila real, que es de otro color (`$warning-muted`) y está fija abajo.
- **Por qué:** el código obligaba a mirar el hash junto al contenido. Lo que se pide ahora es que nada apruebe sin un gesto explícito y sin que el contenido haya pasado por la pantalla. Cada regla cierra un camino:
  - el foco neutro, contra el Enter de la línea anterior;
  - el armado, contra lo escrito por adelantado y el clic de antes de leer;
  - el final mostrado, contra aprobar solo lo que se ve arriba;
  - la fila fija, contra el texto que imita botones.
- **Alternativas rechazadas:**
  - Foco inicial en «Reject». Un Enter de más rechazaría, y si lo seguía otro Enter, también confirmaría.
  - Ningún elemento enfocado. El primer Tab iría al primer botón habilitado, «Approve», sin pasar por nada neutro. Con el foco en la propuesta, también la rueda y las teclas de desplazamiento actúan sobre ella.
  - Habilitar «Approve» al llegar al final aunque no se haya armado. Es el caso de una propuesta corta, que se vería entera a la vez que llega un Enter adelantado.
- **Impacto:** spec `interactive-shell` (requisitos de la caja); `tui.py` (`ApprovalScreen`, `ProposalArea`, `ApprovalButton`); pruebas en `tests/unit/test_shell_tui_buttons.py`.

### D3 · «Reject» pide una confirmación dentro de la caja

- **Qué:** «Reject» no decide. Cambia la fila de botones por otra fila: «Reject this proposal? The run is cancelled and nothing is written.», con [Back] y [Yes, reject]. El foco va a «Back». «Yes, reject» no cuenta durante `ARM_S` desde que apareció la pregunta, así que el segundo clic de un doble clic no confirma. «Back» o Escape vuelven a la caja. Sin confirmar, la aprobación sigue pendiente. Solo «Yes, reject» envía `ButtonPress("reject", hash)`.
- **Por qué:** Wilson decidió el 2026-11-25 que en la conversación una tecla suelta no rechazase (`n` seguido de `reject`). Rechazar cancela la ejecución, y con Copilot eso es repetir preguntas al modelo. Sin foco en los botones, el riesgo de una tecla suelta baja, pero quedan dos:
  - un clic al lado de «Approve»;
  - el doble clic, porque la pregunta aparece donde estaba la fila.

  Un paso más es barato y mantiene la regla «sin confirmar → pendiente».
- **Alternativas rechazadas:**
  - Sin confirmación: un clic de más cancela la ejecución.
  - Confirmar escribiendo `reject`: vuelve a meter una entrada de texto en la caja, que es lo que se quería quitar.
- **Impacto:** spec `interactive-shell` (rechazo con su pregunta); `tui.py` (`_confirming`, `confirm_opened`).

### D4 · El código ya no se escribe en la pantalla completa

- **Qué:** se quita `CodeInput` de la caja. Quien solo usa el teclado tiene Tab y Enter, y Tab, Enter, Tab y Enter para rechazar. El código sigue siendo la única forma en texto plano y en la CLI.
- **Por qué:** menos caminos. Una segunda forma de conceder en la misma caja tendría que llevar todas las protecciones de D2 (pegado, portapapeles, armado, final mostrado) y su propia auditoría, sin aportar nada a quien ya puede pulsar con el teclado.
- **Alternativas rechazadas:** una entrada visible «o escribe el código», para quien prefiera escribir. Si alguien la pide, `chat --plain` da exactamente eso.
- **Impacto:** `tui.py` (sin `CodeInput` ni `answer`); `TuiTerminal.ask` devuelve `None`. Salen las pruebas de la entrada del código de `test_shell_tui.py` y `test_shell_tui_review.py`, y sus protecciones (sin pegado, armado, final mostrado) pasan a las de los botones.

### D5 · Idioma de la caja

- **Qué:** inglés: «Approve», «Reject», «The whole proposal has been shown», «Reject this proposal? …», «Back», «Yes, reject». La maqueta está en español, pero el resto de la pantalla completa también está en inglés:
  - la cabecera «Approval requested», con sus campos, la escribe el motor;
  - los atajos, los avisos y la paleta.
- **Por qué:** la convención de la aplicación y no mezclar idiomas en una misma pantalla. `openspec/config.yaml` pide en inglés el código, los comentarios, los logs y los identificadores; los textos de la interfaz ya lo están.
- **Alternativas rechazadas:** la caja en español y el resto en inglés: dos idiomas en una sola pantalla.
- **Impacto:** `tui.py` (constantes `APPROVE_LABEL`, `REJECT_LABEL`, `SHOWN_ALL`, `NOT_ALL`, `CONFIRM_*`); README.

### D6 · Lo que el botón no cambia: la aprobación no prueba que haya una persona

- **Qué:** sigue el límite de `skill-engine` D12, aceptado el 2026-11-24. Un programa que maneje tu terminal, con tu cuenta, puede pulsar un botón igual que podía escribir el código: Tab y Enter, o un clic enviado como secuencia de ratón. Se escribe así en `README.md` y `SECURITY.md`. Lo que el botón sí protege: un Enter de más, lo escrito por adelantado, un pegado, el texto ajeno que imita la caja y aprobar sin que el final haya pasado por la pantalla.

  `docs/security/known-debt.md` vive en una rama sin mergear (`feature/hardening`). Cuando se mergee, su apartado «la aprobación no prueba que haya una persona» se actualiza con el botón (tarea 4.3).
- **Por qué:** un botón es más fácil de pulsar que copiar 8 caracteres, para una persona y para un programa. Frente al programa no cambia nada: el código tampoco lo paraba.
- **Alternativas rechazadas:** abrir aquí el canal más fuerte (un diálogo del sistema o un segundo dispositivo). Wilson lo descartó para el MVP el 2026-11-24.
- **Impacto:** `README.md`, `SECURITY.md`; tarea 4.3.

### D7 · La caja sobre una escala de espaciado (grid de 8 puntos en celdas)

- **Qué:** una escala con nombre en un solo sitio, `harness/shell/spacing.py`, que el CSS de la pantalla declara como variables de Textual (`$box-x`, `$row`, `$button-w`…; los colores de la caja van por alias del tema: `$approval-frame`, `$approval-fill`, `$foreign-frame`, `$box-fill`). Columnas 1/2/4/8; filas 1/2, y **1 fila = 2 columnas**. Se aplica solo a la caja de aprobación:
  - **Botones:** los cuatro miden 16 columnas (`BUTTON_WIDTH`, dos pasos de 8, que además es el `min-width` de Textual) y 3 filas (unos 48 px, el objetivo táctil mínimo habitual). El texto va centrado.
  - **Separación entre botones:** 8 columnas (`BUTTON_GAP`), mayor que el relleno alrededor de cualquier etiqueta (como mucho 5 columnas en «Reject»: interno ≤ externo). La pareja va centrada.
  - **Relleno de la caja:** 2 columnas entre el borde y el contenido a cualquier tamaño (antes, 1).
  - **Filas en blanco según la altura** (`VERTICAL_BREAKPOINTS` de la pantalla):
    - menos de 30 filas (`-tight`): ninguna fila en blanco; todas van al contenido;
    - de 30 a 39 (`-snug`): una fila en blanco encima de los botones. Las dos líneas de pista («N more line(s)…» y la pregunta) quedan juntas, como un grupo. La fila en blanco que antes había entre ellas se mueve debajo, así que no cuesta ninguna fila;
    - 40 o más (`-roomy`): además, `padding: 1 2` en la caja y una fila en blanco antes y después de la propuesta.
  - **Confirmación de Reject:** su pregunta va en su propia línea centrada, en el lugar de la pregunta del motor, con [Back] [Yes, reject] debajo y la misma rejilla. Antes iba a la izquierda en la misma fila que los botones, y a 80, 100 y 120 columnas «Yes, reject» quedaba fuera de la caja y de la pantalla. Medido el 2026-11-27: en x=97, x=96 y x=98, con 16 de ancho.
  - **Estados sin depender del color:**
    - deshabilitado → tachado;
    - habilitado → negrita;
    - enfocado → negrita invertida.

    Antes, deshabilitado y habilitado solo se distinguían por la opacidad, un color.
- **Por qué:**
  - **Fuentes del grid.**
    - Spec.fm, «8-Point Grid»: múltiplos de 8 para dimensiones, rellenos y márgenes; la rejilla «blanda» y la media rejilla de 4 pt para el texto.
    - Material Design: rejilla de 8 dp, de 4 dp para iconos y texto, y objetivos táctiles de 48×48 dp separados al menos 8 dp.
    - La regla interno ≤ externo: Cieden, «Spacing best practices».
    - El estudio del repositorio `docs/estudios/2026-11-27-sistema-de-diseno-tui.md` (§3 y §5).
  - **La celda.** Mide unos 8×16 px, así que una columna es un paso y una fila son dos. No hay media fila, de modo que el espacio vertical se gasta en filas enteras y solo donde sobran.
  - **Medido antes y después** (Pilot, propuesta de 43 líneas), en filas de propuesta visibles:

    | Tamaño | Antes | Después |
    |---|---|---|
    | 80×24 | 0 | 0 |
    | 100×30 | 7 | 7 |
    | 120×40 | 17 | 13 |

    - 80×24 sigue en el caso «ventana demasiado pequeña», que ahora se ve entero con la pregunta. Antes los botones tapaban la pregunta.
    - 120×40 cede 4 filas a los huecos.
- **Alternativas rechazadas:**
  - **Botones `compact` de 1 fila por debajo de 30 filas** (estudio §5.5). Darían 2 filas a 80×24, pero la propuesta seguiría sin sitio útil: 1 fila, por la cabecera de 12. Además se pierde el relieve y el objetivo de 48 px. Compactar la cabecera queda para otra iteración.
  - **Botones de etiqueta + 2×2 columnas alineados a la derecha** (estudio §5.5): anchos distintos por etiqueta. El encargo pide anchos iguales en múltiplos de 8 y la pareja centrada.
  - **Relleno `0 1` en modo denso** (estudio §3): a lo ancho no falta sitio (66 columnas de propuesta a 80). Con 2 columnas la propuesta se separa igual del borde grueso a cualquier tamaño.
  - **Huecos verticales a cualquier altura:** a 100×30 costarían 3 de las 7 filas de la propuesta.
- **Impacto:**
  - spec `interactive-shell`: el requisito «Botones dentro de la caja y distinguibles sin color»;
  - `tui.py` (CSS, `ApprovalScreen.compose` y `_confirming`) y `spacing.py`;
  - pruebas en `tests/unit/test_shell_tui_grid.py`.

  El resto de la pantalla (registro, panel, entrada y pie) no cambia aquí: va en una segunda fase con la misma escala, después de `collapsible-blocks`.

### D8 · El código en línea del modelo no se pinta como un aviso del harness

- **Qué:** `MD_CODE` pasa de `#e5c07b` a `$text-secondary`, una variable del tema que ningún estado del harness usa. Una prueba comprueba que ningún estilo de texto ajeno (`FOREIGN` y `MD_*`) lleva el color de `HARNESS_ERROR` ni el de `HARNESS_WARNING`, ni fondo, ni `reverse`. Otra dibuja una respuesta con `` `warning: disk full` `` y mira el color en pantalla.
- **Por qué:**
  - `MD_CODE` y `HARNESS_WARNING` tenían el mismo color (estudio, §4). Un `` `warning: …` `` del modelo se veía como un aviso del harness, aunque fuera dentro del recuadro.
  - Es imitación de chrome, lo mismo que D2 evita para los botones.
- **Alternativas rechazadas:**
  - Pasar ahora todo `STYLES` a variables del tema: es la segunda fase, junto con el resto de la pantalla.
  - Negrita para el código: `MD_STRONG` y `STATUS` ya la usan.
- **Impacto:**
  - `tui.py` (`STYLES`);
  - pruebas en `tests/unit/test_shell_tui_styles.py`;
  - spec `interactive-shell`: el requisito «El texto ajeno no se pinta como un aviso del harness».

### D9 · El armado no depende de la velocidad de la máquina (segunda ejecución en Windows, 2026-11-27)

- **Medido:** Windows 11, copia de prueba de `79cde60`, `arm_s=0.5`, tres ejecuciones de `test_keys_typed_ahead_of_the_box_cannot_approve`, tiempos desde el `on_mount` de la caja:
  - las teclas escritas por adelantado se procesaron entre +154 y +601 ms, +171 y +452 ms, y +159 y +458 ms, todas sin armar salvo un Enter a +601 ms (armada, foco en la propuesta, sin efecto);
  - la caja se armó a +502, +501 y +501 ms;
  - el Tab del test llegó a +656, +530 y +586 ms (armada, el foco pasa a Approve, habilitado porque la propuesta cabe), y su Enter a +702, +602 y +663 ms: aprobado, `written=1`.

  Ninguna tecla procesada sin armar tuvo efecto. Las que aprobaron llegaron después del plazo: el plazo solo por reloj caduca, y en una máquina lenta o un bucle ocupado no separa lo escrito antes de lo escrito después. Reproducido en macOS sin Windows: teclas creadas (leídas) antes de `_arm()` y entregadas después aprueban con el código anterior (`test_keys_read_before_a_late_arming_never_act`: la caja se cierra y aplica).
- **Qué:** dos reglas, juntas:
  1. **Silencio antes de armar.** Los botones se habilitan cuando la caja se ha pintado (`call_after_refresh` tras montarla, `shown`) y después ha pasado `ARM_S` sin ninguna tecla, pegado o botón del ratón. Cada entrada recibida sin armar reinicia la cuenta (`_quiet_from`); un único temporizador vuelve a mirar cuando el silencio se cumpliría (`_arm_if_quiet`).
  2. **Corte por la hora de lectura.** Cada evento de entrada trae la hora a la que el driver de Textual lo leyó del terminal (`Message.time`). Una entrada leída antes del momento del armado (`armed_at`) nunca actúa, por tarde que la procese el bucle. Se descarta donde se entrega (`check_message_enabled` de la propuesta, de los botones y de la caja), así que no llega a ningún binding ni burbujea. Textual rehace cada evento del ratón con una hora nueva antes de dárselo al widget, así que el ratón se juzga en la caja, sobre el evento que hizo el driver (`_forward_event`). Y como la aplicación fabrica el Click al procesar el MouseUp, un clic cuenta solo si su MouseDown pasó el filtro sobre ese mismo botón.

  La caja usa un solo reloj, el de los eventos (`ApprovalScreen.clock`), para el armado, la comprobación de `on_button_pressed` y la confirmación de Reject. ctrl+c, ctrl+q y ctrl+n son bindings prioritarios de la aplicación y siguen funcionando sin armar. Las teclas de desplazamiento con binding propio (`pagedown`, `end`…) tampoco deciden y también reinician el silencio.
- **Por qué:** lo que se promete es que lo escrito antes de que la caja aparezca no aprueba. La primera regla cubre a quien sigue escribiendo cuando aparece la caja: mientras escribe, la caja no se arma. La segunda cubre el bucle ocupado: las teclas ya leídas que el bucle procesa tarde. Ninguna depende de cuánto tarde la máquina.
- **Alternativas rechazadas:**
  - Solo silencio: con el bucle ocupado, el temporizador y las teclas ya leídas se procesan juntos y el orden no está garantizado; el armado puede ir primero.
  - Solo armar en el primer momento ocioso tras montar la caja: las colas de la aplicación y de la pantalla son distintas, así que «ocioso» no garantiza que lo ya leído se haya procesado.
  - Subir `ARM_S`: sigue dependiendo de la velocidad de la máquina y hace esperar a todos.
  - Descartar toda entrada sin armar: impediría desplazarse por la propuesta con el teclado en el primer medio segundo, sin cerrar nada que el silencio no cierre ya.
- **Residual (escrito, no se arregla):** unas teclas que el terminal, el sistema o una sesión remota retengan y entreguen después de `ARM_S` de silencio llegan con hora nueva, y ninguna aplicación las distingue de unas teclas nuevas. La regla depende del reloj con el que Textual sella los eventos (`textual._time.get_time`, privado; Textual está fijado exacto y un test compara los dos relojes).
- **Impacto:**
  - spec `interactive-shell`: el texto del requisito «Nada aprueba al abrirse la caja» y tres escenarios nuevos;
  - `tui.py`: `ProposalArea`, `ApprovalButton` y `ApprovalScreen`;
  - pruebas en `tests/unit/test_shell_tui_arming.py`;
  - `tests/tui_support.py` (`approval_box`, que espera a `shown`; ver 8.2).

## Risks / Trade-offs

- [Aprobar es más fácil que con el código: un Tab y un Enter] → lo aceptó Wilson el 2026-11-27. Las protecciones de D2 cierran lo accidental, y lo deliberado sigue ligado al hash, con caducidad y uso único.
- [Un clic llega en el primer medio segundo y se pierde] → es lo pedido; el botón se ve deshabilitado hasta que se puede pulsar.
- [Quien sigue escribiendo cuando aparece la caja no la ve armarse hasta que para medio segundo] → es lo pedido (D9); el botón se ve deshabilitado.
- [Un terminal o una sesión remota retienen teclas más de `ARM_S` y las entregan después] → residual escrito en D9: llegan como teclas nuevas.
- [Textual cambie cómo trata un `Button` deshabilitado o el orden de Tab] → Textual está fijado exacto. Las pruebas de la caja fallan si un botón deshabilitado se puede pulsar o enfocar.
- [Una pulsación de una caja vieja llega a la siguiente] → se vacía al abrir, y el motor exige el mismo hash.
- [Quien quiera escribir el código en la pantalla completa no puede] → `chat --plain`.

## Open Questions

(ninguna)
