# request-recovery Specification

## Purpose

Garantiza que una pregunta interrumpida nunca se pierde en silencio ni se envía dos veces: queda marcada como incierta y es el usuario quien decide qué hacer con ella.

## Requirements

### Requirement: Solicitud interrumpida marcada como incierta
Al arrancar, el sistema SHALL pasar a `uncertain` toda solicitud que siga en `pending` o `running` y cuyo proceso ya no exista, y SHALL dejar su sesión en estado `uncertain`.

#### Scenario: Proceso muerto a mitad de una pregunta
- **WHEN** el proceso que ejecuta `ask` muere sin terminar y el usuario ejecuta después cualquier comando
- **THEN** esa solicitud aparece en `history` como `uncertain`
- **AND** `session list` muestra la sesión en estado `uncertain`

#### Scenario: Interrupción con Ctrl+C
- **WHEN** el usuario interrumpe `ask` con Ctrl+C después de que el prompt haya salido
- **THEN** la solicitud queda en `uncertain` antes de que el proceso termine

### Requirement: Sin reenvío automático
El sistema SHALL NOT volver a enviar al proveedor una solicitud en `uncertain`, `timeout` o `failed`. Solo una orden nueva y explícita del usuario SHALL producir un envío, registrado como una solicitud distinta.

#### Scenario: La recuperación no reenvía
- **WHEN** el sistema recupera una solicitud interrumpida al arrancar
- **THEN** el proveedor no recibe ninguna llamada durante la recuperación

#### Scenario: Repetir es una solicitud nueva
- **WHEN** el usuario vuelve a ejecutar `ask` con el mismo texto tras una solicitud `uncertain`
- **THEN** se registra una solicitud nueva con otro identificador y la anterior sigue en `uncertain`

### Requirement: Una solicitud viva no se toca
El sistema SHALL NOT marcar como `uncertain` una solicitud que otro proceso todavía está ejecutando.

#### Scenario: Listar mientras otra pregunta sigue en curso
- **WHEN** un proceso tiene una pregunta en curso en la sesión A y otro proceso ejecuta `session list`
- **THEN** la solicitud en curso conserva su estado y termina en `completed` cuando el proveedor responde

### Requirement: Una pregunta a la vez por sesión
El sistema SHALL rechazar una pregunta en una sesión que ya tiene otra en curso, sin registrar una solicitud nueva. Preguntas simultáneas en sesiones distintas SHALL poder completarse.

#### Scenario: Segunda pregunta en la misma sesión
- **WHEN** un proceso tiene una pregunta en curso en la sesión A y otro ejecuta `ask A "otra"`
- **THEN** el segundo termina con código distinto de 0, indica que la sesión está ocupada y no registra ninguna solicitud

#### Scenario: Preguntas en sesiones distintas
- **WHEN** dos procesos preguntan a la vez en las sesiones A y B
- **THEN** las dos solicitudes terminan en `completed`

### Requirement: La sesión vuelve a activa con una pregunta completada
Una sesión en estado `uncertain` SHALL avisar de la solicitud incierta pendiente al recibir una pregunta nueva y SHALL volver a `active` cuando esa pregunta nueva se complete.

#### Scenario: Aviso y vuelta a activa
- **WHEN** el usuario ejecuta `ask` en una sesión en estado `uncertain` y la pregunta se completa
- **THEN** el sistema avisa por stderr de que hay una solicitud anterior incierta y la sesión queda en `active`
- **AND** la solicitud anterior sigue en `uncertain` en el historial
