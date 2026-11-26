# Spec Delta

## ADDED Requirements

### Requirement: Pantalla completa y respaldo plano
Al entrar en la conversación desde una consola, el sistema SHALL abrir la pantalla completa: la conversación con su propio desplazamiento, un panel lateral de contexto, la entrada fija abajo y un pie con los atajos. El sistema SHALL usar el texto plano cuando la persona lo pide, cuando la consola no admite la pantalla completa o cuando una variable de depuración de Textual está puesta.

#### Scenario: Consola sin indicaciones
- **WHEN** la persona ejecuta `chat` en una consola sin ninguna de esas indicaciones
- **THEN** la conversación se abre en la pantalla completa, en la pantalla alternativa de la terminal

#### Scenario: Texto plano pedido o necesario
- **WHEN** la persona ejecuta `chat --plain`, o `chat` con `NO_COLOR=1`, `TERM=dumb`, `HARNESS_PLAIN=1` o `TEXTUAL_LOG` puesta
- **THEN** la conversación muestra la cabecera de texto plano y la salida no contiene ninguna secuencia de escape

### Requirement: Un solo núcleo para los dos modos
La pantalla completa SHALL conducir la misma conversación que el texto plano: la misma sesión tomada, el mismo análisis de líneas, el mismo motor de Skills con su aprobación y la misma apertura y cierre del proveedor. La pantalla completa SHALL NOT enviar al núcleo nada que no sea una línea, una respuesta a la aprobación, una interrupción o el fin de la entrada.

#### Scenario: Un selector acaba en una línea
- **WHEN** la persona elige una sesión en el selector de sesiones
- **THEN** la conversación recibe la línea `/resume N` con el número que `/sessions` le daría, y la cambia como si se hubiera escrito

### Requirement: Texto ajeno contenido e inerte en la pantalla completa
En la pantalla completa, el texto que viene de fuera del harness SHALL mostrarse solo dentro de un bloque con borde cuyo título pone el harness, a partir del texto ya saneado, y SHALL NOT interpretarse como marcado de la pantalla: corchetes de estilo, de enlace o de acción se muestran como caracteres, y ninguna parte del bloque ejecuta una acción ni abre nada al pulsarla. El texto ajeno SHALL NOT dibujarse fuera de su bloque, cambiar el panel lateral ni abrir la caja de aprobación.

#### Scenario: Respuesta hostil
- **WHEN** el proveedor responde con `[@click=app.quit]salir[/]`, `[link=https://example.invalid]enlace[/link]`, secuencias de escape y un texto que imita la caja de aprobación y el panel lateral
- **THEN** todo eso aparece como caracteres dentro del bloque de la respuesta, sin estilos de enlace ni acciones; pulsarlo no hace nada; el panel no cambia y no se abre ninguna caja

#### Scenario: Respuesta muy larga
- **WHEN** el proveedor responde con 1 MiB de texto
- **THEN** la pantalla muestra lo que cabe en el límite de la conversación y avisa de lo que no se muestra, en un tiempo acotado

### Requirement: Panel lateral de la sesión tomada
El panel lateral SHALL mostrar solo estado del harness de la sesión tomada en ese momento: su nombre e identificador, el proyecto, el proveedor configurado, las notas de memoria incluidas en la última pregunta de esa sesión (número y nombres, saneados), el número de peticiones de la sesión y el estado de la última. El panel SHALL actualizarse cada vez que la conversación vuelve a esperar una línea.

#### Scenario: Sesión nueva
- **WHEN** la persona pulsa `ctrl+n` o escribe `/new`
- **THEN** al volver a esperar una línea, el panel muestra la sesión nueva y ya no la anterior

### Requirement: Paleta de órdenes del harness
La paleta SHALL ofrecer solo órdenes del harness y SHALL NOT ofrecer órdenes de sistema de la librería (tema, captura de pantalla, salir sin cerrar). La paleta SHALL NOT abrirse sobre la caja de aprobación.

#### Scenario: Orden desde la paleta
- **WHEN** la persona abre la paleta con `ctrl+p`, escribe `status` y pulsa Intro
- **THEN** la conversación muestra lo mismo que con `/status`

### Requirement: Caja de aprobación en la pantalla completa
La aprobación SHALL mostrarse en una caja del harness con la cabecera del motor (destino, hash, caducidad) y el contenido propuesto en un área marcada como ajena, con su propia entrada. Las reglas de la decisión no cambian: el código son los primeros caracteres del hash de los bytes mostrados, `n` pide escribir `reject` para rechazar y cualquier otra respuesta deja la aprobación pendiente.

#### Scenario: Aprobación con el código
- **WHEN** la persona escribe en la caja los primeros 8 caracteres del hash mostrado
- **THEN** la Skill se aplica una vez y el código no aparece en el historial de la entrada ni en la conversación

#### Scenario: Rechazo sin confirmar
- **WHEN** la persona escribe `n` y después algo distinto de `reject`
- **THEN** la aprobación queda pendiente y no se aplica nada

### Requirement: Entrada de la aprobación
La entrada de la caja de aprobación SHALL NOT guardar historial, SHALL NOT aceptar un pegado y SHALL rechazar una respuesta enviada antes de un intervalo mínimo desde que la caja se abrió.

#### Scenario: Pegado en la caja
- **WHEN** la persona pega el código en la entrada de la caja
- **THEN** la entrada sigue vacía y la aprobación no se decide

#### Scenario: Respuesta adelantada
- **WHEN** llega una respuesta a la caja antes del intervalo mínimo
- **THEN** la caja la rechaza, sigue abierta y la aprobación no se decide

### Requirement: Salir de la pantalla completa
Salir SHALL hacerse con una tecla distinta de `ctrl+c` (`ctrl+q`), con `ctrl+d` en la entrada vacía o con `/exit`, y SHALL cerrar el proveedor, soltar la sesión y devolver la terminal a su estado (fuera de la pantalla alternativa, cursor visible), también tras un error o una señal de terminación.

#### Scenario: Salir con ctrl+q
- **WHEN** la persona pulsa `ctrl+q`
- **THEN** la conversación cierra el proveedor, suelta la sesión, la terminal vuelve a su estado y el código de salida es 0

### Requirement: Ctrl+C en la pantalla completa
En la pantalla completa, `ctrl+c` SHALL interrumpir la pregunta en curso, que queda incierta y no se reenvía, sin cerrar la pantalla; con nada en curso SHALL NOT salir; en la caja de aprobación SHALL dejar la aprobación sin decidir; mientras el proveedor abre SHALL cancelar la apertura y salir con el código 130.

#### Scenario: Ctrl+C durante una pregunta
- **WHEN** la persona pulsa `ctrl+c` mientras el proveedor trabaja
- **THEN** la petición queda incierta, el proveedor no recibe otra petición y la pantalla sigue abierta esperando una línea

#### Scenario: Ctrl+C sin nada en curso
- **WHEN** la persona pulsa `ctrl+c` sin nada en curso
- **THEN** la pantalla sigue abierta y dice cómo salir

#### Scenario: Ctrl+C mientras el proveedor abre
- **WHEN** la persona pulsa `ctrl+c` antes de que el proveedor termine de abrir
- **THEN** la conversación cierra el proveedor y sale con el código 130

### Requirement: Nada escrito queda en disco
La pantalla completa SHALL guardar lo que la persona escribe solo en memoria y SHALL NOT escribir registros, capturas de pantalla ni historial en disco.

#### Scenario: Captura pedida
- **WHEN** algo pide a la pantalla completa una captura de pantalla
- **THEN** la pantalla la rechaza y no se escribe ningún fichero
