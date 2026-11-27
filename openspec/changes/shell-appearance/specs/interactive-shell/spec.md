# Spec Delta

## ADDED Requirements

### Requirement: Terminal con estilo y respaldo plano
Al entrar en la conversación desde una consola, el sistema SHALL usar la terminal con estilo (colores, edición de línea, completado y línea de estado). El sistema SHALL usar el texto plano de la conversación, sin colores ni movimientos de cursor, cuando la persona lo pide con `chat --plain` o con `HARNESS_PLAIN`, cuando `NO_COLOR` tiene valor, cuando `TERM` es `dumb` o cuando la consola no se puede manejar con estilo.

#### Scenario: Consola con estilo
- **WHEN** la persona ejecuta `chat` en una consola sin ninguna de esas indicaciones
- **THEN** la cabecera muestra la línea de estado con colores y la conversación queda esperando una línea

#### Scenario: Texto plano pedido
- **WHEN** la persona ejecuta `chat --plain`, o `chat` con `NO_COLOR=1`, `TERM=dumb` o `HARNESS_PLAIN=1`
- **THEN** la conversación muestra la cabecera de texto plano y la salida no contiene ninguna secuencia de escape

#### Scenario: Consola que no se puede manejar
- **WHEN** la terminal con estilo no se puede crear en la consola actual
- **THEN** la conversación se abre igual, en texto plano

### Requirement: Respuesta con formato y marca intacta
En la terminal con estilo, el sistema SHALL resaltar en las respuestas un subconjunto de Markdown sin quitar ni añadir ningún carácter respecto al texto plano, y toda fila de texto ajeno SHALL empezar por la misma marca que en el texto plano.

#### Scenario: Mismo texto con y sin colores
- **WHEN** una respuesta con Markdown se muestra en la terminal con estilo y se le quitan los colores
- **THEN** las filas son exactamente las que muestra el texto plano para esa respuesta

#### Scenario: Respuesta que imita la línea de estado
- **WHEN** una respuesta contiene una línea con la forma de la línea de estado, de un aviso de aprobación o de una línea `applied:`
- **THEN** esa línea aparece tras la marca de texto ajeno y con el estilo del texto ajeno

### Requirement: Formato sin órdenes de terminal
El resaltado SHALL hacerse sobre el texto ya saneado, y ningún enlace, imagen o HTML de una respuesta SHALL convertirse en un hiperenlace, una imagen o una orden de la terminal.

#### Scenario: Respuesta con secuencias y enlaces
- **WHEN** una respuesta contiene secuencias de escape, un hiperenlace de terminal o un enlace Markdown
- **THEN** la terminal no recibe ninguna secuencia procedente de la respuesta y el enlace se ve como texto

#### Scenario: Texto adversario grande
- **WHEN** una respuesta de 1 MiB está hecha para forzar el análisis del Markdown
- **THEN** se muestra en un tiempo proporcional a su tamaño

### Requirement: Línea de estado de la sesión tomada
La línea de estado SHALL mostrar solo el proyecto de la sesión tomada, el nombre del proveedor configurado y los 8 primeros caracteres de la sesión tomada, leídos del propio harness cada vez que se muestra. SHALL NOT mostrar texto del proveedor, de la memoria ni de otra sesión.

#### Scenario: Cambio de sesión
- **WHEN** la persona cambia de sesión con `/new` o `/resume`
- **THEN** la línea de estado siguiente muestra la sesión nueva y ninguna parte de la anterior

### Requirement: Indicador mientras el proveedor trabaja
En la terminal con estilo, mientras el proveedor prepara una respuesta el sistema SHALL mostrar en una sola línea el proveedor y los segundos transcurridos, y SHALL borrarla al terminar la pregunta, también si se interrumpe.

#### Scenario: Pregunta en curso
- **WHEN** la persona envía una pregunta y el proveedor tarda varios segundos
- **THEN** se ve una línea con el proveedor y los segundos que pasan, y desaparece antes de la respuesta

### Requirement: Edición e historial de entradas
En la terminal con estilo, la persona SHALL poder editar la línea y recuperar con las flechas las líneas que escribió en la conversación durante esa ejecución. El historial de entradas SHALL existir solo en memoria y SHALL NOT contener lo escrito en el aviso de aprobación.

#### Scenario: Recuperar una línea
- **WHEN** la persona pulsa la flecha arriba en la espera de línea
- **THEN** aparece la última línea que escribió, para editarla o enviarla

#### Scenario: El código de aprobación no se recuerda
- **WHEN** la persona aprueba un Skill escribiendo el código y después pulsa la flecha arriba
- **THEN** aparece la línea anterior de la conversación y nunca el código

#### Scenario: Nada en disco
- **WHEN** termina una conversación con la terminal con estilo
- **THEN** no existe ningún fichero con las líneas que escribió la persona

### Requirement: Completado de comandos
En la terminal con estilo, Tab SHALL completar el nombre de un comando que empieza por `/`, el número de `/resume` entre los de la última `/sessions`, el nombre de un Skill disponible en `/skill` y una ruta en `/file`. Una ruta con caracteres de control o invisibles SHALL NOT ofrecerse. Fuera de una línea que empieza por `/`, y en el aviso de aprobación, Tab SHALL NOT completar nada.

#### Scenario: Comando a medias
- **WHEN** la persona escribe `/sta` y pulsa Tab
- **THEN** la línea pasa a ser `/status`

#### Scenario: Ruta con caracteres de control
- **WHEN** hay en la carpeta un fichero cuyo nombre contiene una secuencia de escape y la persona completa `/file` con su inicial
- **THEN** ese nombre no se ofrece

### Requirement: Interrupción y aprobación en la terminal con estilo
En la terminal con estilo, Ctrl+C y la aprobación SHALL comportarse como en el texto plano: en la espera de línea no cierra la conversación; durante una pregunta la deja `uncertain` sin reenviarla; mientras el proveedor abre, el primero termina la conversación con código 130; en el aviso de aprobación deja la aprobación sin decidir. Una `n` en el aviso SHALL seguir necesitando la palabra `reject` para rechazar. Un pegado de varias líneas en un aviso SHALL contar como una sola respuesta.

#### Scenario: Ctrl+C a media línea
- **WHEN** la persona escribe parte de una línea y pulsa Ctrl+C en la terminal con estilo
- **THEN** la conversación sigue abierta y no se registra ninguna solicitud

#### Scenario: Ctrl+C durante la pregunta
- **WHEN** la persona pulsa Ctrl+C con una pregunta ya enviada en la terminal con estilo
- **THEN** la solicitud queda `uncertain`, no se reenvía y la conversación espera otra línea

#### Scenario: Aprobación con estilo
- **WHEN** la persona escribe el código correcto en el aviso de aprobación de la terminal con estilo
- **THEN** el efecto se aplica una vez y la aprobación queda consumida

#### Scenario: Pegado de rechazo
- **WHEN** la persona pega en el aviso de aprobación las líneas `n` y `reject` de una vez
- **THEN** la aprobación no se rechaza por ese pegado
