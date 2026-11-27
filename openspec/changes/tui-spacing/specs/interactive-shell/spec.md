## ADDED Requirements

### Requirement: Colores del tema con nombre
Todo color de la pantalla completa SHALL salir de una variable del tema de Textual nombrada por su función; el código de la pantalla SHALL NOT contener colores propios. Ningún estilo aplicado a texto ajeno SHALL usar el color de un estado del harness, un fondo o el vídeo inverso. El marco del texto ajeno SHALL ser de un color que no usa ningún estado.

#### Scenario: Tema de terminal ANSI
- **WHEN** la pantalla se dibuja con un tema ANSI
- **THEN** todos los colores de la pantalla se resuelven con el tema y el texto ajeno sigue sin colores de estado

#### Scenario: Marco del texto ajeno
- **WHEN** se muestra una respuesta del proveedor
- **THEN** su marco no tiene el color de un error, de un aviso, de la aprobación ni de la barra de la persona

### Requirement: Panel lateral solo donde cabe
El panel lateral SHALL mostrarse solo con 100 columnas o más. Por debajo, la conversación SHALL ocupar todo el ancho, y `/status` SHALL dar los mismos datos que el panel: sesión, proyecto, proveedor, número de peticiones, estado de la última y notas de memoria de la última pregunta.

#### Scenario: Terminal de 80 columnas
- **WHEN** la terminal mide 80×24
- **THEN** no se ve el panel lateral y la conversación ocupa las 80 columnas

#### Scenario: Datos del panel con `/status`
- **WHEN** tras una pregunta la persona escribe `/status`
- **THEN** la respuesta incluye el número de peticiones y cuántas notas de memoria llevó la última pregunta

### Requirement: Mensajes de la persona marcados por la forma
Cada mensaje de la persona SHALL llevar una barra a la izquierda y un fondo propio, con una fila en blanco encima. La barra SHALL bastar para reconocerlo cuando el tema no dibuja fondos.

#### Scenario: Tema sin fondos
- **WHEN** la pantalla usa un tema ANSI y se muestra un mensaje de la persona
- **THEN** la barra se dibuja a su izquierda y las líneas del harness no llevan barra

### Requirement: Una columna para el texto
El texto de la persona, las líneas del harness, el texto ajeno dentro de su marco y lo que se escribe en la entrada SHALL empezar en la misma columna a 80×24, 100×30 y 120×40.

#### Scenario: Tres tamaños
- **WHEN** la conversación tiene una pregunta, una respuesta y una línea del harness a cada uno de los tres tamaños
- **THEN** todos sus textos y la entrada empiezan en la misma columna

### Requirement: Huecos verticales según el alto
Con 30 filas o más, SHALL haber una fila en blanco delante de cada bloque de la conversación, salvo el primero del panel. Con menos de 30, las líneas del harness SHALL ir sin fila en blanco y la entrada SHALL ocupar 2 filas. El pie SHALL verse siempre. Las filas de conversación visibles SHALL ser al menos las de antes de este cambio.

#### Scenario: Terminal de 24 filas
- **WHEN** la terminal mide 80×24
- **THEN** la entrada ocupa 2 filas, el pie se ve debajo de ella y la conversación tiene al menos 20 filas visibles

#### Scenario: Terminal de 40 filas
- **WHEN** la terminal mide 120×40
- **THEN** hay una fila en blanco delante de cada bloque salvo el primero, la entrada ocupa 3 filas y la conversación tiene al menos 36 filas visibles
