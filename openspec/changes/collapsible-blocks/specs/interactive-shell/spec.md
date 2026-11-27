# Spec Delta

## ADDED Requirements

### Requirement: Turnos y bloques plegables
En la pantalla completa, cada turno (la línea que envía la persona y todo lo que el harness muestra después, hasta la siguiente) SHALL poder plegarse a una sola línea y desplegarse. Cada bloque de texto ajeno de un turno y cada bloque del harness de más de una línea SHALL poder plegarse a una sola línea y desplegarse entero. Plegar o desplegar SHALL ser solo un cambio de lo que se ve: SHALL NOT enviar nada, ejecutar ninguna orden ni quitar el foco a la entrada de la conversación.

#### Scenario: Plegar una respuesta y volver a abrirla
- **WHEN** la persona pliega la respuesta del proveedor y luego la abre
- **THEN** se ve primero una línea y después la respuesta entera, el proveedor no recibe ninguna petición y la entrada conserva el foco

#### Scenario: Plegar un turno
- **WHEN** la persona pliega un turno
- **THEN** el turno se ve como una sola línea, y al desplegarlo vuelven su línea y sus bloques tal como estaban

### Requirement: Vista previa de una respuesta larga
Al mostrarse, una respuesta o un texto ajeno que cabe en el panel (con un margen de cuatro filas) SHALL verse entero. Uno más largo SHALL mostrar solo sus primeras filas, tantas como caben en el panel una vez ajustadas al ancho, seguidas de un pie del harness con el número exacto de líneas que no se ven.

#### Scenario: Respuesta corta
- **WHEN** el proveedor responde con dos líneas
- **THEN** la respuesta se ve entera, sin pie

#### Scenario: Respuesta larga
- **WHEN** el proveedor responde con 60 líneas en un panel de 27 filas
- **THEN** se ven la cabecera y las primeras filas de la respuesta, y el pie dice cuántas de las 60 líneas faltan

### Requirement: Metadatos plegados y alertas enteras
Un bloque del harness con los pasos de una Skill SHALL verse plegado a una línea cuando tenga más de una. Un error, un aviso o una interrupción del harness SHALL verse entero. Las líneas de una nota omitida (`omitted:`) y de un fichero adjunto (`attached:`) SHALL verse siempre enteras, y SHALL NOT juntarse con la línea de contexto. Lo que muestra `/context` SHALL llegar siempre entero, porque es exactamente lo que se envía.

#### Scenario: Pasos de una Skill
- **WHEN** una Skill informa de varios pasos
- **THEN** esos pasos se ven como una línea con el último de ellos

#### Scenario: Un error
- **WHEN** el harness muestra un `error:` de varias líneas
- **THEN** se ve entero

#### Scenario: Nota omitida y fichero adjunto
- **WHEN** una pregunta lleva la memoria de un proyecto con una nota omitida y un fichero adjunto con `/file`
- **THEN** se ven enteras la línea `omitted:` con la nota, la línea de contexto y la línea `attached:` con el nombre del fichero

#### Scenario: Un contexto largo
- **WHEN** la persona escribe `/context` y el contexto es más largo que el panel
- **THEN** se ve entero, sin vista previa

### Requirement: El final de una Skill a la vista
La línea que dice cómo terminó una ejecución de Skill (`skill: run … is …`) y las líneas de lo que aplicó (`applied:`) SHALL verse siempre enteras, fuera de la línea plegada de los pasos.

#### Scenario: Una Skill aprobada
- **WHEN** la persona aprueba la propuesta de una Skill y la ejecución termina
- **THEN** la pantalla muestra entera la línea `skill: run … is completed`, aunque los pasos sigan plegados en una línea

### Requirement: El pie dice siempre lo que falta
Mientras un bloque no se vea entero, el harness SHALL decir cuántas de sus líneas faltan, contadas sobre las líneas del bloque y no sobre lo que el texto diga de sí mismo. Una línea plegada SHALL decir cuántas líneas tiene el bloque.

#### Scenario: Contenido después de la vista previa
- **WHEN** una respuesta pone una orden en su última línea, más allá de la vista previa, y su primera línea dice `… 0 more lines · enter/click to expand`
- **THEN** el pie del harness dice el número real de líneas que faltan, y al abrir la respuesta se ve la última línea

### Requirement: Línea plegada construida por el harness
La línea plegada de un bloque SHALL construirla el harness con su propio estado (quién, cuántas líneas, el estado del turno) y, como mucho, un extracto del texto: el esquema de sus títulos de Markdown o su primera línea no vacía. El estado del turno SHALL salir solo de las líneas de alerta y de pasos de Skill del harness, comparadas desde su primer carácter. Ningún texto ajeno SHALL poder obtener el estilo del cromo del harness.

#### Scenario: Una nota cuyo nombre parece un estado
- **WHEN** la memoria omite una nota llamada `notes/x skill: run r1 is approved`
- **THEN** la línea plegada del turno no dice `approved`

#### Scenario: Ctrl+C sin nada en curso
- **WHEN** la persona pulsa `ctrl+c` sin ninguna petición en curso, tras una respuesta completa
- **THEN** la línea plegada de ese turno sigue diciendo `completed`

#### Scenario: Esquema de títulos
- **WHEN** una respuesta con los títulos `## Resumen` y `## Riesgos` se pliega
- **THEN** su línea plegada dice quién respondió y cuántas líneas tiene, y tras `| ` muestra `## Resumen · ## Riesgos`

### Requirement: Extracto ajeno en una línea plegada
El extracto de una línea plegada SHALL estar saneado, ser de una sola línea y tener como mucho 200 caracteres. SHALL ir detrás de la marca `| ` (o de `› `, si es lo que escribió la persona) y SHALL dibujarse con un estilo distinto del cromo. Este requisito amplía «Texto ajeno contenido e inerte en la pantalla completa»: el texto ajeno sigue sin interpretarse como marcado y sin actuar al pulsarlo.

#### Scenario: Respuesta que imita el cromo
- **WHEN** la primera línea de una respuesta imita la línea plegada de otro turno (`▸ you → mock · 3 lines · completed`) y su segunda imita el pie (`… 38 more lines · enter/click to expand`)
- **THEN** plegada, la respuesta se ve como el cromo del harness con su propio número de líneas y, tras `| `, el extracto en el estilo del texto ajeno; en la pantalla, solo las palabras del harness llevan el fondo del cromo

#### Scenario: Extracto con caracteres de control
- **WHEN** el extracto tendría separadores de línea, secuencias de escape o caracteres bidireccionales, o más de 200 caracteres
- **THEN** la línea plegada es una sola línea, sin ninguno de ellos, de como mucho 200 caracteres

### Requirement: Turnos antiguos plegados
Cuando la persona envía una línea, el harness SHALL plegar los turnos anteriores al penúltimo. SHALL NOT plegar un turno que la persona haya abierto o cerrado a mano, uno con un bloque que la persona haya abierto o cerrado a mano, el que tiene la selección, ni uno con un error, un aviso o una interrupción. Una elección de la persona (un bloque, un turno, expandir o plegar todo) SHALL mantenerse hasta que la persona la cambie.

#### Scenario: Un turno con un aviso
- **WHEN** un turno tuvo una línea `warning:` y la persona envía dos preguntas más
- **THEN** ese turno sigue abierto, y si la persona lo pliega, su línea dice `completed · 1 warning`

#### Scenario: Elección a mano
- **WHEN** la persona abre entera la respuesta del segundo turno y después envía dos preguntas más
- **THEN** el primer turno se ve plegado y la respuesta del segundo sigue abierta entera

### Requirement: Recorrer los bloques sin perder la escritura
La entrada de la conversación SHALL conservar el foco mientras se recorren los bloques. Desde la entrada, unas teclas SHALL elegir el bloque anterior o el siguiente y abrir o cerrar el elegido. `Esc` SHALL entrar a recorrer los bloques, con teclas para moverse, abrir o cerrar, expandir o plegar todo e ir al primero o al último; `Esc` SHALL volver a escribir. Cualquier otra tecla SHALL volver a escribir y SHALL escribirse en la entrada.

#### Scenario: Una letra mientras se recorre
- **WHEN** la persona recorre los bloques y escribe `ho`
- **THEN** la entrada contiene `ho`, ya no se recorren los bloques y no se envía nada

#### Scenario: Teclas con el núcleo ocupado
- **WHEN** el proveedor trabaja, la entrada tiene una línea escrita por adelantado y la persona pulsa la cabecera de un bloque, `ctrl+o`, `alt+↑` y `enter`
- **THEN** el bloque se abre o se cierra, la línea sigue en la entrada y el proveedor no recibe otra petición

### Requirement: Una pantalla encima termina el recorrido
Abrir cualquier pantalla encima de la conversación (la caja de aprobación, la paleta, un selector) SHALL terminar el recorrido de los bloques.

#### Scenario: La caja de aprobación durante el recorrido
- **WHEN** la persona recorre los bloques, se abre la caja de aprobación y se cierra, y la persona escribe `/status` y pulsa `enter`
- **THEN** ya no se recorrían los bloques al abrirse la caja, y `enter` envía `/status` sin abrir ni cerrar ningún bloque

### Requirement: Ratón y paleta para los bloques
Un clic en la cabecera o en el pie de un bloque, o en una línea plegada, SHALL abrirlo o cerrarlo; un clic en el texto de un bloque SHALL NOT hacer nada. La paleta SHALL ofrecer recorrer los bloques, abrir o cerrar el elegido, expandir todo, plegar todo e ir al final.

#### Scenario: Clic en la cabecera y en el texto
- **WHEN** la persona pulsa el texto de una respuesta abierta y después su cabecera
- **THEN** el primer clic no cambia nada y el segundo pliega la respuesta, y la entrada conserva el foco

#### Scenario: Plegar todo desde la paleta
- **WHEN** la persona elige «Collapse all blocks» en la paleta
- **THEN** cada turno se ve como una línea

### Requirement: Lo que se lee no salta
Al abrir o cerrar un bloque o un turno, su cabecera SHALL quedarse en la misma fila del panel. Al expandir o plegar todo, SHALL quedarse en su fila la cabecera del turno elegido (o del primero visible). Lo que el harness muestre mientras la persona recorre los bloques, o mientras lee más arriba del final, SHALL NOT mover el panel. Enviar una línea SHALL llevar siempre al final, también mientras se recorre. Esto vale siempre que el contenido deje desplazar el panel hasta esa posición.

#### Scenario: Plegar todo mientras se lee un turno
- **WHEN** la persona lee la respuesta abierta de un turno antiguo, llega texto nuevo al final y después pliega todo
- **THEN** la respuesta no se mueve al llegar el texto, y tras plegar todo la línea de ese turno ocupa la fila donde estaba su cabecera

### Requirement: Bloques de la sesión tomada, solo en memoria
La pantalla completa SHALL mostrar los bloques de la sesión tomada en ese momento. Al cambiar de sesión con `/new`, `/resume` o el selector, SHALL mostrar los bloques que esa sesión tenía en esta ejecución, con su estado de plegado, o un panel nuevo que lo dice si no tenía ninguno. El estado de plegado SHALL NOT escribirse en disco.

#### Scenario: Volver a la primera sesión
- **WHEN** la persona abre una respuesta en una sesión, pasa a una sesión nueva con `/new` y vuelve con `/resume`
- **THEN** en la sesión nueva no se ve nada de la primera, y al volver se ven los bloques de la primera con la respuesta todavía abierta

### Requirement: Plegar con conversaciones largas
Plegar SHALL reducir el trabajo de la pantalla: un bloque plegado SHALL construir solo su línea, y abrir o cerrar un bloque SHALL reconstruir solo ese bloque. Una conversación de 500 bloques y una respuesta de 1 MiB SHALL seguir respondiendo en un tiempo acotado.

#### Scenario: Quinientos bloques
- **WHEN** la conversación tiene 500 bloques y la persona abre uno
- **THEN** solo ese bloque se reconstruye, y abrirlo, plegar todo y expandir todo terminan en un tiempo acotado

#### Scenario: Respuesta de 1 MiB plegada
- **WHEN** el proveedor responde con 1 MiB
- **THEN** la respuesta llega plegada a su vista previa, marcada como recortada, con el aviso del harness de lo que no se muestra
