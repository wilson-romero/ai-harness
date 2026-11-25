# Spec Delta

## Purpose

Garantiza que lo que un Skill hace tras un paso `approval` solo ocurre con una aprobación humana local, concedida fuera del modelo, ligada al contenido exacto de la propuesta, con caducidad y de un solo uso.

## ADDED Requirements

### Requirement: Propuesta con hash canónico
Al llegar a un paso `approval`, el sistema SHALL construir la propuesta (alcance, ejecución, paso, Skill con versión y hash, destino y SHA-256 y tamaño del contenido exacto) y SHALL calcular su hash SHA-256 sobre una serialización canónica. La misma propuesta SHALL producir siempre el mismo hash, y cualquier cambio de un byte del contenido, del destino, de la ejecución o del Skill SHALL producir otro.

#### Scenario: Vector de prueba fijo
- **WHEN** se calcula el hash de la propuesta sintética del vector de prueba
- **THEN** el resultado es exactamente el hash fijado en el test, en macOS y en Windows

#### Scenario: Un byte distinto
- **WHEN** dos propuestas solo difieren en un carácter del contenido
- **THEN** sus hashes son distintos

### Requirement: Lo que se muestra es lo que se aprueba
La terminal SHALL mostrar el contenido exacto de la propuesta, su destino, su tamaño, su hash y su caducidad antes de pedir la decisión. El contenido aprobable SHALL NOT contener caracteres de control distintos de salto de línea y tabulador, ni caracteres de control bidireccional; se eliminan antes de calcular el hash. El contenido aprobable SHALL estar limitado a 32 KiB.

#### Scenario: Secuencia de escape en una salida del modelo
- **WHEN** la salida que se va a aprobar contiene `ESC[2K` o U+202E
- **THEN** el contenido mostrado y el contenido hasheado no contienen esos caracteres y son idénticos entre sí

#### Scenario: Propuesta demasiado grande
- **WHEN** el contenido de la propuesta supera 32 KiB
- **THEN** el paso queda `failed` sin pedir aprobación

### Requirement: Caracteres invisibles escritos de forma visible
Cualquier carácter invisible que quede en el contenido aprobable (categorías `Cs`, `Co`, `Cn`, selectores de variación y demás puntos ignorables por defecto) SHALL mostrarse, hashearse y aplicarse escrito como `<U+XXXX>`.

#### Scenario: Caracteres invisibles en el contenido
- **WHEN** la salida que se va a aprobar contiene U+FE0F, U+E0100, U+3164 o U+034F
- **THEN** el contenido mostrado los escribe como `<U+FE0F>`, `<U+E0100>`, `<U+3164>` y `<U+034F>`, no contiene los caracteres, y lo que el efecto aplica tiene exactamente esos bytes y el SHA-256 aprobado

### Requirement: Un solo destino mostrado, hasheado y aplicado
El destino de una propuesta SHALL mostrarse, hashearse y aplicarse como la misma cadena. Un destino que no esté en NFC o que contenga un carácter de control, de formato o invisible SHALL hacer fallar el paso sin pedir aprobación.

#### Scenario: Destino con caracteres invisibles
- **WHEN** el destino que prepara el efecto contiene U+202E, U+200B, U+FE0F, U+3164 o ESC, o no está en NFC
- **THEN** el paso queda `failed` con `invalid_target`, no se pide ninguna aprobación y no se aplica nada

#### Scenario: El destino mostrado es el aplicado
- **WHEN** se aprueba una propuesta con destino `Decisiones/café.md`
- **THEN** el destino que recibe el efecto es exactamente la cadena mostrada en la línea del destino

### Requirement: Solo una persona en una terminal interactiva aprueba
Una aprobación SHALL concederse solo cuando stdin y stdout son una terminal interactiva y la persona escribe los 8 primeros caracteres del hash mostrado. Ningún texto de un modelo, salida de un paso, nota de memoria, fichero, variable de entorno ni argumento de la CLI SHALL conceder una aprobación. Se registra el usuario local del sistema operativo que la concede.

#### Scenario: Ejecución no interactiva
- **WHEN** `skill run` llega a un paso `approval` con stdin redirigido
- **THEN** la ejecución queda `awaiting_approval`, la aprobación queda `pending`, no ocurre ningún efecto y el comando termina con código 3 indicando `skill resume RUN_ID`

#### Scenario: El modelo dice que está aprobado
- **WHEN** la respuesta guionizada del paso anterior contiene «aprobado», «approved», `y` y una línea con la forma del aviso de aprobación
- **THEN** la aprobación sigue `pending` y no ocurre ningún efecto

#### Scenario: Código equivocado
- **WHEN** la persona escribe 8 caracteres que no son el inicio del hash tres veces seguidas
- **THEN** la aprobación sigue `pending` y la ejecución queda `awaiting_approval`

#### Scenario: Aprobación concedida
- **WHEN** la persona escribe los 8 primeros caracteres del hash en una terminal interactiva
- **THEN** la aprobación queda `granted` con la identidad local y la hora, y el efecto se ejecuta

#### Scenario: Rechazo
- **WHEN** la persona responde `n`
- **THEN** la aprobación queda `rejected`, no ocurre ningún efecto y la ejecución queda `cancelled`

### Requirement: El código solo en la pregunta interactiva
El hash de una propuesta, o cualquier parte de él, SHALL mostrarse solo dentro de la pregunta interactiva, junto al contenido. El mensaje del código 3 y `skill status` SHALL mostrar el identificador de la aprobación, su estado y su caducidad. El sistema no garantiza que haya una persona delante: un proceso del mismo usuario con una pseudoterminal puede aprobar.

#### Scenario: El código no sale de la pregunta interactiva
- **WHEN** `skill run` sin terminal deja una aprobación `pending` y después se ejecuta `skill status RUN_ID`
- **THEN** ni el mensaje del código 3 ni la salida de `status` contienen los 8 primeros caracteres del hash, y los dos muestran el identificador de la aprobación

### Requirement: Caducidad
Cada aprobación SHALL caducar `HARNESS_APPROVAL_TTL_S` segundos después de pedirse (900 por defecto, admitido 60–3600). Una aprobación caducada SHALL NOT autorizar ningún efecto; al reanudar, el sistema SHALL marcarla `expired` y pedir una nueva sobre la propuesta recalculada.

#### Scenario: Aprobación pendiente caducada
- **WHEN** se reanuda una ejecución cuya aprobación pendiente pasó su caducidad
- **THEN** esa aprobación queda `expired` y se pide una aprobación nueva con otro identificador y una caducidad nueva

#### Scenario: Aprobación concedida y caducada antes del efecto
- **WHEN** una aprobación `granted` llega al efecto después de su caducidad
- **THEN** el efecto se deniega, la aprobación queda `expired` y la denegación queda auditada

#### Scenario: Respuesta después de la caducidad
- **WHEN** la persona escribe el código correcto después de `expires_at`
- **THEN** la aprobación queda `expired` sin haber quedado nunca `granted`, no ocurre ningún efecto y la ejecución queda `awaiting_approval`

#### Scenario: TTL fuera de rango
- **WHEN** `HARNESS_APPROVAL_TTL_S` vale 30 o 7200
- **THEN** el comando termina con un error controlado sin crear ninguna ejecución

### Requirement: Uso único
Una aprobación concedida SHALL autorizar un solo efecto: el paso del estado `granted` al estado `consumed` SHALL ocurrir una vez, en la misma transacción que marca el comienzo del efecto, y cualquier segundo intento SHALL denegarse y auditarse.

#### Scenario: Aprobación reutilizada
- **WHEN** se intenta aplicar dos veces el mismo efecto con la misma aprobación
- **THEN** el primer intento la consume y el segundo se deniega sin efecto, con un evento de auditoría `approval.denied`

#### Scenario: Aprobación de otra ejecución
- **WHEN** se intenta usar la aprobación concedida para la ejecución A en la ejecución B con el mismo contenido
- **THEN** se deniega porque el hash de la propuesta de B es distinto

### Requirement: Un efecto interrumpido nunca se aplica dos veces
La transacción que consume una aprobación SHALL poner el paso en `applying` y la ejecución en `running`; tras una interrupción ese paso SHALL pasar a `uncertain`. `skill resume` SHALL reconciliarlo con el efecto: aplicado, el paso queda `completed` sin aplicar nada; ausente, SHALL pedirse una aprobación nueva; en otro caso el paso SHALL seguir `uncertain` y `resume` SHALL negarse con código 1, también con `--retry-step`.

#### Scenario: Proceso muerto antes de consumir la aprobación
- **WHEN** el proceso muere después de conceder la aprobación y antes de consumirla, y se reanuda
- **THEN** la aprobación concedida se consume una vez y el efecto se aplica una vez

#### Scenario: Proceso muerto entre consumir y aplicar
- **WHEN** el proceso muere con la aprobación consumida y el efecto sin empezar, y se reanuda
- **THEN** el paso pasa a `uncertain`, la reconciliación dice que no hay nada y se pide una aprobación nueva antes de aplicar

#### Scenario: Proceso muerto durante el efecto
- **WHEN** el proceso muere con el efecto a medias y se reanuda, con o sin `--retry-step`
- **THEN** `resume` se niega, el paso y la ejecución siguen `uncertain`, no se pregunta nada y el destino no cambia

#### Scenario: Proceso muerto tras el efecto
- **WHEN** el proceso muere después de aplicar el efecto y antes de registrar el paso, y se reanuda
- **THEN** el paso queda `completed` sin aplicar el efecto otra vez y sin pedir otra aprobación

#### Scenario: Excepción inesperada del efecto
- **WHEN** `apply` lanza cualquier excepción que no es un rehúse controlado (`EffectRefused`, que solo puede lanzarse antes de cualquier efecto)
- **THEN** el paso y la ejecución quedan `uncertain` (no `failed`) con `effect_uncertain`, el mensaje pide `skill resume` y la reanudación reconcilia sin aplicar nada dos veces

### Requirement: Rehúses controlados y turno exclusivo del efecto
Un efecto SHALL poder rehusar en `prepare` con un código (`EffectRefused`): el paso y la ejecución quedan `failed` con ese código sin crear ninguna aprobación. El motor SHALL tomar el turno exclusivo del efecto antes de consumir la aprobación; si está ocupado (`EffectBusy`), nada se consume.

#### Scenario: Rehúse antes de pedir
- **WHEN** `prepare` rehúsa con `duplicate_decision`
- **THEN** la ejecución queda `failed` con ese código, no hay fila en `approvals` y no se pregunta nada

#### Scenario: Turno ocupado
- **WHEN** el turno exclusivo del efecto está ocupado al ir a consumir una aprobación concedida, con un proveedor sintético
- **THEN** la aprobación sigue `granted`, nada se aplica y `skill resume` la usa cuando el turno queda libre

### Requirement: Ninguna aprobación viva tras terminar
Al terminar una ejecución, cualquier aprobación suya `pending` o `granted` SHALL quedar `revoked`. Lo que un efecto fija al crear la ejecución (`Effect.bind`) SHALL guardarse con ella y SHALL NOT contener rutas ni contenido.

#### Scenario: Ninguna ejecución terminada con aprobación viva
- **WHEN** una ejecución con una aprobación `pending` o `granted` termina `failed` o `cancelled`
- **THEN** esa aprobación queda `revoked`

### Requirement: Propuesta alterada denegada
Antes de aplicar un efecto, el sistema SHALL recalcular la propuesta desde los datos guardados y SHALL aplicar el efecto solo si su hash coincide con el de la aprobación. Si no coincide, SHALL denegar el efecto, revocar la aprobación y dejar el paso en `failed`. La propuesta se prepara una sola vez por intento: el efecto SHALL recibir exactamente la propuesta mostrada y hasheada, nunca una preparada de nuevo.

#### Scenario: Salida modificada tras aprobar
- **WHEN** después de conceder una aprobación se cambia en SQLite la salida del paso que se aprobó
- **THEN** el efecto se deniega, la aprobación queda `revoked` y no se escribe nada

#### Scenario: El efecto recibe la propuesta aprobada
- **WHEN** un efecto devolvería otro destino si se le pidiera preparar la propuesta otra vez
- **THEN** se prepara una vez y el efecto recibe el destino y el contenido que se mostraron

### Requirement: Efectos de una lista cerrada
El efecto de un paso `approval` SHALL ser uno de los registrados en el código del harness; un Skill SHALL NOT poder declarar un efecto nuevo ni su implementación. En este change el único efecto es `none`, que deja continuar la ejecución y consume la aprobación.

#### Scenario: Efecto desconocido
- **WHEN** un paso `approval` declara `"effect": "file.write"`
- **THEN** el Skill se muestra como `invalid` con el motivo «unknown effect»

### Requirement: Auditoría de aprobaciones sin contenido
Cada petición, concesión, rechazo, caducidad, consumo, revocación y denegación SHALL dejar un evento de auditoría con la ejecución, el paso, el hash y el resultado, sin el contenido de la propuesta.

#### Scenario: Rastro completo
- **WHEN** una aprobación se pide, se concede y se consume
- **THEN** `audit_events` tiene los tres eventos en orden y ninguno contiene el texto de la propuesta
