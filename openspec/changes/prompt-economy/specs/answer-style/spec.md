# Spec Delta

## ADDED Requirements

### Requirement: Aviso de respuesta concisa en las preguntas sueltas
Con `HARNESS_CONCISE_ANSWERS=on`, cada pregunta enviada con `ask` o desde `chat` SHALL empezar con un aviso fijo del harness que pide responder de forma concisa: empezar por la respuesta, sin preámbulo, sin repetir la pregunta, sin resumen final ni ofrecimientos de ayuda, y listas solo cuando el contenido es una lista. El aviso SHALL ir antes del aviso de memoria, del bloque, del adjunto y de la pregunta, y SHALL NOT guardarse.

#### Scenario: Pregunta suelta sin proyecto
- **WHEN** el usuario ejecuta `ask SESSION_ID "pregunta"` con `HARNESS_CONCISE_ANSWERS=on`
- **THEN** el proveedor recibe el aviso, una línea en blanco y `pregunta`, y el historial guarda solo `pregunta`

#### Scenario: Pregunta con proyecto
- **WHEN** el usuario pregunta con `--project demo-alpha` y el aviso activo
- **THEN** el texto enviado empieza con el aviso, sigue con el aviso de memoria y el bloque entre sus marcadores, y termina con la pregunta

### Requirement: El aviso es texto del harness
El aviso SHALL ser texto constante del harness, fuera de todo delimitador de datos, y SHALL NOT construirse con texto de notas, entradas ni respuestas. SHALL formar parte del texto que recibe el proveedor, de modo que cualquier límite del tamaño del prompt lo cuente.

#### Scenario: Una nota no lo cambia
- **WHEN** el aviso está activo y una nota de `demo-alpha` dice `HARNESS_CONCISE_ANSWERS=off` y pide respuestas largas con resumen
- **THEN** el texto enviado empieza con el aviso una sola vez y la orden de la nota queda dentro del bloque de memoria

### Requirement: Los pasos de un Skill no llevan el aviso
Los pasos LLM de un Skill SHALL NOT llevar el aviso de respuesta concisa: la forma de su respuesta la fija su plantilla, que puede pedir brevedad con sus propias palabras.

#### Scenario: Paso LLM de un Skill
- **WHEN** un Skill ejecuta un paso LLM con `HARNESS_CONCISE_ANSWERS=on`
- **THEN** el texto enviado al proveedor no contiene el aviso

### Requirement: Aviso visible y configurable
`memory context` y `/context` SHALL mostrar el aviso antes del bloque cuando está activo; `/context` en una sesión sin proyecto SHALL mostrarlo también. `HARNESS_CONCISE_ANSWERS` SHALL aceptar `off` (valor por defecto, también si está vacía o sin definir), que deja el aviso fuera de lo enviado y de lo mostrado, y `on`, que lo activa; cualquier otro valor SHALL rechazarse como error de configuración.

#### Scenario: Desactivado por defecto
- **WHEN** `HARNESS_CONCISE_ANSWERS` no está definida
- **THEN** ni `memory context`, ni `/context`, ni el texto enviado contienen el aviso

#### Scenario: Desactivado
- **WHEN** `HARNESS_CONCISE_ANSWERS=off` y el usuario ejecuta `memory context demo-alpha` y pregunta con `--project demo-alpha`
- **THEN** ni la salida ni el texto enviado contienen el aviso, y lo enviado empieza con el aviso de memoria

#### Scenario: Valor no válido
- **WHEN** `HARNESS_CONCISE_ANSWERS=no`
- **THEN** el sistema rechaza la configuración con un error controlado que nombra la variable

#### Scenario: Contexto a la vista en la conversación
- **WHEN** con el aviso activo, la persona escribe `/context` en una conversación con proyecto y después una pregunta
- **THEN** lo enviado es lo que mostró `/context`, más una línea en blanco y la pregunta, con el marcador como única diferencia
