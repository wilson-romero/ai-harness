# Proposal

## Why

Hoy el harness no puede hablar con ninguna herramienta externa: tiene 0 comandos MCP y 0 líneas que mencionen MCP (medido el 2026-11-24 sobre `8cb2ec5`: `uv run python main.py --help` lista `session`, `ask`, `history` y `memory`; `grep -rn -i mcp harness/ | wc -l` → 0), y `uv.lock` no contiene el SDK de MCP. El Norte del plan necesita que el harness «lea el modelo de Enterprise Architect», y el plan fija que EA vive en un servidor MCP en otro proceso: sin un cliente MCP con políticas no hay forma segura de llegar a él, ni a ninguna otra herramienta que venga después (Computer Use, memoria por MCP).

Corte **5 · EA lectura** de `docs/plan/2026-11-24-ai-harness-cortes.md`, primera de sus dos mitades (la otra es `ea-read`). Riesgo **N2** (el del corte; esta mitad, por sí sola, no toca EA). Cubre **SEC-05** (servidor, herramienta o argumentos desconocidos: denegado y auditado), **SEC-10** en su parte de procesos (un servidor MCP que se cuelga, muere o se porta mal no deja procesos propios vivos ni cuelga el harness) y **SEC-09** solo en el sentido que tiene en este corte (ver design D9: el harness no expone ninguna superficie a la que un cliente pueda conectarse; el servidor MCP propio del harness es del Corte 8). Se demuestra entero en **macOS** con un servidor MCP local sintético; el código es el mismo en Windows (sin ramas por plataforma), y una ejecución en Windows es confirmación opcional.

**El repositorio es público en GitHub.** La lista de servidores permitidos vive fuera del repo (`HARNESS_MCP_CONFIG`), los servidores de prueba son sintéticos y ningún resultado real de una herramienta se escribe en el repo ni en SQLite.

## What Changes

- **Lista local de servidores permitidos** (`HARNESS_MCP_CONFIG`, fichero JSON fuera del repo que solo edita la persona): por servidor, la orden de arranque como lista de argumentos, las variables de entorno que hereda, los plazos y las herramientas permitidas con su tipo de operación (`read` | `write`) y sus argumentos admitidos. Sin fichero, ningún servidor existe. La orden de arranque nunca sale de un modelo, de un argumento de la CLI ni de un resultado de herramienta.
- **Cliente MCP por stdio** sobre el SDK oficial (`mcp`): descubrimiento con `list_tools`, invocación con `call_tool`, validación de los argumentos antes de enviarlos y del resultado al recibirlo, límites de tamaño y de tiempo, y ciclo de vida del subproceso con plazos duros (arranque, llamada, cierre) que no dependen de que el servidor coopere.
- **Motor de políticas deny-by-default** delante de cada llamada: servidor, herramienta, argumentos y tipo de operación. Lo que no está declarado se deniega y se audita. Las herramientas `write` se deniegan siempre en este corte (`write_requires_approval`); el Corte 6 las habilitará reutilizando la aprobación de `skill-engine`, no una segunda.
- **Resultados como datos no confiables:** todo texto de un resultado pasa por el saneado y la redacción comunes (los de `project-memory`, movidos a un módulo neutral) antes de imprimirse; nunca se guarda en SQLite.
- **CLI:** `mcp list`, `mcp tools SERVER`, `mcp call SERVER TOOL --args JSON`.
- **Auditoría:** una fila por llamada (permitida o denegada) con servidor, herramienta, decisión, motivo, hash y tamaño de los argumentos, tamaño del resultado, duración y estado; nunca valores de argumentos ni contenido del resultado. Migración con el siguiente número libre al integrar.
- **Protección contra bucles y recursión:** un solo `call_tool` por comando de la CLI en este corte, el servidor no puede pedir nada al cliente (muestreo, elicitación, raíces) y un proceso lanzado por el cliente MCP del harness no puede volver a usar el cliente MCP del harness.
- **Servidor MCP sintético de prueba** (`get_project_metadata`, solo lectura) y variantes que se portan mal (se cuelga, inunda, escribe basura en stdout, muere, ignora el cierre), en `tests/fixtures/`.

**No entra**, aunque un lector lo asumiría:

- El servidor MCP **propio** del harness (`mcp serve`, `create_session`, `ask`…) y su autorización de clientes: Corte 8 (`harness-mcp-server`). Este corte solo es cliente.
- Enterprise Architect: es `ea-read`, que depende de este change. Aquí no hay ni una línea de COM.
- Transportes que no sean stdio (HTTP, SSE, WebSocket) y servidores remotos.
- Herramientas que escriben: se declaran, se deniegan y se auditan; nada más. Aprobaciones: Corte 4 (`skill-engine`) las crea, el Corte 6 las conecta aquí.
- Llamar a herramientas desde un Skill o a propuesta de un modelo (el Corte 7 lo integra). En este corte solo la persona, desde la CLI, pide una llamada.
- Enviar un resultado de herramienta al proveedor de lenguaje. El marcado como datos no confiables para el proveedor reutilizará el de la memoria cuando haya un consumidor (Corte 7).
- Recursos, prompts, muestreo, elicitación y notificaciones de MCP: solo herramientas.
- Garantizar que un servidor de terceros no haga nada malo dentro de su propio proceso: el harness controla qué arranca, qué le envía, cuánto espera y qué deja salir, no lo que el servidor hace con los permisos del usuario.

## Capabilities

### New Capabilities

- `mcp-client`: lista local de servidores permitidos, arranque y cierre de servidores por stdio con plazos duros, descubrimiento y llamada a herramientas, límites de tamaño y conducta ante un servidor que se porta mal; comandos `mcp list`, `mcp tools`, `mcp call`.
- `tool-policy`: decisión deny-by-default sobre cada llamada (servidor, herramienta, argumentos, tipo de operación), denegación de escrituras sin aprobación, protección contra bucles y recursión, tratamiento de los resultados como datos no confiables y auditoría sin contenido.

### Modified Capabilities

- `secret-redaction`: requisito nuevo (ADDED) «Resultados de herramientas enmascarados»: el texto que devuelve una herramienta MCP, claves y valores de un resultado estructurado incluidos, pasa por el mismo saneado y la misma redacción que el texto del vault. Los tres requisitos vigentes no cambian: su lista de formatos, el orden (limpiar y después redactar) y el límite declarado se aplican tal cual. Se escribe como ADDED y no como MODIFIED de «Formatos conocidos enmascarados» porque añade un origen de texto sin cambiar ninguna conducta existente.

Comprobado antes de declararlo (2026-11-24, sobre `8cb2ec5`): `openspec list --specs` devuelve 8 capacidades (`llm-provider`, `memory-maintenance`, `memory-search`, `memory-vault`, `project-context`, `request-recovery`, `secret-redaction`, `session-management`) y `grep -rn -i -E "mcp|herramienta|enterprise architect" openspec/specs/` no devuelve nada: ninguna capacidad vigente habla de herramientas. `session-management` («Auditoría sin contenido») no se modifica: sus eventos siguen igual y la auditoría de llamadas es un requisito nuevo de `tool-policy`.

## Impact

- Código nuevo: `harness/mcp/` (configuración, política, cliente, auditoría) y el subcomando `mcp` en `harness/cli.py`. Se mueven `harness/memory/redaction.py` y `harness/memory/safe_text.py` a un módulo neutral (`harness/text/`) sin cambiar su conducta; `harness/memory/` los importa desde allí.
- Almacenamiento: una migración aditiva (`tool_calls`) con **el siguiente número libre al integrar** (`feature/skill-engine` ocupa la `003` y aún no está mergeada).
- Dependencias: `mcp` (SDK oficial, versión fijada al implementar; 2.3.0 el 2026-11-24). Añade 25 paquetes al lock universal (él incluido; medido el 2026-11-24 con `uv lock` en un proyecto desechable fuera del repo), entre ellos `pywin32` con marcador de Windows, que el propio SDK declara (design D1).
- Configuración: `HARNESS_MCP_CONFIG` (ya está vacía en `.env.example`).
- Fixtures: servidores MCP sintéticos en `tests/fixtures/mcp/`.
- Documentación: `README.md` (comandos `mcp`, formato de la lista, qué se deniega, qué garantiza el cierre de procesos y qué no), `SECURITY.md` (el límite de D9), `scripts/demo_mcp_gateway.py`.
- `ea-read` (mismo corte) consume todo lo anterior; el Corte 6 añade la aprobación a las herramientas `write`; el Corte 7 conecta las llamadas a los Skills; el Corte 8 añade el servidor propio.
