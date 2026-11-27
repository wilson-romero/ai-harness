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

## Risks / Trade-offs

- [Aprobar es más fácil que con el código: un Tab y un Enter] → lo aceptó Wilson el 2026-11-27. Las protecciones de D2 cierran lo accidental, y lo deliberado sigue ligado al hash, con caducidad y uso único.
- [Un clic llega en el primer medio segundo y se pierde] → es lo pedido; el botón se ve deshabilitado hasta que se puede pulsar.
- [Textual cambie cómo trata un `Button` deshabilitado o el orden de Tab] → Textual está fijado exacto. Las pruebas de la caja fallan si un botón deshabilitado se puede pulsar o enfocar.
- [Una pulsación de una caja vieja llega a la siguiente] → se vacía al abrir, y el motor exige el mismo hash.
- [Quien quiera escribir el código en la pantalla completa no puede] → `chat --plain`.

## Open Questions

(ninguna)
