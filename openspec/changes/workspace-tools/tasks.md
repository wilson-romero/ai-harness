# Tasks

Leyenda: **oráculo** = qué dice SÍ; **control negativo** = la mutación o el caso con el que ese oráculo tiene que decir NO antes de marcar la tarea; **recibo** = lo que se pega aquí al marcarla (comando, SHA, cifra). Sin recibo, no se marca `[x]`.

## 1. Premisas y decisiones (antes de B1)

- [x] 1.1 Comprobar que hoy no hay herramientas de ficheros fuera del vault. Oráculo: `grep -rln "os.replace\|write_bytes\|write_text\|os.rename" harness/` lista solo escrituras del directorio de datos. Recibo (2026-11-27, `a9c51fe`): `harness/mcp/gateway.py` (rotación del log MCP), `harness/browser/profile.py` (marca del perfil) y `harness/browser/login.py` (`login.json`). Ninguna toma una ruta del modelo. La nota del vault escribe con `os.open`/`os.link` en `harness/memory/decisions.py`.
- [x] 1.2 Medir las premisas del diseño. Oráculo: `uv run python -c` sobre `string_refusal`, `normalise_content`, `MAX_PLAN_BYTES`, `MAX_STEPS`, `MAX_CONTENT_BYTES` y `NAME_PATTERN`. Recibo (2026-11-27, macOS, `a9c51fe`):
  - `string_refusal('a\nb')`, `('a\tb')` y `('a\r\nb')` dan `invisible_character`; `'x = 1'` da `None`;
  - `normalise_content('a\tb\r\nc') == 'a b\nc'`;
  - `16384 10 32768`;
  - `workspace` casa con `NAME_PATTERN`.
- [x] 1.3 Añadir el Corte 12 a `docs/plan/2026-11-24-ai-harness-cortes.md` **con la aprobación de Wilson**, y resolver el choque de numeración con `code-run` («Corte 11» = `response-mode`). Hecho: el párrafo «Revisado el … (Wilson): Corte 12» existe y cita este change.

  Recibo (2026-11-27): aprobado por Wilson. El párrafo «Revisado el 2026-11-27 (Wilson): Corte 12 · Herramientas de la carpeta de trabajo» está al final de `docs/plan/2026-11-24-ai-harness-cortes.md`.

  Revisado (2026-11-28, merge de `develop` = `8a8afbd`): `develop` ya trae el Corte 12 en la tabla de cortes (fila «12 · Herramientas de la carpeta de trabajo») y en la revisión «Revisado el 2026-11-27: plan por hitos», que además fija `code-run` como Corte 13. El párrafo de esta rama se quitó al resolver el merge para no duplicarlo; las decisiones del dueño siguen en `design.md`.

- [x] 1.4 Registrar en `design.md` la respuesta del dueño a las decisiones abiertas 1–10. Si alguna cambia, editar la decisión en su sitio, marcarla y releer `specs/workspace-files/spec.md`. Hecho: cada decisión dice «tomada por el dueño el …».

  Recibo (2026-11-27): `design.md` «Decisiones del dueño (2026-11-27)». Las decisiones 1, 3, 4 y 10 las tomó el dueño. Las 2, 7, 8 y 9 se adoptaron por defecto, y el dueño puede revisarlas. No cambió ninguna regla de la spec.

## 2. B1 · Carpeta, confinamiento, reglas fijas y lecturas por la CLI

- [x] 2.1 Crear el fixture de carpeta sintética `tests/fixtures/workspace/` con:
  - un generador que crea en `tmp_path` los casos que git no guarda: enlaces, enlace duro, fichero de solo lectura, CRLF, BOM, sin salto final, NUL, Latin-1 y 300 KiB;
  - los ficheros de texto normales y un `README.md` hostil (D16).

  Hecho: `tests/unit/test_workspace_fixture.py` comprueba que el generador produce cada caso. El guard de seguridad pública pasa sobre el fixture (sin nombres reales).

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): el generador es `tests/fixtures/workspace/build.py` (incluye `hostile.txt`, CRLF, BOM, NUL, Latin-1, 300 KiB, enlaces y enlace duro). No hay `test_workspace_fixture.py` aparte: cada caso del generador lo usa un test (`test_the_fixture_cases_are_refused`, `test_list_marks_links_and_denied_entries_and_never_descends_into_them`, `test_newline_styles`) y la demo. El fichero de solo lectura y el «sin salto final» pasan a B3, donde importan. public-safety: PASS.

- [x] 2.2 Validación de la carpeta (D1). Oráculo: un test parametrizado con cada motivo (`not_absolute`, `link`, `not_a_directory`, `harness_repo`, `data_dir`, `vault`, `code_run_root`, `home`, `filesystem_root`), en los dos sentidos (dentro y conteniendo), más una subcarpeta de la carpeta personal aceptada. Control negativo: quitar la comprobación «contiene» hace fallar el caso `data_dir` contenido. Recibo: salida de pytest con el caso que falla.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `tests/unit/test_workspace_root.py`, cada motivo en los dos sentidos. `code_run_root` queda **aplazado** (design B1-3): `code-run` no está mergeado. Control negativo: las mutaciones 33–41 de 2.12 (quitar el sentido «contiene» mata `test_a_vault_that_does_not_exist_yet_is_still_protected_by_name`).

- [x] 2.3 Forma de ruta pura (D2, fase 1). Oráculo: tabla de cadenas literales con cada rechazo:
  - `..`, `/x`, `C:\x`, `C:x`, `\\s\x`, `\\?\x`, `//x`;
  - `a\b`, `a:b`, `a//b`, `./a`;
  - `con.txt`, `NUL`, `a.`, `a `;
  - NFD, U+200B, `<`;
  - 1 025 caracteres y un componente de 256 bytes.

  Los aceptados también van en la tabla. El mismo test en todas las plataformas, sin `skip`. Control negativo: aceptar `\` hace fallar `a\b`. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `tests/unit/test_workspace_paths.py` (tabla REFUSED/ACCEPTED, sin `skip`, con todos los `FORM_CODES`). Control negativo: mutaciones 9–18 de 2.12 (aceptar `\` hace fallar `a\b`).

- [x] 2.4 Camino real y apertura (D2, fases 2 y 3). Oráculo, en `tests/security/test_workspace_confinement.py`:
  - nombre con otras mayúsculas: `name_not_exact`;
  - NFD guardado: `name_not_exact`;
  - colisión por mayúsculas en un nombre nuevo: `name_collision`;
  - enlace en un componente intermedio y en el final: `link`, con `make_symlink` y omitido por capacidad;
  - enlace duro: `hard_link`;
  - fichero sustituido por un enlace entre fases: `changed`, con un gancho de test entre `lstat` y `open`;
  - FIFO: `not_regular`.

  Control negativo: la mutación «no comprobar la identidad tras abrir» hace fallar `changed`. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `tests/security/test_workspace_confinement.py`. Las uniones de Windows y los nombres cortos 8.3 se simulan. `name_collision` (nombre nuevo) pasa a B3: en B1 no se crea nada. Control negativo: mutaciones 1–8 y 19 de 2.12 (sin la identidad tras abrir falla `test_a_file_replaced_by_another_between_the_walk_and_the_open`).

- [x] 2.5 Reglas fijas (D3). Oráculo: cada nombre, componente y extensión de la lista; `.env.example` aceptado; `credential_in_file` con una credencial sintética de cada forma del redactor; `binary` (NUL y Latin-1); `too_large` (300 KiB). Control negativo: quitar `.git` de la lista hace fallar su caso. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `tests/unit/test_workspace_rules.py`. Control negativo: mutaciones 20–29 de 2.12 (sin `.git` fallan 7 tests).

- [x] 2.6 `read` y `list` (D4). Oráculo: rangos, topes (200/400 líneas, 500 caracteres, 16 KiB, 500 entradas, profundidad 3), cabecera (sha, newline, bom), marcas `[link]` y `[denied: …]`, y salida redactada. Además, un test de «nada guardado» que busca una línea centinela del fichero en SQLite y en todo `HARNESS_DATA_DIR` y no la encuentra. Control negativo: guardar el resultado en `tool_calls` hace fallar el test centinela. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `tests/unit/test_workspace_output.py` y el centinela en `tests/integration/test_workspace_cli.py::test_every_call_is_audited_without_path_or_text`. Control negativo: mutaciones 30–32 y 42–51 de 2.12.

- [x] 2.7 Auditoría (D7). Oráculo: un `SELECT` sobre `tool_calls` y la tabla de eventos tras un `read` permitido y otro denegado: `server='workspace'`, HMAC de 64, motivo exacto en la tabla de eventos y ninguna fila con el nombre del fichero (`instr` sobre todas las columnas de texto). Además, la migración nueva solo añade (test de migraciones vigente). Control negativo: guardar la ruta en claro hace fallar el `instr`. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): la migración es la **011** (`011_workspace_events.sql`). Revisado el 2026-11-28 tras el merge de `develop` (`8a8afbd`, con 009, 010 y 013; la 012 está reservada para otra rama): `test_011_applies_on_a_database_at_010_and_at_013` aplica la 011 sobre una base en la 010 (aplica `[11, 13]`) y sobre una base que ya tiene la 013 (aplica `[11]`), y en los dos casos el esquema final es el de una base nueva. Control negativo (visto el 2026-11-28): un `migrate` mutado que salta toda versión menor que la mayor ya aplicada (un ejecutor que no admite huecos) hace fallar el caso «en la 013» (`[absent1-later1]`, 1 failed, 1 passed); restaurado, 2 passed. `test_storage.py`, `test_response_mode.py` y `test_sql_values.py` se ajustaron solo añadiendo. Control negativo: mutaciones 52–54 de 2.12 (la ruta en claro hace fallar 21 tests).

- [x] 2.8 `main.py workspace --root <ruta> check|read|list` en `harness/cli.py`. Oráculo: un test de integración con códigos de salida (0, 1 si se rechaza, 2 si es un mal uso) y el texto con `| ` delante. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `tests/integration/test_workspace_cli.py`: salidas 0/1/2, `| ` delante, y una ejecución real por subproceso. Control negativo: mutación 55 de 2.12.

- [x] 2.9 Portabilidad. Oráculo: `tests/unit/test_portability.py` pasa con el paquete nuevo (sin `sys.platform`, `os.name`, `fcntl`, `msvcrt`; todo `os.open` con `O_BINARY`). Control negativo: un `if sys.platform` temporal en `harness/workspace/` lo hace fallar. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `tests/unit/test_portability.py` pasa. Control negativo: un `if sys.platform == "win32"` temporal en `harness/workspace/codes.py` hace fallar `test_product_code_has_no_platform_branches`, y al quitarlo vuelve a pasar (4 passed).

- [x] 2.10 Documentación de B1: `docs/runbook/workspace-tools.md` (elegir la carpeta, qué se rechaza y por qué, el ejemplo con el fixture) y la sección «Carpeta de trabajo» de `SECURITY.md`, con «qué NO protege» de D3 y D16. Oráculo: los comandos del runbook se ejecutan tal cual en una carpeta temporal y dan la salida citada. Recibo.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): `docs/runbook/workspace-tools.md`, la sección «Carpeta de trabajo» de `SECURITY.md` (con «Lo que no garantiza») y la entrada 15 de `docs/security/known-debt.md` (16 desde el merge de `develop` = `02b2c09`, que trae su propia entrada 15). Se añadieron a SEC-01, 03 y 04 los requisitos y tests nuevos, sin cambiar ningún estado. Los comandos del runbook se ejecutaron tal cual en zsh, sobre una carpeta de `mktemp -d`, y dieron la salida citada.

- [x] 2.11 Demo B1: `scripts/demo_workspace.py` con el fixture: acepta la carpeta, rechaza el repo y la carpeta personal, lee `src/app.py` (rango), lista con marcas y rechaza `.env`, `../x`, el enlace y la credencial. Termina en `demo: PASS`. Estado: PASS, FAIL, NOT RUN o BLOCKED, con el SHA y el log.

  Recibo (2026-11-27, macOS 26 arm64, Python 3.14, commit del tramo B1): la demo es `scripts/demo_workspace.py`, sin subcomando. Cubre los casos pedidos y además `/etc/hosts`, `.git/config`, `deploy.pem`, `image.bin`, `big.txt`, `src/App.py`, `NUL`, `README.md:hidden`, el enlace duro y el directorio de datos como carpeta, y comprueba la auditoría. Estado: **PASS** en macOS (`demo: PASS`, exit 0). En Windows: NOT RUN.

- [x] 2.12 Mutaciones del tramo B1 (cada garantía, vista fallar). Cada mutación se aplica a un fichero de `harness/workspace/` y se restaura al momento. Con cada una se corren los 7 ficheros de test del tramo.

  Recibo (2026-11-27, macOS): **55 mutaciones, 0 supervivientes**.

  **Primera pasada: 5 supervivientes.** Cada uno destapó una capa sin test propio y se mató con un test nuevo:
  - el enlace duro al pasear: `test_a_hard_link_is_refused_while_walking_before_any_open`;
  - `O_NOFOLLOW`: `test_the_open_itself_does_not_follow_a_final_link`;
  - un NUL en UTF-8 válido: `test_a_nul_inside_the_sniff_window_is_binary_even_in_valid_utf8`;
  - la contención por nombre en un sentido: `test_a_vault_that_does_not_exist_yet_is_still_protected_by_name`;
  - el plegado de mayúsculas: `test_the_name_rule_ignores_case`.

  | # | Mutación | Tests que fallan (ejemplo) |
  |---|---|---|
  | 1 | sin coincidencia exacta con `listdir` | 5 (`test_a_name_with_other_case_is_refused`, nombre corto simulado, NFD) |
  | 2 | seguir un enlace en un componente | 6 (`test_a_folder_link_to_outside_is_refused`, unión simulada) |
  | 3 | sin identidad sobre el descriptor | 1 (`test_a_file_replaced_by_another_between_the_walk_and_the_open`) |
  | 4 | sin `st_nlink` sobre el descriptor | 1 (`test_a_hard_link_made_between_the_walk_and_the_open_is_caught_on_the_descriptor`) |
  | 5 | sin `st_nlink` al pasear | 1 (`test_a_hard_link_is_refused_while_walking_before_any_open`) |
  | 6 | sin volver a resolver tras abrir | 1 (`test_a_file_that_resolves_outside_after_the_open_is_refused`) |
  | 7 | sin detectar la raíz sustituida | 1 (`test_the_root_replaced_after_it_was_chosen_suspends_it`) |
  | 8 | sin tope sobre el descriptor | 1 (`test_reading_is_capped_on_the_descriptor`) |
  | 9 | aceptar `..` | 3 |
  | 10 | solo rechazar absolutas POSIX | 6 |
  | 11 | aceptar `:` | 3 |
  | 12 | aceptar `\` | 1 |
  | 13 | aceptar nombres reservados | 10 |
  | 14 | aceptar punto o espacio final | 3 |
  | 15 | no exigir NFC | 1 |
  | 16 | aceptar `\n` en una ruta | 1 |
  | 17 | tope de ruta ×10 | 1 |
  | 18 | tope de componente ×10 | 2 |
  | 19 | sin `O_NOFOLLOW` | 1 (`test_the_open_itself_does_not_follow_a_final_link`) |
  | 20 | `.git` legible | 7 |
  | 21 | `.env` legible | 5 |
  | 22 | extensiones de clave legibles | 11 |
  | 23 | prefijos de clave legibles | 4 |
  | 24 | `.env.*` legible | 1 |
  | 25 | sin buscar credenciales en el contenido | 3 |
  | 26 | sin buscar la credencial partida por un invisible | 1 |
  | 27 | NUL como texto | 1 |
  | 28 | Latin-1 en vez de UTF-8 estricto | 3 |
  | 29 | tope de fichero ×10 | 2 |
  | 30 | sin escapar invisibles | 8 (`test_a_hostile_file_cannot_imitate_a_harness_line`) |
  | 31 | sin enmascarar al mostrar | 1 |
  | 32 | sin el prefijo `| ` | 5 |
  | 33 | sin proteger el repo del harness | 5 |
  | 34 | sin proteger el vault | 5 |
  | 35 | contención por nombre en un solo sentido | 2 |
  | 36 | sin contención por identidad | 1 |
  | 37 | nombres sin plegar mayúsculas | 1 |
  | 38 | aceptar la carpeta personal | 1 |
  | 39 | aceptar la raíz del sistema | 1 |
  | 40 | aceptar un enlace como carpeta | 2 |
  | 41 | aceptar una carpeta relativa | 2 |
  | 42 | ventana de lectura ×10 | 2 |
  | 43 | ventana por defecto ×10 | 50 |
  | 44 | tope de salida ×10 | 2 |
  | 45 | corte de línea ×10 | 1 |
  | 46 | tope de entradas de `list` ×10 | 1 (`test_list_is_bounded`) |
  | 47 | profundidad de `list` ×10 | 1 (`test_bad_ranges_are_usage_errors`) |
  | 48 | aceptar un `offset` tras el final | 1 |
  | 49 | `list` sigue enlaces | 1 |
  | 50 | `list` entra en carpetas prohibidas | 3 |
  | 51 | `list` sin reglas de nombre para el destino | 1 |
  | 52 | ruta en claro en la auditoría | 21 |
  | 53 | rechazo de carpeta auditado como permitido | 1 |
  | 54 | rechazo de forma auditado como fallo | 1 |
  | 55 | sin comprobar `--limit` | 2 |

  Límite: la profundidad de `list` solo la frena la CLI (mutación 47). `list_folder` con `depth` mayor no tiene test directo porque es código interno y la CLI es la única entrada en B1. En B2, el catálogo deberá comprobarla otra vez.

## 3. B2 · Conversación, catálogo y lecturas automáticas (tras el merge de `feature/code-mode-loop`)

- [x] 3.1 Volver a medir las premisas de A2 y A3 sobre el `develop` mergeado: nombre real del `auto_read`, modo `rule`, tope de envío y forma de los datos marcados. Si difieren de este diseño, editar D6, D7 y D14 en su sitio. Recibo (2026-11-28, `develop` = `8a8afbd`, mergeado en `6418e91`):
  - la marca es `ToolEntry.auto_read` (`harness/mcp/config.py`), válida solo como booleano en una `read`;
  - el modo es `means = 'rule'` en `plan_runs` (`plan_flow.approve_and_run`);
  - topes de `harness/mcp/loop.py`: `STEP_SEND_MAX_BYTES` = 4 096, `RESULTS_SEND_MAX_BYTES` = 12 288, `TURN_SEND_MAX_CHARS` = 28 000, `DEFAULT_MAX_TURNS` = 5;
  - los datos van entre `<<<RESULTADOS <marca>` y `RESULTADOS <marca>>>>`, con `| ` delante de cada línea.

  Lo que no estaba en el diseño: dentro de `/agent`, una lectura corre por regla solo si **todos** sus argumentos están acotados (A3-12: un `string` con `pattern` y `max_length` ≤ 64). Se resolvió declarando así la ruta (B2-2). D1 (la carpeta no se guarda en una tabla) y D6 (la línea aparte del catálogo) quedan revisados en su sitio (B2-1, B2-4). D7 y D14 no cambian.
- [x] 3.2 `/workspace`, `/workspace off`, `/workspace send on|off` en `harness/shell/commands.py` (tabla declarativa), el panel y `/status`. Oráculo: tests de la conversación para cada orden y para `workspace_busy` con la caja abierta. Control negativo: permitir el cambio con la caja abierta hace fallar su test. Recibo (2026-11-28):
  - tests `test_workspace_sets_shows_and_unsets_the_folder`, `test_a_refused_folder_keeps_the_one_set`, `test_the_folder_does_not_follow_the_person_to_another_session`, `test_the_folder_cannot_change_while_a_plan_is_in_course`, `test_the_side_panel_shows_the_folder`, `test_completion_offers_the_words_and_a_folder` y `test_the_conversation_s_own_vault_is_protected_without_the_variable` de `tests/unit/test_workspace_shell.py`;
  - `workspace_busy` se prueba con un `/plan` en curso, no con la caja abierta: con la caja abierta, lo que se escribe es la respuesta de la caja, no una orden (B2-7);
  - control negativo: las mutaciones 2, 3, 20 y 21 de 3.10.
- [x] 3.3 Nombre reservado. Oráculo: una lista MCP con `workspace` falla con `reserved_server_name`. Control negativo: quitar la reserva hace fallar el test. Recibo (2026-11-28): `test_a_local_list_cannot_declare_a_server_named_workspace`; mutación 1 de 3.10.
- [x] 3.4 Servidor interno en la vista de política y en el catálogo (D6, D7). Oráculo:
  - el catálogo con carpeta nombra las 2 herramientas de B2 con la descripción fija, sin la ruta absoluta (`assert root not in prompt`) y dentro de 8 000 caracteres (cifra medida y citada);
  - sin carpeta no las nombra;
  - un plan que nombra `workspace` sin carpeta da `server_not_allowed`.

  Recibo (2026-11-28):
  - `test_the_catalogue_names_the_two_tools_without_the_path`: **572 caracteres** de catálogo con la carpeta y sin lista local, de 8 000;
  - `test_without_a_folder_there_is_no_workspace_server` y `test_a_plan_that_names_workspace_without_a_folder_is_server_not_allowed`;
  - la política decide antes de tocar la carpeta (cinco llamadas `denied` sin fila en `workspace_events`): `test_the_policy_decides_before_the_folder_is_touched`;
  - el hash de la lista ata la carpeta (otra carpeta da `list_changed`): `test_the_plan_binds_the_folder_it_was_read_with`;
  - control negativo: las mutaciones 4, 5, 15 y 16 de 3.10.
- [x] 3.5 Lecturas automáticas en `/plan` y en el bucle. Oráculo: con el Mock, un guion de dos vueltas (lee `src/app.py`, responde) corre sin caja, con `running plan:`, deja dos filas en `tool_calls` y respeta el tope de envío de A3. Control negativo: marcar `read` como no automática hace que se abra la caja. Recibo (2026-11-28):
  - `test_plan_reads_two_files_by_rule_and_shows_them_only_here`: dos lecturas por regla, dos filas de `tool_calls` con el plan y el paso, y el Mock recibe solo la pregunta;
  - `test_agent_lists_then_reads_then_answers`: tres vueltas (`list`, `read`, respuesta), sin caja; cada vuelta enviada es la mostrada y cabe en los topes de 3.1;
  - `test_a_denied_file_stops_the_plan_with_its_reason_and_no_text` y `test_a_path_outside_the_pattern_refuses_the_plan_before_anything_runs` (`../`, `/`, un espacio, 65 caracteres: `argument_invalid` al leer el plan);
  - control negativo: mutación 6 de 3.10 (con `auto_read` falso se abre la caja y el test falla).
- [x] 3.6 Consentimiento por carpeta (D14). Oráculo: con un proveedor de test que no es el Mock y sin consentimiento, nada vuelve al proveedor (contador de envíos sin cambiar) y se ve `not sent: no consent for this folder`; con consentimiento, el resultado vuelve marcado; al revocarlo, deja de volver. Control negativo: ignorar el consentimiento hace fallar el contador. Recibo (2026-11-28):
  - el proveedor de test es el Mock marcado como no sintético (`synthetic_content = False`), que hace lo mismo que un proveedor de fuera de la máquina;
  - `test_without_consent_agent_sends_nothing_of_the_folder`: un envío (la pregunta) y el bucle `stopped (send_not_approved)`;
  - `test_with_consent_the_results_go_after_the_loop_s_own_box`: dos cajas (la del consentimiento y la de A3-14) y el resultado marcado en el segundo envío;
  - `test_a_revoked_consent_stops_sending_again`, `test_a_rejected_consent_grants_nothing`, `test_a_refusal_is_sent_without_consent_it_holds_no_file_text` y `test_the_consent_belongs_to_the_folder_not_to_its_name` (otra carpeta con la misma ruta no lo hereda);
  - control negativo: las mutaciones 7 a 13 de 3.10.
- [x] 3.7 Inyección (D16). Oráculo: el guion del Mock propone, tras leer el `README.md` hostil, `read` de `.env` (se rechaza con su motivo) y un `edit` del `Makefile` (en B2 se rechaza con `write_not_allowed`; en B3, la caja). Recibo (2026-11-28): `test_a_hostile_readme_can_only_propose_and_its_proposals_are_refused` y `test_a_hostile_file_reaches_the_model_marked_and_cannot_imitate_the_harness`. El `edit` se rechaza con **`tool_not_allowed`**, no con `write_not_allowed`: en B2 la herramienta no existe (B2-8). El `Makefile` queda igual (mismo SHA-256). Control negativo: mutación 18 de 3.10.
- [x] 3.8 Filas SEC-01, 03, 04, 05 y 15 de `docs/security/sec-matrix.md`: añadir los tests de B1 y B2 sin cambiar ningún estado. Oráculo: `scripts/check_sec_matrix.py` pasa. Recibo (2026-11-28): `sec-matrix: PASS (15 rows, 229 tests)`, código 0. Ningún estado cambia. SEC-04 y SEC-05 ganan los requisitos «Rutas acotadas en un plan», «Carpeta suspendida si cambia», «Elegir la carpeta de trabajo», «Herramientas en el catálogo» y «Nombre reservado».
- [x] 3.9 Demo B2: en la pantalla completa con el Mock: `/workspace <fixture>`, se ve en el panel, una pregunta que lee dos ficheros sola y el contador de envíos. PASS/FAIL/NOT RUN/BLOCKED, con el SHA y el log o vídeo. Recibo (2026-11-28, macOS): **PASS**.
  - `uv run python scripts/demo_workspace.py` termina en `demo: PASS`, código 0. Los casos B2-a a B2-f usan el modo plano del guion de los tests con el Mock: el contador de envíos es el número de prompts que recibe;
  - la pantalla completa la prueba `test_the_full_screen_shows_the_folder_and_the_reads` (Pilot, 100×30): el panel `Workspace`, `/plan` con dos lecturas sin caja y `/agent`;
  - `uv run python scripts/demo_workspace.py --prepare DIR` prepara la carpeta sintética y el guion del Mock para probarlo a mano (runbook);
  - sin navegador: este tramo no cambia código del proveedor ni del navegador, así que no se corrió la batería de Edge.
- [x] 3.10 Mutaciones del tramo B2. Cada mutación se aplica a un fichero de producto y se restaura al momento; con cada una se corre `tests/unit/test_workspace_shell.py`.

  Recibo (2026-11-28, macOS): **21 mutaciones, 0 supervivientes**.

  **Primera pasada: 2 supervivientes**, de 22:
  - quitar la comprobación de la raíz en cada llamada del servidor: era redundante, porque `paths.locate` ya la hace antes de nada. Se quitó del servidor, y la mutación con ella;
  - no proteger el vault de la conversación cuando falta `HARNESS_VAULT_ROOT`: se mató con `test_the_conversation_s_own_vault_is_protected_without_the_variable`.

  | # | Mutación | Test que falla (el primero) |
  |---|---|---|
  | 1 | aceptar una lista con un servidor `workspace` | `test_a_local_list_cannot_declare_a_server_named_workspace` |
  | 2 | la carpeta sigue en otra sesión | `test_the_folder_does_not_follow_the_person_to_another_session` |
  | 3 | sin `workspace_busy` | `test_the_folder_cannot_change_while_a_plan_is_in_course` |
  | 4 | el patrón de la ruta pasa a `.*` | `test_the_catalogue_names_the_two_tools_without_the_path` |
  | 5 | la ruta con 1 024 caracteres | `test_the_catalogue_names_the_two_tools_without_the_path` |
  | 6 | `read` sin `auto_read` | `test_plan_reads_two_files_by_rule_and_shows_them_only_here` |
  | 7 | `withhold` nunca retiene | `test_without_consent_agent_sends_nothing_of_the_folder` |
  | 8 | el bucle no llama a `withhold` | `test_without_consent_agent_sends_nothing_of_the_folder` |
  | 9 | ningún paso cuenta como contenido | `test_without_consent_agent_sends_nothing_of_the_folder` |
  | 10 | el consentimiento no mira el proveedor | `test_the_consent_belongs_to_the_folder_not_to_its_name` |
  | 11 | el HMAC de la carpeta sin su identidad | `test_the_consent_belongs_to_the_folder_not_to_its_name` |
  | 12 | cualquier respuesta de la caja lo concede | `test_a_rejected_consent_grants_nothing` |
  | 13 | `send off` no revoca | `test_a_revoked_consent_stops_sending_again` |
  | 14 | sin suspensión | `test_a_folder_replaced_after_it_was_chosen_stays_suspended` |
  | 15 | el hash de la lista sin la carpeta | `test_the_plan_binds_the_folder_it_was_read_with` |
  | 16 | el servidor interno antes de la política | `test_the_policy_decides_before_the_folder_is_touched` |
  | 17 | la auditoría sin el plan | `test_plan_reads_two_files_by_rule_and_shows_them_only_here` |
  | 18 | las líneas del fichero sin `\| ` | `test_a_hostile_file_reaches_the_model_marked_and_cannot_imitate_the_harness` |
  | 19 | el tope del listado por 10 | `test_a_long_listing_is_cut_at_its_bound` |
  | 20 | el vault de la conversación sin proteger | `test_the_conversation_s_own_vault_is_protected_without_the_variable` |
  | 21 | el panel sin la carpeta | `test_workspace_sets_shows_and_unsets_the_folder` |

## 3b. Revisión independiente (2026-11-28, sobre `d0a65d8`)

Cada arreglo tiene una prueba que se vio fallar sobre el código revisado, antes del arreglo. Ese fallo es su control negativo, y su mutación vuelve a hacerla fallar (3b.7). Las mutaciones se corrieron con `PYTHONDONTWRITEBYTECODE=1`: una mutación del mismo tamaño restaurada en el mismo segundo deja un `.pyc` viejo que pytest sigue usando (pasó una vez en esta revisión y se vio por un fallo que no tocaba).

- [x] 3b.1 Hallazgo 1 (MEDIUM), una carpeta que da a las protegidas por un segundo camino. Medido en macOS 26: `/System/Volumes/Data`, `/System/Volumes` y `/System` se aceptaban. La premisa de la revisión (un punto de montaje tiene otro `st_dev`) **no se cumple** en APFS: `/`, `/Users` y `/System/Volumes/Data` dan el mismo `st_dev`, y `os.path.ismount('/System/Volumes/Data')` es `False`. Arreglo (design B1-6):
  - búsqueda del final de la ruta de cada carpeta protegida, con su misma identidad, dentro de la carpeta elegida y de sus subcarpetas hasta dos niveles, como mucho 2 000 carpetas (`root._second_path`);
  - `mount_point` para una carpeta cuyo `st_dev` no es el de su padre;
  - `device_path` para una ruta, escrita o resuelta, que empieza por dos separadores;
  - `home` también para una carpeta que contiene la personal.

  Sin `sys.platform` ni `os.name`: `test_portability.py` pasa.
  - Oráculo: `test_a_folder_that_reaches_a_protected_folder_by_a_second_path_is_refused` (simulado con `_identity`, tres niveles), `test_a_folder_beside_the_second_path_is_still_accepted`, `test_a_folder_containing_the_home_folder_is_refused`, `test_a_mount_point_is_refused` (`st_dev` simulado), `test_a_network_or_device_path_is_refused_on_every_platform` (seis formas, sin `skip`), `test_a_resolved_network_path_is_refused` y `test_the_real_data_volume_is_refused_where_the_machine_has_one` (las tres rutas reales; se omite por capacidad si la máquina no muestra el repo o el directorio de datos otra vez bajo `/System/Volumes/Data`).
  - Recibo (2026-11-28, macOS 26 arm64): antes del arreglo → `15 failed, 26 passed`, también las tres rutas reales (`DID NOT RAISE`); después → `41 passed`. Con el código arreglado, `check_root` rechaza `/System/Volumes/Data`, `/System/Volumes`, `/System` y `/System/Volumes/Data/Users` con `harness_repo`. Mutaciones M1 a M6 → muertas.
  - Windows: `\\?\GLOBALROOT\…` y `\\localhost\C$\…` se rechazan por su forma, probado en macOS con las cadenas. **NOT RUN en Windows**.
- [x] 3b.2 Hallazgo 2 (LOW), el corte de línea iba después de la redacción. Ahora `render.shown_line` redacta otra vez tras cortar, como `loop.results_block`. Arregla la salida de la CLI, la pantalla de `/plan` y los nombres de `list`, que pasan por la misma función.
  - Oráculo: `test_a_credential_that_the_cut_makes_recognisable_is_masked` (459 `x`, un espacio, `ghp_` y 36 caracteres, y `_suffix`).
  - Recibo (2026-11-28): antes → `failed` (el token en claro, `masked == 0`); después → pasa. M7 → muerta.
- [x] 3b.3 Hallazgo 3 (LOW), nombres de credenciales que se leían y contraseñas en URL sin tapar.
  - Nombres nuevos en `rules.py`:
    - `*.env`, `.env-*`, `.env_*`, `kubeconfig` y `*.kubeconfig`;
    - `*.tfstate`, `*.tfstate.backup`, `*.tfvars` y `*.tfvars.json`;
    - `.pgpass`, `.my.cnf`, `.htpasswd`, `.vault-token`, `.dockercfg` y `secrets.toml`.

    `.npmrc`, `.pypirc`, `.netrc`, `id_rsa*`, `id_ed25519*`, `*.pem`, `*.key`, `*.p12` y `*.pfx` ya estaban.
  - La contraseña de una URL (el `usuario:contraseña` de `esquema://…@host`) es el formato 14 de `harness/text/redaction.py`. Se tapa solo `usuario:contraseña`, en todas las superficies que redactan (vault, stderr MCP, resultados, carpeta). En la carpeta, como cualquier credencial conocida, rechaza el fichero (`credential_in_file`). Patrón lineal: el esquema empieza su tramo, y ni el usuario ni la contraseña admiten `/`, `@` ni espacios.
  - Documentado que los nombres son convenciones, no una garantía.
  - Oráculo: `test_the_review_s_credential_names_are_refused` (18 nombres), `test_the_review_s_look_alikes_are_still_read`, `test_a_file_with_credentials_in_a_url_is_not_read`, `test_a_password_in_a_url_is_masked_and_the_rest_is_kept` (cuatro esquemas), `test_url_look_alikes_are_unchanged` (siete casos) y `test_the_url_pattern_is_linear`.
  - Recibo (2026-11-28): antes → `21 failed, 111 passed`; después → pasan, junto con `test_stream_redaction.py`. `test_thirteen_formats` pasa a `test_thirteen_formats_and_the_url_password` (14 patrones). M8 a M13 → muertas; M9 (sin la condición de inicio de tramo) vuelve cuadrático el patrón y hace fallar la prueba de tiempo.
- [x] 3b.4 Hallazgo 4 (LOW), la caja de `/workspace send on` no caducaba ni retiraba un Ctrl+C. Ahora copia el control de `loop_flow._Loop._consent`: muestra `expires:`, una respuesta tardía queda `expired` y lo escrito tras un Ctrl+C queda `undecided` (design B2-3, revisado).
  - Oráculo: `test_a_consent_answered_after_it_expired_grants_nothing` (reloj de test, 901 s) y `test_a_code_typed_after_ctrl_c_at_the_consent_box_grants_nothing`. En los dos, ninguna fila en `workspace_consents` y un solo envío al proveedor.
  - Recibo (2026-11-28): antes → `2 failed` (el segundo concedía el consentimiento); después → pasan. M14 y M15 → muertas.
- [x] 3b.5 Hallazgo 5 (LOW), `call_timeout_s` no se aplicaba y la parada se ignoraba. Ahora `WorkspaceServer.call` corre la herramienta en un hilo y espera como mucho `call_timeout_s`, o hasta la `StopSignal` que el gateway le pasa ahora (design B2-9). Cortada por el plazo, la llamada da `timeout`; por la parada, `KeyboardInterrupt` con su `outcome`, como `run_session`. Los códigos nuevos `timeout` e `interrupted` están en `CALL_CODES` y en el `CHECK` de la migración 011, que no ha salido de esta rama.
  - Oráculo: `test_a_read_that_does_not_answer_ends_at_its_call_timeout`, `test_a_stop_cuts_a_read_that_does_not_answer` (los dos con un `run_tool` que se bloquea, en menos de 5 s) y `test_the_gateway_hands_its_stop_to_the_work_folder`.
  - Recibo (2026-11-28): antes → `3 failed`; después → pasan. M17, M18 y M19 → muertas.
  - **Lo que no queda acotado** (deuda conocida 16):
    - la llamada al sistema sigue bloqueada en su hilo hasta que el disco responde;
    - `main.py workspace` y la elección de la carpeta (con su búsqueda de un segundo camino) no tienen plazo.
- [x] 3b.6 Hallazgo 6, el texto y el código no coincidían:
  - **Tope total por bucle**, escrito en `SECURITY.md`, el runbook y design B2-9: N × 12 KiB de resultados, 60 KiB con 5 vueltas y 120 KiB con 10. La revisión estimó unos 72 y 132 KiB, contando también el primer envío, que no lleva resultados. Medido con `test_what_one_loop_sends_of_the_folder_is_bounded`: **59 280 bytes** en 5 envíos.
  - **«El cambio de la carpeta se detecta»** ahora dice «al principio de cada llamada» en `SECURITY.md`, `known-debt.md` 16, el runbook y design B2-6.
  - **D4 y la cuenta de lo que falta.** `list` sigue contando pasado su tope, como mucho 5 000 entradas más (`LIST_COUNT_MAX`): `[listing stopped at 500 entries; N more not listed]`. El servidor dice `M more not shown` cuando corta a 16 KiB, y la CLI lo dice en su aviso. Oráculo: `test_list_says_how_many_entries_it_left_out`, `test_the_count_of_what_was_left_out_is_bounded` y `test_a_listing_says_how_many_entries_it_did_not_show`. Antes → `3 failed`; M20 y M21 → muertas.
  - **`workspace_changed` en la auditoría.** Encontrado por una llamada que la política permitió, se guarda `allowed`, `failed` y `tool_error`, lo que ve el plan. El rechazo de `--root` en la CLI sigue siendo `denied`/`server_not_allowed`. Oráculo: `test_a_replaced_folder_is_audited_as_what_the_plan_saw` y el caso revisado de `test_each_outcome_leaves_its_rows`. Antes → `failed`; M16 → muerta.
- [x] 3b.7 Mutaciones de esta revisión. Cada una se aplica a un fichero de producto y se restaura al momento, con `PYTHONDONTWRITEBYTECODE=1`.

  Recibo (2026-11-28, macOS): **21 mutaciones, 0 supervivientes**. M6 sobrevivió en la primera pasada, porque la búsqueda del segundo camino también rechaza una carpeta que contiene la personal. Se mató añadiendo a su test el caso con `_second_path` anulado: son dos capas.

  | # | Mutación | Test que falla (el primero) |
  |---|---|---|
  | M1 | sin buscar el segundo camino | `test_a_folder_that_reaches_a_protected_folder_by_a_second_path_is_refused` y las 3 rutas reales |
  | M2 | la búsqueda sin bajar de nivel | los mismos, niveles 1 y 2, y `/System/Volumes`, `/System` reales |
  | M3 | sin `mount_point` | `test_a_mount_point_is_refused` |
  | M4 | sin `device_path` sobre lo escrito | `test_a_network_or_device_path_is_refused_on_every_platform` (6) |
  | M5 | sin `device_path` sobre lo resuelto | `test_a_resolved_network_path_is_refused` |
  | M6 | `home` sin «contiene» | `test_a_folder_containing_the_home_folder_is_refused` |
  | M7 | sin redactar tras el corte | `test_a_credential_that_the_cut_makes_recognisable_is_masked` |
  | M8 | sin el patrón de URL | `test_a_password_in_a_url_is_masked_and_the_rest_is_kept` (4) y `test_a_file_with_credentials_in_a_url_is_not_read` |
  | M9 | el patrón de URL sin la condición de inicio | `test_the_url_pattern_is_linear` |
  | M10 | `*.env` legible | `test_the_review_s_credential_names_are_refused` |
  | M11 | `.env-*` y `.env_*` legibles | `test_the_review_s_credential_names_are_refused` |
  | M12 | estado y variables de Terraform legibles | `test_the_review_s_credential_names_are_refused` |
  | M13 | `kubeconfig` legible | `test_the_review_s_credential_names_are_refused` |
  | M14 | la caja del consentimiento sin plazo | `test_a_consent_answered_after_it_expired_grants_nothing` |
  | M15 | sin retirar el Ctrl+C | `test_a_code_typed_after_ctrl_c_at_the_consent_box_grants_nothing` |
  | M16 | `workspace_changed` otra vez `denied` | `test_a_replaced_folder_is_audited_as_what_the_plan_saw` |
  | M17 | el gateway sin pasar la parada | `test_the_gateway_hands_its_stop_to_the_work_folder` |
  | M18 | sin plazo | `test_a_read_that_does_not_answer_ends_at_its_call_timeout` |
  | M19 | la parada sin despertar la espera | `test_a_stop_cuts_a_read_that_does_not_answer` |
  | M20 | `list` sin contar lo que falta | `test_list_says_how_many_entries_it_left_out` |
  | M21 | el servidor sin sumar lo que falta | `test_a_listing_says_how_many_entries_it_did_not_show` |
- [ ] 3b.8 **Decisiones del dueño, pendientes.** No las tomó esta revisión; el código hace hoy lo que dice cada punto:
  1. el consentimiento es persistente por carpeta y proveedor, sin plazo sobre lo concedido: dura hasta `/workspace send off` (la caja que lo pide sí caduca, 3b.4);
  2. un fichero con más de un enlace duro se rechaza (`hard_link`), así que no se leen los `node_modules` de pnpm, que son enlaces duros a su almacén;
  3. un punto de montaje dentro de la carpeta se atraviesa sin aviso (solo se rechaza la carpeta que es un punto de montaje);
  4. tras `/workspace send off`, lo ya enviado se queda en la conversación del proveedor: el harness no puede retirarlo.

  Hecho: cada punto dice «tomada por el dueño el …», o se edita la decisión en `design.md`.
- [x] 3b.9 Integración con `develop` y la tanda sin Edge sobre el árbol mergeado. Oráculo: código 0 en todo.
  - **Merge.** `git merge origin/develop` (`02b2c09`) sobre `0848426`, en `04aec2f`, con dos conflictos:
    - `docs/security/known-debt.md`: `develop` trae su propia entrada 15 (el motivo previo al envío que se pierde). Quedan las dos, y la de la carpeta de trabajo pasa a ser la **16**, con sus referencias en `SECURITY.md`, `design.md` y esta lista;
    - `docs/security/sec-matrix.md`, cuatro filas: quedan los tests y el control negativo de esta rama, y la línea **Windows** de `develop`, con la ejecución de `a9c51fe`.
  - **Recibo (2026-11-28, macOS arm64, sobre `04aec2f`):**
    - `caffeinate -i uv run pytest -m "not edge and not copilot" -q -p no:cacheprovider` → `2944 passed, 193 deselected in 469.83s`, código 0. Las dos pruebas de TUI sensibles a la carga pasaron en la tanda;
    - `scripts/check_public_safety.py` → `PASS (558 file(s))`;
    - `scripts/check_sec_matrix.py` → `PASS (15 rows, 240 tests)`;
    - `openspec validate --all --strict --no-interactive` → `30 passed, 0 failed`;
    - `scripts/demo_workspace.py` → `demo: PASS`, código 0.
  - Sin la batería de Edge: esta ronda no cambia código del proveedor ni del navegador. Windows: **NOT RUN**.

## 4. B3 · Escrituras con diff y aprobación

- [ ] 4.1 Medir si `plan_runs` (migración 009) guarda la aprobación de una lista de efectos sin columnas nuevas. Hecho: la respuesta y, si hace falta, la columna en la migración nueva. Recibo.
- [ ] 4.2 Tipo de argumento `lines`, `mixed_plan` y escrituras solo de `workspace` (D8). Oráculo: cada línea pasa `string_refusal` (un `\t`, un `\n` o una credencial en una línea rechazan el plan); `mixed_plan`; una escritura MCP sigue siendo `write_not_allowed`; topes de elementos. Control negativo: aceptar una escritura MCP hace fallar su caso. Recibo.
- [ ] 4.3 `prepare` (D9, D13). Oráculo:
  - bytes nuevos y diff para `write` y `edit`;
  - `no_match`, `ambiguous_match` (con el número), `no_change`, `exists`, `hidden_target`, `mixed_newlines` y `read_only`;
  - CRLF, BOM y sin salto final conservados (comparación de bytes);
  - carpetas nuevas listadas, como mucho 4.

  Control negativo: normalizar a LF hace fallar el caso CRLF. Recibo.
- [ ] 4.4 Leer antes de editar (D11). Oráculo: `not_read`, `changed_since_read` y una edición encadenada tras un `apply` aceptada. Control negativo: no registrar la lectura hace fallar el caso aceptado. Recibo.
- [ ] 4.5 Propuesta y hash (D10). Oráculo:
  - cambiar un byte de los bytes nuevos, del `sha256` anterior, de la ruta, del modo, de la carpeta o del plan cambia el hash (un caso por campo);
  - la aprobación de un plan de lectura o de un Skill no vale;
  - caducada y reutilizada se rechazan;
  - `diff_too_large` a 32 KiB + 1.

  Control negativo: sacar el `sha256` anterior del hash hace fallar su caso. Recibo.
- [ ] 4.6 La caja. Oráculo: con `open_approval` de la pantalla completa, la caja muestra todos los diffs sin plegar, el aviso fijo y los invisibles del contenido anterior como `<U+XXXX>`, y «Approve» se habilita al ver el final. En el modo plano, el código tecleado. Tests en el estilo de `tests/unit/test_shell_tui_buttons.py`. Recibo.
- [ ] 4.7 `apply` y `exclusive`. Oráculo:
  - la escritura atómica deja el SHA-256 de los bytes aprobados;
  - `changed_since_prepare` con la caja abierta;
  - `target_busy` simulado (un `os.replace` que falla) sin temporales;
  - el segundo de tres falla y el tercero no se aplica;
  - el bloqueo por carpeta.

  Control negativo: no comprobar el `sha256` en `apply` hace fallar `changed_since_prepare`. Recibo.
- [ ] 4.8 `reconcile` y muerte del proceso. Oráculo: un test de integración como `tests/integration/test_skill_crash.py` que mata el proceso antes y después del `os.replace` y comprueba `absent`/`applied`/`conflict`, temporales borrados y que nada se reaplica. Control negativo: un `reconcile` que responde siempre `absent` hace fallar el caso «después». Recibo.
- [ ] 4.9 Resultado al modelo (D14). Oráculo: lo enviado tras una escritura contiene `applied`/`rejected`/`refused: <motivo>`/`uncertain` y ninguna línea centinela del fichero. Recibo.
- [ ] 4.10 Fila SEC nueva (D17): sección en `sec-matrix.md`, entrada en `sec-states.json` y en `scripts/check_sec_matrix.py`, con sus tests, su control negativo y sus límites. Oráculo: `scripts/check_sec_matrix.py` pasa, y falla si se quita la fila. Recibo.
- [ ] 4.11 Documentación de B3: `SECURITY.md` (qué garantiza una escritura y qué no, incluido el aviso de los ficheros que se ejecutan después); `known-debt.md` (ventana entre la comprobación y `os.replace`, sin `openat`, metadatos que se pierden, Windows NOT RUN); runbook. Oráculo: el ejemplo del runbook se ejecuta tal cual. Recibo.
- [ ] 4.12 Demo B3: con el Mock en la pantalla completa: leer `src/app.py`, plan que edita dos ficheros, caja con dos diffs, Approve, SHA-256 de los ficheros igual al aprobado. Controles negativos en la misma demo: `edit` sin leer, `ambiguous_match`, `.github/…`, el fichero cambiado con la caja abierta y la aprobación reutilizada. PASS/FAIL/NOT RUN/BLOCKED, con el SHA y el log o vídeo.

## 5. B4 · Deshacer

- [ ] 5.1 Copia previa (D12). Oráculo:
  - existe en `workspace-undo/` con modo 0600/0700 (omitido por capacidad donde no hay bits POSIX);
  - `undo_too_large` a 1 MiB + 1;
  - purga de más de 20 listas y de más de 7 días al arrancar.

  Control negativo: guardar sin `private_file` hace fallar el modo. Recibo.
- [ ] 5.2 `/undo`. Oráculo:
  - diff inverso en la caja, Approve, y los bytes vuelven a ser los anteriores;
  - `changed_since_apply`;
  - una sola vez;
  - deshacer un `create` borra solo ese fichero y sus carpetas vacías;
  - un `/undo` no se deshace.

  Control negativo: deshacer sin comprobar el `sha256` actual hace fallar `changed_since_apply`. Recibo.
- [ ] 5.3 Documentación: `SECURITY.md` dice que hay copias de ficheros de la persona en el directorio de datos, cuánto duran y cómo borrarlas. Recibo.
- [ ] 5.4 Demo B4: editar, `/undo`, Approve, bytes anteriores; `/undo` otra vez: nada que deshacer. PASS/FAIL/NOT RUN/BLOCKED, con el SHA y el log.

## 6. B5 · `glob` y `grep`

- [ ] 6.1 `glob` (D5). Oráculo: patrones `*`, `?`, `**` y `[]`; sin seguir enlaces; topes 5 000/200 con la marca; lo prohibido no aparece. Recibo.
- [ ] 6.2 `grep` literal y con regex acotada. Oráculo: `regex_not_supported` para `(a+)+$`, `(x|xx)*y`, `\1`, `(?=a)` y `(?<!a)`; líneas de más de 2 000 caracteres saltadas y contadas; topes de 8 MiB, 2 000 ficheros y 100 coincidencias; `.env` y `credential_in_file` saltados. Control negativo: dejar pasar los grupos cuantificados hace fallar `(a+)+$`. Recibo.
- [ ] 6.3 Medir el peor caso de una regex admitida sobre 8 MiB del fixture (los 5 patrones más lentos de una lista escrita en el test). Recibo: la cifra en ms y la fecha. Si pasa de 2 s en macOS, bajar los topes y editar D5 y D15.
- [ ] 6.4 Demo B5: buscar una función en el fixture con `grep` y `glob` dentro del bucle del Mock. PASS/FAIL/NOT RUN/BLOCKED, con el SHA y el log.

## 7. Verificación transversal

- [ ] 7.1 Mutaciones de los topes: multiplicar por 10 cada constante de D15 en una copia desechable (bajo `mktemp -d`) y comprobar que falla un test por cada una. Recibo: una tabla como la de `sec-matrix.md`.
- [ ] 7.2 `scripts/verify.sh` completo en macOS. Recibo: salida y código 0.
- [ ] 7.3 `uv run python scripts/check_public_safety.py` sobre todo el change. Recibo: código 0.

## 8. Windows (confirmación opcional, no puerta)

- [ ] 8.1 Ejecutar en el PC de pruebas de Windows la batería sin navegador y `scripts/demo_workspace.py`. Recibo: resultado y SHA, o NOT RUN. **Tramos B1 y B2: NOT RUN** (2026-11-27 y 2026-11-28). Órdenes, en PowerShell desde el repo:

  ```powershell
  uv run pytest tests/unit/test_workspace_paths.py tests/unit/test_workspace_root.py tests/unit/test_workspace_rules.py tests/unit/test_workspace_output.py tests/unit/test_workspace_audit.py tests/security/test_workspace_confinement.py tests/integration/test_workspace_cli.py tests/unit/test_workspace_shell.py tests/unit/test_portability.py -rs
  uv run python scripts/demo_workspace.py
  ```

  Los tests de enlaces simbólicos se omiten si la cuenta no puede crearlos (`-rs` lo dice).
- [ ] 8.2 (Tramo B1: NOT RUN.) Casos solo de Windows: `mklink /J` y `mklink /H` reales, `dir /x` para un nombre corto 8.3 que debe dar `not_found`, con un test que se omite fuera de Windows **por capacidad** (no por plataforma): una unión de directorio en un componente (`link`), `os.replace` con el destino abierto por otro proceso (`target_busy`), `st_nlink` de un enlace duro de NTFS, `a.txt:x` y `NUL` reales, y una raíz de más de 240 caracteres. Recibo o NOT RUN.

## 9. Demo del corte

- [ ] 9.1 Demo final que reproduce Wilson en macOS, con el Mock y la carpeta sintética, en la pantalla completa:
  1. `/workspace <fixture>` (se ve en el panel);
  2. una pregunta que lee sola `src/app.py`;
  3. un plan que edita dos ficheros, con la caja de diffs y Approve;
  4. `/undo` aprobado.

  Controles negativos en la misma sesión: `/workspace` del repo del harness, `read` de `.env`, `../x`, `edit` sin leer, `.github/workflows/x.yml`, el fichero cambiado con la caja abierta y la aprobación reutilizada. Evidencia: el SHA de la rama, el log de `scripts/demo_workspace.py` (ampliada en cada tramo) con `demo: PASS` y un vídeo de la pantalla completa. Estado: PASS, FAIL, NOT RUN o BLOCKED. Windows: el resultado de 8.1, o NOT RUN.
