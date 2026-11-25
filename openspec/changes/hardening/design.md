# Design

## Context

Ver `proposal.md` para el porqué. Estado del que parte (medido el 2026-11-25 sobre `develop` = `86f1079`, Mac arm64, CPython 3.14.8):

- 852 tests recogidos por `uv run pytest --collect-only -q`; los marcadores declarados en `pyproject.toml` con `--strict-markers`.
- Los recibos de cada SEC están repartidos en `openspec/changes/archive/2026-11-24-session-core/tasks.md`, `openspec/changes/archive/2026-11-24-project-memory/tasks.md`, `openspec/changes/skill-engine/tasks.md` y `openspec/changes/mcp-gateway/tasks.md`; en ramas sin mergear, `copilot-web-provider` y `architecture-skills-llm`.
- `scripts/verify.sh` ejecuta el guard público, `uv lock --check`, `uv run pytest` y `openspec validate --all --strict`, y termina con `verify: PASS on <SHA>`.
- `HARNESS_DATA_DIR` contiene hoy: `harness.sqlite3` (y sus `-wal`/`-shm`), `locks/` (bloqueos con nombre), `keys/mcp-args.key` (`0600`), `logs/mcp/*.stderr.log` (`0600`, stderr crudo de servidores MCP, hasta 1 MiB por sesión) y, con la rama de Copilot, `edge-profile/` (sesión iniciada) y `copilot/` (mediciones de la sonda).

## Goals / Non-Goals

**Goals:** que cualquier lector sepa, en un solo documento, qué SEC está cubierto y por qué test, y que esa afirmación no pueda quedarse desfasada sin que `verify.sh` falle; que instalar, usar y diagnosticar el harness esté escrito para macOS y PowerShell.

**Non-Goals:** cambiar conducta; copia y restauración (aplazada, proyecto educativo); cubrir lo que depende de EA.

## Decisions

### D1 · Qué es conducta y qué es documentación

- **Qué:** nada de este change es conducta del harness. La matriz, el runbook, la guía y la deuda son documentos; la comprobación de la matriz es una herramienta de desarrollo que corre en `verify.sh`, como el guard público. Por eso `skip_specs: true`.
- **Por qué:** una spec describe lo que hace el producto; «el documento cita tests que existen» no es algo que haga el harness. Inventar un requisito para pasar la validación es lo que `openspec/config.yaml` y la instrucción de specs prohíben.
- **Alternativas rechazadas:** una capacidad `security-matrix` con requisitos sobre el documento: describiría un fichero, no una conducta, y duplicaría las specs que ya cubren cada SEC.
- **Impacto:** ninguna spec; tareas 1.x.

### D2 · Formato de la matriz y su comprobación

- **Qué:** `docs/security/sec-matrix.md` tiene una sección por SEC (`## SEC-01 · Credenciales en logs/vault`) con cinco campos en líneas fijas: `Estado:` (uno de `cubierto`, `parcial`, `pendiente de merge`, `no cubierto`, `BLOCKED`), `Requisitos:` (rutas de spec y nombre de requisito), `Tests:` (identificadores de pytest `fichero::test`, uno por línea), `Control negativo:` (cita del recibo: change y tarea) y `Límites:`. `scripts/check_sec_matrix.py` (biblioteca estándar) comprueba: las 15 secciones en orden y ninguna más; un estado de la lista; al menos un test en `cubierto` y `parcial`; que cada test citado aparece en la salida de `uv run pytest --collect-only -q` (subproceso con plazo de 120 s, salida a fichero, sin `wait()` sin plazo); que cada ruta de spec citada existe y contiene el requisito nombrado; y que una fila `BLOCKED` o `pendiente de merge` dice por qué. Termina con `sec-matrix: PASS (15 rows, N tests)` o con la lista de fallos y código 1. `verify.sh` lo llama después de `pytest`.
- **Por qué:** «un control que nunca ha rechazado nada es un control que nadie ha comprobado»: la matriz cita tests y requisitos por nombre, y renombrar un test o archivar un change rompería la cita en silencio. La comprobación convierte la cita en un recibo vivo. Los recibos de control negativo se citan, no se vuelven a ejecutar: re-ejecutar mutaciones en cada `verify.sh` sería un framework de mutación que el proyecto no necesita.
- **Alternativas rechazadas:**
  - Una tabla Markdown de una línea por SEC: celdas con veinte tests son ilegibles y frágiles de analizar.
  - Marcadores de pytest por SEC (`@pytest.mark.sec01`): tocaría 852 tests y no dice nada del requisito ni del control negativo.
  - Comprobar solo que el fichero de test existe: un test renombrado pasaría.
- **Límite escrito:** la comprobación garantiza que lo citado existe, no que pruebe lo que dice la matriz; eso lo garantiza la revisión del documento y el control negativo citado.
- **Revisado en la implementación (2026-11-25):** cada campo va en negrita (`**Estado:** parcial`) para que el documento se lea bien en GitHub, y se añaden tres campos: `Propiedad` (la propiedad en una frase), `Windows` (qué se ha ejecutado allí y qué no) y `Motivo` (obligatorio en `pendiente de merge`, `no cubierto` y `BLOCKED`). Un requisito se cita como `` `ruta de la spec` · Nombre del requisito ``. La misma ejecución de `pytest --collect-only` comprueba también los identificadores citados en `docs/security/known-debt.md`, y el script comprueba que los enlaces relativos de `README.md`, `SECURITY.md` y los documentos de `docs/security/` apuntan a un fichero que existe; así no hacen falta tests aparte que vuelvan a recoger la batería. Cuando se escriba la guía de diagnóstico (aplazada, ver D4), se añade a esas dos listas.
- **Impacto:** `scripts/check_sec_matrix.py`, `scripts/verify.sh`, tests del script; tareas 1.1–1.4.

### D3 · Matriz de partida (lo que existe en `develop` el 2026-11-25)

Rellenada leyendo el código, los tests recogidos y los recibos. La implementación la vuelve a comprobar contra el `develop` de ese día (tarea 1.3); lo que haya cambiado se corrige en el documento, no aquí.

| SEC | Estado | Tests en `develop` (fichero::test) | Control negativo citado | Lo que falta o el límite |
|---|---|---|---|---|
| 01 Credenciales en logs/vault | parcial | `tests/unit/test_redaction.py::test_each_format_is_masked`, `tests/security/test_memory_hardening.py::test_hidden_credential_masked_in_context_and_sent_text`, `::test_credential_in_a_file_name_and_in_type`, `::test_credential_glued_to_an_escape_sequence_is_masked`, `tests/unit/test_mcp_render.py::test_credentials_in_keys_and_nested_values_are_masked`, `tests/unit/test_skill_checks.py::test_controls_and_credentials_are_cleaned`, `tests/integration/test_mcp_review.py::test_arguments_are_kept_as_an_hmac_with_a_private_local_key` | `project-memory` 8.2 y 8.3; `mcp-gateway` 1.3 y 6.4 | La redacción reconoce 13 formatos, no todos los secretos (límite declarado de `secret-redaction`). `logs/mcp/*.stderr.log` guarda el stderr de un servidor MCP **sin redactar** (`0600`): no cubierto. La nota escrita en el vault: pendiente de merge (`architecture-skills-llm`) |
| 02 Cruce de sesiones/proyectos | cubierto | `tests/security/test_session_isolation.py::test_history_does_not_mix_sessions`, `::test_cross_session_message_is_rejected_by_storage`, `tests/unit/test_ask_project.py::test_project_other_than_the_sessions`, `::test_service_refuses_a_context_of_another_project`, `tests/unit/test_memory_context.py::test_no_project_mixing`, `tests/unit/test_memory_search.py::test_other_project_excluded`, `tests/unit/test_skill_approval.py::test_approval_of_another_run` | `session-core` (recibos de aislamiento); `skill-engine` 5.4 | Por MCP: pendiente (`harness-mcp-server`, ámbitos) |
| 03 Prompt injection en memoria, EA o tool result | parcial | `tests/security/test_note_instructions.py::test_note_with_orders_to_the_harness`, `::test_note_with_orders_that_reaches_the_limit`, `tests/unit/test_memory_context.py::test_forged_marker_in_a_note`, `tests/unit/test_skill_references.py::test_forged_close_marker_in_an_input`, `tests/unit/test_skill_approval.py::test_the_model_says_it_is_approved`, `tests/integration/test_mcp_cli.py::test_a_leaky_result_is_cleaned_and_asks_for_nothing` | `project-memory` 8.12; `skill-engine` 3.1 | Prueba que el harness no obedece; no prueba lo que un modelo real hace con el texto. EA: BLOCKED |
| 04 Traversal/symlink | cubierto | `tests/security/test_vault_confinement.py::test_symlink_to_outside_file_ignored`, `::test_symlinked_directory_to_outside_ignored`, `::test_traversal_in_project_rejected_by_the_cli`, `::test_windows_path_forms_rejected_by_the_cli`, `tests/security/test_memory_hardening.py::test_note_replaced_by_a_link_after_the_walk`, `tests/unit/test_memory_paths.py::test_containment_is_not_fooled_by_unresolved_parent_parts`, `tests/unit/test_skill_definition.py::test_template_linked_outside_the_root`, `::test_hard_link_is_refused` | `project-memory` 8.5, 8.16, 8.18; `skill-engine` 2.2 | Los enlaces simbólicos se prueban solo donde la cuenta puede crearlos (omitidos con motivo visible) |
| 05 MCP desconocido o argumentos inválidos | cubierto | `tests/unit/test_mcp_policy.py::test_each_reason_in_its_order`, `tests/integration/test_mcp_cli.py::test_denied_calls_start_no_process`, `tests/unit/test_mcp_config.py::test_unknown_server_is_refused_without_starting_anything`, `tests/integration/test_mcp_cli.py::test_audit_rows_never_hold_argument_values_or_result_text` | `mcp-gateway` 2.3 y 2.4 | Servidor propio: pendiente (`harness-mcp-server`) |
| 06 MFA/login expirado | pendiente de merge | — | — | `copilot-web-provider` (sin mergear) |
| 07 Timeout tras envío/escritura | parcial | `tests/integration/test_recovery.py::test_interruption_after_send_leaves_the_request_uncertain`, `::test_killed_process_leaves_the_request_uncertain`, `::test_recovery_does_not_resend`, `tests/unit/test_ask.py::test_result_depends_on_where_it_failed`, `tests/unit/test_skill_engine.py::test_step_deadline_after_send`, `tests/integration/test_skill_crash.py::test_killed_after_the_effect_is_not_applied_again` | `skill-engine` 4.3 y 8.1 | Copilot real y escritura en el vault: pendiente de merge. Reintentos por MCP: pendiente (`harness-mcp-server`) |
| 08 Reinicio | parcial | `tests/integration/test_recovery.py::test_history_survives_a_new_process`, `tests/integration/test_skill_cli_run.py::test_non_interactive_run_waits_and_status_after_restart`, `tests/unit/test_storage.py::test_migrating_twice_changes_nothing` | `session-core` (recibo de recuperación) | Recuperación de la conversación de Copilot: pendiente de merge |
| 09 Cliente no autorizado | parcial | `tests/integration/test_mcp_cli.py::test_no_socket_is_bound_during_a_call`, `tests/integration/test_mcp_review.py::test_no_socket_is_created_by_the_harness_or_its_session_process`, `::test_the_socket_oracle_sees_a_listen_without_bind` | `mcp-gateway` 6.10 | Hoy prueba que no hay puerta. El servidor propio y lo que significa sobre stdio: pendiente (`harness-mcp-server` D3) |
| 10 Crash navegador/COM | parcial | `tests/integration/test_mcp_review.py::test_a_grandchild_of_the_server_is_killed_too`, `::test_a_session_process_stuck_in_c_code_is_killed_at_the_deadline`, `tests/integration/test_mcp_cli.py::test_a_server_that_ignores_the_end_of_its_input_and_sigterm`, `::test_a_server_that_dies`, `tests/unit/test_locks.py::test_lock_is_freed_when_the_owner_process_is_killed` | `mcp-gateway` 3.3 y 6.5 | Navegador: pendiente de merge. COM: BLOCKED (EA). Un nieto en su propia sesión escapa (límite escrito) |
| 11 Escritura EA productiva | BLOCKED | — | — | EA en pausa |
| 12 Aprobación reutilizada o propuesta alterada | cubierto | `tests/unit/test_skill_approval.py::test_approval_reused`, `::test_output_changed_after_approving`, `::test_fixed_vector`, `::test_one_byte_different`, `::test_granted_approval_expired_before_the_effect`, `::test_the_code_never_leaves_the_interactive_prompt`, `tests/unit/test_mcp_policy.py::test_what_the_server_says_never_allows_a_write` | `skill-engine` 5.1, 5.3, 5.4 y 8.2 | No prueba que haya una persona delante (límite aceptado por Wilson el 2026-11-24) |
| 13 Vault work intenta sincronizar | parcial | `tests/security/test_memory_no_writes.py::test_memory_package_has_no_copy_upload_or_write_path`, `::test_the_allowlist_says_no`, `::test_no_memory_command_writes_outside_the_data_dir`, `tests/security/test_memory_hardening.py::test_data_dir_inside_the_vault_refused_by_memory_commands` | `project-memory` 8.7 y 8.13 | El harness no tiene camino para copiar ni sincronizar; no detecta ni impide que otro programa sincronice el vault (decisión del 2026-11-24) |
| 14 Skill malicioso o script arbitrario | cubierto | `tests/unit/test_skill_definition.py::test_invalid_fixtures`, `::test_unknown_step_kind`, `::test_expression_in_a_template`, `tests/unit/test_skill_engine.py::test_invalid_skill_is_not_run`, `tests/security/test_mcp_structure.py::test_the_mcp_package_has_no_other_way_to_a_process_or_a_socket` | `skill-engine` 2.2 y 2.3 | — |
| 15 Límite de pasos/tamaño/timeout | cubierto | `tests/unit/test_skill_limits.py::test_response_too_large`, `::test_run_time_limit`, `tests/unit/test_skill_definition.py::test_too_many_steps`, `tests/integration/test_mcp_cli.py::test_a_result_over_the_limit_is_refused_and_not_printed`, `::test_a_tool_that_never_ends`, `tests/unit/test_strict_json.py::test_deep_nesting_is_refused_without_recursion` | `skill-engine` 2.5 y 6.1; `mcp-gateway` 3.6 | — |

Los identificadores de esta tabla se comprobaron el 2026-11-25 contra la salida de `uv run pytest --collect-only -q` sobre `86f1079` (852 tests).

### D4 · Runbook y guía de diagnóstico

**Aplazada el 2026-11-25 por decisión de Wilson: la interfaz conversacional va antes** (change `interactive-shell`). Un runbook y una guía de diagnóstico escritos hoy describirían una interfaz que va a cambiar enseguida. Lo que sigue queda como diseño de referencia para cuando exista la interfaz nueva; los nombres de fichero pasan a español (`instalacion-y-uso.md`, `diagnostico.md`).


- **Qué:** `docs/runbook/instalacion-y-uso.md` con dos columnas de comandos (macOS/zsh y Windows/PowerShell): instalar uv, `uv sync`, `.env` y variables (`HARNESS_DATA_DIR` fuera del repo), activar el hook del guard, primer uso con el Mock, memoria, Skills, MCP, y Copilot enlazando al runbook de su change. `docs/runbook/diagnostico.md` organizado por síntoma: `uncertain` (qué significa, que nunca se reenvía solo, cómo seguir: `ask` nuevo explícito o `skill resume --retry-step`), `awaiting_approval` y código 3, `authentication_required` (`copilot login`), sesión ocupada, bloqueos (`HARNESS_DATA_DIR/locks/`: no borrar a mano con un proceso vivo; un bloqueo de SQLite se libera solo al morir su dueño), dónde están los logs y qué contienen, y qué hay en `HARNESS_DATA_DIR` y qué no debe salir nunca de la máquina (perfil de Edge, claves, logs de stderr, base de datos). Cada síntoma enlaza el test que lo produce.
- **Por qué:** el runbook es lo que más tarda en escribirse bien y lo primero que se necesita al volver a un proyecto educativo meses después. Enlazar cada síntoma a un test permite reproducirlo en lugar de describirlo de memoria.
- **Alternativas rechazadas:** meterlo todo en el README: ya tiene 327 líneas (2026-11-25).
- **Impacto:** tareas 2.x.

### D5 · Deuda conocida, cada punto con dueño y decisión

- **Qué:** `docs/security/known-debt.md`, una entrada por punto con `Qué`, `Riesgo`, `Decisión` (aceptado, arreglar en un change nombrado, aplazado por proyecto educativo, pendiente de Wilson) y `Dueño`. Lista de partida:
  1. Nada ejecutado en Windows salvo recibos parciales (demos de los cortes 1–5 NOT RUN, tareas opcionales 5.3 de `mcp-gateway` y 7.6 de `skill-engine`). Decisión: aceptado (Windows no es puerta); dueño Wilson.
  2. Opciones de Playwright en Edge `--password-store=basic` y `--use-mock-keychain` (macOS): las cookies del perfil dedicado se cifran con una clave fija. Decisión: pendiente de Wilson (D3 de `copilot-web-provider`).
  3. Sandbox de Edge en Windows no comprobado. Decisión: pendiente de medir por Wilson.
  4. HMAC con clave local en lugar de SHA-256 sin sal para los argumentos MCP: hecho (`mcp-gateway` 6.11). Se lista como cerrado para que nadie lo reabra.
  5. La aprobación no prueba que haya una persona delante. Decisión: aceptada por Wilson el 2026-11-24 (opción 3 de `skill-engine`).
  6. `logs/mcp/*.stderr.log` guarda stderr de servidores sin redactar. Decisión: pendiente de Wilson (redactar al guardar o aceptar con `0600`).
  7. ACL de la lista local de MCP no comprobada en Windows. Decisión: aceptado y documentado.
  8. Un proceso que escapa del grupo o del Job Object (`setsid`) sobrevive. Decisión: aceptado y documentado.
  9. Medición sobre el vault real de Wilson NOT RUN (`project-memory`). Decisión: pendiente de Wilson.
  10. Filas de SQLite sin retención ni purga; copia y restauración de `HARNESS_DATA_DIR`. Decisión: aplazado (proyecto educativo, 2026-11-25).
- **Por qué:** cada límite ya está escrito en su design, pero disperso; una deuda sin dueño ni decisión no se cierra nunca.
- **Impacto:** tarea 3.1.

## Risks / Trade-offs

- [La matriz dice más de lo que prueban los tests citados] → cada fila cita su control negativo; la revisión independiente de este change lee la matriz contra los tests; la comprobación solo garantiza existencia (límite escrito en D2).
- [`pytest --collect-only` en `verify.sh` alarga la verificación] → una recogida tarda menos de 1 s (medido el 2026-11-25 en la Mac: 852 tests, `real 0.82` con `/usr/bin/time -p`).
- [Al archivar `skill-engine` o `mcp-gateway` cambian las rutas de sus specs] → la comprobación falla y obliga a actualizar la matriz en el mismo PR del archivo.
- [Un documento de seguridad en un repo público da pistas a un atacante] → solo describe controles y límites ya publicados en `SECURITY.md` y en los designs; ningún dato del entorno de Wilson.

## Migration Plan

Sin migración. Vuelta atrás: revertir el change y quitar la línea de `verify.sh`.

## Decisiones pendientes de Wilson (antes de implementar)

1. ¿Aceptas que la copia y restauración de `HARNESS_DATA_DIR`, la retención de SQLite y la rotación de logs queden aplazadas (proyecto educativo)? (Ya indicado por ti el 2026-11-25; se pide confirmar la lista.)
2. Deuda 2: ¿se quitan `--password-store=basic` y `--use-mock-keychain` (obliga a iniciar sesión de nuevo y puede pedir el llavero) o se aceptan?
3. Deuda 6: ¿se redacta el stderr de los servidores MCP antes de guardarlo o se acepta guardarlo crudo con `0600`?
4. Deuda 9: ¿harás la medición sobre el vault real o se cierra como no aplicable en un proyecto que solo usa prompts sintéticos?
