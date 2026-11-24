# llm-provider Specification

## Purpose

Define cómo el harness envía una pregunta a un proveedor de lenguaje y qué resultado registra, de modo que el resto del sistema no dependa de qué proveedor hay detrás.

## Requirements

### Requirement: Proveedor seleccionable por configuración
El sistema SHALL elegir el proveedor a partir de la configuración local y SHALL usar el proveedor Mock cuando no se configure ninguno. Un nombre de proveedor desconocido SHALL producir un error controlado antes de registrar ninguna solicitud.

#### Scenario: Mock por defecto
- **WHEN** no hay proveedor configurado y el usuario crea una sesión
- **THEN** la sesión queda asociada al proveedor `mock`

#### Scenario: Proveedor desconocido
- **WHEN** la configuración nombra un proveedor que no existe y el usuario ejecuta `ask`
- **THEN** el sistema informa del error por stderr, termina con código distinto de 0 y no registra ninguna solicitud

### Requirement: Preguntar en una sesión
El sistema SHALL registrar cada pregunta como una solicitud con identificador propio dentro de su sesión, enviarla al proveedor de esa sesión y, si se completa, mostrar la respuesta y registrar su duración.

#### Scenario: Pregunta completada
- **WHEN** el usuario ejecuta `ask SESSION_ID "Analiza este requerimiento"` con el proveedor Mock
- **THEN** el sistema imprime la respuesta, termina con código 0 y la solicitud queda en `completed` con duración registrada
- **AND** la sesión queda en estado `active`

#### Scenario: Prompt vacío rechazado
- **WHEN** el usuario ejecuta `ask SESSION_ID ""`
- **THEN** el sistema informa del error, termina con código distinto de 0 y no registra ninguna solicitud

### Requirement: Mock determinista y sin red
El proveedor Mock SHALL devolver siempre la misma respuesta para el mismo prompt en la misma sesión y SHALL funcionar sin acceso a red.

#### Scenario: Misma pregunta, misma respuesta
- **WHEN** el usuario hace la misma pregunta dos veces en la misma sesión con el Mock
- **THEN** las dos respuestas son idénticas

#### Scenario: Funciona sin red
- **WHEN** las pruebas del Mock se ejecutan con las conexiones de red bloqueadas
- **THEN** todas pasan

### Requirement: Resultado distinto según el punto de fallo
El sistema SHALL registrar `failed` cuando el proveedor informa de un error, `timeout` cuando vence el plazo antes de que el prompt haya salido y `uncertain` cuando vence el plazo o se pierde el proceso después de que el prompt haya salido. En los tres casos SHALL terminar con código distinto de 0 y un mensaje que nombre el estado.

#### Scenario: Error del proveedor
- **WHEN** el proveedor informa de un error al procesar la pregunta
- **THEN** la solicitud queda en `failed` y el sistema lo comunica por stderr

#### Scenario: Plazo vencido antes del envío
- **WHEN** vence el plazo antes de que el proveedor haya enviado el prompt
- **THEN** la solicitud queda en `timeout`

#### Scenario: Plazo vencido después del envío
- **WHEN** vence el plazo después de que el proveedor haya enviado el prompt
- **THEN** la solicitud queda en `uncertain` y el sistema avisa de que la pregunta pudo haber llegado

### Requirement: El contenido solo se guarda si es sintético
El sistema SHALL guardar el texto de prompts y respuestas únicamente cuando el proveedor de la sesión declara que su contenido es sintético. Con cualquier otro proveedor SHALL guardar la solicitud, su estado y sus fechas, sin el texto.

#### Scenario: Contenido del Mock guardado
- **WHEN** el usuario pregunta en una sesión del proveedor Mock
- **THEN** el historial posterior muestra el texto de la pregunta y de la respuesta

#### Scenario: Contenido de un proveedor no sintético omitido
- **WHEN** se completa una pregunta con un proveedor de prueba que no se declara sintético
- **THEN** el almacenamiento conserva la solicitud y su estado, y ningún mensaje guarda el texto del prompt ni de la respuesta
