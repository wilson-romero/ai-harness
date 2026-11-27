# Spec Delta

## ADDED Requirements

### Requirement: Tablas de una respuesta alineadas por el harness
Una tabla de Markdown en una respuesta del proveedor SHALL mostrarse como texto alineado: cada columna del ancho de su contenido medido en celdas de la terminal, la cabecera separada por una raya y cada columna alineada según su marca (`:--`, `:-:`, `--:`). Los únicos caracteres que el harness añade SHALL ser `│`, `─`, `┼` y espacios, sin fondo; el texto de las celdas SHALL mantener sus caracteres.

#### Scenario: Tabla con alineaciones
- **WHEN** el proveedor responde con una tabla de tres columnas, la segunda centrada y la tercera a la derecha
- **THEN** cada columna empieza en la misma posición en todas sus filas, una raya separa la cabecera y la tercera columna queda alineada a la derecha

#### Scenario: Ni recuadro ni fondo
- **WHEN** se muestra una tabla de una respuesta
- **THEN** lo que el harness añade no tiene esquinas ni fondo

### Requirement: Tabla partida dentro de sus columnas
Si una tabla de una respuesta es más ancha que el panel, sus celdas SHALL partirse dentro de su columna sin perder texto y ninguna fila SHALL pasar del ancho.

#### Scenario: Tabla más ancha que el panel
- **WHEN** una celda de la tabla no cabe en el ancho del panel
- **THEN** la celda ocupa varias filas dentro de su columna, ninguna fila pasa del ancho y se leen todas sus palabras en orden

### Requirement: Tabla que no se alinea
Una tabla mal formada, una que no cabe en el panel ni estrechando cada columna a 3 celdas, o una de más de 200 filas, 16 columnas o 1000 caracteres en una celda SHALL mostrarse como llegó.

#### Scenario: Fila con más celdas que la cabecera
- **WHEN** una fila de la tabla tiene más celdas que su cabecera
- **THEN** la tabla se ve tal como llegó

#### Scenario: Tabla de 201 filas
- **WHEN** el proveedor responde con una tabla de 201 filas
- **THEN** la tabla se ve tal como llegó

### Requirement: Bloque de código con su lenguaje
Las líneas de la valla de un bloque de código de una respuesta SHALL sustituirse por una raya con la etiqueta del lenguaje, que solo puede ser una palabra corta y si no es `code`, y una raya de cierre. Las líneas de código SHALL mostrarse sin cambios. Dentro de un bloque de código, una tabla SHALL mostrarse como código.

#### Scenario: Bloque de Python
- **WHEN** una respuesta contiene un bloque de código marcado `python`
- **THEN** en lugar de las vallas se ven una raya que empieza por `── python ` y una raya de cierre, y el código entre ellas tal cual

#### Scenario: Etiqueta que imita el chrome
- **WHEN** la información de la valla es `Approve? ──┼── yes`
- **THEN** la etiqueta de la raya es `code`

### Requirement: Misma tabla en texto plano
El texto plano SHALL mostrar las tablas y los bloques de código de una respuesta con la misma disposición que la pantalla completa, sin color, y cada fila con la marca del texto ajeno. Sin colores, las filas de la pantalla completa SHALL ser exactamente las del texto plano para el mismo ancho.

#### Scenario: Conversación en texto plano
- **WHEN** en `chat --plain` el proveedor responde con una tabla y un bloque de código
- **THEN** la tabla se ve alineada y el bloque entre rayas, sin secuencias de color y sin las vallas

### Requirement: Respuesta entera al llegar
En la pantalla completa, una respuesta del proveedor SHALL llegar entera, salvo que pase de 64 000 caracteres, en cuyo caso SHALL llegar plegada a su vista previa con el pie de las líneas que faltan. La persona SHALL poder plegarla y abrirla a mano, y los turnos anteriores al penúltimo SHALL seguir plegándose al enviar una línea. Este requisito sustituye, para las respuestas del proveedor, a «Vista previa de una respuesta larga».

#### Scenario: Respuesta de 73 líneas
- **WHEN** el proveedor responde con 73 líneas en un panel de 30 filas
- **THEN** la respuesta está entera, sin el pie de líneas que faltan, y `ctrl+o` la pliega a su línea

#### Scenario: Respuesta de más de 64 000 caracteres
- **WHEN** el proveedor responde con más de 64 000 caracteres
- **THEN** la respuesta llega plegada a su vista previa con el pie de las líneas que faltan

### Requirement: El principio de la respuesta a la vista
Cuando llega una respuesta más alta que el panel y el panel seguía el final, el panel SHALL mostrar el principio de la respuesta y el pie del harness SHALL decir cuántas filas quedan debajo, hasta que la persona llegue al final. Una respuesta que cabe SHALL dejar el final a la vista, sin ese aviso.

#### Scenario: Respuesta más alta que el panel
- **WHEN** llega una respuesta más alta que el panel
- **THEN** su cabecera está en la primera fila del panel y el pie empieza por `↓` y el número de filas que quedan debajo

#### Scenario: Leer hasta el final
- **WHEN** tras esa respuesta la persona baja hasta el final
- **THEN** el pie ya no dice que quedan filas debajo

#### Scenario: Respuesta que cabe
- **WHEN** llega una respuesta de dos líneas
- **THEN** se ve el final del panel y el pie no dice que quedan filas debajo

### Requirement: Cuándo se coloca una respuesta
Si llegan varias respuestas seguidas, SHALL colocarse en su principio solo la última. Si la persona recorría los bloques o leía más arriba, o empieza a recorrerlos o envía una línea antes de que la respuesta se coloque, el panel SHALL NOT ir al principio de la respuesta.

#### Scenario: Recorrer los bloques al final
- **WHEN** la persona recorre los bloques con el panel en su final y llega una respuesta más alta que el panel
- **THEN** el panel no se mueve, ni al final ni al principio de la respuesta

#### Scenario: Línea enviada antes de colocar la respuesta
- **WHEN** llega una respuesta más alta que el panel y la persona envía una línea antes de que la pantalla la haya colocado
- **THEN** el panel queda en su final

#### Scenario: Varias respuestas seguidas
- **WHEN** llegan diez respuestas más altas que el panel antes de que la pantalla se redibuje
- **THEN** la cabecera de la última está en la primera fila del panel
