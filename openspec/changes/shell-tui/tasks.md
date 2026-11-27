# Tasks

Cada `[x]` lleva su recibo debajo, con fecha y plataforma. Los oráculos se nombran en cada tarea. Todo se ejecutó en macOS arm64 con Python 3.14.8; Windows no se ha ejecutado (ver «Supuestos de Windows» en `design.md`).

## 1. Rama, dependencia y premisas

- [x] 1.1 Rama `feature/shell-tui` desde `feature/shell-appearance` (`f8aa64a`, PR #25, que no se toca); `textual==8.2.8` fijada exacta y `prompt_toolkit` quitada. Hecho: `uv lock --check` pasa y `import textual` funciona en Python 3.14.
  - Recibo (2026-11-26, macOS arm64): `uv remove prompt_toolkit` → quita `prompt-toolkit==3.0.53` y `wcwidth==0.9.5`; `uv add "textual==8.2.8"` → instala `textual 8.2.8`, `rich 15.0.0`, `markdown-it-py 4.3.0`, `mdit-py-plugins 0.7.0`, `linkify-it-py 2.2.0`, `mdurl 0.1.2`, `platformdirs 4.14.8` (`pygments`, `typing-extensions` y `uc-micro-py` ya estaban o llegan con ellos). Versiones, licencias y fechas leídas de la API JSON de PyPI el mismo día.
- [x] 1.2 Leer en el código instalado de Textual lo que fija el diseño: atajos por defecto, modo crudo y Ctrl+C (POSIX y Windows), *markup* en `str`/`Content`/`border_title`, el widget `Markdown` y `open_url`, el pegado de `Input`, las variables de depuración, las órdenes de sistema de la paleta, `run_test`/`Pilot`. Oráculo: las citas de fichero y línea en `design.md` («Premisas leídas»).
  - Recibo (2026-11-26, macOS arm64): context7 no estaba disponible; leído en `.venv/lib/python3.14/site-packages/textual/` (`app.py`, `visual.py`, `content.py`, `widget.py`, `widgets/_markdown.py`, `widgets/_input.py`, `constants.py`, `drivers/linux_driver.py`, `drivers/win32.py`, `command.py`, `_compositor.py`).

## 2. Núcleo y corte vertical

- [x] 2.1 Costura del núcleo sin bifurcarlo (D2, D4, D6): `ShellState.panel` y `sessions`, `PanelState`, `ApprovalTerminal`, notas de la última pregunta; `converse` común a los dos modos en `app.py`. Oráculo: la batería existente de la conversación pasa sin tocar ninguna aserción.
  - Recibo (2026-11-26, macOS arm64): `uv run pytest -q tests/unit/test_shell_*.py tests/security/test_shell_output.py tests/integration/test_chat_*.py tests/unit/test_portability.py` → 316 passed tras los arreglos de 2.2 (ninguna aserción de las pruebas del núcleo cambió; las de `prompt_toolkit` se borraron con su módulo).
- [x] 2.2 Pantalla completa con el Mock: disposición, pregunta, bloque de respuesta, panel (D1-D3). Oráculo: `tests/unit/test_shell_tui.py` (pregunta → bloque «you», bloque ajeno titulado `mock`, panel con la sesión tomada; captura de texto de 100 × 24). Control negativo: el bloque ajeno con *markup* activado.
  - Recibo (2026-11-26, macOS arm64): pasa. Dos fallos reales encontrados al probar: `App._closing` es un atributo privado de Textual y el nuestro con ese nombre impedía salir (renombrado `_leaving`); y las llamadas del núcleo por `call_soon_threadsafe` se ejecutaban fuera del contexto de la aplicación (`NoActiveAppError` al abrir la caja); ahora cruzan como mensaje (`CoreCall`), que Textual admite desde cualquier hilo.

## 3. Paleta, selectores y aprobación

- [x] 3.1 Paleta con solo órdenes del harness y selectores de sesión, Skill y fichero (D5). Oráculo: `test_the_palette_runs_a_harness_command`, `test_the_palette_offers_only_the_harness_commands`, `test_the_session_picker_switches_session`, `test_the_skill_picker_fills_the_input`, `test_the_file_picker_attaches_a_file`. Control negativo: devolver las órdenes de sistema de Textual.
  - Recibo (2026-11-26, macOS arm64): pasan; control negativo → `1 failed`.
- [x] 3.2 Caja de aprobación (D6): concedida con el código, las tres variantes del rechazo, Ctrl+C, respuesta adelantada, pegado, paleta encima. Oráculo: las pruebas `test_an_approval_…`, `test_the_rejection_…`, `test_ctrl_c_in_the_approval_box_…`, `test_an_answer_typed_ahead_…`, `test_a_paste_…`, `test_the_palette_never_opens_…`. Controles negativos: sin `ARM_S`, pegado aceptado, respuesta en el historial, paleta sobre la caja.
  - Recibo (2026-11-26, macOS arm64): pasan; cada control negativo → `1 failed`. Un fallo real del aspecto encontrado al probar: el hash salía partido en dos filas `|+` dentro de la caja; ahora la caja recibe las líneas de la cabecera sin cortar.

## 4. Garantías, terminal real y pulido

- [x] 4.1 Garantías con su control negativo (D3, D7, D8): respuesta hostil (`[@click=…]`, `[link=…]`, OSC 8, ESC, caja y panel falsos, clic), 1 MiB, cambio de tamaño, Ctrl+C en pregunta / sin nada / al abrir (130), salir durante una pregunta, línea con el núcleo ocupado, historial en memoria, elección de terminal y variables de Textual. Oráculo: `tests/unit/test_shell_tui.py`. Controles negativos aplicados con un guion fuera del repositorio (mutación, prueba, restauración): *markup* activado, pegado aceptado, sin `ARM_S`, `ctrl+c` de Textual, panel sin refrescar, órdenes de sistema, líneas aceptadas con el núcleo ocupado, `TEXTUAL_LOG` ignorada en `textual_is_quiet` y en `plain_reason`, respuesta en el historial, paleta sobre la caja, Ctrl+C sin nada que sale.
  - Recibo (2026-11-26, macOS arm64): 12 de 12 controles → `1 failed` (ninguno sobrevive). El de `plain_reason` sobrevive a la prueba de pseudoterminal porque la segunda defensa (`textual_is_quiet`) también deja la conversación en texto plano; lo detecta la tabla unitaria.
- [x] 4.2 `main.py chat` real en pseudoterminal (`tests/integration/test_chat_tui_terminal.py`, omitido con motivo donde no hay `pty`): pregunta y `ctrl+q`, Ctrl+C sin nada y durante la pregunta (`uncertain`, una sola petición), SIGTERM, texto plano con `--plain`, `NO_COLOR`, `TERM=dumb`, `HARNESS_PLAIN` y `TEXTUAL_LOG` (sin crear el fichero). En todas las salidas: se deja la pantalla alternativa y se muestra el cursor.
  - Recibo (2026-11-26, macOS arm64): 8 passed.
- [x] 4.3 El núcleo no corta filas en la pantalla completa; el panel pone envíos y estado antes de la lista de notas. Oráculo: la prueba del cambio de tamaño (el bloque se estrecha y crece en alto, sin filas `|+`) y la captura del README.
  - Recibo (2026-11-26, macOS arm64): pasa.
- [x] 4.4 README, «Conversación › Aspecto»: captura de texto (Pilot, contenido sintético), bloques, panel, teclas, aprobación y cómo quitarlo.
  - Recibo (2026-11-26, macOS arm64): hecho con `capture_tui.py` (fuera del repositorio) sobre una copia de `tests/fixtures/vault-synthetic`.
- [x] 4.5 `scripts/verify.sh` sobre el árbol limpio. Oráculo: código 0 y la línea `verify: PASS on <sha>`.
  - Recibo (2026-11-26, macOS arm64): `bash scripts/verify.sh` → código 0, `verify: PASS on 656a51cdb98e95a93ce1072a85a108bdf2d06384` (1478 passed en 244,95 s; public-safety PASS; OpenSpec 18 passed). El SHA es el del commit anterior al que añade este recibo (solo cambia `tasks.md`).
- [x] 4.7 Revisión independiente (2026-11-26), hallazgos 1 a 9 y mutantes M6 y M9 (`design.md` D6, D7, D8, riesgos). Oráculo: `tests/unit/test_shell_tui_review.py`, más dos pruebas nuevas en `tests/integration/test_chat_tui_terminal.py`: una sola escritura con dos líneas da una sola petición, y SIGHUP durante una pregunta sale con 0. Controles negativos aplicados con un guion fuera del repositorio (mutación, prueba, restauración, con caché de *bytecode* propia por mutante):
  - (1) tomar la línea sin cerrar la espera;
  - (5) conservar respuestas viejas;
  - (2) tomar el código sin haber visto el final, quitar `pagedown` de la caja, quitar el «N more line(s) below»;
  - (3) `ctrl+v` y `ctrl+x` sin anular;
  - (4) `action_screenshot`, `deliver_text`, `deliver_binary`, `open_url` y `copy_to_clipboard` sin anular;
  - (6) la traza de Textual;
  - (7) los descriptores sin redirigir tras SIGHUP;
  - (9) el fallo del *driver* sin capturar;
  - M6: sin `self._notes = ()` al cambiar de sesión;
  - M9: `ctrl+q` sin interrumpir la pregunta en curso, con un tiempo límite de 120 s para que no lo tape.
  - Recibo (2026-11-26, macOS arm64): 17 de 17 controles → `failed` (ninguno sobrevive). Los 12 controles de 4.1 se repitieron sobre el código nuevo: 12 de 12. En la primera pasada sobrevivieron dos mutantes, `action_screenshot` y la traza. La traza era un artefacto del guion: dos mutantes del mismo tamaño escritos en el mismo segundo reutilizaban el `.pyc`; ahora cada mutante usa una caché propia. `action_screenshot` sobrevivía porque la segunda defensa, `deliver_screenshot`, también lo paraba; la prueba ahora comprueba que la acción no llega a entregar nada.
- [x] 4.8 Receta de PowerShell del README («Paso a paso con el Mock») válida en Windows PowerShell 5.1 y en 7. En 5.1, `ConvertTo-Json` hace un objeto del texto de `Get-Content -Raw`; ahora se lee con `[IO.File]::ReadAllText` y se escribe UTF-8 sin BOM con `[IO.File]::WriteAllText`. Es la única receta de PowerShell que escribe un fichero, en el README y en `docs/runbook/`. El cargador del Mock ya acepta un BOM, como todo fichero UTF-8 que lee el harness (`strict_json.read_text_limited`), y no se cambia. Oráculo: `tests/unit/test_mock_script.py::test_a_responses_file_written_by_windows_powershell_loads`. Control negativo: quitar el `removeprefix("\ufeff")` de `decode_text_limited`.
  - Recibo (2026-11-26, macOS arm64): pasa; control negativo → `1 failed`. La receta en sí no se ha ejecutado: no hay PowerShell en esta máquina (va en 4.6).
- [x] 4.9 `scripts/verify.sh` tras la ronda de revisión, sobre el árbol limpio y con `origin/develop` (`7188870`) ya unido. Oráculo: código 0 y la línea `verify: PASS on <sha>`.
  - Recibo (2026-11-26, macOS arm64): `caffeinate -i bash scripts/verify.sh` → código 0, `verify: PASS on c2a66a28b725e7c627729b90e3bd48100455c5c3` (1502 passed en 261,15 s; public-safety PASS en 330 ficheros; OpenSpec 18 passed). El SHA es el del commit anterior al que añade este recibo (solo cambia `tasks.md`).
- [x] 4.10 Ejecución en Windows 11 de `de089d1`: la prueba `test_no_app_action_writes_opens_or_copies_out` fallaba. La ruta de `tmp_path` iba entre comillas simples dentro de la acción `screenshot(...)`, y Textual lee los argumentos con `ast.literal_eval`: una ruta de perfil de Windows (la unidad y luego la carpeta Users) es un escape `\U` truncado (`ActionError`), así que la prueba no llegaba a su comprobación. Ahora la ruta entra con `repr`. La prueba se repite con una carpeta `sub\Users\probe` (en POSIX, un solo nombre con barras invertidas; en Windows, carpetas). Además comprueba que la acción llega a ejecutarse y se rechaza (`_refused("screenshots")`) sin entregar nada. Revisadas las demás pruebas de la rama (`test_shell_tui*.py`, `test_chat_tui_terminal.py`, `tui_support.py`, `test_shell_completion.py`, `test_mock_script.py`): ninguna otra mete una ruta en una acción, expresión regular, JSON o cadena de shell.
  - Recibo (2026-11-26, macOS arm64): con la cita antigua y la carpeta `sub\Users\probe`, el mismo error que en Windows (`unicodeescape … truncated \UXXXXXXXX escape`, `ActionError`); con `repr`, 2 passed. Los cinco controles negativos del grupo 4 siguen fallando como deben (`2 failed` cada uno).
- [ ] 4.6 Windows (Wilson): lo que dice «Supuestos de Windows» en `design.md`. Además, en Windows PowerShell 5.1 (`powershell.exe`) y en 7 (`pwsh`), las líneas de `respuestas.json` del README: `Get-Content -Raw $w\respuestas.json` debe empezar por `{` y `(Get-Content -Raw $w\respuestas.json | ConvertFrom-Json).'tarea: architecture-memory/extract'.GetType().Name` debe dar `String`; y `/skill architecture-memory` debe llegar a la caja de aprobación. Resultado: PASS, FAIL o NOT RUN con lo que se vio.

## 5. Archivo

- [ ] 5.1 Antes de archivar: archivar `shell-appearance` y convertir en este delta sus cuatro requisitos de la terminal con estilo en MODIFIED/REMOVED (proposal, «Modified Capabilities»).

## 6. Demo

- [ ] 6.1 Demo (Wilson, macOS): `HARNESS_PROVIDER=mock HARNESS_MOCK_DELAY_MS=4000 uv run python main.py chat`; una pregunta (se ve `mock: thinking (N s)` y el bloque `mock`), `ctrl+c` durante otra, `ctrl+p` → «Switch session...», `ctrl+n`, `/skill` con aprobación en su caja, `ctrl+q`; después `--plain`. Evidencia: SHA de la rama y una captura. Estado: **NOT RUN** (pendiente de Wilson).
