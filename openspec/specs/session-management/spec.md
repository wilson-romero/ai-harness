# session-management Specification

## Purpose

Permite mantener varias conversaciones de trabajo independientes y persistentes en local: crearlas, listarlas y consultar su historial sin que una sesión vea datos de otra.

## Requirements

### Requirement: Crear una sesión
El sistema SHALL crear una sesión a partir de un nombre no vacío y devolver su identificador único. La sesión nueva SHALL quedar en estado `created`, asociada al proveedor configurado, con fechas de creación y actualización en UTC y, si se indica, con un proyecto.

#### Scenario: Sesión creada con nombre
- **WHEN** el usuario ejecuta `session create "Arquitectura WhatsApp"`
- **THEN** el sistema imprime el identificador de la sesión nueva y termina con código 0
- **AND** `session list` muestra esa sesión con estado `created`

#### Scenario: Nombre vacío rechazado
- **WHEN** el usuario ejecuta `session create ""`
- **THEN** el sistema informa del error por stderr, termina con código distinto de 0 y no crea ninguna sesión

### Requirement: Listar sesiones
El sistema SHALL listar todas las sesiones con su identificador, nombre, proyecto, proveedor, estado y fecha de actualización, de la más reciente a la más antigua.

#### Scenario: Tres sesiones listadas
- **WHEN** existen tres sesiones y el usuario ejecuta `session list`
- **THEN** la salida contiene exactamente esas tres sesiones, cada una con su identificador y estado

#### Scenario: Lista vacía
- **WHEN** no existe ninguna sesión y el usuario ejecuta `session list`
- **THEN** el sistema indica que no hay sesiones y termina con código 0

### Requirement: Historial por sesión
El sistema SHALL mostrar el historial de una sesión en orden cronológico, con el rol de cada mensaje y el estado de la solicitud a la que pertenece.

#### Scenario: Historial tras dos preguntas
- **WHEN** una sesión ha completado dos preguntas y el usuario ejecuta `history SESSION_ID`
- **THEN** la salida muestra cuatro mensajes en orden: pregunta, respuesta, pregunta, respuesta

#### Scenario: Solicitud sin respuesta visible en el historial
- **WHEN** una solicitud de la sesión terminó en `failed`, `timeout` o `uncertain`
- **THEN** el historial muestra la pregunta con ese estado y ninguna respuesta inventada

### Requirement: Aislamiento entre sesiones
El sistema SHALL devolver en cada consulta únicamente datos de la sesión pedida. El sistema SHALL rechazar en el almacenamiento un mensaje cuya solicitud pertenezca a otra sesión.

#### Scenario: El historial no mezcla sesiones
- **WHEN** las sesiones A y B tienen preguntas distintas y el usuario ejecuta `history A`
- **THEN** la salida no contiene ningún mensaje de B

#### Scenario: Mensaje cruzado rechazado
- **WHEN** se intenta guardar en la sesión B un mensaje ligado a una solicitud de la sesión A
- **THEN** el almacenamiento rechaza la escritura y no queda ningún mensaje nuevo

### Requirement: Persistencia tras reinicio
El sistema SHALL conservar sesiones, solicitudes e historial entre ejecuciones del proceso, en el directorio de datos configurado.

#### Scenario: Historial disponible en un proceso nuevo
- **WHEN** el usuario crea una sesión, hace una pregunta y ejecuta `history SESSION_ID` en un proceso posterior
- **THEN** la salida muestra la misma pregunta y la misma respuesta

### Requirement: Identificadores validados
El sistema SHALL aceptar como identificador de sesión solo un UUID completo y SHALL responder con un error controlado, sin traza de excepción, ante un identificador mal formado o inexistente.

#### Scenario: Identificador mal formado
- **WHEN** el usuario ejecuta `history no-es-un-uuid`
- **THEN** el sistema informa por stderr de que el identificador no es válido y termina con código distinto de 0

#### Scenario: Sesión inexistente
- **WHEN** el usuario ejecuta `ask` con un UUID válido que no corresponde a ninguna sesión
- **THEN** el sistema informa por stderr de que la sesión no existe, termina con código distinto de 0 y no registra ninguna solicitud

### Requirement: Esquema migrable y repetible
El sistema SHALL llevar el almacenamiento a la versión de esquema vigente al arrancar y SHALL dejarlo intacto si ya está en esa versión.

#### Scenario: Primera ejecución sobre un directorio vacío
- **WHEN** el usuario ejecuta cualquier comando con un directorio de datos vacío
- **THEN** el almacenamiento queda creado en la versión vigente y el comando funciona

#### Scenario: Migrar dos veces no cambia nada
- **WHEN** el sistema arranca dos veces seguidas sobre el mismo directorio de datos
- **THEN** el segundo arranque no aplica ninguna migración y los datos existentes siguen iguales

### Requirement: Auditoría sin contenido
El sistema SHALL registrar un evento de auditoría por cada creación de sesión y por cada cambio de estado de una solicitud, con tipo, resultado, sesión y fecha. Un evento de auditoría SHALL NOT contener el texto de un prompt ni de una respuesta.

#### Scenario: La auditoría no guarda el prompt
- **WHEN** el usuario pregunta con un texto que contiene una cadena reconocible
- **THEN** existe un evento de auditoría de esa solicitud y esa cadena no aparece en ningún evento
