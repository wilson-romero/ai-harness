# Matriz SEC

Estado de cada propiedad de seguridad SEC-01..SEC-15 del plan maestro (`docs/plan/AI-HARNESS-PLAN-v0.4.md` §14) sobre lo que hay en `develop`. Rellenada el 2026-11-25 sobre `develop` = `ee550b6` (igual a `v0.2.0`). Lo que vive en ramas sin mergear se marca `pendiente de merge` y no se describe.

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

Los campos `Windows` de cada fila describen `v0.2.0`; se actualizarán cuando se mergee `hotfix/0.2.1`.

- Wilson ejecutó la batería de `v0.2.0` en Windows el 2026-11-25: 997 pasados, 13 fallados, 28 omitidos. El detalle test a test no está en el repositorio, así que **ninguna fila afirma que un test concreto pasó en Windows**.
- Esa ejecución encontró un defecto de producto: `harness/mcp/audit.py` escribe la clave de los HMAC de argumentos MCP (`keys/mcp-args.key`) con `os.open` sin modo binario; en Windows un byte `0x0A` de la clave se escribe como `0x0D 0x0A`, la clave pasa de 32 bytes y todo `mcp call` termina con «the MCP argument key is damaged» antes de decidir nada. Falla cerrado (no arranca ningún servidor), pero la pasarela MCP no funciona en esa instalación. Se corrige en `0.2.1` (`hotfix/0.2.1`, sin publicar el 2026-11-25).
- Y defectos de tests: `tests/unit/test_mcp_client.py` y `tests/unit/test_mcp_policy.py` declaraban una orden de servidor con ruta POSIX (`/opt/...`), que en Windows no es absoluta, y no se recogían allí. Corregido en `hotfix/0.2.1` (`871ab1b`, sin mergear en `develop`).
- Los tests que dependen de una capacidad del sistema se omiten con un motivo visible cuando la cuenta no la tiene: crear enlaces simbólicos (`make_symlink` en `tests/conftest.py`), hacer ilegible una carpeta (`chmod 0`), los bits de permiso POSIX (`0600`/`0700` y el dueño de la lista MCP), `os.mkfifo` y `os.setsid`. Por eso **el rechazo de enlaces simbólicos, el informe de carpetas ilegibles y las comprobaciones de permisos están probados solo en macOS**. Las uniones de directorio (junctions) de Windows no las ejercita ningún test.

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

**Propiedad:** una credencial con un formato conocido que llega en un texto leído del vault, en el resultado de una herramienta MCP o en la salida del modelo que valida un Skill no sale en claro hacia la terminal, el proveedor, SQLite, la auditoría ni la nota que el harness escribe en el vault; los argumentos MCP se guardan solo como HMAC.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/secret-redaction/spec.md` · Formatos conocidos enmascarados
- `openspec/specs/secret-redaction/spec.md` · Límite declarado de la redacción
- `openspec/specs/session-management/spec.md` · Auditoría sin contenido
- `openspec/changes/mcp-gateway/specs/secret-redaction/spec.md` · Resultados de herramientas enmascarados
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Auditoría de cada decisión sin contenido
- `openspec/changes/architecture-skills-llm/specs/architecture-memory/spec.md` · Credenciales enmascaradas en la nota
**Tests:**
- `tests/unit/test_redaction.py::test_each_format_is_masked`
- `tests/security/test_memory_hardening.py::test_hidden_credential_masked_in_context_and_sent_text`
- `tests/security/test_memory_hardening.py::test_credential_in_a_file_name_and_in_type`
- `tests/security/test_memory_hardening.py::test_credential_glued_to_an_escape_sequence_is_masked`
- `tests/unit/test_mcp_render.py::test_credentials_in_keys_and_nested_values_are_masked`
- `tests/integration/test_mcp_cli.py::test_a_leaky_result_is_cleaned_and_asks_for_nothing`
- `tests/integration/test_mcp_cli.py::test_audit_rows_never_hold_argument_values_or_result_text`
- `tests/integration/test_mcp_review.py::test_arguments_are_kept_as_an_hmac_with_a_private_local_key`
- `tests/unit/test_skill_checks.py::test_controls_and_credentials_are_cleaned`
- `tests/integration/test_architecture_memory.py::test_a_token_in_the_model_output_is_masked_in_what_is_shown_and_written`
**Control negativo:** `project-memory` 8.2 y 8.3 (archivado); `mcp-gateway` 1.3 y 6.4; `architecture-skills-llm` 4.2; mutación SEC-01 de la tabla.
**Windows:** la redacción es código puro, el mismo en las dos plataformas. Que la clave HMAC y los logs de stderr sean `0600` se prueba solo en macOS; en Windows el harness no fija ni comprueba ACL. En `v0.2.0` la clave HMAC se escribía mal en Windows (ver arriba).
**Límites:** **no cubre lo que escribe la persona:** el texto de `ask` llega al proveedor tal cual y, con el Mock, se guarda en `messages` y se ve en `history` (la respuesta de `ask` tampoco se redacta). Solo se reconocen formatos conocidos; una contraseña en prosa, una cadena de conexión o un token de formato desconocido pasan tal cual (lo dice el requisito «Límite declarado»). **No cubierto en `develop`:** el stderr de un servidor MCP se guarda sin sanear ni redactar en `HARNESS_DATA_DIR/logs/mcp/<servidor>.stderr.log` (hasta 1 MiB por sesión); su corrección vive en una rama sin mergear: pendiente de merge. Ningún test comprueba la rotación a `.1`. SQLite no está cifrado y, con el Mock, guarda prompts y respuestas (sintéticos por definición).

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
**Windows:** código y SQL sin ramas por plataforma; no hay resultado por test en Windows.
**Límites:** es aislamiento lógico dentro de una cuenta del sistema y una base SQLite: cualquier proceso con la misma cuenta lee todas las sesiones. No hay clientes externos (SEC-09), así que no se prueba el aislamiento a través de MCP.

## SEC-03 · Prompt injection en memoria, EA o tool result

**Propiedad:** un texto que viene de una nota, de un documento de entrada, de la salida del modelo o del resultado de una herramienta no cambia lo que hace el harness: qué lee, qué envía, qué aprueba ni dónde escribe.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/project-context/spec.md` · Memoria marcada como datos no confiables
- `openspec/specs/project-context/spec.md` · Una instrucción en una nota no cambia la conducta del harness
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Referencias sustituidas literalmente
- `openspec/changes/skill-engine/specs/human-approval/spec.md` · Solo una persona en una terminal interactiva aprueba
- `openspec/changes/architecture-skills-llm/specs/hls-review/spec.md` · Instrucciones dentro del documento
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Resultados como datos no confiables
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Lo que dice el servidor no amplía la política
**Tests:**
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
**Control negativo:** `project-memory` 8.12 (archivado); `skill-engine` 3.1; mutación SEC-03 de la tabla. (`architecture-skills-llm` 5.2 tiene recibo pero no anota un control negativo.)
**Windows:** código puro. `tests/unit/test_mcp_policy.py` no se recogía en Windows en `v0.2.0` (ver arriba).
**Límites:** prueba que el harness no obedece, con el Mock; no prueba lo que un modelo real hace con el texto (los delimitadores son una mitigación). Copilot real: pendiente de merge (`copilot-web-provider`). EA: BLOCKED.

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
**Windows:** las formas de ruta de Windows (`C:\`, `\\servidor`, nombres reservados) se prueban en macOS con `PureWindowsPath`. Todo lo que crea un enlace simbólico se omite donde la cuenta no puede crearlos (Windows sin modo desarrollador): **el rechazo de enlaces está probado solo en macOS**.
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
**Tests:**
- `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order`
- `tests/integration/test_mcp_cli.py::test_denied_calls_start_no_process`
- `tests/unit/test_mcp_config.py::test_unknown_server_is_refused_without_starting_anything`
- `tests/integration/test_mcp_cli.py::test_audit_rows_never_hold_argument_values_or_result_text`
- `tests/integration/test_mcp_review.py::test_a_read_tool_the_server_calls_destructive_is_denied`
- `tests/unit/test_mcp_policy.py::test_undeclared_argument_is_named_in_the_detail`
**Control negativo:** `mcp-gateway` 2.3 (29 fallos con `deny` devolviendo `allowed`) y 2.4; mutaciones SEC-05 de la tabla (cada caso de `test_each_reason_in_its_order` que mata una).
**Windows:** en `v0.2.0`, `tests/unit/test_mcp_policy.py` no se recogía en Windows, y con la clave HMAC dañada todo `mcp call` fallaba antes de decidir (cerrado, pero sin denegación auditada). La comprobación de que la lista local no la pueden escribir otros es solo POSIX: en Windows no se comprueban ACL.
**Límites:** solo con servidores sintéticos de los tests. El servidor MCP propio del harness no existe todavía (`harness-mcp-server`, planificado).

## SEC-06 · MFA/login expirado

**Propiedad:** con el login de Copilot vencido o un MFA pendiente, el harness se detiene y pide intervención humana; no automatiza credenciales.
**Estado:** pendiente de merge
**Motivo:** el proveedor de Copilot Web vive en `feature/copilot-web-provider`, sin mergear en `develop` el 2026-11-25.
**Requisitos:**
- —
**Tests:**
- —
**Control negativo:** —
**Windows:** —
**Límites:** en `develop` solo existe el proveedor Mock; esta fila no afirma nada.

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
**Tests:**
- `tests/integration/test_recovery.py::test_interruption_after_send_leaves_the_request_uncertain`
- `tests/integration/test_recovery.py::test_killed_process_leaves_the_request_uncertain`
- `tests/integration/test_recovery.py::test_recovery_does_not_resend`
- `tests/unit/test_ask.py::test_result_depends_on_where_it_failed`
- `tests/unit/test_skill_engine.py::test_step_deadline_after_send`
- `tests/integration/test_skill_crash.py::test_killed_after_the_effect_is_not_applied_again`
- `tests/integration/test_decision_crash.py::test_killed_after_the_note_is_published_completes_without_writing_again`
- `tests/integration/test_decision_crash.py::test_killed_before_the_note_is_published_needs_a_new_approval`
**Control negativo:** `skill-engine` 4.3 y 8.1; `architecture-skills-llm` 4.4; mutaciones SEC-07 de la tabla.
**Windows:** los tests de proceso muerto matan un subproceso real; no hay resultado por test en Windows.
**Límites:** solo con el Mock; Copilot real: pendiente de merge (`copilot-web-provider`). Las llamadas MCP no se reintentan, pero hoy solo se permiten herramientas de lectura. `skill resume --retry-step` repite una pregunta por decisión explícita de la persona (puede duplicarla en la conversación). Sin `fsync` del directorio tras publicar la nota: tras un corte de luz en ese instante la nota puede faltar y `skill resume` pediría aprobarla otra vez (límite 3 del README).

## SEC-08 · Reinicio

**Propiedad:** tras reiniciar el proceso, el historial, las ejecuciones de Skills, las aprobaciones pendientes y las llamadas MCP interrumpidas se recuperan en un estado verificable, sin reenviar nada.
**Estado:** parcial
**Requisitos:**
- `openspec/specs/session-management/spec.md` · Persistencia tras reinicio
- `openspec/specs/session-management/spec.md` · Esquema migrable y repetible
- `openspec/specs/request-recovery/spec.md` · Una solicitud viva no se toca
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Recuperación de ejecuciones interrumpidas
- `openspec/changes/skill-engine/specs/skill-execution/spec.md` · Reanudar con el mismo Skill y las mismas entradas
**Tests:**
- `tests/integration/test_recovery.py::test_history_survives_a_new_process`
- `tests/integration/test_recovery.py::test_live_request_is_not_touched_by_another_process`
- `tests/unit/test_storage.py::test_migrating_twice_changes_nothing`
- `tests/integration/test_skill_cli_run.py::test_non_interactive_run_waits_and_status_after_restart`
- `tests/integration/test_skill_crash.py::test_killed_after_the_effect_is_not_applied_again`
- `tests/integration/test_mcp_review.py::test_a_live_call_is_never_recovered_as_stale`
**Control negativo:** `session-core` 5.2 (archivado: sin la comprobación del bloqueo en la recuperación, una solicitud viva se tocaba); `skill-engine` 4.3 y 8.1.
**Windows:** sin ramas por plataforma; no hay resultado por test en Windows.
**Límites:** recuperar la identidad de una conversación de Copilot: pendiente de merge (`copilot-web-provider`). No hay copia ni restauración de `HARNESS_DATA_DIR`: aplazado (proyecto educativo, ver la deuda conocida).

## SEC-09 · Cliente no autorizado

**Propiedad:** ningún cliente externo puede usar el harness sin autorización.
**Estado:** parcial
**Requisitos:**
- `openspec/changes/mcp-gateway/specs/tool-policy/spec.md` · Ninguna superficie de entrada en este corte
**Tests:**
- `tests/integration/test_mcp_cli.py::test_no_socket_is_bound_during_a_call`
- `tests/integration/test_mcp_review.py::test_no_socket_is_created_by_the_harness_or_its_session_process`
- `tests/integration/test_mcp_review.py::test_the_socket_oracle_sees_a_listen_without_bind`
**Control negativo:** mutación SEC-09 de la tabla. `mcp-gateway` 6.10 reforzó el oráculo (`listen()` sin `bind`) pero no anota un control negativo.
**Windows:** el test distingue los `bind` de la emulación de `socketpair` de la biblioteca estándar en Windows; no hay resultado por test en Windows.
**Límites:** hoy prueba que no hay puerta (ningún socket de escucha durante un `mcp call`), no que haya autorización. Cualquier proceso con la misma cuenta del sistema puede ejecutar el harness: la frontera es la cuenta. El servidor MCP propio, que abriría una entrada, está planificado (`harness-mcp-server`), sin código.

## SEC-10 · Crash navegador/COM

**Propiedad:** si un proceso propio (servidor MCP, proceso de sesión, navegador, EA) muere o se cuelga, el harness libera lo que es suyo: procesos, bloqueos y filas en curso.
**Estado:** parcial
**Requisitos:**
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · Ningún proceso propio queda vivo
- `openspec/changes/mcp-gateway/specs/mcp-client/spec.md` · Plazos duros
- `openspec/specs/request-recovery/spec.md` · Una solicitud viva no se toca
**Tests:**
- `tests/integration/test_mcp_review.py::test_a_grandchild_of_the_server_is_killed_too`
- `tests/integration/test_mcp_review.py::test_a_session_process_stuck_in_c_code_is_killed_at_the_deadline`
- `tests/integration/test_mcp_review.py::test_a_grandchild_in_its_own_session_escapes_as_documented`
- `tests/integration/test_mcp_cli.py::test_a_server_that_ignores_the_end_of_its_input_and_sigterm`
- `tests/integration/test_mcp_cli.py::test_a_server_that_dies`
- `tests/unit/test_locks.py::test_lock_is_freed_when_the_owner_process_is_killed`
**Control negativo:** `mcp-gateway` 3.3 y 6.5.
**Windows:** en Windows el árbol se termina con el Job Object del SDK; la confirmación opcional `mcp-gateway` 5.3 sigue NOT RUN y no hay resultado por test. El test del nieto que escapa con `setsid` se omite donde no existe `os.setsid`.
**Límites:** un proceso que el servidor lance en otra sesión o grupo, o fuera del Job Object, escapa, y la auditoría dice igualmente `server_stopped = 1` (lo documenta el test que escapa). Navegador: pendiente de merge (`copilot-web-provider`). COM: BLOCKED (EA en pausa).

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
**Control negativo:** `skill-engine` 5.1, 5.3, 5.4 y 8.2; mutaciones SEC-12 de la tabla (la caducidad en el momento de consumir y el hash de la propuesta, de la revisión independiente).
**Windows:** código puro y SQL. `tests/unit/test_mcp_policy.py` no se recogía en Windows en `v0.2.0`.
**Límites:** no prueba que haya una persona delante (límite aceptado por Wilson el 2026-11-24; ver la deuda conocida). Los tests inyectan una terminal falsa: el camino real con `isatty()` e `input()` no lo ejercita ningún test (no hay `pty` en Windows); lo cubren la demo de Wilson (`skill-engine` 7.7, abierta) y el test por subproceso de que sin terminal se espera (código 3).

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
**Windows:** la escritura de la nota en una carpeta de OneDrive no se ha comprobado (`architecture-skills-llm` 7.11, NOT RUN).
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
**Control negativo:** `skill-engine` 2.2 y 2.3; mutaciones SEC-14 de la tabla (dos de la revisión independiente).
**Windows:** los casos con enlaces simbólicos en la carpeta del Skill se omiten donde no se pueden crear.
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
**Control negativo:** `skill-engine` 2.5 y 6.1; `mcp-gateway` 3.3 y 3.6; mutaciones SEC-15 de la tabla.
**Windows:** los tests de plazos usan márgenes de tiempo; no hay resultado por test en Windows.
**Límites:** SQLite crece sin retención ni purga, y no hay rotación de logs salvo la de una generación (`.1`) de los logs de stderr MCP, que ningún test comprueba (aplazado, proyecto educativo). `ask` no tiene límite de tamaño de la respuesta (los límites de respuesta son de los pasos de un Skill y de las llamadas MCP); su plazo solo se prueba con el Mock.
