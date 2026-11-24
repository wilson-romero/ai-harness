# Spec Delta

## Purpose

Permite que el harness use herramientas de servidores MCP locales que la persona ha permitido, arrancándolos y cerrándolos con plazos que no dependen de que el servidor coopere.

## ADDED Requirements

### Requirement: Lista local de servidores permitidos
El sistema SHALL conocer solo los servidores declarados en el fichero que indica `HARNESS_MCP_CONFIG`. Sin esa variable, con un fichero inexistente o con un fichero no válido, ningún servidor existe y todo comando `mcp` que nombre uno SHALL terminar con un error controlado sin arrancar ningún proceso.

#### Scenario: Sin configuración
- **WHEN** `HARNESS_MCP_CONFIG` no está definida y el usuario ejecuta `mcp list`
- **THEN** el sistema imprime que no hay servidores configurados y termina con código 0

#### Scenario: Servidor no declarado
- **WHEN** el usuario ejecuta `mcp tools otro` y `otro` no está en la lista
- **THEN** el sistema termina con código distinto de 0, nombra el servidor como no permitido y no arranca ningún proceso

#### Scenario: Fichero de configuración no válido
- **WHEN** el fichero de configuración tiene un campo desconocido, un servidor sin orden de arranque o una orden escrita como una sola cadena
- **THEN** todo comando `mcp` termina con un error que nombra el campo y no arranca ningún proceso

### Requirement: La orden de arranque solo sale de la configuración local
El sistema SHALL arrancar un servidor solo con la orden de la lista local, como lista de argumentos y sin intérprete de órdenes. Ningún argumento de la CLI, resultado de herramienta ni texto de un modelo SHALL poder cambiar la orden, sus argumentos, su directorio ni su entorno.

#### Scenario: Metacaracteres en la orden
- **WHEN** un argumento de la orden configurada contiene `;`, `&&` o `$(...)`
- **THEN** el servidor recibe ese argumento literal y no se ejecuta ninguna otra orden

#### Scenario: Orden pedida desde la CLI
- **WHEN** el usuario pasa en `--args` un campo `command` o `env`
- **THEN** ese campo se trata como un argumento más de la herramienta y la política lo deniega si no está declarado

### Requirement: Entorno heredado acotado
El proceso de un servidor SHALL recibir solo las variables de entorno de una lista base fija y las que su entrada declare, con el valor que tienen en el proceso del harness, más la marca de recursión. Ninguna otra variable del harness SHALL llegar al servidor.

#### Scenario: Variable no declarada
- **WHEN** el entorno del harness contiene `HARNESS_TEST_CANARY=1` y la entrada del servidor no la declara
- **THEN** el servidor sintético informa de que no la ve

#### Scenario: Variable declarada
- **WHEN** la entrada del servidor declara `HARNESS_TEST_CANARY`
- **THEN** el servidor sintético informa de que la ve con su valor

### Requirement: Descubrir herramientas
`mcp tools SERVER` SHALL arrancar el servidor, listar sus herramientas y mostrar para cada una su nombre, su tipo de operación declarado y si la política la permite, la deniega o falta en el servidor, y SHALL cerrar el servidor antes de terminar.

#### Scenario: Herramientas del servidor sintético
- **WHEN** el usuario ejecuta `mcp tools synthetic`
- **THEN** la salida lista `get_project_metadata` como `read` y permitida, y una herramienta que el servidor ofrece pero la lista no declara como denegada

#### Scenario: Herramienta declarada que el servidor no ofrece
- **WHEN** la lista declara una herramienta que el servidor no devuelve en `list_tools`
- **THEN** la salida la marca como ausente y una llamada a ella se deniega sin enviarse

### Requirement: Llamar a una herramienta
`mcp call SERVER TOOL --args JSON` SHALL, si la política lo permite, arrancar el servidor, enviar una sola llamada con esos argumentos, imprimir el resultado saneado por stdout, cerrar el servidor y terminar con código 0 si la herramienta no informó de error.

#### Scenario: Llamada permitida
- **WHEN** el usuario ejecuta `mcp call synthetic get_project_metadata --args '{"project": "demo-alpha"}'`
- **THEN** el sistema imprime los metadatos sintéticos de `demo-alpha`, termina con código 0 y el proceso del servidor ya no existe

#### Scenario: La herramienta informa de error
- **WHEN** la herramienta devuelve un resultado marcado como error
- **THEN** el sistema imprime el mensaje saneado por stderr y termina con código 1

### Requirement: Plazos duros
Cada fase con un servidor SHALL tener un plazo propio (arranque y negociación, llamada, cierre) y el comando entero un plazo total. Vencido un plazo, el sistema SHALL dejar de esperar al servidor, cerrarlo y terminar con un error que nombra la fase, aunque el servidor no responda a nada.

#### Scenario: Servidor que no responde a la negociación
- **WHEN** el servidor sintético arranca y nunca contesta
- **THEN** el comando termina con un error de arranque dentro de su plazo más el margen de cierre

#### Scenario: Herramienta que no termina
- **WHEN** la herramienta sintética duerme más que el plazo de llamada
- **THEN** el comando termina con estado `timeout` dentro del plazo de llamada más el margen de cierre y la llamada queda auditada como `timeout`

#### Scenario: Servidor que ignora el cierre
- **WHEN** el servidor sintético ignora el fin de su entrada y la señal de terminar
- **THEN** el comando termina dentro de su plazo total y el proceso del servidor deja de existir

### Requirement: Ningún proceso propio queda vivo
Al terminar cualquier comando `mcp`, con éxito, con error, por plazo vencido o por interrupción del usuario, el proceso del servidor que arrancó SHALL haber terminado. Si no se puede comprobar, el sistema SHALL decirlo por stderr y en la auditoría.

#### Scenario: Interrupción del usuario
- **WHEN** el usuario interrumpe `mcp call` mientras la herramienta trabaja
- **THEN** el comando termina con código 130 y el proceso del servidor ya no existe

#### Scenario: El servidor muere a mitad de llamada
- **WHEN** el servidor sintético termina su proceso al recibir la llamada
- **THEN** el comando termina con un error que dice que el servidor terminó, sin traza de Python, y la llamada queda auditada como `failed`

### Requirement: Límites de tamaño
El sistema SHALL rechazar unos argumentos de más de 16 KiB en JSON y un resultado de más del límite de su herramienta (64 KiB por defecto, configurable hasta 1 MiB), sin imprimir nada del resultado rechazado.

#### Scenario: Argumentos demasiado grandes
- **WHEN** `--args` mide más de 16 KiB
- **THEN** el comando termina con un error de uso sin arrancar el servidor

#### Scenario: Resultado demasiado grande
- **WHEN** la herramienta sintética devuelve 2 MiB de texto
- **THEN** el comando termina con un error que da el tamaño y el límite, no imprime el resultado y la llamada queda auditada como `failed` con motivo `result_too_large`

### Requirement: Servidor que escribe basura
Una línea de la salida del servidor que no es un mensaje del protocolo SHALL terminar la sesión con ese servidor con un error controlado, sin traza de Python y sin imprimir esa línea.

#### Scenario: Texto suelto en stdout
- **WHEN** el servidor sintético escribe una línea de texto que no es JSON antes de contestar
- **THEN** el comando termina con un error de protocolo y la línea no aparece en la salida del harness

### Requirement: Resultado conforme a su esquema
Si la herramienta declara un esquema de salida, un resultado estructurado que no lo cumple SHALL rechazarse sin imprimirse.

#### Scenario: Resultado que no cumple el esquema
- **WHEN** la herramienta sintética declara un esquema con `project` obligatorio y devuelve un objeto sin él
- **THEN** el comando termina con un error de resultado no válido y no imprime el objeto
