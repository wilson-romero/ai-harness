# Proposal

## Why

Hoy `ask` envía al proveedor solo el texto que escribe el usuario: el harness tiene 0 comandos que lean la segunda memoria y 0 líneas de código que toquen un vault (medido el 2026-11-24 con `uv run python main.py --help`, que lista `session`, `ask` e `history`, y `grep -rn -i vault harness/` sin resultados, sobre `0c14f33`). El Norte del plan necesita que el harness «recupere el contexto del proyecto en la memoria» antes de pedir una propuesta; sin eso, cada pregunta a Copilot (Corte 2) empieza de cero y el Corte 7 no tiene de dónde sacar el contexto.

Corte **3 · Memoria** de `docs/plan/2026-11-24-ai-harness-cortes.md`. Riesgo **N1**. Cubre **SEC-01** (credenciales en lo que sale del vault), **SEC-03** (instrucciones dentro de una nota), **SEC-04** (traversal y enlaces simbólicos) y **SEC-13**, solo en este sentido: el harness no tiene ningún camino de código que copie, suba o sincronice el vault, y nunca escribe en él (revisado el 2026-11-24: ya no rechaza vaults ni directorios de datos en carpetas sincronizadas; ver design D3). Se demuestra en **macOS**; el diseño usa un único camino de código para macOS y Windows (sin ramas por plataforma) y una ejecución en Windows es confirmación opcional, no una puerta del corte.

**El repositorio es público en GitHub.** Ninguna nota real, ruta de vault, ruta personal, correo, host, nombre de empresa, cliente o sistema, ni ningún secreto entra en el repo. El vault de pruebas es 100 % sintético y los secretos de ejemplo de las pruebas de SEC-01 se ensamblan en tiempo de ejecución, nunca se escriben literales en un fichero versionado.

## What Changes

- Configuración del vault: raíz (`HARNESS_VAULT_ROOT`) y límite del contexto (`HARNESS_MEMORY_CONTEXT_MAX_BYTES`). Revisado el 2026-11-24 por decisión de Wilson (el harness se usa solo para trabajo y el vault tiene que poder vivir en el OneDrive corporativo): no hay perfiles, el directorio de datos no se liga a ningún vault y no se rechaza ninguna ubicación sincronizada, de red o dentro de un repositorio git (design D1–D3).
- Lectura del vault confinada a su raíz: rutas validadas, enlaces simbólicos y uniones ignorados, carpetas de configuración, temporales y de archivo excluidas.
- `memory search QUERY [--project SLUG]`: búsqueda local por texto, con fragmentos redactados.
- `memory context SLUG`: imprime exactamente el bloque de contexto acotado que se enviaría para ese proyecto.
- `ask SESSION_ID PROMPT --project SLUG`: antepone ese bloque, marcado como datos no confiables, a la pregunta. El bloque nunca se guarda en SQLite; se guarda su procedencia (qué notas, con qué hash).
- `memory maintain --dry-run`: informe determinista del estado del vault (conflictos de sync, enlaces rotos, índice, frontmatter, secretos detectados, entradas ignoradas) sin escribir nada.
- Redacción de formatos de credenciales conocidos en todo lo que sale del vault hacia la terminal o el proveedor.
- Vault sintético en `tests/fixtures/` con la estructura medida de `claude-memory-system`.

**No entra**, aunque el plan maestro lo nombre en F05:

- Guardar decisiones (`memory_save_decision`) ni ninguna otra escritura en el vault: este corte solo lee el vault. Guardar una decisión exige aprobación, que llega en el Corte 4 (ver design D9).
- Curador asistido, Sueño y cualquier mantenimiento que modifique el vault (Corte 8). `memory maintain` sin `--dry-run` no existe.
- Herramientas MCP `memory_search`, `memory_get_project_context`, `memory_save_decision` (MCP llega en el Corte 5).
- Aprobaciones por hash (Corte 4) y la tabla `memory_jobs` (sin consumidor en este corte).
- Índice de búsqueda en SQLite, búsqueda semántica o por embeddings.
- Inyectar memoria sin pedirla: `ask` sin `--project` se comporta exactamente como en el Corte 1.
- Sincronizar el vault, o detectar o impedir que otro programa lo sincronice (design D3, revisada). Tampoco perfiles `work`/`personal` ni ligadura del directorio de datos (retirados el 2026-11-24).

## Capabilities

### New Capabilities

- `memory-vault`: configuración de la raíz, garantía de que el harness no copia, sincroniza ni modifica el vault, confinamiento de la lectura a la raíz y qué entradas del vault se leen.
- `memory-search`: búsqueda local por texto sobre el vault, con filtro por proyecto, límites y salida segura para la terminal.
- `project-context`: selección, orden y límite del contexto de un proyecto; `memory context`; `ask --project` con el contexto marcado como datos no confiables; procedencia sin contenido.
- `memory-maintenance`: informe determinista de `memory maintain --dry-run` sin modificar el vault.
- `secret-redaction`: enmascarado de formatos de credenciales conocidos en todo texto que sale del vault, y su límite declarado.

### Modified Capabilities

Ninguna. `openspec list --specs` devuelve «No specs found» y `ls openspec/specs` solo muestra `.gitkeep` (comprobado el 2026-11-24); `grep -rn -i "memor\|project\|proyecto" openspec/specs` no devuelve nada.

**Dependencia declarada con `session-core`.** `ask --project` amplía la conducta de `ask` (capacidad `llm-provider`) y usa el proyecto de la sesión (capacidad `session-management`). Esas dos capacidades viven todavía en `openspec/changes/session-core/specs/` y no están archivadas, así que no existe en `openspec/specs/` una spec contra la que escribir un delta MODIFIED. Por eso la conducta nueva se escribe como requisitos ADDED de `project-context`, que no reescriben ninguno de `session-core`: `ask` sin `--project` queda exactamente como lo define `session-core`, y el requisito «El contenido solo se guarda si es sintético» sigue vigente; `project-context` añade que el bloque de memoria nunca se guarda, ni siquiera con un proveedor sintético. Orden de archivo: `session-core` antes que `project-memory`. Si al archivar se decide que estos requisitos pertenecen a `llm-provider`, se moverán con un change propio.

## Impact

- Código nuevo: `harness/memory/` (configuración, rutas, lectura del vault, frontmatter, búsqueda, contexto, mantenimiento, redacción); subcomando `memory` y opción `--project` de `ask` en `harness/cli.py`; `SessionService.ask` recibe el contexto aparte de la pregunta.
- Almacenamiento: migración nueva con `request_context` en `harness/storage/migrations/002_memory.sql` (la reimplementación del bloqueo de sesión sobre SQLite se hizo sin migración, así que la 002 quedó libre).
- Dependencias: ninguna nueva. Biblioteca estándar (`pathlib`, `os`, `re`, `difflib`, `hashlib`, `secrets`) y `pydantic`.
- Configuración: `HARNESS_VAULT_ROOT` y `HARNESS_MEMORY_CONTEXT_MAX_BYTES` (en `.env.example`); `HARNESS_PROFILE` sale de `.env.example` y el harness la ignora.
- Fixtures: `tests/fixtures/vault-synthetic/`, sin secretos literales.
- Documentación: `README.md` (comandos `memory`, `ask --project`, qué se lee y qué no, qué se garantiza sobre la sincronización, límites de la redacción).
- Los cortes 4 (`architecture-memory`, guardar decisión con aprobación), 5 (herramientas MCP de memoria) y 7 (`architecture-diagram`) consumen la selección de contexto y el confinamiento de rutas que fija este change.
