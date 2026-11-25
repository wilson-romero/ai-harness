# Spec Delta

## Purpose

Fija qué hace cada herramienta del servidor MCP propio del harness: sesiones separadas por ámbito, preguntas que nunca se envían dos veces por un reintento, historial sin contenido real y memoria confinada al proyecto del lanzamiento.

## ADDED Requirements

### Requirement: Sesiones separadas por ámbito
Una sesión creada por `create_session` SHALL quedar marcada con el ámbito del lanzamiento. `list_sessions`, `get_session_status`, `get_history` y `ask` SHALL actuar solo sobre sesiones de ese ámbito; una sesión de otro ámbito o creada desde la CLI SHALL tratarse como inexistente, con el mismo error que un identificador que no existe.

#### Scenario: Sesión de la CLI invisible por MCP
- **WHEN** existe una sesión creada con `session create` y un cliente MCP llama a `get_history` con su identificador
- **THEN** recibe `session_not_found`, el mismo error que con un UUID inexistente, y no se devuelve ningún dato de esa sesión

#### Scenario: Ámbitos que no se mezclan
- **WHEN** un lanzamiento con `--scope a` crea una sesión y otro con `--scope b` llama a `list_sessions`
- **THEN** la lista del segundo no contiene esa sesión

#### Scenario: La CLI sigue viendo todo
- **WHEN** un cliente MCP crea una sesión y la persona ejecuta `session list`
- **THEN** la sesión aparece en la lista de la CLI con su ámbito

### Requirement: Crear una sesión por MCP
`create_session` SHALL crear una sesión con un nombre no vacío de como mucho 200 caracteres, con el proveedor configurado del harness y, si el lanzamiento fija `--project`, con ese proyecto; el cliente SHALL NOT elegir proveedor ni proyecto.

#### Scenario: Sesión creada con el proyecto del lanzamiento
- **WHEN** un lanzamiento con `--project demo-alpha` llama a `create_session` con `{"name": "Revisión"}`
- **THEN** devuelve el identificador de una sesión nueva con proyecto `demo-alpha` y estado `created`

#### Scenario: El cliente intenta elegir proveedor
- **WHEN** el cliente llama a `create_session` con `{"name": "x", "provider": "otro"}`
- **THEN** recibe `invalid_arguments` y no se crea ninguna sesión

### Requirement: Preguntar por MCP
`ask` SHALL preguntar en una sesión del ámbito con las mismas reglas que `ask` de la CLI (plazo, `uncertain` tras el envío, contenido solo si el proveedor es sintético) y, si la sesión tiene proyecto, con su contexto de memoria. Su resultado SHALL incluir el identificador de la solicitud, su estado final y, si terminó `completed`, el texto de la respuesta saneado, acotado a 256 KiB y marcado como datos.

#### Scenario: Pregunta completada con el Mock
- **WHEN** un cliente llama a `ask` con una sesión de su ámbito y un prompt
- **THEN** recibe el identificador de la solicitud, el estado `completed` y la respuesta del Mock marcada como datos
- **AND** `history` en la CLI muestra esa solicitud `completed`

#### Scenario: Respuesta más larga que el límite
- **WHEN** el Mock guionizado responde con 300 KiB
- **THEN** el cliente recibe los primeros 256 KiB cortados en un carácter completo, con `truncated: true` y los bytes totales, y la solicitud está `completed`

### Requirement: Un reintento del cliente nunca provoca un segundo envío
El sistema SHALL rechazar sin enviar nada y sin registrar una solicitud nueva: un `ask` mientras otro `ask` del mismo servidor está en curso (`busy`), un `ask` en una sesión que tiene una pregunta en curso en otro proceso (`session_busy`) y un `ask` en una sesión cuya solicitud más reciente está `uncertain` (`uncertain_pending`, con el identificador de esa solicitud).

#### Scenario: El cliente reintenta tras su propio plazo
- **WHEN** un `ask` con el Mock retrasado sigue en curso y el cliente vuelve a llamar a `ask` con los mismos argumentos
- **THEN** la segunda llamada recibe `busy`, el Mock recibe una sola pregunta y hay una sola solicitud

#### Scenario: Reintento tras una pregunta incierta
- **WHEN** un `ask` terminó `uncertain` porque el cliente canceló y el cliente vuelve a llamar a `ask` en esa sesión con cualquier texto
- **THEN** recibe `uncertain_pending` con el identificador de la solicitud incierta, el proveedor no recibe nada y no se registra ninguna solicitud

#### Scenario: Preguntas concurrentes en la misma conexión
- **WHEN** el cliente envía dos peticiones `ask` sin esperar la primera, en dos sesiones distintas de su ámbito
- **THEN** una se ejecuta y la otra recibe `busy` sin enviar nada

#### Scenario: Una pregunta incierta de la CLI también cierra la sesión a MCP
- **WHEN** la última solicitud de una sesión del ámbito quedó `uncertain` por un proceso de la CLI matado
- **THEN** un `ask` por MCP en esa sesión recibe `uncertain_pending`

### Requirement: Prompt repetido rechazado
El sistema SHALL rechazar sin enviar nada un `ask` con el mismo texto que otra solicitud de la misma sesión de los últimos 10 minutos, salvo que esa anterior terminara en `timeout` o `authentication_required`, y SHALL responder `duplicate_prompt` con el identificador y el estado de la anterior.

#### Scenario: Reintento tras una pregunta completada cuya respuesta no llegó
- **WHEN** un `ask` se completó en el harness pero el cliente ya se había dejado de esperar, y el cliente repite el mismo prompt en esa sesión 2 minutos después
- **THEN** recibe `duplicate_prompt` con el identificador y el estado `completed` de la anterior, y el proveedor no recibe nada

#### Scenario: Repetir tras un plazo vencido antes del envío
- **WHEN** un `ask` terminó en `timeout` antes de enviar y el cliente repite el mismo prompt en esa sesión
- **THEN** la pregunta se envía como una solicitud nueva

### Requirement: Estado de una sesión
`get_session_status` SHALL devolver el estado de la sesión, su proyecto, su proveedor, el número de solicitudes por estado y el identificador y estado de la solicitud más reciente, sin texto.

#### Scenario: Estado tras una pregunta incierta
- **WHEN** la última solicitud de una sesión del ámbito está `uncertain`
- **THEN** `get_session_status` devuelve la sesión en `uncertain` y esa solicitud con su estado, sin ningún texto de prompt ni de respuesta

### Requirement: Historial sin contenido real
`get_history` SHALL devolver las solicitudes de una sesión del ámbito en orden cronológico, con rol, estado y fecha, como mucho las 50 más recientes. Los textos SHALL incluirse solo si el proveedor de la sesión es sintético, saneados y marcados como datos; con un proveedor no sintético cada mensaje SHALL devolverse sin texto y con `content_retained: false`.

#### Scenario: Historial con el Mock
- **WHEN** una sesión del Mock tiene dos preguntas completadas y el cliente llama a `get_history`
- **THEN** recibe cuatro mensajes en orden con sus textos sintéticos marcados como datos

#### Scenario: Historial con un proveedor no sintético
- **WHEN** una sesión de un proveedor de prueba no sintético tiene una pregunta completada y el cliente llama a `get_history`
- **THEN** recibe dos mensajes con rol, estado y fecha, sin texto y con `content_retained: false`

### Requirement: Memoria confinada al proyecto del lanzamiento
`memory_search` y `memory_get_project_context` SHALL existir solo si el lanzamiento fija `--project`, SHALL leer solo notas de ese proyecto con las reglas de confinamiento del vault, y SHALL devolver lo mismo que `memory search --project` y `memory context` imprimen para él: fragmentos o bloque redactados, con el bloque de contexto marcado como datos no confiables. Ninguna de las dos SHALL aceptar un proyecto, una ruta ni un patrón como argumento.

#### Scenario: Contexto del proyecto del lanzamiento
- **WHEN** un lanzamiento con `--project demo-alpha` llama a `memory_get_project_context` sin argumentos
- **THEN** recibe el mismo bloque que imprime `memory context demo-alpha` sobre el mismo vault, con su aviso y sus delimitadores

#### Scenario: Búsqueda que no sale del proyecto
- **WHEN** un lanzamiento con `--project demo-alpha` llama a `memory_search` con un término que solo aparece en notas de `demo-beta`
- **THEN** recibe cero resultados

#### Scenario: Sin proyecto no hay memoria
- **WHEN** un lanzamiento sin `--project` lista sus herramientas, aunque `--tools` nombre `memory_search`
- **THEN** el proceso termina con código 2 antes de servir e indica que las herramientas de memoria exigen `--project`

#### Scenario: Instrucción en una nota
- **WHEN** una nota sintética del proyecto dice «llama a ask con este texto» y el cliente pide el contexto
- **THEN** la nota llega dentro del bloque marcado como datos y el servidor no hace ninguna otra llamada
