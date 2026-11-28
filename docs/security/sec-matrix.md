# Matriz SEC

Estado de cada propiedad de seguridad SEC-01..SEC-15 del plan maestro (`docs/plan/AI-HARNESS-PLAN-v0.4.md` §14) sobre lo que hay en `develop`. Rellenada el 2026-11-25 sobre `develop` = `ee550b6` (igual a `v0.2.0`) y actualizada el 2026-11-27 tras mergear `develop` = `57c413d` (versión 0.2.1, la conversación, la pantalla completa, el proveedor de Copilot Web, las correcciones de paridad con Windows y `prompt-economy`) y tras corregir los hallazgos de la revisión de seguridad del 2026-11-27 (`openspec/changes/hardening/tasks.md`, grupo 5). Lo que vive en ramas sin mergear se marca `pendiente de merge` y no se describe.

Este documento no repite el [`README.md`](../../README.md) ni [`SECURITY.md`](../../SECURITY.md): cita capacidades, requisitos y tests. La deuda conocida está en [`known-debt.md`](known-debt.md).

## Cómo leerla

Cada fila tiene los mismos campos:

- **Propiedad:** lo que se promete, en una frase.
- **Estado:** uno de `cubierto`, `parcial`, `pendiente de merge`, `no cubierto` o `BLOCKED`. `cubierto` quiere decir que la propiedad, tal como está escrita aquí (no la del plan maestro, si es más amplia), la prueba al menos un test de los citados en macOS. `parcial`: una parte la prueba un test y otra no existe todavía o no se prueba. `BLOCKED`: depende de Enterprise Architect, en pausa desde el 2026-11-25.
- **Requisitos:** la spec y el nombre exacto del requisito. Las capacidades archivadas están en `openspec/specs/`; las de changes mergeados sin archivar (`skill-engine`, `mcp-gateway`, `architecture-skills-llm`), en `openspec/changes/<change>/specs/`.
- **Tests:** identificadores de pytest. Un test parametrizado se cita por su función (vale cualquiera de sus casos) o por un caso exacto (`fichero::test[caso]`), que tiene que existir tal cual.
- **Control negativo:** dónde se vio fallar el test con la propiedad rota: el recibo de un `tasks.md` (change y tarea) o la mutación de la tabla de abajo.
- **Windows:** qué se sabe de esa fila en Windows.
- **Límites:** lo que la fila NO prueba.

`scripts/check_sec_matrix.py` (en `scripts/verify.sh`) falla si falta o sobra una fila; si un estado no es de la lista o no es el fijado para esa fila en [`sec-states.json`](sec-states.json) (cambiar un estado exige dos ediciones); si una fila `cubierto` o `parcial` no cita tests o cita uno dos veces; si un identificador de test que aparece en cualquier parte del documento (listas, tabla de mutaciones, controles negativos, límites) no lo recoge `pytest --collect-only`; si un test citado está marcado `skip` o `xfail`, o se puede omitir y el campo `Windows` de su fila no dice que se omite; o si un requisito citado no está en su spec. **No comprueba que un test pruebe lo que dice la fila**: sustituir los tests de una fila por otro test que existe pasa la comprobación, y un test citado por su función sigue valiendo aunque se borren casos mientras quede uno. Eso lo sostienen el control negativo citado, la tabla de mutaciones y la revisión del documento.

## Windows: lo que se sabe

Los campos `Windows` de cada fila describen `develop` = `57c413d` y, donde lo dicen, la tercera ejecución, sobre `develop` = `a9c51fe` (2026-11-27).

- En un PC personal con Windows, sobre `develop` = `57c413d`, la batería sin los tests de navegador (`-m "not edge and not copilot"`) dio 1592 pasados, 17 omitidos y 1 fallo: `tests/integration/test_mcp_cli.py::test_a_tool_that_never_ends` venció su plazo con la máquina cargada y pasó 5 de 5 veces ejecutado solo. Todos los scripts de demo terminaron en `demo: PASS`. Los tests con marca `edge` (Edge real contra el chat sintético) **no se ejecutaron** (NOT RUN, falta de disco). El detalle de qué 17 tests se omitieron no está en el repositorio: cuando una fila dice que un test pasó en Windows, se refiere a esa ejecución y solo a los tests sin marca `edge` que no se omiten por capacidad (abajo).
- Segunda ejecución, sobre `develop` = `79cde60` (2026-11-27, Windows 11): la batería sin navegador dio 5 fallos y la de Edge 1. Fallaron los dos tests de bloqueo con una carpeta en la ruta (`PermissionError` de `harness/storage/private.py`; `hardening` 8.1), el de lo escrito por adelantado en la caja (SEC-12; `approval-buttons` 7.1), dos casos de `tests/unit/test_shell_tui_grid.py` por carga (`approval-buttons` 7.2) y, con Edge, el del perfil abierto en otro Edge (`copilot-web-provider` 9.1). Las correcciones (`bugfix/windows-parity-2`) se sostienen en Windows en la tercera ejecución.
- Tercera ejecución, sobre `develop` = `a9c51fe` (2026-11-27, Windows 11), con todo lo de `feature/hardening` ya mergeado:
  - sin navegador, 2321 pasados y 3 fallos; con Edge, 188 pasados y 1 fallo. El número de omitidos no se anotó: como arriba, «pasó en Windows» vale solo para los tests que no se omiten por capacidad;
  - los fallos: un caso de `scripts/check_sec_matrix.py` con la recogida fuera de plazo (`PermissionError` al borrar su fichero temporal: el lanzador de uv deja vivo unos milisegundos al intérprete real; `hardening` 9.1), un test de la lista de completado que contaba todos los hilos del proceso (`command-completion` 9.1), un test de plazo del plan cuyo servidor sintético tarda unos 2,5 s en arrancar allí (lo corrige otra rama) y, con Edge, un caso de `response-mode` cuya primera pregunta no encontró la página lista a tiempo (`copilot-web-provider` 10.1; causa sin confirmar). Las correcciones de los tres primeros están en `bugfix/windows-parity-3`: NOT RUN en Windows;
  - las cuatro correcciones de la segunda ejecución se sostienen: `private_file` (también los dos `..._retried_then_raised`), el armado de la caja (en reposo y con una carga de CPU del 11 al 67 %), ningún `NoMatches` en tres ejecuciones, y el perfil en uso, informado bien (`lock artefacts while open: ['lockfile']`);
  - `scripts/check_sec_matrix.py` → `sec-matrix: PASS` y las 10 demos, `demo: PASS`.
- El defecto de `v0.2.0` (la clave de los HMAC de argumentos MCP, `keys/mcp-args.key`, escrita sin modo binario y dañada en Windows) está corregido desde `0.2.1`: todo `os.open` del producto lleva `O_BINARY` (`tests/unit/test_portability.py::test_every_os_open_in_the_product_and_scripts_is_binary`). Los dos módulos de tests MCP que no se recogían en Windows se recogen desde `0.2.1` (`tests/unit/test_portability.py::test_tests_do_not_declare_posix_only_program_paths`).
- Los tests que dependen de una capacidad del sistema se omiten con un motivo visible cuando la cuenta no la tiene: crear enlaces simbólicos (`make_symlink` en `tests/conftest.py`), hacer ilegible una carpeta (`chmod 0`), los bits de permiso POSIX (`0600`/`0700` y el dueño de la lista MCP), `os.mkfifo` y `os.setsid`. Por eso **el rechazo de enlaces simbólicos, el informe de carpetas ilegibles y las comprobaciones de permisos están probados solo en macOS**. Las uniones de directorio (junctions) de Windows no las ejercita ningún test. En Windows los modos `0600`/`0700` no se usan y el harness no fija ni comprueba ACL.

## Comprobación por mutación (2026-11-25)

Para no repetir el error de un oráculo que pasa con la función quitada, se rompió a propósito una muestra de propiedades en una copia desechable (bajo `mktemp -d`) y se ejecutaron los tests citados. Todas las mutaciones de la tabla hicieron fallar el test que se nombra; restaurado el código, pasan. Las filas marcadas «revisión» son mutaciones de la revisión independiente del 2026-11-25 que sobrevivían con toda la batería en verde: el test que las mata se añadió entonces.

| SEC | Mutación en el producto | Test que falla |
|---|---|---|
| 01 | quitar el patrón `aws` de `harness/text/redaction.py` | `tests/unit/test_redaction.py::test_each_format_is_masked` (1 de 5 casos) |
| 02 | la clave foránea `(request_id, session_id)` de `messages` pasa a solo `request_id` (`001_initial.sql`) | `tests/security/test_session_isolation.py::test_cross_session_message_is_rejected_by_storage` |
| 03 | `neutralise_delimiters` devuelve el texto sin tocar | `tests/unit/test_memory_context.py::test_forged_marker_in_a_note` |
| 04 | `_file_skip_reason` deja de saltar los enlaces | `tests/security/test_vault_confinement.py::test_symlink_to_outside_file_ignored` |
| 05 | la política deja pasar las herramientas `write` | `tests/integration/test_mcp_cli.py::test_denied_calls_start_no_process` (el caso `write_requires_approval`) |
| 07 | la recuperación marca `failed` en lugar de `uncertain` | `tests/integration/test_recovery.py::test_killed_process_leaves_the_request_uncertain` |
| 07 | la reconciliación de un efecto interrumpido responde siempre `absent` | `tests/integration/test_skill_crash.py::test_killed_after_the_effect_is_not_applied_again` |
| 09 | `harness/cli.py` hace `bind` de un socket al importarse | `tests/integration/test_mcp_review.py::test_no_socket_is_created_by_the_harness_or_its_session_process` |
| 12 | el consumo acepta una aprobación ya `consumed` | `tests/unit/test_skill_approval.py::test_approval_reused` |
| 12 (revisión) | el consumo deja de comprobar `expires_at > ?` | `tests/unit/test_skill_approval.py::test_granted_approval_that_expires_while_the_effect_is_busy_is_not_consumed` (nuevo; antes no fallaba ninguno) |
| 12 (revisión) | el consumo deja de comprobar `proposal_hash = ?` | `tests/unit/test_skill_approval.py::test_approval_of_another_run` |
| 13 | una función con `path.write_text` en `harness/memory/search.py` | `tests/security/test_memory_no_writes.py::test_memory_package_has_no_copy_upload_or_write_path` |
| 14 | se admite cualquier fichero en las subcarpetas de un Skill | `tests/unit/test_skill_definition.py::test_invalid_fixtures` (`bad-helper`) |
| 14 (revisión) | `fullmatch` → `match` en el nombre de un fichero de contenido | `tests/unit/test_skill_definition.py::test_a_file_outside_the_closed_list_invalidates_the_skill[templates/draft.md.py]` (nuevo, y sus casos `.mdx` y `.md.sh`) |
| 14 (revisión) | se admite cualquier fichero en la raíz del Skill | `tests/unit/test_skill_definition.py::test_a_file_outside_the_closed_list_invalidates_the_skill[run.sh]` (nuevo, y el caso `helper.md`) |
| 15 | el límite de pasos se multiplica por 10 | `tests/unit/test_skill_definition.py::test_too_many_steps` |
| 15 | el límite de ficheros, de bytes totales o de entradas de un Skill se multiplica por 10 | `tests/unit/test_skill_definition.py::test_too_many_files`, `tests/unit/test_skill_definition.py::test_too_large_in_total`, `tests/unit/test_skill_definition.py::test_too_many_inputs` |
| 15 | el límite del prompt compuesto se multiplica por 10 | `tests/unit/test_skill_limits.py::test_prompt_too_large` |
| 15 | el límite de una entrada se multiplica por 10 (motor; `--input-file`) | `tests/unit/test_skill_engine.py::test_inputs_checked_before_the_run`; `tests/integration/test_skill_cli_run.py::test_input_file_too_large` |
| 05 | `re.fullmatch` → `re.match` en el `pattern` de un argumento | `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order[pattern is a full match]` |
| 05 | el `max_length` de un argumento se multiplica por 10 | `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order[too long]` |
| 05 | se admite un argumento no declarado | `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order[undeclared argument]`, `tests/unit/test_mcp_policy.py::test_undeclared_argument_is_named_in_the_detail` |
| 05 | no se exige un argumento obligatorio | `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order[missing required]` |
| 05 | un booleano vale como entero | `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order[boolean for integer]` |
| 02 (revisión) | un proyecto se reconoce por subcadena de una etiqueta | `tests/unit/test_notes.py::test_a_project_named_inside_another_is_not_that_project` (nuevo; 3 casos fallan) |
| 02 (revisión) | un proyecto se reconoce por prefijo de `project_slug` | `tests/unit/test_notes.py::test_a_project_named_inside_another_is_not_that_project[project_slug: demo-alpha-2-demo-alpha]` (nuevo) |

No se mutaron SEC-08 ni SEC-10: su control negativo es el del recibo citado en la fila. La revisión independiente mutó SEC-01, 02, 05, 12, 14 y 15; **no mutó SEC-03, 04, 07, 08, 09, 10 ni 13**: para esas filas, las únicas mutaciones son las del autor de esta tabla.

## SEC-01 · Credenciales en logs/vault

**Propiedad:** una credencial con un formato conocido que llega en un texto leído del vault, en el resultado de una herramienta MCP, en el stderr de un servidor MCP, en la respuesta del proveedor o en la salida del modelo que valida un Skill no sale en claro hacia la terminal, el proveedor, SQLite, la auditoría, el log de stderr ni la nota que el harness escribe en el vault; los argumentos MCP se guardan solo como HMAC; de una sesión de Copilot no se guarda texto.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/secret-redaction/spec.md` · Formatos conocidos enmascarados
- `openspec/specs/secret-redaction/spec.md` · Límite declarado de la redacción
- `openspec/specs/session-management/spec.md` · Auditoría sin contenido
- `openspec/changes/mcp-gateway/specs/secret-redaction/spec.md` · Resultados de herramientas enmascarados
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Auditoría de cada decisión sin contenido
- `openspec/changes/architecture-skills-llm/specs/architecture-memory/spec.md` · Credenciales enmascaradas en la nota
- `openspec/changes/copilot-web-provider/specs/copilot-web-provider/spec.md` · Sin contenido real guardado
**Tests:**
- `tests/unit/test_redaction.py::test_each_format_is_masked`
- `tests/security/test_audit_findings.py::test_a_gitlab_token_of_every_current_shape_is_masked`
- `tests/security/test_memory_hardening.py::test_hidden_credential_masked_in_context_and_sent_text`
- `tests/security/test_memory_hardening.py::test_credential_in_a_file_name_and_in_type`
- `tests/security/test_memory_hardening.py::test_credential_glued_to_an_escape_sequence_is_masked`
- `tests/unit/test_mcp_render.py::test_credentials_in_keys_and_nested_values_are_masked`
- `tests/integration/test_mcp_cli.py::test_a_leaky_result_is_cleaned_and_asks_for_nothing`
- `tests/integration/test_mcp_cli.py::test_audit_rows_never_hold_argument_values_or_result_text`
- `tests/integration/test_mcp_review.py::test_arguments_are_kept_as_an_hmac_with_a_private_local_key`
- `tests/integration/test_mcp_cli.py::test_a_credential_split_across_two_stderr_writes_is_redacted_in_the_log`
- `tests/unit/test_stream_redaction.py::test_the_log_keeps_redacted_text`
- `tests/security/test_audit_findings.py::test_a_credential_glued_to_an_escape_sequence_is_masked_in_the_stderr_log`
- `tests/security/test_audit_findings.py::test_ask_prints_the_answer_without_terminal_escapes`
- `tests/security/test_audit_findings.py::test_history_prints_stored_text_without_terminal_escapes`
- `tests/unit/test_skill_checks.py::test_controls_and_credentials_are_cleaned`
- `tests/integration/test_architecture_memory.py::test_a_token_in_the_model_output_is_masked_in_what_is_shown_and_written`
- `tests/browser/test_copilot_provider.py::test_canaries_never_reach_storage`
- `tests/unit/test_mcp_loop.py::test_a_credential_the_cut_reveals_is_masked_in_what_is_sent`
- `tests/unit/test_mcp_loop.py::test_a_credential_split_by_the_cut_leaves_no_piece`
- `tests/unit/test_mcp_loop.py::test_a_turn_the_screen_would_change_is_never_sent`
- `tests/unit/test_shell_agent.py::test_a_credential_at_the_cut_is_masked_alike_on_screen_and_in_what_is_sent`
**Control negativo:** `project-memory` 8.2 y 8.3 (archivado); `mcp-gateway` 1.3 y 6.4; `architecture-skills-llm` 4.2; `copilot-web-provider` 6.1; `hardening` 5.1, 5.2 y 5.3 (cada test nuevo visto fallar sobre el código sin corregir); mutación SEC-01 de la tabla.
**Windows:** la redacción es código puro, el mismo en las dos plataformas; los tests sin marca `edge` de esta fila pasaron en la ejecución de `57c413d` (ver arriba), salvo los que comprueban `0600`/`0700`, que se omiten donde no hay bits de permiso POSIX: en Windows el harness no fija ni comprueba ACL. Los tests de `tests/browser/` (marca `edge`) usan Edge contra el chat sintético local y se omiten donde Edge no se puede lanzar; en Windows se ejecutaron por primera vez sobre `a9c51fe` y pasaron, salvo un caso de `response-mode` que no es de esta fila (ver arriba). Los tests de `tests/security/test_audit_findings.py` pasaron en la ejecución de `a9c51fe`.
**Límites:** **no cubre lo que escribe la persona:** el texto de `ask` llega al proveedor tal cual y, con el Mock, se guarda en `messages` (`history` y `ask` lo muestran ya redactado). Solo se reconocen formatos conocidos; una contraseña en prosa, una cadena de conexión o un token de formato desconocido pasan tal cual (lo dice el requisito «Límite declarado»); un token de GitLab de más de 300 caracteres de cuerpo tampoco se reconoce. En el log de stderr MCP se quitan las secuencias de escape antes de redactar, pero no otros caracteres invisibles: un carácter de formato metido dentro de una credencial la deja en claro allí (en el vault y en la terminal se quitan antes). Lo que no cubre la redacción del stderr lo enumera `SECURITY.md`. Ningún test comprueba la rotación a `.1`. SQLite no está cifrado y, con el Mock, guarda prompts y respuestas (sintéticos por definición).

## SEC-02 · Cruce de sesiones/proyectos

**Propiedad:** lo de una sesión o un proyecto no aparece en otra sesión u otro proyecto, ni en el historial, ni en el contexto de memoria, ni en una aprobación, ni en la nota escrita.
**Estado:** cubierto
**Requisitos:**
- `openspec/specs/session-management/spec.md` · Aislamiento entre sesiones
- `openspec/specs/project-context/spec.md` · Preguntar con contexto de proyecto
- `openspec/specs/project-context/spec.md` · Selección de notas del proyecto
- `openspec/specs/memory-search/spec.md` · Búsqueda dentro de un proyecto
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Propuesta con hash canónico
- `openspec/changes/architecture-skills-llm/specs/architecture-memory/spec.md` · Proyecto y destino los decide el harness
- `openspec/changes/architecture-skills-llm/specs/decision-notes/spec.md` · Aprobación ligada al vault de la ejecución
**Tests:**
- `tests/security/test_session_isolation.py::test_history_does_not_mix_sessions`
- `tests/security/test_session_isolation.py::test_cross_session_message_is_rejected_by_storage`
- `tests/unit/test_ask_project.py::test_project_other_than_the_sessions`
- `tests/unit/test_ask_project.py::test_service_refuses_a_context_of_another_project`
- `tests/unit/test_memory_context.py::test_no_project_mixing`
- `tests/unit/test_memory_search.py::test_other_project_excluded`
- `tests/unit/test_skill_approval.py::test_approval_of_another_run`
- `tests/integration/test_architecture_memory.py::test_model_source_and_memory_text_never_approve_nor_choose_the_target`
- `tests/integration/test_architecture_memory.py::test_an_approval_for_one_vault_is_never_written_into_another`
- `tests/unit/test_notes.py::test_a_project_named_inside_another_is_not_that_project`
**Control negativo:** `session-core` 2.4 (archivado); `skill-engine` 5.4; `architecture-skills-llm` 7.3; mutación SEC-02 de la tabla.
**Windows:** código y SQL sin ramas por plataforma; los tests de esta fila pasaron en la ejecución de `57c413d`, salvo `tests/unit/test_notes.py::test_a_project_named_inside_another_is_not_that_project`, que se añadió en `feature/hardening` y pasó en la ejecución de `a9c51fe`.
**Límites:** es aislamiento lógico dentro de una cuenta del sistema y una base SQLite: cualquier proceso con la misma cuenta lee todas las sesiones. No hay clientes externos (SEC-09), así que no se prueba el aislamiento a través de MCP.

## SEC-03 · Prompt injection en memoria, EA o tool result

**Propiedad:** un texto que viene de una nota, de un documento de entrada, de la salida del modelo o del resultado de una herramienta no cambia lo que hace el harness (qué lee, qué envía, qué aprueba ni dónde escribe) ni se puede leer como una línea del harness: cada fila de texto ajeno lleva su marca, también en el aviso de aprobación de `skill run`.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/project-context/spec.md` · Memoria marcada como datos no confiables
- `openspec/specs/project-context/spec.md` · Una instrucción en una nota no cambia la conducta del harness
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Referencias sustituidas literalmente
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Solo una persona en una terminal interactiva aprueba
- `openspec/changes/architecture-skills-llm/specs/hls-review/spec.md` · Instrucciones dentro del documento
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Resultados como datos no confiables
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Lo que dice el servidor no amplía la política
- `openspec/changes/code-mode/specs/code-mode/spec.md` · El resultado es para la persona
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Los resultados vuelven como datos
- `openspec/changes/code-mode/specs/tool-policy/spec.md` · El bucle de code mode no es recursión
**Tests:**
- `tests/unit/test_shell_agent.py::test_a_hostile_result_stays_inside_its_block`
- `tests/unit/test_shell_agent.py::test_a_plan_inside_a_result_is_never_the_model_s`
- `tests/unit/test_shell_agent.py::test_a_nonce_injected_by_a_result_is_refused`
- `tests/unit/test_mcp_loop.py::test_a_hostile_result_cannot_close_the_block_or_pass_for_the_harness`
- `tests/unit/test_mcp_loop.py::test_the_marker_must_never_appear_inside_the_block`
- `tests/security/test_note_instructions.py::test_note_with_orders_to_the_harness`
- `tests/security/test_note_instructions.py::test_note_with_orders_that_reaches_the_limit`
- `tests/unit/test_memory_context.py::test_forged_marker_in_a_note`
- `tests/unit/test_skill_references.py::test_forged_close_marker_in_an_input`
- `tests/unit/test_skill_approval.py::test_the_model_says_it_is_approved`
- `tests/integration/test_hls_review.py::test_orders_inside_the_document_change_nothing`
- `tests/integration/test_architecture_memory.py::test_a_source_that_asks_for_another_target_changes_nothing`
- `tests/integration/test_mcp_cli.py::test_a_leaky_result_is_cleaned_and_asks_for_nothing`
- `tests/integration/test_mcp_review.py::test_a_result_cannot_forge_harness_lines`
- `tests/unit/test_mcp_policy.py::test_what_the_server_says_never_allows_a_write`
- `tests/security/test_shell_output.py::test_an_answer_that_imitates_the_harness`
- `tests/security/test_shell_output.py::test_the_content_of_an_approval_notice_is_marked`
- `tests/security/test_audit_findings.py::test_the_cli_approval_notice_marks_every_row_of_the_content`
- `tests/security/test_audit_findings.py::test_emoji_presentation_sequences_never_make_a_row_wider_than_the_terminal`
- `tests/browser/test_copilot_provider.py::test_hostile_reply_is_printed_without_control_or_invisible_characters`
- `tests/unit/test_shell_plan.py::test_a_result_that_asks_for_another_call_changes_nothing`
- `tests/unit/test_shell_plan.py::test_no_reply_or_result_can_draw_harness_lines`
- `tests/unit/test_plan_cli.py::test_no_reply_or_result_can_draw_harness_lines_in_the_cli`
- `tests/unit/test_shell_plan.py::test_read_plan_is_called_only_for_the_reply_to_plan`
- `tests/unit/test_shell_tui_plan.py::test_a_reply_that_draws_the_box_chrome_stays_foreign`
- `tests/unit/test_mcp_plan_prompt.py::test_the_server_says_nothing_in_the_catalogue`
**Control negativo:** `project-memory` 8.12 (archivado); `skill-engine` 3.1; `copilot-web-provider` 4.4 (sin la limpieza, el test de respuesta hostil falla); `hardening` 5.4 y 5.9; mutación SEC-03 de la tabla. (`architecture-skills-llm` 5.2 tiene recibo pero no anota un control negativo.) Code mode, tramo 2: `code-mode` 4.6 y 4.7 (el modo `inject` del servidor sintético y las líneas falsas del harness; ver los controles de `tasks.md`).
**Windows:** código puro; los tests sin marca `edge` de esta fila pasaron en la ejecución de `57c413d`. Los tests de `tests/browser/` (marca `edge`) usan Edge contra el chat sintético local y se omiten donde Edge no se puede lanzar; en Windows se ejecutaron por primera vez sobre `a9c51fe` y pasaron, salvo un caso de `response-mode` que no es de esta fila (ver arriba). Los tests de `tests/security/test_audit_findings.py` pasaron en la ejecución de `a9c51fe`. Los tests de `code-mode` 4.x pasaron en la ejecución de `a9c51fe`, salvo un test de plazo del plan (ver arriba).
**Límites:** prueba que el harness no obedece, con el Mock y con el chat sintético; no prueba lo que un modelo real hace con el texto (los delimitadores son una mitigación). La anchura de una fila se calcula como la mide Rich; cómo dibuja cada emulador de terminal los emoji y los caracteres de anchura ambigua no se ha observado. El cuerpo del contexto de memoria puede imitar una línea de cabecera de nota (deuda conocida 14). EA: BLOCKED.

## SEC-04 · Traversal/symlink

**Propiedad:** ninguna lectura del vault, de un Skill o la escritura de la nota de decisión sale de su raíz por `..`, una ruta absoluta o de Windows, un enlace o un enlace duro, ni por un cambio entre la comprobación y el uso.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/memory-vault/spec.md` · Lectura confinada a la raíz del vault
- `openspec/specs/memory-vault/spec.md` · Identificador de proyecto validado
- `openspec/specs/memory-vault/spec.md` · Entradas del vault que no se leen
- `openspec/changes/skill-engine/specs/skill-definition/spec.md` · Enlaces y traversal rechazados
- `openspec/changes/architecture-skills-llm/specs/decision-notes/spec.md` · Escritura confinada a Decisiones
**Tests:**
- `tests/security/test_vault_confinement.py::test_symlink_to_outside_file_ignored`
- `tests/security/test_vault_confinement.py::test_symlinked_directory_to_outside_ignored`
- `tests/security/test_vault_confinement.py::test_traversal_in_project_rejected_by_the_cli`
- `tests/security/test_vault_confinement.py::test_windows_path_forms_rejected_by_the_cli`
- `tests/security/test_memory_hardening.py::test_note_replaced_by_a_link_after_the_walk`
- `tests/unit/test_memory_paths.py::test_containment_is_not_fooled_by_unresolved_parent_parts`
- `tests/unit/test_skill_definition.py::test_template_linked_outside_the_root`
- `tests/unit/test_skill_definition.py::test_hard_link_is_refused`
- `tests/unit/test_decision_writer.py::test_decisiones_as_a_link_to_outside_is_refused`
- `tests/unit/test_decision_writer.py::test_decisiones_swapped_for_a_link_during_the_write_takes_the_note_back`
- `tests/integration/test_architecture_memory.py::test_decisiones_as_a_link_to_outside_fails_before_the_approval`
**Control negativo:** `project-memory` 8.5, 8.16 y 8.18 (archivado); `skill-engine` 2.2; mutación SEC-04 de la tabla.
**Windows:** las formas de ruta de Windows (`C:\`, `\\servidor`, nombres reservados) se prueban en macOS con `PureWindowsPath`. Todo lo que crea un enlace simbólico se omite donde la cuenta no puede crearlos (Windows sin modo desarrollador): **el rechazo de enlaces está probado solo en macOS**. El resto de los tests de esta fila pasaron en la ejecución de `57c413d`.
**Límites:** el código rechaza las uniones de directorio (`is_junction`), pero ningún test crea una. Entre la comprobación de `Decisiones/` y la escritura del temporal, quien pueda escribir en el vault puede cambiar la carpeta por un enlace: el harness lo detecta después de publicar y retira la nota, pero el temporal existió un momento fuera (límite 2 de «Skills de arquitectura» en el README).

## SEC-05 · MCP desconocido o argumentos inválidos

**Propiedad:** un servidor que no está en la lista local, una herramienta no declarada, un argumento no declarado, inválido o que falta, o una herramienta que escribe, se deniegan antes de arrancar ningún proceso y quedan en la auditoría.
**Estado:** cubierto
**Requisitos:**
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · Lista local de servidores permitidos
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · La orden de arranque solo sale de la configuración local
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Denegado por defecto
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Escrituras denegadas sin aprobación
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Lo que dice el servidor no amplía la política
- `openspec/changes/code-mode/specs/tool-policy/spec.md` · Llamadas de un plan aprobado
- `openspec/changes/code-mode/specs/code-mode/spec.md` · La lista se ata al leer el plan
**Tests:**
- `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order`
- `tests/integration/test_mcp_cli.py::test_denied_calls_start_no_process`
- `tests/unit/test_mcp_config.py::test_unknown_server_is_refused_without_starting_anything`
- `tests/integration/test_mcp_cli.py::test_audit_rows_never_hold_argument_values_or_result_text`
- `tests/integration/test_mcp_review.py::test_a_read_tool_the_server_calls_destructive_is_denied`
- `tests/unit/test_mcp_policy.py::test_undeclared_argument_is_named_in_the_detail`
- `tests/unit/test_shell_plan.py::test_a_refused_plan_opens_no_box_and_starts_nothing`
- `tests/unit/test_shell_plan.py::test_the_policy_is_decided_again_when_the_plan_runs`
- `tests/unit/test_mcp_auto_read.py::test_auto_read_is_valid_only_as_a_boolean_on_a_read`
- `tests/unit/test_mcp_auto_read.py::test_a_list_changed_after_the_plan_was_read_refuses_the_step`
- `tests/unit/test_mcp_auto_read.py::test_a_step_after_the_first_is_refused_when_its_entry_changed`
- `tests/unit/test_mcp_auto_read.py::test_an_argument_is_bounded_only_by_its_declared_type`
- `tests/unit/test_shell_agent.py::test_a_read_by_rule_with_a_free_text_argument_asks_the_box_in_a_loop`
- `tests/unit/test_shell_agent.py::test_after_results_were_sent_the_session_says_so_and_plan_needs_bounded_args`
**Control negativo:** `mcp-gateway` 2.3 (29 fallos con `deny` devolviendo `allowed`) y 2.4; mutaciones SEC-05 de la tabla (cada caso de `test_each_reason_in_its_order` que mata una). Code mode, tramo 2: `code-mode` 4.5 (un plan con una herramienta `write`, no listada o de otro servidor: ninguna caja y `starts.log` vacío).
**Windows:** los tests de esta fila pasaron en la ejecución de `57c413d` (desde `0.2.1` la clave HMAC ya no se daña y `tests/unit/test_mcp_policy.py` se recoge). La comprobación de que la lista local no la pueden escribir otros es solo POSIX: en Windows no se comprueban ACL. Los tests de `code-mode` 4.x pasaron en la ejecución de `a9c51fe`, salvo un test de plazo del plan (ver arriba).
**Límites:** solo con servidores sintéticos de los tests. El servidor MCP propio del harness no existe todavía (`harness-mcp-server`, planificado).

## SEC-06 · MFA/login expirado

**Propiedad:** con el login de Copilot vencido o un MFA pendiente, el harness se detiene sin escribir nada en la página y pide intervención humana (`copilot login`); no automatiza credenciales.
**Estado:** parcial
**Requisitos:**
- `openspec/changes/copilot-web-provider/specs/copilot-web-provider/spec.md` · Login vencido pide intervención humana
- `openspec/changes/copilot-web-provider/specs/dedicated-edge-browser/spec.md` · Login manual
**Tests:**
- `tests/unit/test_provider_states.py::test_authentication_required_before_sending`
- `tests/unit/test_provider_states.py::test_authentication_required_after_sending_is_uncertain`
- `tests/browser/test_copilot_provider.py::test_expired_login_asks_for_a_person_and_touches_nothing`
- `tests/browser/test_copilot_provider.py::test_back_to_active_after_signing_in_by_hand`
- `tests/browser/test_copilot_login.py::test_no_field_touched_during_login`
**Control negativo:** `copilot-web-provider` 4.3 (sin la guardia de host, el test de login vencido falla).
**Windows:** los dos tests de `tests/unit/` pasaron en la ejecución de `57c413d`. Los tests de `tests/browser/` (marca `edge`) usan Edge contra el chat sintético local y se omiten donde Edge no se puede lanzar; en Windows se ejecutaron por primera vez sobre `a9c51fe` y pasaron, salvo un caso de `response-mode` que no es de esta fila (ver arriba).
**Límites:** probado contra el chat sintético, que imita una página de login; contra la página real de Copilot solo a mano en macOS (recibos de `copilot-web-provider`). Un MFA real no se prueba: el harness solo espera a que la persona termine en la ventana de Edge.

## SEC-07 · Timeout tras envío/escritura

**Propiedad:** si vence el plazo o muere el proceso después de enviar una pregunta o de empezar un efecto, el estado es `uncertain` y el harness no lo repite solo; un efecto interrumpido no se aplica dos veces.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/request-recovery/spec.md` · Solicitud interrumpida marcada como incierta
- `openspec/specs/request-recovery/spec.md` · Sin reenvío automático
- `openspec/specs/llm-provider/spec.md` · Resultado distinto según el punto de fallo
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Paso incierto nunca se repite solo
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Un efecto interrumpido nunca se aplica dos veces
- `openspec/changes/architecture-skills-llm/specs/decision-notes/spec.md` · Escritura interrumpida se reconcilia sin repetir
- `openspec/changes/copilot-web-provider/specs/copilot-web-provider/spec.md` · Plazo vencido tras el envío sin reenvío
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Un plan nunca se reenvía ni se repite solo
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Una respuesta incierta o truncada nunca se analiza
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Fin del bucle
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Registro del bucle
**Tests:**
- `tests/integration/test_recovery.py::test_interruption_after_send_leaves_the_request_uncertain`
- `tests/integration/test_recovery.py::test_killed_process_leaves_the_request_uncertain`
- `tests/integration/test_recovery.py::test_recovery_does_not_resend`
- `tests/unit/test_ask.py::test_result_depends_on_where_it_failed`
- `tests/unit/test_skill_engine.py::test_step_deadline_after_send`
- `tests/integration/test_skill_crash.py::test_killed_after_the_effect_is_not_applied_again`
- `tests/integration/test_decision_crash.py::test_killed_after_the_note_is_published_completes_without_writing_again`
- `tests/integration/test_decision_crash.py::test_killed_before_the_note_is_published_needs_a_new_approval`
- `tests/browser/test_copilot_provider.py::test_reply_that_never_ends_is_uncertain_and_never_resent`
- `tests/unit/test_shell_plan.py::test_a_reply_that_did_not_complete_is_never_read`
- `tests/unit/test_mcp_plan_reply.py::test_a_reply_that_did_not_complete_is_refused_even_with_a_valid_text`
- `tests/unit/test_mcp_plan_reply.py::test_a_truncated_reply_is_refused_even_with_a_valid_text`
- `tests/unit/test_mcp_plan_run.py::test_interrupted_after_its_first_step_it_never_runs_again`
- `tests/unit/test_shell_agent.py::test_a_reply_that_did_not_complete_whole_stops_the_loop_unread`
- `tests/unit/test_shell_agent.py::test_ctrl_c_during_a_turn_stops_the_loop_and_sends_nothing_more`
- `tests/unit/test_shell_agent.py::test_ctrl_c_while_a_step_runs_stops_the_loop`
- `tests/unit/test_shell_agent.py::test_a_reply_not_completed_is_never_read_even_with_a_valid_plan_in_it`
- `tests/unit/test_shell_agent.py::test_a_loop_left_running_is_marked_interrupted_and_never_resumed`
- `tests/unit/test_shell_agent.py::test_a_loop_left_running_is_marked_interrupted_when_the_conversation_opens`
**Control negativo:** `skill-engine` 4.3 y 8.1; `architecture-skills-llm` 4.4; mutaciones SEC-07 de la tabla. (`copilot-web-provider` 5.3 tiene recibo pero no anota un control negativo.) Code mode, tramo 2: `code-mode` 4.5b y 4.6 (una respuesta incierta, fallida o truncada no se lee; un plan interrumpido no vuelve a ejecutarse).
**Windows:** los tests de proceso muerto matan un subproceso real; los tests sin marca `edge` de esta fila pasaron en la ejecución de `57c413d`. Los tests de `tests/browser/` (marca `edge`) usan Edge contra el chat sintético local y se omiten donde Edge no se puede lanzar; en Windows se ejecutaron por primera vez sobre `a9c51fe` y pasaron, salvo un caso de `response-mode` que no es de esta fila (ver arriba). Los tests de `code-mode` 4.x pasaron en la ejecución de `a9c51fe`, salvo un test de plazo del plan (ver arriba).
**Límites:** Copilot, solo contra el chat sintético en la batería; la página real, a mano en macOS. Las llamadas MCP no se reintentan, pero hoy solo se permiten herramientas de lectura. `skill resume --retry-step` repite una pregunta por decisión explícita de la persona (puede duplicarla en la conversación). Sin `fsync` del directorio tras publicar la nota: tras un corte de luz en ese instante la nota puede faltar y `skill resume` pediría aprobarla otra vez (límite 3 del README).

## SEC-08 · Reinicio

**Propiedad:** tras reiniciar el proceso, el historial, las ejecuciones de Skills, las aprobaciones pendientes y las llamadas MCP interrumpidas se recuperan en un estado verificable, sin reenviar nada.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/session-management/spec.md` · Persistencia tras reinicio
- `openspec/specs/session-management/spec.md` · Esquema migrable y repetible
- `openspec/specs/request-recovery/spec.md` · Una solicitud viva no se toca
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Recuperación de ejecuciones interrumpidas
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Reanudar con el mismo Skill y las mismas entradas
- `openspec/changes/copilot-web-provider/specs/copilot-web-provider/spec.md` · Recuperación de la conversación tras reiniciar
**Tests:**
- `tests/integration/test_recovery.py::test_history_survives_a_new_process`
- `tests/integration/test_recovery.py::test_live_request_is_not_touched_by_another_process`
- `tests/unit/test_storage.py::test_migrating_twice_changes_nothing`
- `tests/integration/test_skill_cli_run.py::test_non_interactive_run_waits_and_status_after_restart`
- `tests/integration/test_skill_crash.py::test_killed_after_the_effect_is_not_applied_again`
- `tests/integration/test_mcp_review.py::test_a_live_call_is_never_recovered_as_stale`
- `tests/browser/test_copilot_provider.py::test_conversation_recovered_in_a_new_process`
- `tests/browser/test_copilot_provider.py::test_lost_remote_conversation_closes_the_session_without_sending`
**Control negativo:** `session-core` 5.2 (archivado: sin la comprobación del bloqueo en la recuperación, una solicitud viva se tocaba); `skill-engine` 4.3 y 8.1; `copilot-web-provider` 5.2 (sin la comprobación del identificador, el test de conversación perdida falla).
**Windows:** sin ramas por plataforma; los tests sin marca `edge` de esta fila pasaron en la ejecución de `57c413d`. Los tests de `tests/browser/` (marca `edge`) usan Edge contra el chat sintético local y se omiten donde Edge no se puede lanzar; en Windows se ejecutaron por primera vez sobre `a9c51fe` y pasaron, salvo un caso de `response-mode` que no es de esta fila (ver arriba).
**Límites:** la conversación de Copilot se recupera por su identificador solo contra el chat sintético en la batería (en la página real, a mano en macOS). Una carrera en la recuperación puede pasar a `uncertain` una sesión ya cerrada (deuda conocida 14). No hay copia ni restauración de `HARNESS_DATA_DIR`: aplazado (proyecto educativo, ver la deuda conocida).

## SEC-09 · Cliente no autorizado

**Propiedad:** ningún cliente externo puede usar el harness sin autorización.
**Estado:** parcial
**Requisitos:**
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Ninguna superficie de entrada en este corte
**Tests:**
- `tests/integration/test_mcp_cli.py::test_no_socket_is_bound_during_a_call`
- `tests/integration/test_mcp_review.py::test_no_socket_is_created_by_the_harness_or_its_session_process`
- `tests/integration/test_mcp_review.py::test_the_socket_oracle_sees_a_socket_made_outside_the_loop`
**Control negativo:** mutación SEC-09 de la tabla. `mcp-gateway` 6.10 reforzó el oráculo (`listen()` sin `bind`) pero no anota un control negativo.
**Windows:** el oráculo reconoce por la pila de llamadas el par de sockets del propio bucle de eventos, también la emulación de `socketpair` de Windows; los tests de esta fila pasaron en la ejecución de `57c413d`.
**Límites:** el Edge de Copilot se controla por una tubería (`remote-debugging-pipe`), no por un puerto, pero ningún test lo comprueba con este oráculo. Hoy prueba que no hay puerta (ningún socket de escucha durante un `mcp call`), no que haya autorización. Cualquier proceso con la misma cuenta del sistema puede ejecutar el harness: la frontera es la cuenta. El servidor MCP propio, que abriría una entrada, está planificado (`harness-mcp-server`), sin código.

## SEC-10 · Crash navegador/COM

**Propiedad:** si un proceso propio (servidor MCP, proceso de sesión, navegador, EA) muere o se cuelga, el harness libera lo que es suyo (procesos, bloqueos y filas en curso), y el navegador se lanza con su sandbox activado.
**Estado:** parcial
**Requisitos:**
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · Ningún proceso propio queda vivo
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · Plazos duros
- `openspec/specs/request-recovery/spec.md` · Una solicitud viva no se toca
- `openspec/changes/copilot-web-provider/specs/copilot-web-provider/spec.md` · Pérdida del navegador según el punto de fallo
- `openspec/changes/copilot-web-provider/specs/dedicated-edge-browser/spec.md` · Solo se liberan recursos propios
**Tests:**
- `tests/integration/test_mcp_review.py::test_a_grandchild_of_the_server_is_killed_too`
- `tests/integration/test_mcp_review.py::test_a_session_process_stuck_in_c_code_is_killed_at_the_deadline`
- `tests/integration/test_mcp_review.py::test_a_grandchild_in_its_own_session_escapes_as_documented`
- `tests/integration/test_mcp_cli.py::test_a_server_that_ignores_the_end_of_its_input_and_sigterm`
- `tests/integration/test_mcp_cli.py::test_a_server_that_dies`
- `tests/unit/test_locks.py::test_lock_is_freed_when_the_owner_process_is_killed`
- `tests/browser/test_copilot_provider.py::test_browser_closed_before_sending_fails`
- `tests/browser/test_copilot_provider.py::test_browser_closed_during_the_reply_is_uncertain`
- `tests/browser/test_copilot_provider.py::test_nothing_is_left_open_after_a_deadline`
- `tests/browser/test_edge_launcher.py::test_edge_runs_with_its_sandbox_on`
- `tests/browser/test_edge_launcher.py::test_users_edge_survives_when_the_harness_loses_its_own`
**Control negativo:** `mcp-gateway` 3.3 y 6.5; `copilot-web-provider` 4.5 (sin `on_sent`, el cierre durante la respuesta deja de ser `uncertain`) y 8.8 (con el sandbox apagado, el test del sandbox falla).
**Windows:** en Windows el árbol se termina con el Job Object del SDK; la confirmación opcional `mcp-gateway` 5.3 sigue NOT RUN. Los tests sin marca `edge` de esta fila pasaron en la ejecución de `57c413d`, salvo el del nieto que escapa con `setsid`, que se omite donde no existe `os.setsid`. Los tests de `tests/browser/` (marca `edge`) usan Edge contra el chat sintético local y se omiten donde Edge no se puede lanzar; en Windows se ejecutaron por primera vez sobre `a9c51fe` y pasaron, salvo un caso de `response-mode` que no es de esta fila (ver arriba). El sandbox de Edge en Windows no se ha comprobado.
**Límites:** un proceso que el servidor lance en otra sesión o grupo, o fuera del Job Object, escapa, y la auditoría dice igualmente `server_stopped = 1` (lo documenta el test que escapa). Navegador: solo Edge contra el chat sintético en la batería. COM: BLOCKED (EA en pausa).

## SEC-11 · Escritura EA productiva

**Propiedad:** una escritura en un repositorio de Enterprise Architect que no sea el de pruebas se deniega en capas independientes.
**Estado:** BLOCKED
**Motivo:** Enterprise Architect está en pausa desde el 2026-11-25 (`docs/plan/2026-11-24-ai-harness-cortes.md`, «Revisado el 2026-11-25»): `ea-read`, `ea-test-write` y `architecture-skills-ea` sin empezar.
**Requisitos:**
- —
**Tests:**
- —
**Control negativo:** —
**Windows:** —
**Límites:** en `develop` no hay código de EA; esta fila no afirma nada. Lo único relacionado que existe es que la pasarela MCP deniega toda herramienta `write` (SEC-05).

## SEC-12 · Aprobación reutilizada o propuesta alterada

**Propiedad:** una aprobación vale para una sola propuesta exacta, caduca, se usa una vez y no la concede ningún texto; cambiar un byte de lo aprobado, del destino, del Skill o de la ejecución la deniega.
**Estado:** cubierto
**Requisitos:**
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Propuesta con hash canónico
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Lo que se muestra es lo que se aprueba
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · El código solo en la pregunta interactiva
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Caducidad
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Uso único
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Propuesta alterada denegada
- `openspec/changes/architecture-skills-llm/specs/decision-notes/spec.md` · Solo los bytes aprobados
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Escrituras denegadas sin aprobación
- `openspec/changes/approval-buttons/specs/interactive-shell/spec.md` · Nada aprueba al abrirse la caja
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Aprobación del plan entero ligada a su hash
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Aprobación en cada turno
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Consentimiento del bucle
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Lecturas permitidas por regla
**Tests:**
- `tests/unit/test_skill_approval.py::test_approval_reused`
- `tests/unit/test_skill_approval.py::test_output_changed_after_approving`
- `tests/unit/test_skill_approval.py::test_fixed_vector`
- `tests/unit/test_skill_approval.py::test_one_byte_different`
- `tests/unit/test_skill_approval.py::test_granted_approval_expired_before_the_effect`
- `tests/unit/test_skill_approval.py::test_granted_approval_that_expires_while_the_effect_is_busy_is_not_consumed`
- `tests/unit/test_skill_approval.py::test_approval_of_another_run`
- `tests/unit/test_skill_approval.py::test_the_code_never_leaves_the_interactive_prompt`
- `tests/unit/test_skill_approval.py::test_the_model_says_it_is_approved`
- `tests/integration/test_architecture_memory.py::test_a_consumed_approval_cannot_be_used_again`
- `tests/integration/test_architecture_memory.py::test_validated_output_altered_after_the_approval_revokes_it`
- `tests/integration/test_architecture_memory.py::test_apply_refuses_a_proposal_that_does_not_match_its_target`
- `tests/unit/test_mcp_policy.py::test_what_the_server_says_never_allows_a_write`
- `tests/security/test_audit_findings.py::test_the_cli_approval_notice_marks_every_row_of_the_content`
- `tests/unit/test_shell_tui_arming.py::test_the_windows_trace_replayed_approves_nothing`
- `tests/unit/test_shell_tui_arming.py::test_input_read_before_the_arming_never_acts_however_late_it_is_handled`
- `tests/unit/test_shell_tui_arming.py::test_a_stall_then_a_burst_across_the_arming_approves_nothing`
- `tests/unit/test_mcp_plan_run.py::test_changed_what_runs_refuses`
- `tests/unit/test_mcp_plan_run.py::test_changed_what_was_hashed_refuses`
- `tests/unit/test_mcp_plan_run.py::test_changed_what_was_shown_refuses`
- `tests/unit/test_mcp_plan_run.py::test_changed_bytes_the_steps_do_not_show_refuse`
- `tests/unit/test_shell_plan.py::test_what_the_box_shows_is_what_its_hash_covers`
- `tests/unit/test_mcp_plan_run.py::test_an_approval_runs_once`
- `tests/unit/test_mcp_plan_run.py::test_an_approval_never_runs_the_plan_for_another_request`
- `tests/unit/test_mcp_plan_run.py::test_an_approval_that_expires_before_the_run_runs_nothing`
- `tests/unit/test_shell_plan.py::test_an_answer_after_the_expiry_runs_nothing`
- `tests/unit/test_shell_tui_plan.py::test_the_box_shows_the_plan_and_approve_runs_it_once`
- `tests/unit/test_plan_cli.py::test_ctrl_c_at_the_code_prompt_leaves_the_plan_undecided`
- `tests/unit/test_mcp_plan_run.py::test_a_plan_whose_lock_is_held_elsewhere_runs_nothing`
- `tests/unit/test_shell_plan.py::test_the_box_says_each_server_command_is_not_approved`
- `tests/unit/test_mcp_auto_read.py::test_a_plan_with_one_read_not_by_rule_goes_to_the_box_whole`
- `tests/unit/test_mcp_auto_read.py::test_harness_auto_read_off_asks_the_box_for_every_plan`
- `tests/unit/test_mcp_auto_read.py::test_a_command_changed_while_the_box_is_open_refuses_the_plan`
- `tests/unit/test_mcp_auto_read.py::test_a_plan_recorded_before_010_never_runs`
- `tests/unit/test_shell_agent.py::test_a_plan_that_is_not_by_rule_asks_the_box_every_turn`
- `tests/unit/test_shell_agent.py::test_a_plan_not_approved_stops_the_loop`
- `tests/unit/test_shell_agent.py::test_box_sends_every_plan_of_the_loop_to_the_box`
- `tests/unit/test_mcp_auto_read.py::test_box_turns_the_rule_off_for_one_question_only`
- `tests/unit/test_shell_agent.py::test_a_provider_outside_the_machine_asks_once_with_the_exact_text`
- `tests/unit/test_shell_agent.py::test_a_send_not_approved_sends_nothing_and_stops`
- `tests/unit/test_shell_agent.py::test_a_send_approved_after_it_expired_sends_nothing`
**Control negativo:** `skill-engine` 5.1, 5.3, 5.4 y 8.2; `hardening` 5.4 (el aviso de la CLI sin marca: el test falla); `approval-buttons` 7.1 (mutantes M1 a M4 del armado); mutaciones SEC-12 de la tabla (la caducidad en el momento de consumir y el hash de la propuesta, de la revisión independiente). Code mode, tramo 2: `code-mode` 4.5 (cambiar lo ejecutado, lo hasheado o lo mostrado; otra solicitud; dos usos; caducidad: cada uno deniega).
**Windows:** código puro y SQL; los tests de esta fila pasaron en la ejecución de `57c413d`, salvo `tests/unit/test_skill_approval.py::test_granted_approval_that_expires_while_the_effect_is_busy_is_not_consumed`, añadido en `feature/hardening`, que pasó en la ejecución de `a9c51fe`. Los tests de `tests/security/test_audit_findings.py` pasaron en la ejecución de `a9c51fe`. Sobre `develop` = `79cde60` (2026-11-27), `tests/unit/test_shell_tui_buttons.py::test_keys_typed_ahead_of_the_box_cannot_approve` falló en cada ejecución: el armado solo por reloj caducaba en esa máquina y un Tab y un Enter llegados después aprobaron (`approval-buttons` D9). La corrección se sostiene en Windows sobre `a9c51fe`: `tests/unit/test_shell_tui_arming.py`, que reproduce esa traza y una parada del bucle, y `tests/unit/test_shell_tui_buttons.py` pasaron con la máquina en reposo y con una carga de CPU del 11 al 67 % (`approval-buttons` 7.3). Los tests de `code-mode` 4.x pasaron en la ejecución de `a9c51fe`, salvo un test de plazo del plan (ver arriba).
**Límites:** unas teclas que el terminal o una sesión remota retengan más de medio segundo y entreguen tras un silencio llegan como teclas nuevas (`approval-buttons` D9). No prueba que haya una persona delante (límite aceptado por Wilson el 2026-11-24; ver la deuda conocida): un programa que maneje la terminal de la persona puede escribir el código, y en la pantalla completa pulsar el botón de aprobación (en `develop` desde `1b460ea`) igual que ella. El aviso puede engañar sobre qué se aprueba solo dentro del contenido marcado: lo aprobado es siempre el hash mostrado. Los tests inyectan una terminal falsa: el camino real con `isatty()` e `input()` no lo ejercita ningún test (no hay `pty` en Windows); lo cubren la demo de Wilson (`skill-engine` 7.7, abierta) y el test por subproceso de que sin terminal se espera (código 3).

## SEC-13 · Vault work intenta sincronizar

**Propiedad:** el harness no copia, sube ni sincroniza el vault, y su única escritura en él es una nota de decisión nueva en `Decisiones/` tras una aprobación.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/memory-vault/spec.md` · El harness no copia, sincroniza ni modifica el vault
- `openspec/changes/architecture-skills-llm/specs/memory-vault/spec.md` · El harness no copia, sincroniza ni modifica el vault
- `openspec/changes/architecture-skills-llm/specs/decision-notes/spec.md` · Única escritura del harness en el vault
- `openspec/specs/memory-maintenance/spec.md` · Informe determinista y sin escrituras
**Tests:**
- `tests/security/test_memory_no_writes.py::test_memory_package_has_no_copy_upload_or_write_path`
- `tests/security/test_memory_no_writes.py::test_the_allowlist_says_no`
- `tests/security/test_memory_no_writes.py::test_each_write_primitive_is_where_it_belongs_and_no_more`
- `tests/security/test_memory_no_writes.py::test_memory_commands_never_load_the_writer`
- `tests/security/test_memory_no_writes.py::test_no_memory_command_writes_outside_the_data_dir`
- `tests/security/test_memory_no_writes.py::test_an_approved_run_adds_exactly_one_file_to_the_vault`
- `tests/security/test_memory_hardening.py::test_data_dir_inside_the_vault_refused_by_memory_commands`
- `tests/integration/test_hls_review.py::test_the_review_writes_nothing_in_the_vault`
**Control negativo:** `project-memory` 8.7 y 8.13 (archivado); `architecture-skills-llm` 7.6 y 7.8; mutación SEC-13 de la tabla.
**Windows:** los tests de esta fila pasaron en la ejecución de `57c413d`; la escritura de la nota en una carpeta de OneDrive no se ha comprobado (`architecture-skills-llm` 7.11, NOT RUN).
**Límites:** el test estructural mira solo `harness/memory/`; fuera de ese paquete lo que vale son las huellas del vault antes y después de los comandos probados. El harness no detecta ni impide que otro programa (OneDrive, iCloud) sincronice el vault (decisión del 2026-11-24).

## SEC-14 · Skill malicioso o script arbitrario

**Propiedad:** un Skill solo contiene ficheros declarativos de una lista cerrada y un workflow de esquema cerrado; el harness nunca ejecuta ni carga código de un Skill, y los efectos son de una lista cerrada del harness.
**Estado:** cubierto
**Requisitos:**
- `openspec/changes/skill-engine/specs/skill-definition/spec.md` · Solo ficheros declarativos permitidos
- `openspec/changes/skill-engine/specs/skill-definition/spec.md` · Workflow declarativo y cerrado
- `openspec/changes/skill-engine/specs/skill-definition/spec.md` · Referencias resueltas al cargar
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Efectos de una lista cerrada
**Tests:**
- `tests/unit/test_skill_definition.py::test_invalid_fixtures`
- `tests/unit/test_skill_definition.py::test_a_file_outside_the_closed_list_invalidates_the_skill`
- `tests/unit/test_skill_definition.py::test_unknown_step_kind`
- `tests/unit/test_skill_definition.py::test_expression_in_a_template`
- `tests/unit/test_skill_engine.py::test_invalid_skill_is_not_run`
- `tests/unit/test_skill_approval.py::test_unknown_effect`
- `tests/security/test_mcp_structure.py::test_the_mcp_package_has_no_other_way_to_a_process_or_a_socket`
- `tests/unit/test_shell_plan.py::test_plan_has_no_short_form`
**Control negativo:** `skill-engine` 2.2 y 2.3; mutaciones SEC-14 de la tabla (dos de la revisión independiente). Code mode, tramo 2: `code-mode` 4.5b (`/pla` y `/p` no son `/plan`).
**Windows:** los casos con enlaces simbólicos en la carpeta del Skill se omiten donde no se pueden crear; el resto pasó en la ejecución de `57c413d`, salvo `tests/unit/test_skill_definition.py::test_a_file_outside_the_closed_list_invalidates_the_skill`, añadido en `feature/hardening`, que pasó en la ejecución de `a9c51fe`. Los tests de `code-mode` 4.x pasaron en la ejecución de `a9c51fe`, salvo un test de plazo del plan (ver arriba).
**Límites:** un servidor MCP de la lista local es código arbitrario por diseño: corre con los permisos de la cuenta y el harness no lo encierra (lo dice `SECURITY.md`). La sugerencia de Skills por IA y los scripts dentro de un Skill están fuera del alcance hasta después del MVP.

## SEC-15 · Límite de pasos/tamaño/timeout

**Propiedad:** cada ejecución tiene límites de pasos, tamaño y tiempo, y al pasarlos se detiene con un error registrado, también si el otro extremo no coopera.
**Estado:** cubierto
**Requisitos:**
- `openspec/changes/skill-engine/specs/skill-definition/spec.md` · Límites de un Skill en disco
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Límites de ejecución
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Entradas declaradas y acotadas
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · Límites de tamaño
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · Plazos duros
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Ejecución paso a paso por la pasarela
- `openspec/changes/code-mode/specs/code-mode/spec.md` · Topes de lo que se envía
**Tests:**
- `tests/unit/test_skill_limits.py::test_response_too_large`
- `tests/unit/test_skill_limits.py::test_run_time_limit`
- `tests/unit/test_skill_definition.py::test_too_many_steps`
- `tests/unit/test_skill_definition.py::test_too_many_files`
- `tests/unit/test_skill_definition.py::test_too_large_in_total`
- `tests/unit/test_skill_definition.py::test_too_many_inputs`
- `tests/unit/test_skill_limits.py::test_prompt_too_large`
- `tests/unit/test_skill_engine.py::test_inputs_checked_before_the_run`
- `tests/integration/test_skill_cli_run.py::test_input_file_too_large`
- `tests/integration/test_mcp_cli.py::test_a_result_over_the_limit_is_refused_and_not_printed`
- `tests/integration/test_mcp_cli.py::test_a_tool_that_never_ends`
- `tests/integration/test_mcp_review.py::test_a_session_process_stuck_in_c_code_is_killed_at_the_deadline`
- `tests/integration/test_mcp_review.py::test_a_server_flooding_stderr_is_capped_and_stopped`
- `tests/unit/test_strict_json.py::test_deep_nesting_is_refused_without_recursion`
- `tests/unit/test_decisions.py::test_escaping_is_linear_in_the_size_of_the_input`
- `tests/security/test_audit_findings.py::test_a_reply_longer_than_the_cap_is_cut_in_python_and_reported`
- `tests/browser/test_copilot_provider.py::test_huge_reply_is_read_up_to_the_cap`
- `tests/security/test_audit_findings.py::test_the_duplicate_pass_stops_at_its_budget_and_says_so`
- `tests/security/test_audit_findings.py::test_many_links_to_one_missing_name_search_for_a_fix_once`
- `tests/unit/test_shell_plan.py::test_the_first_failing_step_stops_the_plan`
- `tests/unit/test_shell_plan.py::test_the_plan_deadline_ends_a_step_in_course`
- `tests/unit/test_shell_plan.py::test_a_single_hung_step_ends_as_its_own_timeout`
- `tests/unit/test_shell_plan.py::test_ctrl_c_while_a_step_runs_stops_the_plan_and_its_tree`
- `tests/unit/test_mcp_plan_prompt.py::test_too_many_tools_or_characters_are_refused`
- `tests/unit/test_mcp_loop.py::test_the_largest_turn_fits_its_cap`
- `tests/unit/test_mcp_loop.py::test_a_turn_over_its_cap_is_never_composed`
- `tests/unit/test_mcp_loop.py::test_a_huge_result_is_cut_in_the_middle_with_a_mark`
- `tests/unit/test_mcp_loop.py::test_any_other_cap_is_refused_before_anything_is_sent`
- `tests/unit/test_shell_agent.py::test_the_cap_then_one_closing_turn_whose_reply_is_never_read`
**Control negativo:** `skill-engine` 2.5 y 6.1; `mcp-gateway` 3.3 y 3.6; `copilot-web-provider` 4.4 (sin el límite de lectura, su test falla); `hardening` 5.5 y 5.7; mutaciones SEC-15 de la tabla. Code mode, tramo 2: `code-mode` 4.6 (primer fallo, plazo total e interrupción).
**Windows:** los tests de plazos usan márgenes de tiempo: en la ejecución de `57c413d`, `tests/integration/test_mcp_cli.py::test_a_tool_that_never_ends` venció una vez con la máquina cargada y pasó 5 de 5 solo; el resto de los tests sin marca `edge` de esta fila pasaron. Los tests de `tests/browser/` (marca `edge`) usan Edge contra el chat sintético local y se omiten donde Edge no se puede lanzar; en Windows se ejecutaron por primera vez sobre `a9c51fe` y pasaron, salvo un caso de `response-mode` que no es de esta fila (ver arriba). Los tests de `tests/security/test_audit_findings.py` pasaron en la ejecución de `a9c51fe`. Los tests de `code-mode` 4.x pasaron en la ejecución de `a9c51fe`, salvo un test de plazo del plan (ver arriba).
**Límites:** SQLite crece sin retención ni purga, y no hay rotación de logs salvo la de una generación (`.1`) de los logs de stderr MCP, que ningún test comprueba (aplazado, proyecto educativo). Con el Mock, la respuesta de `ask` no tiene tope propio (la del Mock es sintética); con Copilot, se leen como mucho 200 000 caracteres, comprobado en la página y otra vez en Python. `memory maintain --dry-run` compara como mucho 100 000 pares de nombres por pasada y avisa al pararse; la búsqueda de encabezados de un paso `validate` sigue siendo cuadrática en el peor caso (deuda conocida 13).
