# Spec Delta

## ADDED Requirements

### Requirement: Recursos del proveedor con vida de conversación
Un proveedor SHALL poder abrir sus recursos una vez para una serie de preguntas y cerrarlos al final. Entre la apertura y el cierre, cada pregunta SHALL conservar sus propios estados y reglas, incluida la de no reenviar. Un proveedor sin recursos que conservar SHALL funcionar igual con o sin apertura.

#### Scenario: Una apertura para varias preguntas
- **WHEN** una conversación hace tres preguntas a un proveedor que abre recursos
- **THEN** el proveedor abre sus recursos una vez y los cierra una vez, al terminar la conversación

#### Scenario: Cierre aunque una pregunta falle
- **WHEN** una pregunta de la conversación termina en `failed` o `uncertain` y la persona sale
- **THEN** los recursos del proveedor quedan cerrados

#### Scenario: Pregunta suelta sin cambios
- **WHEN** se ejecuta `ask` como orden suelta
- **THEN** el resultado y lo registrado son los mismos que antes de existir la apertura
