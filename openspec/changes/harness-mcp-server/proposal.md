# Proposal

## Why

Hoy el harness solo se puede usar desde su propia línea de órdenes: es cliente MCP (`mcp list|tools|call`, de `mcp-gateway`) pero no servidor. Medido el 2026-11-25 sobre `develop` (`86f1079`): `uv run python main.py mcp --help` ofrece `list`, `tools` y `call`, ninguno sirve; `grep -rn "MCPServer\|stdio_server\|mcp\.server" harness/ | wc -l` → 0; y `grep -rn -i -E "mcp|cliente no autorizado" openspec/specs/` → 0 requisitos. El plan maestro (§7) pide un servidor MCP propio con `create_session`, `list_sessions`, `ask`, `get_session_status` y `get_history`, y §10 las herramientas de memoria `memory_search`, `memory_get_project_context` y `memory_save_decision`. Sin servidor, otro programa local que hable MCP no puede preguntar en una sesión del harness ni leer el contexto de un proyecto, y **SEC-09** («cliente no autorizado → sin acceso») no tiene ninguna superficie sobre la que probarse: `mcp-gateway` lo dejó escrito así (su D9).

Corte **8 · Cierre** de `docs/plan/2026-11-24-ai-harness-cortes.md`, adelantado por la revisión del 2026-11-25: ya no espera a EA y va en paralelo a la Puerta MVP sin EA. Riesgo **N2**: abre la primera superficie de entrada del harness y, con el proveedor real, deja que otro proceso maneje la sesión de Copilot iniciada por Wilson. Cubre **SEC-09** (con el sentido exacto que tiene sobre stdio, design D3), **SEC-02** (un cliente no ve sesiones que no son de su ámbito), **SEC-05** (herramienta o argumentos no permitidos), **SEC-07** (un cliente que reintenta nunca provoca un segundo envío), **SEC-10** (el trabajo largo vive en un proceso que se mata, nada propio queda vivo), **SEC-01** y **SEC-03** (lo que sale hacia el cliente va redactado y marcado como datos) y **SEC-15** (tamaños y plazos). Se demuestra en **macOS** con el Mock; un único camino de código para macOS y Windows; Windows es confirmación opcional. Las tareas que preguntan a Copilot real quedan **BLOCKED** hasta que `copilot-web-provider` esté mergeado y Wilson confirme el alcance de su autorización.

**El repositorio es público.** Los clientes de prueba, las sesiones, los prompts y las respuestas de los tests son sintéticos. El fragmento de configuración de cliente del README usa rutas de ejemplo.

## What Changes

- Comando nuevo **`mcp serve`**: el harness sirve MCP por stdio al proceso que lo lanza. Sin puertos ni sockets de escucha, nunca.
- **Herramientas expuestas en la primera versión**, elegidas por lanzamiento con una lista explícita (`--tools`), de solo lectura por defecto:
  - lectura: `list_sessions`, `get_session_status`, `get_history`, `memory_search`, `memory_get_project_context`;
  - envío, solo si se nombran en `--tools`: `create_session` y `ask`.
  - **No** existen `memory_save_decision` ni ninguna herramienta que escriba fuera de SQLite (design D2).
- **Ámbito por lanzamiento** (`--scope NOMBRE`): las sesiones que crea un cliente MCP quedan marcadas con ese ámbito, y el servidor solo lista, lee y pregunta en sesiones de su ámbito. Las sesiones creadas desde la CLI no son visibles por MCP. Las herramientas de memoria solo existen si el lanzamiento fija un proyecto (`--project`) y quedan confinadas a él.
- **Un envío como mucho por petición, y ningún segundo envío por un reintento:** una pregunta a la vez por servidor y por sesión; una sesión con una solicitud `uncertain` queda cerrada a envíos por MCP; el mismo prompt en la misma sesión dentro de una ventana se rechaza sin enviar (design D5).
- **El trabajo largo en un proceso hijo que se mata** (pregunta al proveedor, lectura del vault) con un plazo duro que no depende del intérprete del servidor; al cancelar el cliente, al desconectarse o al vencer el plazo se termina el árbol del hijo y la solicitud queda en el estado que dicta la recuperación vigente.
- **Entrada no confiable:** cada mensaje se mide antes de analizarlo, se analiza como JSON estricto y los argumentos se validan con esquemas cerrados escritos por el harness; ningún identificador o ruta sale de su ámbito.
- **Salida no confiable:** la respuesta del proveedor (solo en memoria, nunca guardada si el proveedor no es sintético), las notas de memoria y los fragmentos se devuelven saneados, redactados, acotados y marcados como datos.
- **stdout solo para el protocolo;** stderr y el log del servidor sin contenido, acotados y privados.
- **Auditoría sin contenido** de cada llamada, permitida o denegada.
- **Recursión:** un proceso lanzado por el cliente MCP del harness no puede servir, y el servidor no da acceso al cliente MCP del harness.
- Documentación: sección «Servidor MCP» del README con un fragmento de configuración genérico para un cliente MCP, `SECURITY.md` (qué protege y qué no un servidor por stdio) y `scripts/demo_harness_mcp_server.py`.

**No entra**, aunque un lector lo asumiría:

- `memory_save_decision` ni ninguna escritura en el vault por MCP, ni una herramienta que devuelva «esperando aprobación»: la aprobación no se puede dar por el canal MCP y abrir colas de propuestas desde un agente es una decisión pendiente de Wilson (design D2).
- Transportes de red (HTTP, SSE, WebSocket), autenticación OAuth, varios clientes por proceso servidor.
- Recursos, prompts, muestreo, elicitación, notificaciones de progreso o de lista cambiada: solo herramientas.
- Llamar a herramientas MCP de terceros a través del servidor, ejecutar Skills por MCP o encadenar llamadas: un cliente pide una herramienta del harness y recibe su resultado.
- Controlar qué hace el cliente con lo que recibe: el harness no puede impedir que el cliente envíe la respuesta de Copilot o una nota del vault a otro sitio (design D7, riesgo escrito).
- Autenticar al proceso que lanza el servidor: stdio no es autenticación (design D3).
- Copilot real como tarea verificable antes de que `copilot-web-provider` esté mergeado.
- Lo que solo sirve para operar en producción (criterio del proyecto educativo, decisión de Wilson del 2026-11-25): varios clientes por proceso, demonio o servicio del sistema, rotación de logs entre lanzamientos, métricas, retención o purga de la tabla de auditoría. Se aplaza; las propiedades de seguridad (frontera de stdio, ámbito, ningún segundo envío, procesos que se matan, salida redactada) no se aplazan.

## Capabilities

### New Capabilities

- `harness-mcp-server`: el comando `mcp serve`, la lista de herramientas por lanzamiento, qué significa «cliente no autorizado» sobre stdio, límites y saneado de lo que entra, marcado y saneado de lo que sale, procesos hijo con plazo duro, ciclo de vida y desconexión, stdout reservado, logs sin contenido, recursión y auditoría.
- `harness-mcp-tools`: la conducta de cada herramienta expuesta: ámbito de las sesiones, `create_session`, `ask` sin segundos envíos, `get_session_status`, `get_history` sin contenido real y las dos herramientas de memoria confinadas al proyecto del lanzamiento.

### Modified Capabilities

Ninguna. Comprobado el 2026-11-25 sobre `develop` (`86f1079`): `openspec list --specs` devuelve 8 capacidades (`llm-provider`, `memory-maintenance`, `memory-search`, `memory-vault`, `project-context`, `request-recovery`, `secret-redaction`, `session-management`) y `grep -rn -i -E "mcp|cliente no autorizado" openspec/specs/` no devuelve nada. Lo que este change hace con las capacidades vigentes:

- `session-management`: `session list` e `history` en la CLI siguen mostrando todas las sesiones; el ámbito MCP restringe solo lo que ve un cliente MCP. Sin cambio de requisito.
- `request-recovery`: «Sin reenvío automático» y «Una pregunta a la vez por sesión» se aplican tal cual a una pregunta que llega por MCP; `harness-mcp-tools` añade restricciones más estrictas (una sesión con una solicitud `uncertain` no admite envíos por MCP), no las relaja. «La sesión vuelve a activa con una pregunta completada» sigue valiendo para la CLI.
- `project-context`, `memory-search`, `secret-redaction`: las herramientas de memoria devuelven lo mismo que `memory context` y `memory search`, con el mismo marcado, límite y redacción.

**Dependencias con changes mergeados pero sin archivar** (sus capacidades viven en `openspec/changes/<change>/specs/`, no en `openspec/specs/`, así que no se puede escribir un delta contra ellas):

- `mcp-gateway` (`tool-policy`, `mcp-client`): se reutiliza la marca de recursión `AI_HARNESS_MCP_CHILD` y el patrón de proceso hijo con su propio ámbito de terminación (su D4). Su requisito «Ninguna superficie de entrada en este corte» dice que nadie puede pedirle al harness una llamada a herramienta salvo la persona por la CLI. Sigue siendo cierto para las herramientas del gateway: el servidor no expone ningún camino hacia ellas (requisito «El servidor no da acceso al cliente MCP del harness»). Cuando se archive `mcp-gateway`, ese requisito se revisará para nombrar el servidor propio. Workflow follow-up lo recoge.
- `skill-engine` (`human-approval`): no se usa en la primera versión; si Wilson decide exponer propuestas de decisión, se reutilizará esta aprobación y no una segunda (design D2).
- `copilot-web-provider` (sin mergear): el `ask` por MCP con el proveedor real depende de él; con el Mock todo es demostrable.

## Impact

- Código nuevo: `harness/mcp_server/` (servidor, herramientas, transporte acotado de entrada, trabajador hijo, auditoría) y el subcomando `mcp serve` en `harness/mcp/commands.py`. Se reutiliza, extraído a un módulo neutral sin cambiar su conducta, el supervisor de proceso hijo de `harness/mcp/client.py`.
- Almacenamiento: una migración aditiva con el siguiente número libre al integrar (hoy `005`): columna `sessions.mcp_scope` y tabla `mcp_server_calls`.
- Dependencias: ninguna nueva; el SDK `mcp==2.3.0` ya está en el lock.
- Configuración: ninguna variable obligatoria nueva; el lanzamiento se configura con opciones de `mcp serve` en la configuración del cliente.
- Documentación: `README.md` («Servidor MCP»), `SECURITY.md` («Servidor MCP propio»), `.env.example` si hace falta, `scripts/demo_harness_mcp_server.py`.
- Seguridad y política: con el proveedor real, el servidor deja que el proceso que lo lanza pregunte en la sesión de Copilot de Wilson. Las condiciones de los Online Services de Microsoft prohíben «scraping or other data extraction methods»; Wilson declara estar autorizado y debe confirmar que el alcance incluye que otro programa local pregunte a través del harness (design D3 y D7, «Decisiones pendientes de Wilson»).
