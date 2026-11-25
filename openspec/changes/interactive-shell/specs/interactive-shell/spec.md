# Spec Delta

## Purpose

Permite usar el harness como una conversación: se entra una vez, se escriben preguntas y comandos, y la sesión, la memoria del proyecto y las aprobaciones viven dentro de esa conversación hasta que la persona sale.

## ADDED Requirements

### Requirement: Entrar en la conversación
El sistema SHALL abrir una conversación con `chat`, y con el programa sin argumentos cuando la entrada y la salida son una terminal interactiva. Al entrar SHALL mostrar el proveedor, la sesión y, si lo hay, el proyecto. Sin terminal interactiva, `chat` SHALL terminar con error de uso sin crear ni tocar ninguna sesión.

#### Scenario: Entrada con terminal
- **WHEN** la persona ejecuta `chat` en una terminal interactiva
- **THEN** el sistema muestra una cabecera con proveedor y sesión y queda esperando una línea

#### Scenario: Entrada sin terminal
- **WHEN** `chat` se ejecuta con la entrada redirigida
- **THEN** el sistema termina con código de uso, lo explica por stderr y no existe ninguna sesión nueva

#### Scenario: Sin argumentos y sin terminal
- **WHEN** el programa se ejecuta sin argumentos y sin terminal interactiva
- **THEN** el sistema muestra la ayuda de uso y no abre ninguna conversación

### Requirement: Una línea es una pregunta
Dentro de la conversación, una línea que no empieza por `/` SHALL enviarse como una pregunta en la sesión de la conversación, con el mismo registro, estados y reglas que `ask`. El sistema SHALL mostrar la respuesta y volver a esperar. Una línea vacía SHALL ignorarse sin registrar ninguna solicitud.

#### Scenario: Pregunta respondida
- **WHEN** la persona escribe una línea de texto y el proveedor responde
- **THEN** la respuesta se muestra, la solicitud queda `completed` y el sistema espera otra línea

#### Scenario: Dos preguntas seguidas en la misma sesión
- **WHEN** la persona escribe dos líneas de texto, una tras otra
- **THEN** las dos solicitudes pertenecen a la misma sesión y `history` las muestra en orden

#### Scenario: Línea vacía
- **WHEN** la persona pulsa Intro sin escribir nada
- **THEN** no se registra ninguna solicitud y el sistema sigue esperando

#### Scenario: Pregunta fallida
- **WHEN** el proveedor informa de un error
- **THEN** el sistema muestra el estado `failed` y la conversación sigue abierta

### Requirement: Comandos con barra
Una línea que empieza por `/` SHALL tratarse como un comando de la conversación y SHALL NOT enviarse al proveedor. Un comando desconocido o mal formado SHALL producir un mensaje de error sin registrar ninguna solicitud. Una línea que empieza por `//` SHALL enviarse como pregunta con una sola barra inicial.

#### Scenario: Comando conocido
- **WHEN** la persona escribe `/help`
- **THEN** el sistema lista los comandos y el proveedor no recibe ninguna llamada

#### Scenario: Comando desconocido
- **WHEN** la persona escribe `/nada`
- **THEN** el sistema dice que el comando no existe y el proveedor no recibe ninguna llamada

#### Scenario: Pregunta que empieza por barra
- **WHEN** la persona escribe `//ruta/de/ejemplo es correcta?`
- **THEN** el proveedor recibe la pregunta `/ruta/de/ejemplo es correcta?`

### Requirement: Sesión de la conversación
Una conversación SHALL trabajar sobre una sola sesión a la vez: una nueva al entrar, o una existente indicada al entrar o elegida con `/resume` de la lista que muestra `/sessions`. `/new` SHALL cambiar a una sesión nueva. La conversación SHALL mostrar solo datos de su sesión.

#### Scenario: Sesión nueva por defecto
- **WHEN** la persona entra sin indicar sesión
- **THEN** existe una sesión nueva y las preguntas se registran en ella

#### Scenario: Reanudar una sesión existente
- **WHEN** la persona entra indicando una sesión con historial y escribe `/history`
- **THEN** el sistema muestra el historial de esa sesión y de ninguna otra

#### Scenario: Cambiar de sesión dentro de la conversación
- **WHEN** la persona escribe `/new` y después una pregunta
- **THEN** la pregunta se registra en la sesión nueva y la anterior no cambia

### Requirement: La conversación es dueña de su sesión
Mientras una conversación está abierta sobre una sesión, el sistema SHALL rechazar otra conversación y cualquier pregunta de otro proceso sobre esa sesión, sin registrar ninguna solicitud. Si el proceso de la conversación muere, la sesión SHALL quedar disponible sin intervención.

#### Scenario: Segunda conversación sobre la misma sesión
- **WHEN** una conversación está abierta sobre la sesión A y otro proceso ejecuta `chat` indicando A
- **THEN** el segundo termina diciendo que la sesión está ocupada

#### Scenario: Pregunta suelta sobre una sesión en conversación
- **WHEN** una conversación está abierta sobre la sesión A y otro proceso ejecuta `ask A "x"`
- **THEN** el segundo termina con error de sesión ocupada y no registra ninguna solicitud

#### Scenario: Conversación muerta
- **WHEN** el proceso de una conversación muere y otro proceso ejecuta `ask` sobre su sesión
- **THEN** la pregunta se acepta

### Requirement: Interrumpir una pregunta no cierra la conversación
Una interrupción de la persona durante una pregunta SHALL terminar esa solicitud con el estado que corresponda a si el prompt había salido, SHALL NOT reenviarla y SHALL devolver la conversación a la espera de otra línea. Una interrupción mientras se espera una línea SHALL NOT cerrar la conversación ni registrar nada.

#### Scenario: Interrupción después del envío
- **WHEN** la persona interrumpe una pregunta cuyo prompt ya salió
- **THEN** la solicitud queda `uncertain`, el sistema lo dice y espera otra línea

#### Scenario: Interrupción antes del envío
- **WHEN** la persona interrumpe una pregunta cuyo prompt no había salido
- **THEN** la solicitud no queda `uncertain` y el sistema espera otra línea

#### Scenario: Interrupción en la espera
- **WHEN** la persona interrumpe mientras el sistema espera una línea
- **THEN** la conversación sigue abierta y no hay ninguna solicitud nueva

#### Scenario: Pregunta siguiente tras una incierta
- **WHEN** la persona escribe otra pregunta después de una solicitud `uncertain`
- **THEN** el sistema avisa de la solicitud incierta anterior y registra la nueva como una solicitud distinta

### Requirement: Memoria del proyecto en la conversación
Cuando la sesión de la conversación tiene proyecto, cada pregunta SHALL llevar el contexto del proyecto con las mismas reglas de selección, límite, marcado como datos y procedencia que `ask --project`. `/memory` y `/context` SHALL mostrar lo mismo que `memory search` y `memory context`. Sin proyecto, las preguntas SHALL ir sin memoria.

#### Scenario: Pregunta con memoria
- **WHEN** la sesión tiene proyecto y la persona escribe una pregunta
- **THEN** el proveedor recibe el bloque de memoria marcado como datos y la procedencia queda registrada sin texto

#### Scenario: Sesión sin proyecto
- **WHEN** la sesión no tiene proyecto y la persona escribe una pregunta
- **THEN** el proveedor recibe solo la pregunta

#### Scenario: Contexto a la vista
- **WHEN** la persona escribe `/context`
- **THEN** el sistema muestra el mismo bloque que `memory context` para el proyecto de la sesión

### Requirement: Skills y aprobación dentro de la conversación
`/skill` SHALL ejecutar un Skill en la sesión de la conversación con las mismas reglas que `skill run`. Un paso de aprobación SHALL pedirse en la misma conversación con el mecanismo de aprobación existente. Un texto del modelo o una línea escrita fuera de ese aviso SHALL NOT contar como aprobación.

#### Scenario: Skill aprobado en la conversación
- **WHEN** la persona lanza con `/skill` un Skill con paso de aprobación y escribe el código correcto en el aviso
- **THEN** el efecto se aplica una vez y la conversación vuelve a esperar una línea

#### Scenario: Aprobación rechazada
- **WHEN** la persona rechaza el aviso de aprobación
- **THEN** el efecto no se aplica, la ejecución queda cancelada y la conversación sigue abierta

#### Scenario: Línea que parece una aprobación
- **WHEN** hay una ejecución esperando aprobación y la persona escribe el código como una línea normal, fuera del aviso
- **THEN** el efecto no se aplica y la línea se trata como una pregunta o un comando

### Requirement: Salida segura y distinguible
El sistema SHALL mostrar el texto del proveedor y de la memoria sin secuencias de control ni caracteres invisibles y con las credenciales de formato conocido enmascaradas, y de modo que ninguna línea de ese texto pueda confundirse con una línea del propio harness.

#### Scenario: Respuesta con secuencias de control
- **WHEN** la respuesta contiene secuencias de escape de terminal
- **THEN** la terminal no recibe ninguna secuencia de control procedente de la respuesta

#### Scenario: Respuesta que imita al harness
- **WHEN** la respuesta contiene una línea con la forma de un aviso de aprobación o de un mensaje de estado del harness
- **THEN** esa línea aparece marcada como texto del proveedor

### Requirement: Entrada acotada y ficheros adjuntos
El sistema SHALL rechazar una pregunta que supere el tamaño máximo admitido antes de registrar ninguna solicitud. `/file` SHALL añadir a la siguiente pregunta el contenido de un fichero normal dentro del límite, y SHALL rechazar un fichero que no sea normal, que no sea texto o que lo supere.

#### Scenario: Pregunta demasiado grande
- **WHEN** la persona escribe una pregunta mayor que el límite
- **THEN** el sistema lo rechaza con el tamaño y el límite, y no registra ninguna solicitud

#### Scenario: Fichero adjunto
- **WHEN** la persona escribe `/file` con un fichero de texto dentro del límite y después una pregunta
- **THEN** el proveedor recibe la pregunta con el contenido del fichero marcado como datos

#### Scenario: Fichero que no es normal
- **WHEN** la persona escribe `/file` con un enlace, un dispositivo o un fichero binario
- **THEN** el sistema lo rechaza y la siguiente pregunta va sin adjunto

### Requirement: Salir libera lo que la conversación tomó
Al salir con `/exit` o con fin de entrada, el sistema SHALL cerrar los recursos del proveedor que abrió y dejar libre la sesión, y SHALL terminar con código 0. Ninguna solicitud SHALL quedar en curso.

#### Scenario: Salida ordenada
- **WHEN** la persona escribe `/exit`
- **THEN** el proceso termina con código 0, la sesión queda libre y no hay solicitudes `pending` ni `running`

#### Scenario: Fin de entrada
- **WHEN** la terminal envía fin de entrada mientras se espera una línea
- **THEN** la conversación termina igual que con `/exit`
