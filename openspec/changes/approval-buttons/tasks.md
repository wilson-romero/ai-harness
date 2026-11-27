# Tasks

## 1. El motor

- [x] 1.1 `decide` devuelve `Verdict(decision, means)`. Con una `ButtonApprovalTerminal`, acepta solo un `ButtonPress` con el hash de la pregunta. Sin ella, pide el código como antes, y una respuesta que no sea texto es `undecided` (D1). La auditoría de `approval.granted` y `approval.rejected` lleva `;means=button` o `;means=code`.
  - Oráculo: `tests/unit/test_skill_approval_buttons.py`. Comprueba la pulsación para el hash preguntado y la que trae otro hash, el rechazo, la falta de respuesta, el código registrado como `code`, que `ConsoleTerminal` y `TtyTerminal` no tienen la vía del botón, y que ningún texto ni objeto dado a la pregunta escrita es una pulsación.
  - Controles negativos: el motor ignora el hash de la pulsación; una pulsación dada a la pregunta escrita concede; el modo no se audita.
  - Recibo (2026-11-27, macOS arm64): 14 passed. Cada control negativo → `1 failed`.

## 2. La caja con botones

- [x] 2.1 `ApprovalScreen` con [Approve] [Reject] fijos abajo, la propuesta enfocable y neutra, el armado de `ARM_S`, «Approve» solo tras mostrar el final, una pulsación por caja, la pregunta de Reject con el foco en Back, Escape sin decidir, `TuiTerminal.ask_buttons` y `press`. Se quita la entrada del código (D2, D3, D4).
  - Oráculo: `tests/unit/test_shell_tui_buttons.py` (15 pruebas). Cubren:
    - Tab y Enter, y Enter mantenido;
    - el doble clic en Approve;
    - Enter, Espacio, `ctrl+v` y un pegado de varias líneas al abrir;
    - teclas, clics y una pulsación directa mientras se arma;
    - lo escrito por adelantado;
    - una propuesta de 120 líneas: Tab va a Reject y el clic en Approve no cuenta;
    - la rueda hasta el final;
    - Reject con Back, Escape y Yes;
    - el doble clic en Reject;
    - Escape y `ctrl+q`;
    - botones dibujados por la respuesta y clics sobre ellos;
    - los atajos de la aplicación;
    - una pulsación por caja y solo para su hash;
    - ninguna caja para un hash que el aviso no muestra.
  - Controles negativos, aplicados con un guion fuera del repositorio (mutación, prueba, restauración, con caché de *bytecode* propia por mutante):
    - sin armado;
    - Approve antes de mostrar el final;
    - foco en Approve al armarse;
    - la propuesta sin poder tomar el foco;
    - Reject sin su pregunta;
    - la pregunta con el foco en Yes;
    - el doble clic que confirma;
    - Escape que decide;
    - una segunda pulsación aceptada;
    - la caja que se abre para cualquier hash;
    - la posición del área sin vigilar.
  - Recibo (2026-11-27, macOS arm64): 15 passed. 14 de 14 controles fallan, contando también los tres del motor (1.1). «La caja que se abre para cualquier hash» se detecta porque la prueba se queda esperando una pulsación que no llega: tiempo agotado, que cuenta como detectado. «Sin armado» falla en las dos pruebas de Pilot. La de pseudoterminal (2.2) sigue pasando con ese mutante: lo escrito con la línea del Skill llega antes de que exista la caja y lo recibe la entrada de la conversación, así que esa prueba no comprueba el armado; lo comprueban las de Pilot.
  - Un fallo real encontrado al probar: con `arm_s = 0`, `set_timer(0)` de Textual divide por cero. Ahora la caja se arma tras el primer dibujado.
- [x] 2.2 Pseudoterminal: `main.py chat` real con el Mock. La línea del Skill y, en la misma escritura, Tab, Enter y Espacio; la caja se abre y sigue pendiente; después Tab y Enter aprueban y la auditoría dice `means=button`. Se omite donde no hay `pty`.
  - Oráculo: `tests/integration/test_chat_tui_terminal.py::test_the_approval_buttons_at_a_real_terminal`.
  - Recibo (2026-11-27, macOS arm64): pasa.
- [x] 2.3 Las pruebas de la entrada del código salen de `tests/unit/test_shell_tui.py` y `tests/unit/test_shell_tui_review.py`, y sus protecciones pasan a 2.1. Siguen las de Ctrl+C en la caja y la paleta sobre la caja, que ahora comprueba el foco en la propuesta. El texto plano y la CLI no cambian: `tests/unit/test_shell_skills.py`, `tests/unit/test_skill_approval.py` y `tests/integration/test_architecture_memory.py` pasan sin tocarlos.
  - Recibo (2026-11-27, macOS arm64): `uv run pytest -m "not copilot and not edge"` → 1609 passed, 155 deselected.

- [x] 2.4 Revisión independiente (2026-11-27), dos hallazgos.
  - **Grave:** «Approve» se habilitaba con la última fila todavía oculta. `_watch_scroll` calculaba `int(max_scroll_y - scroll_y)`, pero Textual dibuja en `round(scroll_y)` (`Widget.scroll_offset`, `textual/widget.py:2391`). Con la posición 0,7 antes del final, que es lo que manda arrastrar la barra con desplazamiento suave, el cálculo daba 0, mientras la pantalla dibujaba una fila antes del final. Ahora se decide con `max_scroll_y - scroll_offset.y`, lo dibujado, y la cuenta de «N more line(s) below» usa el mismo valor.
  - **Menor, que ya fallaba cerrado:** a 80×24 el área de la propuesta queda con 0 filas y nada decía por qué «Approve» no se habilitaba. Ahora la caja lo dice (`NO_ROOM`: agrandar la ventana o usar `chat --plain`) y «Approve» sigue deshabilitado.
  - Oráculo: `test_a_fractional_scroll_short_of_the_end_is_not_the_end` y `test_a_window_too_small_for_the_proposal_says_so`, en `tests/unit/test_shell_tui_buttons.py`.
  - Controles negativos:
    - Las dos pruebas se vieron fallar primero sobre el código revisado (`7fec353`): `2 failed`.
    - Después, como mutantes: volver a `int(max_scroll_y - scroll_y)` y no decir nada sin sitio → `1 failed` cada uno.
  - Recibo (2026-11-27, macOS arm64): 17 passed. Los 16 mutantes de la caja y del motor, que son los 14 de antes más estos 2, fallan; ninguno sobrevive.
  - Sin hacer: dar al área unas filas mínimas compactando la cabecera en ventanas pequeñas (queda en el informe).

## 3. Comprobaciones del corte

- [x] 3.1 Sin código por plataforma: `tests/unit/test_portability.py` pasa con los ficheros nuevos.
  - Recibo (2026-11-27, macOS arm64): incluido en 2.3.
- [x] 3.2 Las pruebas marcadas `edge` (el proveedor de Copilot Web contra páginas sintéticas locales), una vez, con `caffeinate -i`, porque pasan por la aprobación del motor.
  - Oráculo: código 0 de `uv run pytest -m edge`.
  - Recibo (2026-11-27, macOS arm64, sobre `38f1d31`): código 0, 153 passed y 1612 deselected, en 1391,40 s.
  - Recibo tras la revisión y el merge de `develop` (`57c413d`, sin conflictos), sobre `100cda0`:
    - `uv run pytest -m edge`: código 0, 155 passed en 1205,67 s;
    - `uv run pytest -m "not edge and not copilot"`: código 0, 1644 passed en 286,03 s;
    - `openspec validate --all --strict`: 21 de 21.

## 4. Documentación

- [x] 4.1 `README.md` («Conversación › Aspecto»): la caja con sus botones, qué hace cada tecla y que el texto plano y la CLI siguen con el código.
- [x] 4.2 `SECURITY.md` («Aprobaciones de Skills»): qué protege el botón y qué no; un programa que maneje la terminal puede pulsarlo igual que podía escribir el código.
- [ ] 4.3 Cuando se mergee `feature/hardening`, actualizar en `docs/security/known-debt.md` el apartado «la aprobación no prueba que haya una persona» con el botón (D6).

## 5. Archivo

- [ ] 5.1 Al archivar: este delta pasa a MODIFIED sobre «Caja de aprobación en la pantalla completa», «Entrada de la aprobación» y «La propuesta entera antes del código» (de `shell-tui`), y sobre «Solo una persona en una terminal interactiva aprueba» y «Auditoría de aprobaciones sin contenido» (de `skill-engine`), después de archivar esos dos changes.

## 6. La caja sobre la escala de espaciado (D7, D8)

- [x] 6.1 La escala vive en `harness/shell/spacing.py` y se declara como variables CSS. La caja la usa:
  - botones de 16×3, separados 8 columnas y centrados;
  - 2 columnas de relleno;
  - filas en blanco según la altura (`-tight`, `-snug` y `-roomy`);
  - la confirmación de Reject en dos líneas, la pregunta encima de los botones;
  - estados por atributo del texto.

  Ninguna protección cambia: las pruebas de la caja pasan sin tocar una sola aserción.
  - Oráculo: `tests/unit/test_shell_tui_grid.py`, con 13 pruebas a 80×24, 100×30 y 120×40, y las pruebas sin cambios de `test_shell_tui_buttons.py`, `test_shell_tui.py` y `test_shell_tui_review.py`.
  - Recibo (2026-11-27, macOS arm64):
    - Sobre el `tui.py` de `e65d250` las 13 fallan: 13 failed.
      - El hueco real entre los botones era de 4 columnas, porque Textual funde los márgenes `0 4`.
      - «Yes, reject» quedaba fuera de la pantalla.
      - Faltaban la fila en blanco y el relleno de 2 columnas.
      - Los tres estados tenían solo 2 estilos de texto.
    - Con el cambio: 15 passed (grid y estilos) y 72 passed con las otras pruebas de la caja.
    - Controles negativos (`PYTHONPYCACHEPREFIX` nuevo por mutante): 12 de 12 mutantes fallan.
      - Hueco de 4 → 6 failed.
      - Ancho de 15 → 6 failed.
      - «Reject» más ancho → 3 failed.
      - Sin la fila sobre los botones → 2 failed.
      - Sin la regla `-tight` → 1 failed.
      - Sin la regla `-roomy` → 1 failed.
      - `-roomy` a cualquier altura → 5 failed.
      - Sin tachado → 1 failed.
      - Sin vídeo inverso → 1 failed.
      - Confirmación en una fila → 3 failed.
      - Relleno de 1 → 2 failed.
      - `MD_CODE` amarillo → 2 failed.
  - Filas de propuesta, medidas con Pilot con una propuesta de 43 líneas:

    | Tamaño | Antes | Después |
    |---|---|---|
    | 80×24 | 0 | 0 |
    | 100×30 | 7 | 7 |
    | 120×40 | 17 | 13 |
- [x] 6.2 `MD_CODE` con `$text-secondary`: el código en línea del modelo no lleva el color de un aviso del harness (D8).
  - Oráculo: `tests/unit/test_shell_tui_styles.py`, con 2 pruebas: los estilos y el color dibujado en pantalla.
  - Recibo (2026-11-27): con `#e5c07b`, 2 failed (`md.code`: `Color(229, 192, 123)` es el de `harness.warning`); con el cambio, 2 passed.
- [x] 6.3 Las dos tandas, una vez cada una con `caffeinate -i`, después del merge de `develop`: `-m "not edge and not copilot"` y `-m edge`. Después, `openspec validate --all --strict` y `scripts/check_public_safety.py`.
  - Oráculo: código 0 en cada tanda; 0 errores de validación; `public-safety: PASS`.
  - Recibo (2026-11-27, macOS arm64), sobre `11c50f9`, el merge de `develop` `1b460ea`, sin conflictos:
    - `-m "not edge and not copilot"`: código 0, 1696 passed en 300,26 s;
    - `-m edge`: código 0, 155 passed en 1277,41 s;
    - `openspec validate --all --strict`: 22 de 22;
    - public-safety: PASS en cada commit (hook).

## 7. Demo

- [ ] 7.1 Demo (Wilson, macOS): con el Mock, `/skill architecture-memory` en la pantalla completa (pasos en el informe del change).
  - Qué comprobar:
    - Enter al abrir no hace nada;
    - con una propuesta larga, Approve espera al final;
    - Tab y Enter aprueban;
    - en otra ejecución, Reject → Back la deja pendiente;
    - `chat --plain` sigue pidiendo el código.
  - Evidencia: el SHA de la rama y una captura.
  - Estado: **NOT RUN**, pendiente de Wilson.
