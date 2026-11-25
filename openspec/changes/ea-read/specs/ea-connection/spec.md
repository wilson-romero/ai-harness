# Spec Delta

## Purpose

Conecta el harness con un modelo de Enterprise Architect a través de un servidor MCP propio, en otro proceso, con una instancia de EA que el servidor crea y cierra él mismo, sobre un destino local que la persona ha permitido.

## ADDED Requirements

### Requirement: Servidor de EA incorporado y en su propio proceso
El servidor de EA SHALL arrancar solo como servidor incorporado de la lista local, con una orden fijada por el sistema, en un proceso distinto del harness y hablando solo por stdio con el proceso que lo arrancó. El harness SHALL NOT cargar en su propio proceso ningún código de COM.

#### Scenario: Orden de arranque fija
- **WHEN** la entrada del servidor de EA en la lista local declara también una orden de arranque
- **THEN** la configuración se rechaza con un error que nombra el campo

#### Scenario: El harness no carga COM
- **WHEN** se ejecuta `mcp call ea ea_connection_info`
- **THEN** el proceso del harness no ha importado ningún módulo de `pywin32` ni del paquete de EA

#### Scenario: Arranque fuera del harness
- **WHEN** alguien ejecuta el servidor de EA a mano, sin la marca de proceso hijo del cliente MCP del harness
- **THEN** el servidor termina con un mensaje de uso por stderr sin crear ninguna instancia de EA

### Requirement: Destinos locales permitidos
El servidor SHALL abrir solo el destino cuyo identificador local indica `EA_READ_TARGET_ID` y que está declarado en la lista local con su fichero de modelo y sus paquetes raíz autorizados. Un identificador desconocido, un destino sin raíces, una ruta relativa, una extensión que no es de modelo de EA o un texto con forma de cadena de conexión SHALL rechazarse sin crear ninguna instancia de EA.

#### Scenario: Identificador desconocido
- **WHEN** `EA_READ_TARGET_ID` nombra un destino que la lista no declara
- **THEN** `mcp call ea ea_connection_info` termina con error `target_not_allowed` y no se crea ninguna instancia de EA

#### Scenario: Cadena de conexión en lugar de fichero
- **WHEN** el destino declara como fichero un texto con `DBType=` o `Connect=` o un esquema `://`
- **THEN** la configuración se rechaza y no se crea ninguna instancia de EA

#### Scenario: Ninguna herramienta elige el destino
- **WHEN** una llamada a cualquier herramienta de EA incluye un argumento `target`, `file` o `connection`
- **THEN** la política la deniega con `argument_not_allowed` y no se envía

### Requirement: Instancia propia y nunca la de la persona
El servidor SHALL crear su propia instancia de EA y SHALL comprobar, antes de abrir nada, que no tiene ningún modelo abierto. Si lo tiene, SHALL soltarla sin cerrar su modelo ni terminarla y terminar con error `foreign_instance`. El servidor SHALL NOT adjuntarse a un EA en ejecución.

#### Scenario: Instancia recién creada
- **WHEN** el servidor crea la instancia y su cadena de conexión está vacía
- **THEN** abre el destino y `ea_connection_info` informa `own_instance: true`

#### Scenario: La instancia ya tenía un modelo abierto
- **WHEN** la instancia creada informa de una cadena de conexión no vacía
- **THEN** el servidor no llama a `CloseFile` ni a `Exit` sobre ella, no la usa y la llamada termina con `foreign_instance`

### Requirement: El modelo de la persona no se modifica
Un destino de fichero SHALL abrirse sobre una copia privada en un directorio temporal del servidor, y el servidor SHALL borrar esa copia al cerrar. El fichero original SHALL quedar idéntico.

#### Scenario: Fichero original intacto
- **WHEN** se ejecutan las cinco herramientas de lectura sobre un destino de fichero
- **THEN** el fichero original tiene el mismo tamaño, fecha de modificación y SHA-256 que antes, y la copia privada ya no existe

### Requirement: Todas las llamadas COM en un solo hilo y en serie
El servidor SHALL hacer todas las llamadas COM desde un único hilo dedicado, una detrás de otra, con un plazo por llamada. Una llamada que vence su plazo SHALL terminar con `timeout` y SHALL dejar el servidor fuera de servicio: no acepta más llamadas y termina su proceso.

#### Scenario: Dos llamadas seguidas
- **WHEN** el cliente envía dos llamadas de lectura seguidas al mismo servidor
- **THEN** el adaptador las recibe en el mismo hilo y la segunda empieza después de que termine la primera

#### Scenario: Llamada COM colgada
- **WHEN** una llamada del adaptador no vuelve dentro de su plazo
- **THEN** la herramienta devuelve un error `timeout` y el proceso del servidor termina sin intentar ninguna otra llamada COM

### Requirement: Cierre de lo propio
Al cerrarse su entrada, al recibir la orden de terminar o tras un error, el servidor SHALL cerrar el modelo que abrió y su propia instancia de EA, borrar la copia privada y terminar dentro de su plazo de cierre. SHALL NOT cerrar ni terminar ninguna instancia ni proceso que no haya creado.

#### Scenario: Cierre normal
- **WHEN** termina un `mcp call` sobre el servidor de EA
- **THEN** el adaptador ha recibido el cierre del modelo y de la instancia propia, una sola vez cada uno, y la copia privada no existe

#### Scenario: Cierre tras error
- **WHEN** una herramienta falla con un error COM
- **THEN** el servidor cierra igualmente el modelo y la instancia propia antes de terminar

### Requirement: Información de la conexión sin datos sensibles
`ea_connection_info` SHALL devolver el identificador local del destino, el tipo de adaptador, si la instancia es propia, la versión de la biblioteca de EA, la edición y el número de raíces autorizadas, y SHALL NOT devolver la ruta del fichero, una cadena de conexión, el identificador del proyecto ni datos del usuario.

#### Scenario: Información sin ruta
- **WHEN** el usuario ejecuta `mcp call ea ea_connection_info`
- **THEN** la salida contiene el identificador del destino y la versión, y no contiene la ruta del fichero del destino ni el nombre del usuario

### Requirement: El servidor de EA no escucha
El proceso del servidor de EA SHALL NOT abrir ningún puerto ni socket de escucha: solo el proceso que lo arrancó puede hablar con él.

#### Scenario: Sin escucha en el servidor de EA
- **WHEN** el servidor de EA atiende una llamada con el adaptador falso
- **THEN** no queda ningún socket escuchando en su proceso
