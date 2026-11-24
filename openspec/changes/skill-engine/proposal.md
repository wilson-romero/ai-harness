# Proposal

## Why

Hoy el harness no sabe encadenar pasos ni pedir una aprobación: `uv run python main.py --help` lista 4 comandos (`session`, `ask`, `history`, `memory`), `grep -rni "skill\|approv" harness/` devuelve 0 líneas, no existe la carpeta `skills/` y `openspec/specs/` no tiene ninguna capacidad (medido el 2026-11-24 sobre `032e989`, la punta de `feature/project-memory`, con 258 tests en verde). Cada trabajo de arquitectura del plan (revisar un HLS, registrar una decisión, más adelante generar un diagrama) es una secuencia fija de preguntas, comprobaciones y una aprobación humana; sin un motor que la ejecute, la persista y la reanude, cada Skill tendría que reinventar el estado `uncertain`, los límites y, sobre todo, la aprobación. Y la primera escritura del harness (la nota de decisión, change `architecture-skills-llm`) no puede existir sin una aprobación ligada al contenido exacto.

Corte **4 · Skills sin herramientas** de `docs/plan/2026-11-24-ai-harness-cortes.md`, primera de sus dos partes. Riesgo **N1**. Cubre **SEC-12** (aprobación reutilizada o propuesta alterada → denegada), **SEC-14** (Skill malicioso o script arbitrario → denegado) y **SEC-15** (límite de pasos, tamaño o tiempo → ejecución detenida). Se demuestra en **macOS**; el diseño usa un único camino de código para macOS y Windows (`pathlib`, `os.replace`, SQLite) y una ejecución en Windows es confirmación opcional, no puerta del corte.

**El repositorio es público.** Los Skills de prueba, las respuestas guionizadas del Mock y cualquier ejemplo son sintéticos y genéricos; nada identifica a una empresa, un cliente o un sistema.

## What Changes

- Formato de Skill en disco: `skills/<nombre>/SKILL.md` (frontmatter `name`, `description`) y `workflow.json` declarativo, con plantillas en `templates/`. Validación estricta: nombre, ficheros permitidos, enlaces, tamaños, tipos de paso y referencias (SEC-14). Hash y versión del Skill.
- Pasos de tipo `llm`, `validate` y `approval`, en secuencia lineal. Las referencias a entradas y salidas anteriores son sustituciones literales de una forma cerrada (`{{inputs.X}}`, `{{steps.Y.output}}`, `{{steps.Y.fields.Z}}`), sin evaluar expresiones.
- `validate` comprueba de forma determinista: tamaño, encabezados Markdown obligatorios, y JSON estricto con campos tipados y acotados.
- CLI: `skill list`, `skill show NAME`, `skill run NAME --session ID`, `skill status RUN_ID`, `skill resume RUN_ID`, `skill cancel RUN_ID`.
- Persistencia en SQLite (migración `003_skills.sql`): `skill_runs`, `skill_steps`, `approvals`. El contenido de entradas nunca se guarda; el de salidas solo si el proveedor es sintético (regla D5 de `session-core`).
- Aprobación humana fuera del modelo: ligada al hash de una serialización canónica de la propuesta, con caducidad y uso único, concedida solo desde una terminal interactiva. Una ejecución no interactiva se detiene en `awaiting_approval`.
- Relación con sesiones: cada ejecución pertenece a una sesión, usa su proveedor, toma su bloqueo y registra sus preguntas en el historial. Un paso `llm` incierto nunca se repite solo: se reconcilia con una decisión explícita.
- Límites (SEC-15) de pasos, ficheros, entradas, prompts, respuestas y tiempo, con parada controlada.
- Mock con respuestas guionizadas por fichero local, para poder probar Skills de punta a punta sin red.
- Efectos tras una aprobación: lista cerrada en código. Este change solo trae `none` (la aprobación deja continuar); `architecture-skills-llm` añade el primer efecto con escritura.

**No entra**, aunque un lector lo asumiría:

- Pasos `tool`, MCP en cualquier sentido, Enterprise Architect, Policy Engine de herramientas (cortes 5–7).
- Los Skills de producto `hls-review` y `architecture-memory` y cualquier escritura en el vault: van en `architecture-skills-llm`, que depende de este change.
- `architecture-diagram` y `architecture-impact` (cortes 6–7).
- Scripts externos, código Python o shell dentro de un Skill, motores de plantillas, expresiones condicionales, bucles, DAG o ramas: solo secuencia lineal.
- Sugerencia de Skill por IA: se elige por nombre explícito.
- Aprobación desde un fichero, una variable de entorno, un argumento de la CLI o un texto del modelo; aprobaciones de varias personas o autenticación de la identidad local.
- Persistir contenido real: entradas nunca; salidas solo con proveedor sintético. Política de retención o borrado de ejecuciones antiguas.
- Validar que un modelo real (Copilot, Corte 2, aún sin mergear) produzca salidas que pasen `validate`: con el Mock no se puede medir.

## Capabilities

### New Capabilities

- `skill-definition`: formato de un Skill en disco, su validación y rechazo de Skills maliciosos (SEC-14), hash y versión, `skill list` y `skill show`.
- `skill-execution`: ejecución lineal de pasos `llm`/`validate`/`approval`, referencias sin evaluación, persistencia, relación con la sesión y su bloqueo, estado `uncertain` y reconciliación, `skill run/status/resume/cancel`, límites (SEC-15) y respuestas guionizadas del Mock.
- `human-approval`: propuesta canónica y su hash, caducidad, uso único, concesión solo humana desde terminal interactiva, rechazo de aprobaciones reutilizadas o propuestas alteradas (SEC-12) y lista cerrada de efectos.

### Modified Capabilities

Ninguna. **Revisado el 2026-11-24:** al redactar, `openspec/specs/` estaba vacío; con `session-core` y `project-memory` archivados en `develop` (`f7c590a`), `openspec list --specs` muestra 8 capacidades (`llm-provider`, `memory-maintenance`, `memory-search`, `memory-vault`, `project-context`, `request-recovery`, `secret-redaction`, `session-management`) y ninguna habla de Skills ni de aprobaciones; este change sigue sin cambiar ningún requisito suyo.

**Dependencias con capacidades ya archivadas.** `session-management`, `llm-provider` y `request-recovery` (de `session-core`) y `project-context` y `secret-redaction` (de `project-memory`) están en `openspec/specs/` (revisado el 2026-11-24; antes vivían en `openspec/changes/`). Lo que este change añade a su conducta se escribe como requisitos ADDED de las capacidades nuevas, sin reescribir ninguno de los suyos:

- Las preguntas de un paso `llm` usan la misma conducta de `ask` (`timeout` antes del envío, `uncertain` después, sin reenvío) y el mismo bloqueo por sesión; `skill-execution` añade que del texto enviado se guarda solo una marca del paso, nunca el prompt compuesto.
- Las respuestas guionizadas del Mock amplían el Mock de `llm-provider`; se escriben en `skill-execution` y, al archivar, se decidirá si se mueven a `llm-provider` con un change propio (el mismo criterio que usó `project-memory`).
- Orden de archivo: este change y después `architecture-skills-llm` (`session-core` y `project-memory` ya están archivados).

## Impact

- Código nuevo: `harness/skills/` (formato y validación, sustitución de referencias, comprobaciones de `validate`, aprobaciones, efectos, motor de ejecución) y el subcomando `skill` en `harness/cli.py`.
- Código modificado: `harness/core/service.py` expone la pregunta con el bloqueo ya tomado y con el texto a guardar aparte (sin cambiar la conducta de `ask`); `harness/storage/locks.py` generaliza el bloqueo por sesión a un bloqueo con nombre; `harness/providers/mock.py` lee respuestas guionizadas.
- Almacenamiento: migración `harness/storage/migrations/003_skills.sql` (la 003 está libre: `copilot-web-provider` declara que no añade migración).
- Dependencias: ninguna nueva. Biblioteca estándar (`json`, `hashlib`, `re`, `getpass`, `sys`, `os`, `pathlib`) y `pydantic`.
- Configuración: `HARNESS_SKILLS_DIR`, `HARNESS_APPROVAL_TTL_S`, `HARNESS_MOCK_RESPONSES` (en `.env.example` y en `scripts/demo_common.py`).
- Fixtures: Skills sintéticos válidos e inválidos en `tests/fixtures/skills/` y respuestas guionizadas en `tests/fixtures/mock-responses/`.
- Documentación: `README.md` (comandos `skill`, formato, aprobación, estados, límites, qué se guarda) y `SECURITY.md` (qué garantiza y qué no la aprobación local).
- `architecture-skills-llm` consume el motor, la aprobación y el registro de efectos.
