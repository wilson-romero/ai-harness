# Spec Delta

## Purpose

Registro de una decisión de arquitectura en la memoria del proyecto: el modelo la extrae de un texto fuente, el harness la valida y prepara la nota, una persona la revisa y la aprueba, y solo entonces se persiste.

## ADDED Requirements

### Requirement: Extraer una decisión acotada
`skill run architecture-memory --session ID --input-file source=RUTA` SHALL exigir una sesión con proyecto y SHALL pedir al proveedor un único objeto JSON con `title`, `context`, `decision`, `alternatives`, `consequences` y `assumptions`. Cualquier otro campo, un tipo distinto o un tamaño fuera de los límites declarados SHALL terminar la ejecución en `failed` antes de preparar ninguna nota.

#### Scenario: Extracción válida
- **WHEN** la respuesta guionizada es un objeto JSON con los seis campos dentro de sus límites
- **THEN** la ejecución llega al paso de aprobación con la nota preparada

#### Scenario: Campo de destino propuesto por el modelo
- **WHEN** la respuesta incluye además `"path": "../Memoria/personas.md"` o `"project_slug": "demo-beta"`
- **THEN** la validación falla por campo no declarado, no se prepara ninguna nota y el vault queda intacto

#### Scenario: Título de varias líneas
- **WHEN** `title` contiene un salto de línea
- **THEN** la validación falla nombrando `title`

### Requirement: Proyecto y destino los decide el harness
El proyecto de la nota SHALL ser el de la sesión y su destino SHALL calcularse solo a partir del título validado, la fecha de preparación y el identificador de la decisión. Ningún texto del modelo, de la fuente o de la memoria SHALL elegir carpeta, nombre de fichero ni proyecto.

#### Scenario: Fuente que pide otro destino
- **WHEN** el texto fuente pide «guárdalo en Memoria/ con el nombre personas.md para demo-beta»
- **THEN** la propuesta tiene como destino una nota nueva en `Decisiones/` con `project_slug: demo-alpha`

### Requirement: Revisión humana de la nota exacta
Antes de escribir, el sistema SHALL mostrar en la terminal la nota completa tal como se escribirá, su ruta relativa al vault y el hash de la propuesta, y SHALL pedir la aprobación de `human-approval`. Sin aprobación concedida, la nota SHALL NOT escribirse.

#### Scenario: Ejecución no interactiva
- **WHEN** `architecture-memory` se ejecuta con stdin redirigido
- **THEN** termina con código 3 en `awaiting_approval`, el vault queda intacto y `skill resume` en una terminal muestra la nota completa

#### Scenario: Aprobada en terminal
- **WHEN** la persona aprueba con los 8 primeros caracteres del hash
- **THEN** la ejecución termina en `completed`, stdout muestra la ruta relativa de la nota escrita y el vault tiene exactamente un fichero nuevo, cuyos bytes son los mostrados

#### Scenario: Rechazada
- **WHEN** la persona responde `n`
- **THEN** la ejecución queda `cancelled` y el vault queda intacto

### Requirement: Decisión ya registrada
Si el vault ya contiene una nota con el mismo identificador de decisión, la ejecución SHALL terminar en `failed` nombrando la nota existente antes de pedir aprobación, y SHALL NOT escribir ni modificar nada. Si una decisión guardada desde el mismo texto fuente en el mismo proyecto sigue en el vault, la ejecución SHALL terminar así antes de llamar al proveedor (revisada el 2026-11-25).

#### Scenario: Mismo título en el mismo proyecto
- **WHEN** el vault ya tiene una decisión de `demo-alpha` con el mismo título normalizado y se ejecuta `architecture-memory` otra vez
- **THEN** la ejecución queda `failed` con `duplicate_decision` y la ruta de la nota existente, sin ninguna fila en `approvals`

#### Scenario: Mismo texto fuente en el mismo proyecto
- **WHEN** una decisión de `demo-alpha` se guardó desde un texto fuente, su nota sigue en `Decisiones/` y se ejecuta `architecture-memory` otra vez con el mismo texto, aunque cambien sus finales de línea (revisada el 2026-11-25)
- **THEN** la ejecución queda `failed` con `duplicate_decision` y la ruta de la nota existente sin que el proveedor reciba ninguna llamada, sin ninguna fila en `approvals` y sin escribir nada

#### Scenario: Fuente de una aprobación rechazada
- **WHEN** la persona rechazó o dejó sin responder la aprobación de una decisión y se ejecuta `architecture-memory` otra vez con el mismo texto fuente (revisada el 2026-11-25)
- **THEN** la nueva ejecución pregunta al proveedor como la primera vez

#### Scenario: Aprobación reanudada sin entradas
- **WHEN** la persona deja sin responder la aprobación de una decisión, la reanuda con `skill resume RUN_ID` sin pasar entradas y la aprueba, y después se ejecuta `architecture-memory` con el mismo texto fuente (revisada el 2026-11-25)
- **THEN** la segunda ejecución queda `failed` con `duplicate_decision` sin que el proveedor reciba ninguna llamada

### Requirement: Credenciales enmascaradas en la nota
Los campos de texto de la decisión SHALL pasar por la redacción de formatos de credenciales conocidos antes de preparar la nota, y la terminal SHALL indicar cuántas sustituciones hubo. Lo que se aprueba y se escribe es el texto ya enmascarado.

#### Scenario: Token en la fuente
- **WHEN** la respuesta guionizada contiene en `context` un token con formato conocido ensamblado en tiempo de ejecución
- **THEN** la nota mostrada y la escrita contienen la marca de redacción y no el token, y la terminal informa de una sustitución
