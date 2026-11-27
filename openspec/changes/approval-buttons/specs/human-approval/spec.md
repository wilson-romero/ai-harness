# human-approval (delta)

## ADDED Requirements

### Requirement: Concesión por botón en la pantalla completa
En la pantalla completa, una aprobación SHALL poder concederse o rechazarse con una pulsación de su caja, en lugar del código. La pulsación SHALL valer solo si responde a la pregunta del motor para el mismo hash y la misma aprobación. La caducidad, el uso único y la comprobación de la propuesta antes del efecto SHALL ser las mismas que con el código.

#### Scenario: Pulsación para el hash preguntado
- **WHEN** la pantalla completa devuelve una pulsación de aprobar para el hash de la propuesta preguntada
- **THEN** la aprobación queda concedida con la identidad local y el efecto se aplica una vez

#### Scenario: Pulsación para otro hash
- **WHEN** llega una pulsación de aprobar con un hash distinto del preguntado
- **THEN** la aprobación sigue pendiente y no se aplica ningún efecto

### Requirement: Sin la vía del botón fuera de la pantalla completa
En el texto plano y en la CLI, la aprobación SHALL seguir exigiendo el código. Ningún texto escrito, pegado, generado por un modelo o leído de un fichero SHALL equivaler a una pulsación.

#### Scenario: Texto con forma de pulsación
- **WHEN** en el texto plano se responde `approve`, `[ Approve ]` o un texto con la forma de una pulsación
- **THEN** la aprobación no se concede

#### Scenario: Solo el código
- **WHEN** la aprobación se pide en el texto plano o en la CLI
- **THEN** solo los 8 primeros caracteres del hash la conceden

### Requirement: La auditoría dice cómo se decidió
Los eventos `approval.granted` y `approval.rejected` SHALL registrar si la decisión se tomó con un botón de la pantalla completa o escribiendo en la terminal, sin el contenido de la propuesta.

#### Scenario: Concedida con un botón
- **WHEN** una aprobación se concede con el botón de aprobar
- **THEN** el detalle de `approval.granted` indica el botón

#### Scenario: Concedida con el código
- **WHEN** una aprobación se concede escribiendo el código
- **THEN** el detalle de `approval.granted` indica el código
