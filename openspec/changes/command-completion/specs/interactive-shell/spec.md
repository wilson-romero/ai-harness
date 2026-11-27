# Spec Delta

## ADDED Requirements

### Requirement: Una sola lista de comandos
La lista de comandos que acepta la conversación, la que muestra `/help` y la que ofrece el completado SHALL ser la misma: un comando que existe SHALL aparecer en las tres con el mismo nombre, y uno que no existe SHALL NOT aparecer en ninguna.

#### Scenario: La ayuda y la lista dicen lo mismo
- **WHEN** la persona escribe `/help` y, en la pantalla completa, escribe `/`
- **THEN** los dos muestran los mismos comandos, en el mismo orden, y cada uno se acepta como comando

### Requirement: Lista de completado bajo la entrada
En la pantalla completa, al escribir una línea que empieza por `/` SHALL aparecer bajo la entrada una lista de candidatos: los comandos con su resumen y, tras un comando, sus opciones y sus valores (proyectos, Skills válidos, entradas del Skill, sesiones y rutas). La lista SHALL filtrarse al escribir, primero por los candidatos que empiezan por lo escrito. Una línea que no empieza por `/`, o que empieza por `//`, SHALL NOT abrir la lista.

#### Scenario: Barra y filtro
- **WHEN** la persona escribe `/` y después `sk`
- **THEN** primero se ven todos los comandos con su resumen, y después solo los que encajan con `sk`, con `/skill` el primero

#### Scenario: Valores de un argumento
- **WHEN** la persona escribe `/skill ` con dos Skills válidos instalados
- **THEN** la lista muestra esos dos Skills con su descripción y ningún otro texto

#### Scenario: Una pregunta no completa
- **WHEN** la persona escribe `revisa el HLS`
- **THEN** no aparece ninguna lista

### Requirement: Rutas en la lista
Donde un comando toma una ruta, la lista SHALL ofrecer los nombres de la carpeta escrita, relativa a la carpeta de trabajo, con las carpetas primero. Los nombres que empiezan por `.` SHALL ofrecerse solo si lo escrito empieza por `.`. Una ruta que empieza por `~/` SHALL listar la carpeta personal y SHALL dejar `~/` escrito.

#### Scenario: Ruta
- **WHEN** la persona escribe `/file tests/fi` en una carpeta con `tests/fixtures/`
- **THEN** la lista ofrece `tests/fixtures/` como carpeta

#### Scenario: Nombres ocultos
- **WHEN** en la carpeta hay `.oculto` y `visible.md` y la persona escribe `/file ` y después `/file .`
- **THEN** primero se ofrece solo `visible.md`, y después `.oculto`

### Requirement: Teclas de la lista y su orden
Al abrirse la lista, ninguna fila SHALL estar elegida. Con la lista abierta, Tab SHALL poner en la entrada la fila elegida o, si no hay ninguna, la primera; ↑ y ↓ SHALL elegir fila; Intro con una fila elegida SHALL ponerla en la entrada sin enviar nada; Intro sin fila elegida SHALL cerrar la lista y enviar lo escrito; Esc SHALL cerrar la lista y nada más. Con la lista cerrada, ↑ y ↓ SHALL recorrer lo escrito antes y Esc SHALL empezar a recorrer los bloques.

#### Scenario: Intro sin elegir envía lo escrito
- **WHEN** la lista está abierta sin fila elegida y la persona pulsa Intro
- **THEN** se envía la línea tal como está escrita

#### Scenario: Intro con teclas que la lista no ha visto
- **WHEN** la persona elige `/status` en la lista de `/s` y la terminal entrega de una vez `e` e Intro
- **THEN** se envía `/se` tal como está escrito y la `e` no se pierde

#### Scenario: Elegir con flechas no envía
- **WHEN** la persona pulsa ↓ y después Intro
- **THEN** la fila elegida queda en la entrada y no se envía nada

#### Scenario: Esc primero cierra
- **WHEN** la lista está abierta y la persona pulsa Esc dos veces
- **THEN** la primera cierra la lista y la segunda empieza a recorrer los bloques

### Requirement: Ninguna tecla se pierde por la lista
Ninguna tecla escrita SHALL perderse ni cambiar de orden por la lista, también cuando varias teclas, Tab incluido, llegan juntas. Con la lista cerrada, Tab SHALL poner el primer candidato de lo escrito. `ctrl+c`, `ctrl+q`, `ctrl+n` y `ctrl+p` SHALL hacer lo mismo que sin lista.

#### Scenario: Teclas que llegan juntas
- **WHEN** la terminal entrega de una vez `/new demo-a` y Tab
- **THEN** la entrada queda en `/new demo-alpha ` y no se pierde ninguna tecla

#### Scenario: Sesión nueva con la lista abierta
- **WHEN** la lista está abierta y la persona pulsa `ctrl+n`
- **THEN** la conversación pasa a una sesión nueva y lo escrito sigue en la entrada

### Requirement: La lista nunca sobre otra pantalla
La lista SHALL NOT abrirse mientras haya encima la caja de aprobación, la paleta o un selector, y abrir una de esas pantallas SHALL cerrarla. Con la caja de aprobación abierta, las teclas de la lista SHALL NOT completar nada.

#### Scenario: Caja de aprobación
- **WHEN** la caja de aprobación está abierta y la persona pulsa `/`, ↓, ↑ y Esc
- **THEN** no aparece ninguna lista y la entrada de la conversación no cambia

### Requirement: Candidatos ajenos dibujados literalmente
Un nombre de fichero o de carpeta, un título de sesión o una descripción de Skill SHALL mostrarse en la lista como caracteres, nunca como marcado ni como órdenes de la terminal, en una sola línea y acotado. Un nombre que no se puede mostrar tal cual (con secuencias de escape, caracteres de control o invisibles, espacios o comillas) SHALL NOT ofrecerse. Lo que se inserta SHALL ser exactamente el nombre mostrado.

#### Scenario: Nombre con secuencia de escape
- **WHEN** en la carpeta hay un fichero cuyo nombre contiene una secuencia de escape y la persona completa `/file` con su inicial
- **THEN** ese nombre no se ofrece

#### Scenario: Nombre con corchetes de estilo o de acción
- **WHEN** en la carpeta hay ficheros `[bold]negrita.md` y `[@click=app.quit]x.md` y la persona elige el segundo
- **THEN** la lista muestra los dos con sus corchetes y sin estilo, la entrada recibe `[@click=app.quit]x.md` y la conversación sigue abierta

#### Scenario: Título de sesión que imita el cromo
- **WHEN** una sesión tiene un título con saltos de línea y escapes y la persona escribe `/resume `
- **THEN** el título se ve en una línea, saneado y acotado

### Requirement: Un candidato se lee como una sola palabra
Un valor de la lista (una ruta, un proyecto, un Skill, una entrada de un Skill o un identificador de sesión) SHALL ofrecerse solo si, puesto en la línea, la conversación lo lee como exactamente ese valor: un nombre con cualquier carácter de espacio (también los de Unicode, como el espacio duro o el estrecho), con comillas o que empieza por `-` SHALL NOT ofrecerse.

#### Scenario: Espacio duro que esconde una opción
- **WHEN** en la carpeta hay un fichero cuyo nombre es `a`, un espacio duro, `--file`, un espacio duro y `focus=.env`, y la persona completa la ruta de un Skill de una entrada
- **THEN** ese nombre no se ofrece y ningún `.env` se lee

#### Scenario: Espacio al principio
- **WHEN** en la carpeta hay `z.md` y ` z.md` (con un espacio delante) y la persona escribe `/file `
- **THEN** solo se ofrece `z.md`

### Requirement: Completar no envía, no ejecuta ni lee ficheros
Abrir, filtrar, recorrer o aceptar la lista SHALL NOT enviar nada al proveedor, ejecutar un comando, crear una solicitud ni abrir el contenido de un fichero: de una carpeta solo SHALL leerse los nombres. Un enlace SHALL ofrecerse como nombre y SHALL NOT seguirse. Una carpeta que no se puede leer SHALL dar una lista vacía, sin mensaje de error.

#### Scenario: Completar y aceptar sin enviar
- **WHEN** la persona completa un comando y una ruta con Tab y no pulsa Intro
- **THEN** no hay ninguna solicitud nueva ni ninguna ejecución de Skill

#### Scenario: Enlace a una carpeta
- **WHEN** en la carpeta hay un enlace a otra carpeta
- **THEN** se ofrece su nombre sin `/` final y el contenido de su destino no se lista

### Requirement: Listar una carpeta no detiene la escritura
Listar una carpeta para la lista SHALL hacerse sin detener la escritura y SHALL tener un tope de entradas y de tiempo. Una respuesta que llega cuando lo escrito ya cambió SHALL NOT mostrarse.

#### Scenario: Carpeta de 50 000 entradas
- **WHEN** la persona completa una ruta dentro de una carpeta de 50 000 entradas
- **THEN** la lista llega en menos de un segundo y lo que se escribe mientras tanto aparece en la entrada

#### Scenario: Respuesta vieja
- **WHEN** un listado lento termina después de que la persona ha escrito más
- **THEN** ese listado no se muestra

#### Scenario: Carpeta que nunca contesta
- **WHEN** el listado de una carpeta no termina nunca, la persona sigue escribiendo y después sale
- **THEN** cada tecla llega a la entrada, el número de listados en curso sigue acotado y la conversación termina sin esperar al listado

### Requirement: Nombre de comando cortado
Una línea que empieza por `/` seguido del principio del nombre de un solo comando SHALL ejecutarse como ese comando. Si el principio es de más de un comando, el sistema SHALL decir cuáles y SHALL NOT ejecutar nada. Un nombre entero SHALL seguir funcionando igual.

#### Scenario: Principio único
- **WHEN** la persona escribe `/hist`
- **THEN** el sistema muestra el historial de la sesión, como con `/history`

#### Scenario: Principio ambiguo
- **WHEN** la persona escribe `/s`
- **THEN** el sistema dice que `/s` es el principio de `/status`, `/sessions` y `/skill`, y no ejecuta ninguno

### Requirement: Formas cortas de /new y /skill
`/new SLUG` SHALL equivaler a `/new --project SLUG` cuando `SLUG` es el nombre de un proyecto del vault; si no lo es, SHALL seguir siendo el nombre de la sesión nueva. `/skill NOMBRE RUTA` SHALL equivaler a `/skill NOMBRE --file ENTRADA=RUTA` cuando el Skill declara exactamente una entrada y `RUTA` es la única palabra suelta. Las formas largas SHALL seguir aceptándose igual.

#### Scenario: Proyecto por su nombre
- **WHEN** la persona escribe `/new demo-alpha` con `demo-alpha` en el vault
- **THEN** la sesión nueva tiene el proyecto `demo-alpha`

#### Scenario: Nombre que no es un proyecto
- **WHEN** la persona escribe `/new Ensayo`
- **THEN** la sesión nueva se llama `Ensayo` y no tiene proyecto

#### Scenario: Skill de una entrada
- **WHEN** la persona escribe `/skill architecture-memory tests/fixtures/skill-inputs/fuente-decision.md` en una sesión con proyecto
- **THEN** el Skill se ejecuta con la entrada `source` leída de ese fichero

### Requirement: Formas cortas decididas por el harness
Que una línea sea una forma corta SHALL depender solo de datos del harness (las carpetas de proyecto del vault y las entradas que declara el Skill), nunca del contenido de un fichero, de una nota ni de una respuesta del proveedor. Si esos datos no se pueden leer, la línea SHALL tratarse como forma larga.

#### Scenario: Skill de varias entradas
- **WHEN** la persona escribe `/skill NOMBRE RUTA` para un Skill que declara dos entradas
- **THEN** la línea no se convierte y el sistema da el error de siempre de la forma larga

### Requirement: Lo que se ejecuta se ve entero antes
Antes de ejecutar un comando escrito en forma corta, la conversación SHALL mostrar el comando entero en su forma larga, saneado, en una línea del harness (`running: …`), en la pantalla completa y en el texto plano. Un comando escrito entero SHALL NOT repetirse. En la pantalla completa, el comando entero SHALL verse además junto a la entrada mientras se escribe, antes de pulsar Intro.

#### Scenario: Eco de una forma corta
- **WHEN** la persona escribe `/new demo-alpha` y pulsa Intro
- **THEN** antes de crear la sesión se ve `running: /new --project demo-alpha`

#### Scenario: Comando escrito entero
- **WHEN** la persona escribe `/new --project demo-alpha`
- **THEN** no aparece ninguna línea `running:`

#### Scenario: Vista previa antes de Intro
- **WHEN** en la pantalla completa la persona escribe `/new demo-alpha` sin pulsar Intro
- **THEN** junto a la entrada se ve `running: /new --project demo-alpha` y no existe ninguna sesión nueva

### Requirement: Reanudar por identificador
`/resume` SHALL aceptar, además del número de la última `/sessions`, el identificador entero de una sesión o un principio de al menos 8 caracteres que solo tiene una sesión. Un principio más corto, o que tienen varias sesiones o ninguna, SHALL dar un error que lo dice y SHALL NOT cambiar de sesión.

#### Scenario: Identificador entero
- **WHEN** la persona escribe `/resume` con el identificador de una sesión existente
- **THEN** la conversación pasa a esa sesión

#### Scenario: Principio demasiado corto
- **WHEN** la persona escribe `/resume 01a2`
- **THEN** el sistema pide al menos los 8 primeros caracteres y la sesión no cambia

### Requirement: Formas cortas en texto plano
En el texto plano SHALL aceptarse las mismas formas cortas y SHALL mostrarse el mismo eco `running: …`, sin lista de completado.

#### Scenario: Forma corta en texto plano
- **WHEN** en `--plain` la persona escribe `/new demo-alpha`
- **THEN** se ve `running: /new --project demo-alpha` y la sesión nueva tiene ese proyecto
