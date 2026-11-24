# ai-harness --- Plan maestro de implementación v0.4

## 0. Instrucciones para Claude Code

Actúa como ingeniero senior Python. Implementa por fases, no todo de una vez. Este documento es el contrato de trabajo. Inspecciona primero el repositorio existente, conserva cambios del usuario y presenta el plan de la fase activa antes de editar. Ejecuta pruebas y entrega evidencias reales; no declares verificadas integraciones que no puedas ejecutar. No hagas commits, pushes, instalaciones globales, cambios de seguridad ni accesos corporativos sin autorización. No uses Claude como proveedor del producto: Claude Code es únicamente la herramienta de desarrollo, en un entorno autorizado y con datos sintéticos. No envíes información corporativa a servicios no aprobados.

Comienza por F00 y F01. Si una validación corporativa está pendiente, continúa únicamente con mocks y fixtures sintéticos. Detente al cierre de cada fase para revisión humana. Mantén `docs/progress.md` con estado, pruebas, bloqueos y siguiente paso. Registra decisiones en `docs/adr/`. No introduzcas arquitectura hexagonal/onion ni frameworks innecesarios; aplica SOLID y DRY sin sobreingeniería.

## 1. Objetivo y alcance

Construir un copiloto de arquitectura funcional para Windows que pueda: - Ejecutarse con `uv run python main.py` (también `python main.py` dentro del entorno). - Usar Microsoft Copilot Web mediante Playwright y Edge, con una cuenta corporativa y múltiples conversaciones independientes y persistentes. - Consumir herramientas MCP y exponer capacidades propias mediante MCP. - Descubrir y ejecutar Skills reutilizables, deterministas, asistidos por IA o híbridos. - Reutilizar el diseño de segunda memoria de `claude-memory-system` con Markdown/Obsidian. - Consultar Enterprise Architect (Sparx) compartido y generar diagramas editables en un repositorio aislado. - Extenderse posteriormente a Computer Use mediante MCP.

Fuera del MVP: escritura en producción, agentes autónomos sin límites, interfaz gráfica propia, despliegue multiusuario, extracción de tokens, APIs privadas, sincronización de información corporativa a servicios personales.

## 2. Decisiones técnicas

  Tema           Decisión
  -------------- ----------------------------------------------------------
  Nombre         ai-harness
  Python         CPython 3.14.x, estándar (no free-threaded inicialmente)
  Dependencias   uv, pyproject.toml, uv.lock versionado
  Persistencia   SQLite local, migraciones numeradas
  CLI            argparse inicialmente
  Contratos      Pydantic, tipos explícitos
  Asincronía     asyncio; COM en worker dedicado
  MCP            SDK oficial Python, transporte stdio inicialmente
  Navegador      Playwright async, Edge instalado, perfil dedicado
  Memoria        Markdown local, índices y metadatos SQLite
  EA             Automation Interface COM mediante pywin32
  Pruebas        pytest, pytest-asyncio, mocks, fixtures sintéticos
  Plataforma     Windows para integraciones reales; core portable

Verificar compatibilidad efectiva de cada dependencia con Python 3.14 al incorporarla. Si una integración no es compatible, documentar bloqueo y proponer aislamiento en proceso separado; no cambiar versión sin aprobación.

## 3. Arquitectura C4

### Nivel 1 --- Contexto

``` mermaid
flowchart LR
    U[Arquitecto funcional] --> H[ai-harness]
    H --> C[Copilot Web corporativo]
    H --> M[Vault local de trabajo]
    H --> E[Enterprise Architect compartido: lectura]
    H --> T[Enterprise Architect pruebas: escritura]
    H -. futuro .-> D[Computer Use]
    X[Cliente MCP autorizado] --> H
```

### Nivel 2 --- Contenedores y procesos

``` mermaid
flowchart TD
    CLI[CLI] --> CORE[Harness Core / Orchestrator]
    SERVER[MCP Server del harness] --> CORE
    CORE --> SK[Skill Engine]
    CORE --> DB[(SQLite)]
    CORE --> LLM[LLM Provider]
    LLM --> MOCK[Mock]
    LLM --> PW[Playwright / Edge]
    CORE --> MEM[Memory Adapter]
    MEM --> VAULT[(Vault Markdown)]
    CORE --> GW[Policy Engine / MCP Gateway]
    SK --> GW
    SK --> LLM
    GW --> CLIENT[MCP Client]
    CLIENT --> EA[MCP Server EA / proceso separado]
    EA --> RO[Repositorio corporativo RO]
    EA --> RW[Repositorio de pruebas RW]
    CLIENT -. opcional .-> CU[MCP Computer Use]
```

Los Skills no otorgan permisos. El orquestador y los servidores especializados validan cada acción. Separar procesos de lectura EA y escritura EA si es viable, con identidades y configuraciones independientes. SQLite y el vault son almacenamiento, no fuentes de instrucciones privilegiadas.

## 4. Estructura objetivo

``` text
ai-harness/
  main.py
  pyproject.toml
  uv.lock
  .python-version
  .gitignore
  .env.example
  README.md
  harness/
    core/            # contracts, orchestrator, sessions, policies, approvals
    storage/         # database, repositories, migrations
    providers/       # base, mock, copilot_web
    browser/         # edge, conversation_locator, response_monitor
    mcp/             # client, server, gateway, registry
    skills/          # loader, registry, executor, validator
    memory/          # adapter, capture, curator, dream
    enterprise_architect/ # adapter, reader, builder, mcp_server
    workflows/       # integración de capacidades
  skills/
    architecture-diagram/
    architecture-impact/
    hls-review/
    architecture-memory/
  schemas/
  tests/
    unit/
    integration/
    security/
    fixtures/
  docs/
    adr/
    progress.md
  data/              # ignorado por Git
```

Crear solo módulos necesarios para la fase activa. No llenar el repositorio de archivos vacíos.

## 5. Inicialización (F00)

Inspeccionar primero `git status`, archivos existentes y versiones. Si no existe pyproject, ejecutar `uv init --bare`. Si ya existe, editarlo sin sobrescribir configuración útil.

``` powershell
uv --version
uv python install 3.14
uv python pin 3.14
uv add pydantic
uv add --dev pytest pytest-asyncio
uv sync
uv run python --version
```

Configurar `requires-python = ">=3.14,<3.15"`. Añadir `mcp`, `playwright`, `pywin32` solo en sus fases; para pywin32 usar marcador de plataforma Windows. No instalar navegadores adicionales si Edge autorizado está disponible. Si la instalación requiere permisos o acceso de red no aprobado, detener esa operación.

Excluir `.venv/`, `.env`, `data/`, perfiles de navegador, vaults, logs, bases SQLite y sus archivos WAL/SHM, cachés y archivos de conexión. Versionar `uv.lock`, ejemplos sin secretos y documentación.

Configuración propuesta: `HARNESS_DATA_DIR`, `HARNESS_PROVIDER=mock`, `HARNESS_VAULT_ROOT`, `HARNESS_PROFILE=work`, `HARNESS_EDGE_PROFILE`, `HARNESS_COPILOT_URL`, `HARNESS_MCP_CONFIG`, `EA_READ_TARGET_ID`, `EA_TEST_TARGET_ID`. No guardar contraseñas en `.env.example` ni pasar secretos como argumentos CLI.

## 6. Contratos y persistencia (F01)

Definir modelos tipados: - Session: UUID, nombre, proyecto opcional, provider, remote_ref opcional, estado, fechas UTC. - LLMRequest: request_id, session_id, prompt, timeout, contexto autorizado. - LLMResponse: request_id, session_id, text, status, duration_ms. - ToolProposal: tool_name, arguments, request_id; no equivale a autorización. - ToolResult: status, data, error_code, audit_id. - Approval: identidad local, alcance, hash de propuesta, expiración, estado. - SkillRun: skill_id, versión, session_id, estado, pasos.

Estados de solicitud: pending, running, completed, failed, timeout, authentication_required, uncertain. Estados de sesión: created, active, authentication_required, uncertain, closed. Estados de ejecución de Skill: pending, running, awaiting_approval, completed, failed, uncertain, cancelled.

Esquema inicial (migración 001; añadir tablas posteriores en su fase):

  ------------------------------------------------------------------------------------------------------------------------------------
  Tabla                               Campos mínimos
  ----------------------------------- ------------------------------------------------------------------------------------------------
  sessions                            session_id PK, name, project_id, provider, remote_ref nullable, status, created_at, updated_at

  requests                            request_id PK, session_id FK, status, started_at, finished_at

  messages                            message_id PK, session_id FK, request_id FK, role, content nullable, status, created_at

  tool_calls                          call_id PK, request_id FK, tool_name, decision, status, created_at

  audit_events                        event_id PK, request_id nullable, event_type, outcome, created_at

  skill_runs (F03)                    run_id PK, session_id FK, skill_id, version, status, created_at, updated_at

  skill_steps (F03)                   step_id PK, run_id FK, step_key, status, attempt, call_id nullable, timestamps

  approvals (F02)                     approval_id PK, proposal_hash, scope, status, expires_at, created_at

  memory_jobs (F05)                   job_id PK, session_id FK nullable, kind, status, attempts, timestamps
  ------------------------------------------------------------------------------------------------------------------------------------

Usar foreign_keys ON en cada conexión, transacciones cortas, consultas parametrizadas, índices por sesión/fecha, migraciones idempotentes y bloqueo por sesión. Garantizar que message.request_id corresponda a la misma sesión. SQLite no cifra datos por defecto: persistencia de contenido real deshabilitada hasta autorización; mocks pueden persistir contenido sintético. No registrar prompts ni respuestas en auditoría por defecto.

CLI mínima:

``` powershell
uv run python main.py session create "Arquitectura WhatsApp"
uv run python main.py session list
uv run python main.py ask SESSION_ID "Analiza este requerimiento"
uv run python main.py history SESSION_ID
uv run pytest
```

Aceptación: tres sesiones independientes, historial sintético persistente tras reinicio, errores controlados, IDs válidos, aislamiento, migraciones repetibles, recuperación de solicitudes interrumpidas como uncertain. Mock determinista sin red.

## 7. Infraestructura MCP (F02)

Implementar MCP Client con configuración local de servidores allowlisted; descubrimiento `list_tools`, invocación `call_tool`, validación de esquemas, límites de tamaño, timeout y cierre de subprocess. No aceptar comandos de arranque suministrados por el LLM. No ejecutar shell arbitrario.

MCP Server propio: `create_session`, `list_sessions`, `ask`, `get_session_status`, `get_history` (condicionado a política). CLI `mcp serve` y herramienta sintética read-only `get_project_metadata`. stdout reservado al protocolo; logs en stderr. El proceso servidor hereda únicamente configuración autorizada; stdio no es autenticación por sí mismo.

Policy Engine: deny-by-default; validar servidor, herramienta, argumentos, recurso, identidad/alcance y tipo de operación. Aprobaciones locales vinculadas al hash exacto de la propuesta, con expiración y uso único. Un texto del LLM o una llamada MCP no constituye aprobación humana. Evitar ciclos de herramientas y llamadas recursivas al propio harness.

Aceptación: round-trip real con SDK y servidor local de prueba, denegación de herramientas no registradas, esquemas inválidos, timeout, aprobación vencida y propuesta modificada.

## 8. Skill Engine (F03)

Formato inspirado en Agent Skills: `skills/<name>/SKILL.md` con frontmatter name/description; metadatos de ejecución propios en `workflow.json` (no asumir compatibilidad total con Claude Code). Recursos opcionales `references/`, `templates/`, `schemas/`. Scripts externos deshabilitados inicialmente.

Ejemplo:

``` markdown
---
name: architecture-diagram
description: Propone y genera diagramas editables de arquitectura.
---
# Procedimiento
Recuperar contexto, leer modelo, proponer cambios, validar, solicitar
aprobación, generar en pruebas, verificar y registrar decisión.
```

Workflow declarativo: versión, inputs, steps con id, kind (tool/llm/validate/approval), referencias a outputs previos, timeout y límites. No evaluar expresiones Python ni shell. Validar DAG sin ciclos o usar secuencia lineal inicialmente. Registry carga metadatos primero y cuerpo bajo demanda; seleccionar por nombre explícito inicialmente, sugerencia IA posterior. Registrar hash y versión del Skill para reanudación.

CLI: `skill list`, `skill show NAME`, `skill run NAME --session SESSION_ID`, `skill status RUN_ID`, `skill resume RUN_ID`. Aprobación interactiva fuera del modelo. No reintentar escrituras inciertas; reconciliar antes de reanudar.

Aceptación: Skill determinista con MCP mock, ejecución híbrida con Mock LLM, persistencia de pasos, fallo controlado, aprobación y recuperación. Rechazar path traversal, symlinks fuera de raíz y herramientas no autorizadas.

## 9. Copilot Web (F04)

Prerequisito: autorización explícita para automatizar la interfaz corporativa y transferirle los datos previstos. Usar Edge persistent context dedicado, no perfil personal ni perfil de trabajo habitual. Login/MFA manual. No extraer cookies, tokens, endpoints privados ni evadir restricciones. Si no hay autorización, mantener Mock y marcar integración bloqueada.

Implementar `LLMProvider` con métodos create_session/ask/recover/close. Playwright async con `channel="msedge"`, navegador visible inicialmente. Descubrir selectores accesibles en UI real; no inventar selectores ni asumir estabilidad de URLs. Una cuenta, múltiples conversaciones, mapeo local a referencia remota verificada. Serializar operaciones del navegador en MVP. Detectar respuesta nueva y finalización mediante señales observadas, no solo sleep. Timeout después de envío =\> uncertain; no reenviar automáticamente. Detectar login vencido y solicitar intervención.

Copilot Web no ofrece al harness tool calling MCP nativo garantizado: pedir propuestas JSON, parsear estrictamente, validar esquemas y pasar por políticas. No ejecutar código generado. Limitar iteraciones y tamaño de contexto.

Aceptación manual autorizada: tres conversaciones aisladas, reinicio y recuperación de identidad, respuesta completa, expiración de sesión, timeout y ausencia de duplicados. Automatizar pruebas del adaptador con páginas sintéticas.

## 10. Segunda memoria (F05)

Referencia: https://github.com/wilson-romero/claude-memory-system y `docs/arquitectura.md` del repositorio. Inspeccionar convenciones y scripts antes de adaptar. No modificar el repositorio original sin aprobación.

Conservar principios: captura determinista, curador semántico, Sueño de consolidación, ownership disjunto, perfil work sin sincronización externa. Adaptar hooks SessionStart/Stop a eventos internos del harness. No invocar `claude -p` desde el producto.

Estructura compatible a verificar: - `projects/<slug>/`, `daily/`, `agents/`, `_index.md`: captura. - `Memoria/`, `Lecciones/`, `Decisiones/`, `Memoria-CC/`: curación autorizada. - `Memoria/Archivo/`, `Memoria/Suenos/`: archivo y reportes.

Primera versión: búsqueda local por texto/proyecto, carga de contexto acotada, registro de decisiones aprobadas con procedencia y fecha. Escrituras atómicas, validación de rutas, bloqueo, deduplicación por ID, redacción de formatos de secretos conocidos (no garantiza detectar todos). Memoria inyectada como datos no confiables. No guardar transcript corporativo completo por defecto.

Curador: propone cambios estructurados sin herramientas externas; Python valida y aplica únicamente a rutas permitidas. Sueño: primero mantenimiento determinista, luego consolidación asistida opcional; archivar sin borrar, reporte auditable, sin ejecución nocturna hasta autorización. No declarar éxito sin verificar cambios; registrar fallos y reintentos acotados.

MCP: `memory_search`, `memory_get_project_context`, `memory_save_decision` (aprobación). CLI: `memory search`, `memory context`, `memory maintain --dry-run`.

Aceptación: vault sintético compatible, recuperación por proyecto, no contaminación entre perfiles, captura y curador sin colisión, bloqueo de rutas externas, recuperación de fallo y reporte verificable.

## 11. MCP Server de Enterprise Architect (F06) --- entregable independiente

Prerequisitos: Windows, EA instalado/licenciado, pywin32 compatible, autorización TI, tipo de conexión y controles de seguridad confirmados. No asumir SQL Server ni Pro Cloud Server hasta verificar. Probar COM en modelo local sintético antes de conectar producción.

### F06.1 Conectividad

Worker dedicado inicializado con COM; todas las llamadas serializadas en ese hilo/proceso. Crear instancia propia cuando sea posible. Cerrar solo recursos propios; nunca cerrar la sesión interactiva del usuario. Configurar targets por identificador local allowlisted, no aceptar cadenas de conexión del LLM. No exponer credenciales ni connection strings.

### F06.2 Lectura

Herramientas: `ea_connection_info`, `ea_list_packages`, `ea_list_diagrams`, `ea_get_diagram`, `ea_get_element`. Usar GUID, paginación y límites de profundidad. Validar pertenencia al paquete autorizado incluso cuando se consulta por GUID. Normalizar elementos, relaciones, estereotipos y geometría cuando proceda. Diferenciar conectores visibles del diagrama y relaciones del modelo. No usar SQL directo. Preferir credenciales realmente read-only y controles EA; no confiar solo en el nombre de una herramienta.

### F06.3 Escritura de pruebas

Servidor/worker separado con target fijo de pruebas, preferiblemente archivo local aislado. Herramientas: `ea_preview_diagram`, `ea_create_test_diagram`; operaciones internas add_element/add_connector no expuestas inicialmente. Usar Automation Interface documentada (colecciones AddNew/Update, DiagramObjects, conectores), comprobar retornos y errores, verificar persistencia releyendo el modelo. No asumir transacciones COM globales: usar copia de trabajo, registro de cambios y reconciliación ante fallo parcial. No borrar ni editar producción.

Contrato de propuesta:

``` json
{
  "name": "WhatsApp - ampliacion ventas",
  "type": "Component",
  "elements": [
    {"id":"channel","name":"WhatsApp","type":"Component"},
    {"id":"router","name":"Orquestador","type":"Component"},
    {"id":"general","name":"Agente general","type":"Component"},
    {"id":"sales","name":"Agente ventas","type":"Component"}
  ],
  "connectors": [
    {"source":"channel","target":"router","type":"Dependency"},
    {"source":"router","target":"general","type":"Dependency"},
    {"source":"router","target":"sales","type":"Dependency"}
  ]
}
```

IDs locales se mapean a GUID creados. Validar unicidad, referencias, tipos permitidos, tamaño, destino y hash de aprobación. Layout inicial determinista, editable manualmente. Resultado: diagram_guid, package_guid, mapping, verification_status y audit_id. Idempotencia mediante identificador de operación y reconciliación; no repetir creación incierta.

### F06.4 Aceptación

Leer diagrama corporativo autorizado y comparar con UI sin cambios; crear cuatro componentes y tres relaciones en pruebas, abrir el diagrama y verificarlo. Denegar escrituras al target productivo, GUID fuera de alcance, destino manipulado, aprobación ausente y errores COM. Las pruebas reales requieren Windows/EA; mocks no sustituyen esta aceptación.

## 12. Skills de arquitectura integrados (F07)

  ----------------------------------------------------------------------------------------------------------------------------------------------------------
  Skill                   Flujo                                                                                           Salida
  ----------------------- ----------------------------------------------------------------------------------------------- ----------------------------------
  architecture-diagram    contexto → lectura EA → propuesta → validación → aprobación → escritura prueba → verificación   Diagrama editable y trazabilidad

  architecture-impact     leer modelo → comparar propuesta → identificar dependencias y riesgos                           Informe de impacto

  hls-review              recuperar contexto → revisar alternativas, restricciones y NFR → preguntas pendientes           Revisión HLS

  architecture-memory     extraer decisión → revisión humana → persistir                                                  Nota de decisión
  ----------------------------------------------------------------------------------------------------------------------------------------------------------

No inventar hechos del modelo; distinguir evidencia, supuesto y propuesta. Mantener convenciones corporativas de diagramación; C4 se usa para documentar el harness, no se impone a los modelos de la empresa. MVP: flujo completo de architecture-diagram con datos sintéticos y luego entorno autorizado. Guardar referencias a GUID, versión de Skill, fuentes y aprobación; no guardar datos sensibles innecesarios.

## 13. Computer Use MCP (F08, opcional)

Evaluar servidor aprobado existente antes de construir uno. Herramientas iniciales `list_windows`, `observe`; después click/type supervisados, preferir Windows UI Automation y accesibilidad a coordenadas. Allowlist de ventanas, límites de pasos, stop manual, timeout, verificación de estado. No capturar escritorio completo ni pantallas sensibles por defecto. No enviar screenshots a Copilot sin autorización y capacidad comprobada. No operar credenciales, MFA ni acciones irreversibles. Piloto sobre aplicación sintética. No es dependencia del MVP.

## 14. Seguridad y pruebas integrales (F09)

  ----------------------------------------------------------------------------------------------------------
  ID                      Prueba                                          Resultado
  ----------------------- ----------------------------------------------- ----------------------------------
  SEC-01                  Credenciales en logs/vault                      Redacción o bloqueo

  SEC-02                  Cruce de sesiones/proyectos                     Denegado

  SEC-03                  Prompt injection en memoria, EA o tool result   No altera políticas

  SEC-04                  Traversal/symlink                               Denegado

  SEC-05                  MCP desconocido o argumentos inválidos          Denegado

  SEC-06                  MFA/login expirado                              Intervención humana

  SEC-07                  Timeout tras envío/escritura                    uncertain, sin duplicación

  SEC-08                  Reinicio                                        Recuperación verificada

  SEC-09                  Cliente no autorizado                           Sin acceso

  SEC-10                  Crash navegador/COM                             Recursos propios liberados

  SEC-11                  Escritura EA productiva                         Denegada en capas independientes

  SEC-12                  Aprobación reutilizada o propuesta alterada     Denegada

  SEC-13                  Vault work intenta sincronizar                  Denegado

  SEC-14                  Skill malicioso o script arbitrario             Denegado

  SEC-15                  Límite de pasos/tamaño/timeout                  Ejecución detenida
  ----------------------------------------------------------------------------------------------------------

Pruebas unitarias sin red; integración local con MCP real y mocks; pruebas manuales autorizadas separadas. Usar marcadores pytest para Windows, EA y Copilot. No ocultar skips. Documentar backup/restauración, diagnóstico, límites, instalación con uv y runbook. Ejecutar `uv run pytest` y `uv lock --check` antes de cada cierre cuando el entorno lo permita.

## 15. Roadmap, dependencias y entregables

Estimaciones de esfuerzo en días-persona, no calendario ni compromiso. Una persona con apoyo IA; accesos corporativos pueden añadir esperas.

  Fase     Esfuerzo Depende de             Entregable
  ------ ---------- ---------------------- -----------------------------------
  F00          1--2 ---                    Entorno, permisos y configuración
  F01          3--4 F00 local              Core, SQLite, CLI, Mock
  F02          3--4 F01                    MCP Client/Server y políticas
  F03          3--5 F02                    Skill Engine
  F04          4--6 F02, autorización      Copilot Web
  F05          4--6 F02                    Segunda memoria
  F06          5--8 F02, Windows/EA        MCP EA independiente
  F07          4--6 F03--F06               Skills integrados; MVP
  F08          4--7 F02, autorización      Computer Use opcional
  F09          3--5 F07; F08 si incluido   Pruebas integrales y runbook

Total sin F08: 30--46 días-persona; con F08: 34--53. F04--F06 pueden avanzar en paralelo si hay recursos. Seguridad y pruebas son transversales, no se posponen hasta F09.

## 16. Definition of Done por fase

Código ejecutable, contratos documentados, pruebas relevantes pasando, errores controlados, ningún secreto versionado, evidencias y bloqueos explícitos, README actualizado, aprobación humana para avanzar. No marcar una fase real completa si solo pasó con mocks. MVP final: requerimiento → memoria → lectura EA → propuesta Copilot → aprobación → diagrama editable en pruebas → verificación → decisión registrada.

## 17. Primera orden de ejecución para Claude Code

1.  Inspecciona el estado actual del repositorio y confirma Python/uv.
2.  Presenta plan concreto F00/F01, archivos a crear o modificar y pruebas.
3.  Tras aprobación, implementa CLI, contratos, migración SQLite, repositorios, Session Manager, Mock Provider y Policy Engine básico.
4.  Prueba creación de tres sesiones, persistencia, aislamiento, errores y recuperación.
5.  Ejecuta `uv run pytest` y reporta resultados reales.
6.  Actualiza `docs/progress.md` y detente antes de F02.

Pendientes que no bloquean el core: autorización de Copilot Web, versión y tipo de conexión EA, credenciales read-only, repositorio de pruebas, política de retención corporativa, compatibilidad real de dependencias 3.14. No solicitar secretos. No implementar integraciones reales hasta resolver sus propios requisitos.
