# interactive-shell (delta)

## ADDED Requirements

### Requirement: Botones de la caja de aprobación
En la pantalla completa, la caja de aprobación SHALL decidir con dos botones del harness, aprobar y rechazar. Los botones SHALL estar fijos en la parte inferior de la caja, fuera del área del contenido propuesto. La caja SHALL NOT tener una entrada de texto. Una sola pulsación SHALL decidir la caja, como mucho una vez.

#### Scenario: Aprobar con Tab y Enter
- **WHEN** se ha mostrado la propuesta entera, la persona pulsa Tab una vez y después Enter varias veces
- **THEN** la aprobación se concede una sola vez, el efecto se aplica una vez y la auditoría registra que se concedió con un botón

#### Scenario: Doble clic en aprobar
- **WHEN** la persona hace doble clic en el botón de aprobar
- **THEN** la aprobación se concede y se consume una sola vez

### Requirement: Nada aprueba al abrirse la caja
Al abrirse la caja, el foco SHALL estar en la propuesta y no en un botón. Los dos botones SHALL estar deshabilitados durante un intervalo mínimo desde que la caja se abrió. Enter, Espacio, un pegado, `ctrl+v`, lo escrito antes de que la caja existiera y los clics de ese intervalo SHALL NOT decidir.

#### Scenario: Teclas y pegados al abrir
- **WHEN** con la caja abierta y la propuesta entera mostrada, llegan Enter, Espacio, `ctrl+v` y un pegado de varias líneas
- **THEN** la caja sigue abierta, el foco sigue en la propuesta y la aprobación sigue pendiente

#### Scenario: Durante el intervalo mínimo
- **WHEN** antes del intervalo mínimo llegan Tab, Enter, Espacio y clics sobre los dos botones
- **THEN** ningún botón recibe el foco ni la pulsación, y la aprobación sigue pendiente

#### Scenario: Escrito por adelantado
- **WHEN** la persona envía la línea del Skill y, en la misma ráfaga, Tab y Enter repetidos
- **THEN** la caja se abre y la aprobación sigue pendiente

### Requirement: Aprobar solo tras mostrar la propuesta entera
El botón de aprobar SHALL estar deshabilitado mientras el final de la propuesta no se haya mostrado en pantalla. Desplazarse hasta el final con el teclado, con la rueda o con la barra SHALL contar como mostrado. La caja SHALL decir cuántas líneas quedan por debajo, o que la propuesta se ha mostrado entera.

#### Scenario: Propuesta larga
- **WHEN** la propuesta tiene 120 líneas y la persona pulsa Tab o hace clic en aprobar sin haber bajado al final
- **THEN** Tab lleva al botón de rechazar, el clic no decide y la caja dice cuántas líneas quedan; tras bajar al final, el botón de aprobar se habilita y aprueba

#### Scenario: Rueda hasta el final
- **WHEN** la persona baja con la rueda del ratón hasta el final de una propuesta larga
- **THEN** el botón de aprobar se habilita

### Requirement: Rechazar con su pregunta
El botón de rechazar SHALL abrir dentro de la caja una pregunta de confirmación con el foco en volver. Solo la confirmación explícita SHALL rechazar. Volver o Escape SHALL dejar la aprobación pendiente. Una confirmación llegada antes del intervalo mínimo desde que apareció la pregunta SHALL NOT rechazar.

#### Scenario: Volver
- **WHEN** la persona pulsa rechazar y después Enter, o Escape
- **THEN** la caja vuelve a sus botones y la aprobación sigue pendiente

#### Scenario: Rechazo confirmado
- **WHEN** la persona pulsa rechazar y después la confirmación
- **THEN** la aprobación queda rechazada, la ejecución cancelada, no se aplica ningún efecto y la auditoría registra que se rechazó con un botón

#### Scenario: Doble clic en rechazar
- **WHEN** el segundo clic de un doble clic sobre rechazar cae en la confirmación
- **THEN** no se rechaza y la aprobación sigue pendiente

### Requirement: Salir de la caja sin decidir
Escape SHALL NOT decidir. `ctrl+c` y `ctrl+q` SHALL dejar la aprobación pendiente. Ningún atajo de la aplicación SHALL pulsar un botón de la caja.

#### Scenario: Escape y ctrl+q
- **WHEN** con la caja abierta la persona pulsa Escape y después `ctrl+q`
- **THEN** la caja sigue abierta tras Escape, la conversación sale tras `ctrl+q` y la aprobación sigue pendiente

#### Scenario: Atajos de la aplicación
- **WHEN** con la caja abierta llegan `ctrl+n`, `ctrl+p`, `ctrl+d`, `ctrl+a`, `ctrl+e` y `ctrl+k`
- **THEN** la caja sigue abierta, no se crea ninguna sesión y la aprobación sigue pendiente

### Requirement: Botones que el texto ajeno no puede imitar ni pulsar
Un contenido propuesto que dibuje una fila de botones SHALL mostrarse como texto dentro del área ajena, por encima de la fila real. Un clic, Enter o Espacio sobre ese texto SHALL NOT decidir.

#### Scenario: Botones dibujados por la respuesta
- **WHEN** la propuesta contiene `[ Approve ]        [ Reject ]` y la persona hace clic sobre ese texto
- **THEN** la caja tiene solo sus botones reales, debajo del área ajena, y la aprobación sigue pendiente
