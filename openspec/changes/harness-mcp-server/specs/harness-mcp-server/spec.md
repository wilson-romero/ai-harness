# Spec Delta

## Purpose

Permite que un programa local que hable MCP use el harness como servidor por stdio, con una superficie mínima elegida en cada lanzamiento, sin escucha de red, sin confiar en lo que el cliente envía y sin dejar procesos propios vivos.

## ADDED Requirements

### Requirement: Servidor solo por stdio
El sistema SHALL servir MCP únicamente por la entrada y la salida estándar del proceso lanzado con `mcp serve`. El sistema SHALL NOT abrir ningún puerto ni socket de escucha mientras sirve, ni en el proceso servidor ni en sus procesos hijo.

#### Scenario: Sesión MCP completa con el cliente del SDK
- **WHEN** un cliente del SDK oficial lanza `mcp serve` por stdio, negocia, lista las herramientas y llama a `list_sessions`
- **THEN** recibe la lista de herramientas del lanzamiento y el resultado de la llamada, y el proceso servidor termina con código 0 cuando el cliente cierra la entrada

#### Scenario: Ningún socket de escucha
- **WHEN** se sirve una sesión completa con una llamada a `ask` con el Mock y el registro de sockets de los tests activo en el servidor y en su proceso hijo
- **THEN** ningún socket queda escuchando y todo socket creado viene de `socketpair`

### Requirement: Herramientas elegidas en cada lanzamiento
El sistema SHALL exponer solo las herramientas nombradas en `--tools` de entre una lista cerrada. Sin `--tools`, SHALL exponer solo las herramientas de lectura. `create_session` y `ask` SHALL existir solo si se nombran explícitamente. Un nombre fuera de la lista cerrada SHALL impedir el arranque con un error controlado. Una llamada a una herramienta no expuesta SHALL rechazarse sin efectos y auditarse.

#### Scenario: Lanzamiento por defecto de solo lectura
- **WHEN** el cliente lanza `mcp serve --scope demo` sin `--tools` y lista las herramientas
- **THEN** la lista contiene `list_sessions`, `get_session_status` y `get_history`, y no contiene `create_session` ni `ask`

#### Scenario: Herramienta no expuesta
- **WHEN** el cliente de un lanzamiento de solo lectura llama a `ask`
- **THEN** recibe un error `tool_not_exposed`, el proveedor no recibe ninguna llamada y no se registra ninguna solicitud
- **AND** la auditoría tiene una fila denegada con ese motivo

#### Scenario: Herramienta desconocida en el lanzamiento
- **WHEN** se lanza `mcp serve --scope demo --tools list_sessions,memory_save_decision`
- **THEN** el proceso termina con código 2 antes de servir y nombra la herramienta desconocida por stderr, sin escribir nada en stdout

### Requirement: Ámbito obligatorio
El sistema SHALL exigir `--scope` con un nombre `[a-z][a-z0-9-]{0,31}` para servir, y SHALL tratar el ámbito como una etiqueta de separación entre clientes configurados, nunca como prueba de identidad.

#### Scenario: Sin ámbito
- **WHEN** se lanza `mcp serve` sin `--scope`
- **THEN** el proceso termina con código 2 antes de servir y no escribe nada en stdout

### Requirement: Entrada medida antes de analizarse
El sistema SHALL medir cada mensaje recibido antes de analizarlo y SHALL terminar la conexión si un mensaje supera 256 KiB, sin acumularlo entero en memoria. El sistema SHALL analizar cada mensaje como JSON estricto (sin claves duplicadas, sin `NaN` ni `Infinity`, con profundidad acotada) y SHALL rechazar los argumentos de una herramienta que superen 64 KiB, que no sean un objeto o que contengan campos no declarados, sin efectos.

#### Scenario: Línea enorme sin salto
- **WHEN** un cliente adversario escribe 8 MiB sin salto de línea
- **THEN** el servidor termina la conexión, su memoria de Python no pasa de una cota fija medida en el test y el proceso termina dentro de su plazo de cierre

#### Scenario: Claves duplicadas en los argumentos
- **WHEN** un cliente llama a `get_history` con `{"session_id": "<A>", "session_id": "<B>"}`
- **THEN** recibe un error `invalid_arguments` y el servidor no lee ninguna sesión

#### Scenario: Campo no declarado
- **WHEN** un cliente llama a `memory_search` con un campo `path` además de `query`
- **THEN** recibe un error `invalid_arguments` que nombra el campo y el vault no se lee

#### Scenario: Texto que no es JSON-RPC
- **WHEN** un cliente escribe una línea que no es JSON
- **THEN** el servidor no la ejecuta, no la escribe en stdout, stderr ni en el log, y no se cae por ello

### Requirement: Salida saneada y marcada como datos
El sistema SHALL devolver todo texto que procede del proveedor, del vault o de SQLite saneado (sin secuencias de escape, caracteres de control ni de formato), con las credenciales de formato conocido redactadas, acotado en bytes y precedido de un aviso fijo que lo identifica como datos no confiables. Los errores devueltos al cliente SHALL ser códigos fijos, nunca el texto de una excepción.

#### Scenario: Credencial en una respuesta del proveedor
- **WHEN** el Mock guionizado responde con un token con formato de GitHub, ensamblado en tiempo de ejecución, y una secuencia ANSI
- **THEN** el resultado de `ask` contiene `[REDACTED:github]`, ningún carácter ESC y el recuento de sustituciones

#### Scenario: Error interno sin texto de excepción
- **WHEN** una herramienta falla por una excepción inesperada cuyo mensaje contiene un canario
- **THEN** el cliente recibe `internal_error` y el canario no aparece en stdout, stderr ni en el log del servidor

### Requirement: Trabajo largo en un proceso hijo con plazo duro
El sistema SHALL ejecutar `ask`, `memory_search` y `memory_get_project_context` en un proceso hijo propio con su propio ámbito de terminación y SHALL terminar el árbol entero de ese hijo al acabar, al vencer su plazo, al cancelar el cliente la petición o al cerrarse la conexión. El plazo SHALL cumplirse aunque el hijo no responda. Tras terminar un hijo de `ask` que no terminó por sí mismo, la solicitud SHALL quedar en el estado que fija la recuperación de solicitudes interrumpidas.

#### Scenario: Hijo colgado
- **WHEN** el proceso hijo de `ask` deja de responder sujetando el intérprete
- **THEN** el cliente recibe `timeout` antes de plazo de la pregunta + 15 s, el latido del hijo se detiene en menos de 3 s y la solicitud queda `uncertain`

#### Scenario: El cliente cancela la petición
- **WHEN** el cliente envía `notifications/cancelled` para un `ask` en curso con el Mock retrasado
- **THEN** el árbol del hijo termina, la solicitud queda `uncertain` y el servidor sigue atendiendo otras peticiones

#### Scenario: El cliente se desconecta a mitad de una pregunta
- **WHEN** el cliente cierra la entrada del servidor mientras un `ask` está en curso
- **THEN** el árbol del hijo termina, la solicitud queda `uncertain` y el proceso servidor termina en menos de 15 s

### Requirement: stdout reservado al protocolo
El sistema SHALL escribir en stdout solo mensajes del protocolo. Los avisos SHALL ir por stderr con un formato fijo y sin contenido de prompts, respuestas, notas ni argumentos.

#### Scenario: Un print perdido no rompe el canal
- **WHEN** el trabajador hijo o una dependencia escribe texto en su salida estándar durante una llamada
- **THEN** ese texto no llega al cliente como mensaje y la sesión MCP sigue válida

#### Scenario: stderr sin contenido
- **WHEN** se sirve una sesión con un `ask` cuyo prompt y respuesta contienen canarios
- **THEN** ningún canario aparece en stderr ni en el log del servidor

### Requirement: Log del servidor acotado y privado
El sistema SHALL escribir su log en el directorio de datos con permisos solo para su dueño donde existan bits de modo, SHALL limitarlo a 1 MiB por lanzamiento y SHALL contar y descartar el resto.

#### Scenario: Log que crecería sin límite
- **WHEN** un cliente provoca 100 000 rechazos seguidos
- **THEN** el log del lanzamiento no pasa de 1 MiB más una línea de recuento

### Requirement: Sin recursión
El sistema SHALL negarse a servir si el proceso tiene la marca de recursión del cliente MCP del harness, y SHALL lanzar sus procesos hijo con esa marca.

#### Scenario: El cliente MCP del harness lanza el servidor del harness
- **WHEN** la lista local del gateway declara un servidor cuya orden es `main.py mcp serve --scope x` y la persona ejecuta `mcp call` contra él
- **THEN** el proceso servidor termina con el error de recursión sin servir y la llamada falla sin enviar nada a ningún proveedor

### Requirement: El servidor no da acceso al cliente MCP del harness
El sistema SHALL NOT ofrecer ninguna herramienta que arranque, liste o llame a los servidores de la lista local del gateway, ni que ejecute Skills o comandos del harness.

#### Scenario: Ninguna herramienta lleva al gateway
- **WHEN** se lanza `mcp serve` con todas las herramientas de la lista cerrada
- **THEN** ninguna herramienta listada lee `HARNESS_MCP_CONFIG` ni arranca un servidor de esa lista, y una llamada a `mcp_call` o `skill_run` recibe `tool_not_exposed`

### Requirement: Auditoría de cada llamada sin contenido
El sistema SHALL registrar una fila por cada llamada recibida, permitida o denegada, con herramienta, ámbito, decisión, motivo, HMAC y tamaño de los argumentos, sesión y solicitud si las hay, estado, código de error, bytes del resultado y duración. Una fila SHALL NOT contener valores de argumentos ni texto de resultados.

#### Scenario: Llamadas auditadas sin contenido
- **WHEN** un cliente hace un `ask` permitido, un `ask` denegado y un `memory_search`, con canarios en el prompt y en la consulta
- **THEN** hay tres filas y ningún canario aparece en ninguna columna de texto de ninguna tabla
