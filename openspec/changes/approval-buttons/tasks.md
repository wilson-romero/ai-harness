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

## 7. Segunda ejecución en Windows (2026-11-27, `develop` = `79cde60` y `34eb55d`) (D9)

Wilson ejecutó `develop` en Windows 11. Dos hallazgos son de esta caja: `test_keys_typed_ahead_of_the_box_cannot_approve` fallaba en cada ejecución, y los casos `[120x40]`, `[100x30]` y, sobre `34eb55d`, `[80x24]` de `tests/unit/test_shell_tui_grid.py` fallaban con `NoMatches '#reject'` / `'#approval-confirm'` bajo carga (pasan solos). Rama `bugfix/windows-parity-2`.

- [x] 7.1 Armado que no depende de la velocidad de la máquina (D9). Hecho: los botones se habilitan tras `ARM_S` sin entrada contado desde el primer pintado, cada entrada sin armar reinicia la cuenta, y una entrada leída antes del armado nunca actúa. Cambios en `tui.py` solo en `ProposalArea`, `ApprovalButton` y `ApprovalScreen`.
  - Oráculo: `tests/unit/test_shell_tui_arming.py` (24 casos, reloj de prueba en `ApprovalScreen.clock`, eventos con su hora de lectura entregados por `App.post_message` como hace el driver):
    - la traza de Windows reproducida (tres ejecuciones y la combinación «teclas hasta +601 ms, Tab +530, Enter +602»): pendiente;
    - silencio y luego Tab+Enter a 0,6 y 2 s, en una ráfaga y una a una: aprueba una vez;
    - teclas o clic leídos a 0 y 0,4 s y procesados tras armar a 0,6 s, en una ráfaga y uno a uno: pendiente; los mismos leídos después del armado: aprueban;
    - una entrada sin armar retrasa el armado exactamente `ARM_S` desde ella;
    - el reloj de la caja es el de los eventos.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8). Antes del cambio, `test_keys_read_before_a_late_arming_never_act`, que solo usa la API anterior (`_arm()`), falla: la caja se cierra y aplica (`isinstance(Screen(id='_default'), ApprovalScreen)` es falso). Es el fallo de Windows, sin Windows. Con el cambio: `test_shell_tui_arming.py` 24 passed; `test_shell_tui_buttons.py` pasa sin tocar ninguna aserción (41 passed entre los dos ficheros).
  - Controles por mutación (`harness/shell/tui.py` mutado, restaurado tras cada uno):
    - M1, sin el corte por hora de lectura: 9 failed (los 8 casos «leído antes, procesado después» y la reproducción);
    - M2, sin reiniciar el silencio: 6 failed (las 4 trazas de Windows y los 2 casos a 0,4 s);
    - M3, un Click que no exige su MouseDown: 4 failed (los casos de clic);
    - M4, el ratón sin juzgar en la caja: 4 failed (los casos de clic: Textual rehace el evento con hora nueva).
- [x] 7.2 Los tests esperan a que la caja esté pintada. Causa: Textual pone la pantalla en la pila antes de componerla, y el hilo del núcleo la empuja mientras Pilot espera a la pantalla anterior; la comprobación `isinstance(app.screen, ApprovalScreen)` era cierta con la caja aún sin widgets.
  - Hecho: `Tui.approval_box()` (`tests/tui_support.py`) espera a `shown`. Se usa en `_approval` (`test_shell_tui.py`, del que dependen `test_shell_tui_buttons.py` y la traza), en `_open` (`test_shell_tui_grid.py`, todos los tamaños), en `test_shell_tui_blocks.py` y en `test_keys_typed_ahead_of_the_box_cannot_approve`. Comprobado por grep: `test_shell_tui_replies.py` y `test_shell_tui_styles.py` no abren la caja.
  - Oráculo: `test_the_box_is_waited_for_until_its_widgets_exist` (80×24, 100×30, 120×40). La caja tarda 0,3 s en componerse y se empuja como lo hace el núcleo (`open_approval`); justo después, la consulta da `NoMatches`, y `approval_box` espera hasta tener `#reject` y `#approval-confirm`.
  - Recibo (2026-11-27, macOS): 16 passed en `test_shell_tui_grid.py`. Control negativo: con `approval_box` reducido a la espera anterior (`isinstance` solo), 3 failed con `NoMatches '#reject'` y `NoMatches '#approval-confirm'`, los dos errores de Windows; restaurado, pasa.
- [x] 7.4 Baterías de la rama, una vez cada una con `caffeinate -i`, sobre `934557e` (2026-11-27, macOS arm64, Python 3.14.8). Oráculo: código 0 en cada tanda.
  - `-m "not edge and not copilot"`: 1949 passed en 332,13 s, código 0;
  - `-m edge`: 156 passed en 1185,13 s, código 0, ninguno repetido;
  - después, `openspec validate --all --strict` → 25 passed, 0 failed; `scripts/check_sec_matrix.py` → `sec-matrix: PASS (15 rows, 137 tests)`; `public-safety: PASS (452 file(s))`.
  - Estas cifras valen también para `hardening` 8.1 y `copilot-web-provider` 9.1.
- [x] 7.5 Revisión independiente de la rama (2026-11-27, sobre `65781e3` = `b4ee1ac` + `develop` `893694a`). H1, H3 y H4 se sostienen. Hallazgos en D9, corregidos con un test visto en rojo antes de cada arreglo, con el mismo reloj de prueba:
  - (1) MEDIO. Con el bucle detenido, la caja se armaba mientras la persona seguía escribiendo. El temporizador corría primero con el silencio contado desde el pintado; las teclas leídas durante la parada se descartaban sin reiniciar la cuenta, y Tab y Enter leídos después aprobaban. Arreglo: una entrada leída antes del armado desarma la caja, y el silencio se cuenta desde la hora de lectura de la última entrada.
    - Oráculo: `test_a_stall_then_a_burst_across_the_arming_approves_nothing` (8 casos: parada de 0,7 s y de 2 s, ráfaga que acaba antes o sigue después, teclas o ratón). Tras procesar las teclas la caja está desarmada, no se arma a «última lectura + 0,49 s» y sí a «+ 0,5 s», y la aprobación sigue pendiente.
    - También `test_a_click_pressed_before_a_late_arming_never_presses_even_if_it_rearms`: el botón baja antes de la parada y sube después de rearmarse.
  - (2) BAJO. La confirmación de Reject solo miraba la hora de proceso. Arreglo: la pregunta desarma y se arma con la misma regla; desaparece `confirm_opened`.
    - Oráculo: `test_the_confirmation_ignores_input_read_just_after_it_appeared` (Tab y Enter leídos a +10 ms y procesados a +0,6 s: pendiente) y el control positivo `test_the_confirmation_accepts_input_after_its_silence`.
  - (3) BAJO. Huecos de los tests:
    - `test_a_paste_restarts_the_silence`;
    - `test_each_widget_of_the_box_filters_input_read_before_the_arming`, para `#approve`, `#reject` y la propuesta: cada filtro, directamente;
    - el reloj de prueba sella ahora todo mensaje de Textual (`textual.message._time`), así que el Click que fabrica la aplicación lleva hora de prueba, sea cual sea el tiempo de encendido de la máquina.
  - (4) BAJO, del lanzador de Edge: ver `copilot-web-provider` 9.3.
  - Recibo (2026-11-27, macOS arm64, Python 3.14.8):
    - antes de los arreglos, 12 failed: los 8 casos de la parada, la confirmación y los 3 filtros por widget;
    - después, `test_shell_tui_arming.py` + `test_shell_tui_buttons.py` + `test_shell_tui_grid.py` → 71 passed;
    - todos los `tests/unit/test_shell_tui*.py`, `test_portability.py` y `test_edge_launch_errors.py` → 240 passed;
    - de paso, un temporizador de Textual con intervalo 0 lanza `ZeroDivisionError` (`timer.py:120`): con espera 0 se usa `call_later`.
  - Mutantes sobre `test_shell_tui_arming.py` (38 tests en ese momento):
    - M1, sin corte por hora de lectura: 21 failed;
    - M2, sin reiniciar el silencio: 15 failed;
    - M4, el ratón sin juzgar en la caja: 4 failed;
    - M5, descartar sin desarmar: 11 failed;
    - M6, silencio desde la hora de proceso: 4 failed;
    - M7, la pregunta sin desarmar: 1 failed;
    - M8, Paste fuera de `_deciding`: 1 failed;
    - M9, sin filtro en la propuesta: 1 failed;
    - M10, sin filtro en los botones: 2 failed.
    - M3, un Click sin exigir su MouseDown, sobrevivía: con el desarmado, un MouseUp leído antes también desarma y el Click encuentra el botón deshabilitado. Se añadió el caso en que el botón sube después de rearmarse: con M3, 1 failed; sin M3, pasa.
  - Baterías sobre `7dd9894` (los arreglos, con `develop` `893694a` dentro), una vez cada una con `caffeinate -i`: `-m "not edge and not copilot"` 2070 passed en 377,92 s, código 0; `-m edge` 156 passed en 1563,70 s, código 0, ninguno repetido; `openspec validate --all --strict` 26 passed; `sec-matrix: PASS (15 rows, 138 tests)`; `public-safety: PASS (461 file(s))`.
- [x] 7.3 Confirmación en Windows (no es puerta). En PowerShell, en la rama:
  - `uv run pytest tests/unit/test_shell_tui_arming.py tests/unit/test_shell_tui_buttons.py -v` → todo pasa, también con la máquina cargada;
  - `uv run pytest tests/unit/test_shell_tui_grid.py tests/unit/test_shell_tui_blocks.py tests/unit/test_shell_tui.py -v`, tres veces, y la batería completa `uv run pytest -m "not edge and not copilot"` → ningún `NoMatches`;
  - Estado: **PASS** sobre `develop` = `a9c51fe` (2026-11-27, Windows 11): los tests de armado pasan en reposo y con una carga de CPU del 11 al 67 %; ningún `NoMatches` en tres ejecuciones; en la batería (2321 pasados, 3 fallos) ningún fallo es de esta caja.

## 8. Demo

- [ ] 8.1 Demo (Wilson, macOS): con el Mock, `/skill architecture-memory` en la pantalla completa (pasos en el informe del change).
  - Qué comprobar:
    - Enter al abrir no hace nada;
    - si se sigue escribiendo cuando la caja aparece, los botones no se habilitan hasta medio segundo después de la última tecla (D9);
    - con una propuesta larga, Approve espera al final;
    - Tab y Enter aprueban;
    - en otra ejecución, Reject → Back la deja pendiente;
    - `chat --plain` sigue pidiendo el código.
  - Evidencia: el SHA de la rama y una captura.
  - Estado: **NOT RUN**, pendiente de Wilson.
