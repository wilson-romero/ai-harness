## ADDED Requirements

### Requirement: Modo de respuesta recordado por sesión
Cada sesión SHALL tener un modo de respuesta, `auto`, `quick` o `deep`, que empieza en `auto` y se conserva entre procesos hasta que la persona lo cambia. Una sesión creada antes de existir el modo SHALL abrirse sin cambios y en `auto`.

#### Scenario: Una sesión nueva empieza en automático
- **WHEN** el usuario crea una sesión
- **THEN** su modo de respuesta es `auto`

#### Scenario: El modo sobrevive a un reinicio
- **WHEN** el usuario pone el modo `deep` en una sesión y abre la conversación de nuevo en otro proceso
- **THEN** la sesión sigue en `deep`

#### Scenario: Una base anterior abre sin cambios
- **WHEN** el harness abre una base de datos creada con las migraciones 001 a 007
- **THEN** las sesiones y solicitudes existentes conservan sus datos, las sesiones quedan en `auto` y las solicitudes antiguas no tienen modo registrado

### Requirement: Elegir el modo sin enviar nada
El sistema SHALL ofrecer `/mode [auto|quick|deep]` en la conversación, también con `--plain`, y `ask --mode auto|quick|deep` en la CLI. Cambiar el modo SHALL escribir solo en la base local: no SHALL enviar nada al proveedor, ni abrir el navegador, ni abrir una conversación remota nueva. `/mode` sin argumento SHALL mostrar el modo de la sesión. Un modo desconocido SHALL rechazarse sin cambiar nada.

#### Scenario: Cambiar de modo no envía
- **WHEN** el usuario escribe `/mode deep` en una conversación
- **THEN** la sesión queda en `deep`, el proveedor no recibe ninguna pregunta y no se registra ninguna solicitud

#### Scenario: Modo desconocido
- **WHEN** el usuario escribe `/mode rapidisimo`
- **THEN** el sistema responde con un error que lista `auto`, `quick` y `deep` y el modo de la sesión no cambia

#### Scenario: La opción de la CLI recuerda el modo
- **WHEN** el usuario ejecuta `ask SESSION_ID "pregunta" --mode quick`
- **THEN** la pregunta sale en `quick` y la siguiente pregunta de esa sesión sin `--mode` también

### Requirement: Solo los modos que el proveedor sabe poner
El sistema SHALL aceptar `quick` o `deep` solo si el proveedor de la sesión dice que sabe ponerlos; `auto` SHALL aceptarse siempre. Si el proveedor no sabe, el comando y cualquier pregunta en ese modo SHALL rechazarse con un mensaje que diga por qué y cómo resolverlo, antes de registrar nada y sin enviar nada.

#### Scenario: Copilot sin el control medido
- **WHEN** la medida de Copilot no contiene el control de modo y el usuario escribe `/mode deep`
- **THEN** el sistema lo rechaza diciendo que falta medir el control con el paso `response-mode` de la sonda, y la sesión sigue en su modo

#### Scenario: Automático siempre funciona
- **WHEN** la medida de Copilot no contiene el control de modo y el usuario escribe `/mode auto` y hace una pregunta
- **THEN** el modo se acepta y la pregunta sale con la página como estaba

#### Scenario: El Mock admite los tres
- **WHEN** el usuario pone cada modo con el Mock y hace una pregunta en cada uno
- **THEN** el Mock recibe cada pregunta con el modo pedido y responde de forma determinista según ese modo

### Requirement: El modo se confirma en la página antes de enviar
Con un modo `quick` o `deep`, Copilot Web SHALL poner el modo con el control medido antes de escribir el prompt y SHALL releerlo de la página. Si no puede confirmarlo, la solicitud SHALL terminar en `failed` sin haber escrito nada en el editor ni enviado nada, nunca en `uncertain`, y SHALL no reenviarse.

#### Scenario: Modo puesto y confirmado
- **WHEN** la sesión está en `deep` y la página muestra el control medido
- **THEN** la página recibe el prompt estando en `deep` y la solicitud registra `deep` como modo confirmado

#### Scenario: El modo no se puede confirmar
- **WHEN** la página no cambia de modo al elegir la opción
- **THEN** la solicitud termina en `failed` con un mensaje que dice que el modo no se confirmó y que no se envió nada, y la página no recibe ningún prompt

#### Scenario: El control no está en la página
- **WHEN** la medida contiene el control pero la página no lo muestra
- **THEN** la solicitud termina en `failed` antes de escribir nada y la página no recibe ningún prompt

### Requirement: Poner el modo no cambia de conversación
Poner el modo SHALL dejar la página en la misma conversación remota de la sesión, o en una conversación nueva vacía si la sesión aún no tiene ninguna. Si al poner el modo la página pasa a otra conversación o aparece un turno, la solicitud SHALL terminar en `failed` sin escribir nada.

#### Scenario: Elegir el modo abre otra conversación
- **WHEN** la sesión ya tiene una conversación remota y al elegir la opción de modo la página abre una conversación nueva
- **THEN** la solicitud termina en `failed` sin escribir nada, la página no recibe ningún prompt y la sesión conserva su referencia remota

### Requirement: El registro dice el modo que quedó
Cada solicitud SHALL registrar el modo pedido y el modo confirmado en la página. Si después de la respuesta la página está en otro modo, el registro SHALL guardar el modo releído y la respuesta SHALL llevar un aviso. Si no se puede releer, SHALL conservarse el modo confirmado antes del envío, con un aviso, sin cambiar el estado de la solicitud.

#### Scenario: La página vuelve a otro modo
- **WHEN** la sesión está en `deep` y la página pasa a `quick` al terminar la respuesta
- **THEN** la solicitud termina en `completed`, registra `deep` como pedido y `quick` como confirmado, y el usuario ve un aviso que lo dice

### Requirement: Modo visible
El modo SHALL verse en el panel lateral de la pantalla completa, en `/status` y, cuando no es el automático sin cambios, en cada solicitud de `/history` y de `history`, con el modo confirmado y el pedido si difieren.

#### Scenario: Panel lateral
- **WHEN** el usuario pone `/mode quick` en la pantalla completa
- **THEN** el panel lateral muestra `quick` como modo de la sesión sin enviar nada

#### Scenario: Historial con el modo confirmado
- **WHEN** una solicitud pidió `deep` y la página confirmó `quick`
- **THEN** `history` muestra en esa solicitud que el modo fue `quick` y que se pidió `deep`

### Requirement: Plazo propio de deep
Una pregunta en `deep` sin plazo propio SHALL usar `HARNESS_DEEP_REQUEST_TIMEOUT_S`, que por defecto vale el triple de `HARNESS_REQUEST_TIMEOUT_S` y no puede ser menor que él. El plazo SHALL conservar los estados: `timeout` si vence antes de enviar y `uncertain` si vence después, sin reenvío.

#### Scenario: Deep espera más que quick
- **WHEN** el proveedor tarda más que `HARNESS_REQUEST_TIMEOUT_S` y menos que `HARNESS_DEEP_REQUEST_TIMEOUT_S` en responder
- **THEN** la pregunta en `deep` termina en `completed` y la misma pregunta en `quick` termina en `uncertain`

#### Scenario: Plazo de deep menor que el normal
- **WHEN** `HARNESS_DEEP_REQUEST_TIMEOUT_S` es menor que `HARNESS_REQUEST_TIMEOUT_S`
- **THEN** el harness rechaza la configuración con un mensaje que nombra las dos variables

### Requirement: Medida del control de modo sin enviar
La sonda SHALL tener un paso `response-mode` que, con la persona, registra cómo se abre el control, las opciones con su rol y nombre accesible, qué opción corresponde a cada modo y cómo se lee el modo actual. SHALL comprobar el control eligiendo cada modo y releyéndolo, SHALL dejar la página en el modo en que estaba y no SHALL enviar ningún prompt ni guardar texto de la página fuera de las etiquetas del control.

#### Scenario: Medida en la página sintética
- **WHEN** el paso `response-mode` se ejecuta contra la página sintética con el selector de modo
- **THEN** `ui.json` gana el control con sus opciones y su forma de lectura, la página no recibe ningún prompt y ningún canario de la página aparece en lo guardado

#### Scenario: Sin control que medir
- **WHEN** el paso `response-mode` se ejecuta contra una página sin selector de modo
- **THEN** el paso termina con código distinto de 0 y `ui.json` no cambia
