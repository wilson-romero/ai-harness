# Spec Delta

## Purpose

Define la única escritura del harness en el vault: una nota de decisión nueva en `Decisiones/`, con formato compatible con la memoria, escrita de forma atómica y confinada solo después de una aprobación ligada a sus bytes exactos.

## ADDED Requirements

### Requirement: Única escritura del harness en el vault
El harness SHALL escribir en el vault solo para crear una nota de decisión nueva directamente dentro de `Decisiones/`, y solo como efecto de una aprobación `granted`, vigente y no consumida cuyo hash coincide con la propuesta recalculada. Ningún comando `memory …` SHALL escribir en el vault, y nada SHALL copiarlo, subirlo ni sincronizarlo.

#### Scenario: Comandos de memoria siguen sin escribir
- **WHEN** se ejecutan `memory search`, `memory context`, `memory maintain --dry-run` y `ask --project` sobre el vault sintético
- **THEN** la huella del vault es idéntica antes y después de cada uno

#### Scenario: Un fichero nuevo y nada más
- **WHEN** se aprueba y se escribe una decisión
- **THEN** la huella del vault después es la de antes más exactamente una entrada nueva, en `Decisiones/`

### Requirement: Nombre e identificador de la nota
El identificador SHALL derivarse de forma determinista del proyecto y del título normalizado, y el fichero SHALL llamarse `YYYY-MM-DD-<slug>-<id8>.md`, con la fecha de preparación, un slug ASCII de como mucho 48 caracteres derivado del título y los 8 primeros caracteres del identificador. El nombre SHALL ser válido en Windows y en macOS.

#### Scenario: Título con acentos y signos
- **WHEN** el título es «¿Cola gestionada o bus propio? Mensajería de ventas»
- **THEN** el nombre es `<fecha>-cola-gestionada-o-bus-propio-mensajeria-de-ventas-<id8>.md` o su recorte a 48 caracteres de slug, sin caracteres fuera de `[a-z0-9-]`

#### Scenario: Título que solo forma un nombre reservado
- **WHEN** el título normalizado produciría el slug `con` o un slug vacío
- **THEN** el nombre usa `decision` como slug y sigue siendo válido

#### Scenario: Mismo título, mismo identificador
- **WHEN** dos decisiones de `demo-alpha` tienen títulos que solo difieren en mayúsculas y espacios
- **THEN** tienen el mismo identificador

### Requirement: Frontmatter compatible con el vault
La nota SHALL empezar con un frontmatter que el lector de memoria acepta como válido, con `type: decision`, `decision_id`, `project_slug`, `status: accepted`, `created`, `updated`, `tags` en línea con `decision` y el proyecto, `source: ai-harness`, `skill` con nombre y versión, y `run_id`. Ningún valor del frontmatter SHALL venir del texto del modelo.

#### Scenario: La nota escrita entra en el contexto del proyecto
- **WHEN** se escribe una decisión de `demo-alpha` y después se ejecuta `memory context demo-alpha`
- **THEN** la nota aparece en la sección `Decisiones` del bloque y `memory maintain --dry-run` no la cuenta en `invalid_frontmatter`

### Requirement: Nota inerte en Obsidian
Todo texto de la nota que viene del modelo SHALL escribirse de forma que Obsidian lo muestre literalmente y ningún plugin lo ejecute, lo embeba ni lo descargue: las construcciones activas (bloques de código, código en línea, Templater, comentarios, HTML, imágenes, embebidos, enlaces internos y campos de Dataview) SHALL escribirse con entidades HTML, sin borrar nada. El escape SHALL ser lineal en el tamaño del texto.

#### Scenario: Contenido activo del modelo
- **WHEN** el modelo devuelve en sus campos un bloque `dataviewjs`, código en línea `$=`, Templater `<% %>` y `<%* %>`, comentarios `<!-- -->` y `%% %%`, una imagen remota, un embebido `![[…]]`, un `<script>` y un enlace `[[…]]`, y la nota se aprueba y se escribe
- **THEN** ninguno de esos marcadores aparece en los bytes del fichero, la nota mostrada es la escrita, decodificar las entidades devuelve el texto del modelo y `memory context` la devuelve sin ellos

### Requirement: Escritura atómica que nunca sobrescribe
La nota SHALL escribirse en un temporal oculto dentro de `Decisiones/` que después se publica con su nombre final mediante una operación que falla si ese nombre ya existe, de cualquier tipo, y SHALL NOT sustituir nunca un fichero existente. Un lector SHALL ver la nota entera o ninguna nota.

#### Scenario: Destino ocupado
- **WHEN** justo antes de publicar la nota el fichero de destino ya existe con otro contenido
- **THEN** no se sobrescribe, el temporal se borra, el paso queda `failed` con `conflict` y el fichero existente conserva sus bytes

#### Scenario: Temporal invisible para la memoria
- **WHEN** queda un temporal de la escritura en `Decisiones/`
- **THEN** `memory search` y `memory context` no lo leen

### Requirement: Escritura confinada a Decisiones
El destino SHALL resolverse dentro de la raíz real del vault, en `Decisiones/` directamente; `Decisiones/` SHALL ser un directorio real, no un enlace ni una unión; si es un enlace, una unión o no es un directorio, la escritura SHALL denegarse sin crear nada. Si `Decisiones/` no existe, el harness SHALL crearla dentro de la raíz real del vault solo en el momento de la primera escritura aprobada, y ningún comando de solo lectura SHALL crearla.

#### Scenario: Decisiones es un enlace hacia fuera
- **WHEN** `Decisiones/` del vault es un enlace simbólico a una carpeta fuera del vault
- **THEN** la ejecución queda `failed` antes de pedir aprobación y la carpeta de fuera queda intacta

#### Scenario: Decisiones creada en la primera escritura aprobada
- **WHEN** el vault no tiene la carpeta `Decisiones/` y se aprueba y se escribe una decisión
- **THEN** la huella del vault después es la de antes más exactamente la carpeta `Decisiones/` y la nota dentro de ella

#### Scenario: Decisiones no se crea sin escritura aprobada
- **WHEN** el vault no tiene la carpeta `Decisiones/` y se ejecutan los comandos `memory …`, `ask --project`, y una ejecución de `architecture-memory` que se rechaza o queda esperando aprobación
- **THEN** la carpeta sigue sin existir y la huella del vault es idéntica

### Requirement: Solo los bytes aprobados
Los bytes escritos SHALL ser exactamente los del contenido de la propuesta aprobada. Si la nota recalculada justo antes de escribir difiere en un byte de la aprobada, SHALL NOT escribirse nada.

#### Scenario: Salida validada alterada tras aprobar
- **WHEN** después de conceder la aprobación se modifica en SQLite la salida validada de la decisión
- **THEN** la escritura se deniega, la aprobación queda `revoked` y el vault queda intacto

#### Scenario: Bytes escritos igual a bytes mostrados
- **WHEN** se aprueba y se escribe una decisión
- **THEN** el SHA-256 del fichero escrito es el de la propuesta aprobada y su contenido es el que mostró la terminal

### Requirement: Aprobación ligada al vault de la ejecución
La ejecución SHALL quedar ligada al crearse al vault resuelto, guardando solo un resumen SHA-256 de su raíz, nunca la ruta. La cabecera de la aprobación SHALL mostrar la raíz y el hash SHALL incluirla. Si al preparar, aplicar o reconciliar el vault es otro, el efecto SHALL rehusar con `vault_changed` sin escribir. Ningún mensaje fuera de la vista interactiva SHALL imprimir la ruta.

#### Scenario: Aprobada para un vault, reanudada con otro
- **WHEN** una aprobación queda `granted` (el escritor estaba ocupado) y la ejecución se reanuda sin terminal con `HARNESS_VAULT_ROOT` apuntando a otro vault
- **THEN** la ejecución queda `failed` con `vault_changed`, la aprobación `revoked`, la huella de los dos vaults no cambia y ni el mensaje ni SQLite contienen ninguna de las dos rutas

### Requirement: Escrituras serializadas
Dos procesos del harness SHALL NOT escribir decisiones en el mismo vault a la vez; el segundo SHALL esperar como mucho un plazo corto y, si no obtiene el turno, SHALL fallar sin escribir y sin consumir su aprobación, que con un proveedor sintético SHALL seguir `granted` para un `resume`.

#### Scenario: Escritor ocupado
- **WHEN** con un proveedor sintético, otro proceso tiene tomado el bloqueo de escritura del vault durante todo el plazo
- **THEN** la escritura falla con un error controlado, la aprobación sigue `granted` y el vault queda intacto

### Requirement: Escritura interrumpida se reconcilia sin repetir
Si el proceso muere después de consumir la aprobación y antes de registrar el final de la escritura, el paso SHALL quedar `uncertain`. Al reanudar, el sistema SHALL comprobar el vault sin escribir: si existe la nota con ese identificador y los bytes aprobados, el paso se completa; si no existe, se pide una aprobación nueva; si existe con otros bytes, el paso SHALL seguir `uncertain` y `resume` SHALL negarse con código 1.

#### Scenario: Muerte tras el renombrado
- **WHEN** el proceso muere justo después de publicar la nota (con el temporal todavía presente o ya borrado) y se reanuda la ejecución
- **THEN** el paso queda `completed` sin escribir otra vez y el vault tiene una sola nota con ese identificador

#### Scenario: Muerte antes del renombrado
- **WHEN** con un proveedor sintético (las salidas de los pasos se guardan), el proceso muere después de consumir la aprobación y antes de publicar la nota (con o sin temporal escrito), y se reanuda en una terminal
- **THEN** se pide una aprobación nueva para los mismos bytes y solo con ella se escribe la nota

#### Scenario: Nota distinta con el mismo identificador
- **WHEN** al reconciliar existe una nota con ese identificador y otro contenido
- **THEN** el paso sigue `uncertain`, `resume` termina con código 1 nombrando el conflicto y no se escribe nada

### Requirement: Tras publicar, escrita o incierta
Una vez creado el enlace de la nota, el resultado SHALL ser «escrita» o `uncertain`, nunca `failed`. Mientras el temporal propio no se pueda borrar, la reconciliación SHALL dejar el paso `uncertain` y `resume` SHALL negarse con código 1 nombrándolo, porque la memoria no lee una nota con dos enlaces.

#### Scenario: Temporal retenido tras publicar
- **WHEN** la nota se publica pero su temporal no se puede borrar porque otro programa lo tiene abierto
- **THEN** la ejecución queda `uncertain` (no `failed`), `resume` termina con código 1 nombrando el temporal mientras siga retenido, y cuando se libera `resume` lo borra, completa el paso sin escribir otra vez y la nota aparece en `memory context`

### Requirement: Cancelar reconcilia antes
`skill cancel` sobre una ejecución `uncertain` SHALL reconciliar antes la escritura, decir si la nota está en el vault y SHALL NOT borrar nunca una nota.

#### Scenario: Cancelar una ejecución incierta
- **WHEN** la nota se publicó pero el temporal quedó (muerte o fallo entre el enlace y el borrado) y la persona ejecuta `skill cancel`
- **THEN** `cancel` reconcilia primero: borra el temporal propio, la nota vuelve a tener un solo enlace y entra en `memory context`, el mensaje dice que la nota está en el vault y la ejecución queda `cancelled`; si no hay nota, el mensaje dice que no se escribió nada

### Requirement: Proveedor real sin salidas guardadas
Con un proveedor que no guarda sus salidas, el motor SHALL reintentar un escritor ocupado en la misma invocación durante un tiempo acotado y después revocar la aprobación; una muerte antes de publicar SHALL obligar a repetir la ejecución, diciéndolo. Ninguna ejecución terminada SHALL conservar una aprobación `granted`.

#### Scenario: Escritor ocupado con proveedor real
- **WHEN** con un proveedor que no guarda sus salidas, el escritor está ocupado unos intentos y después queda libre, o sigue ocupado durante todo el tiempo de reintento
- **THEN** en el primer caso la nota se escribe en la misma invocación con la misma aprobación; en el segundo la ejecución queda `failed` con `effect_busy`, la aprobación `revoked`, el mensaje dice que hay que repetir la ejecución con `skill run` y el vault queda intacto

#### Scenario: Muerte antes del renombrado con proveedor real
- **WHEN** con un proveedor que no guarda sus salidas, el proceso muere después de consumir la aprobación y antes de publicar la nota, y se reanuda
- **THEN** la ejecución queda `failed` con `outputs_not_retained`, el mensaje dice que hay que repetirla con `skill run`, no queda ninguna aprobación `pending` ni `granted` y el vault queda intacto

### Requirement: Nada del contenido en SQLite con proveedor real
Con un proveedor que no declara contenido sintético, SQLite SHALL guardar de la nota solo su identificador de decisión, su SHA-256 y su tamaño, nunca su ruta ni su texto.

#### Scenario: Proveedor de prueba no sintético
- **WHEN** se escribe una decisión con un proveedor de prueba no sintético en una terminal
- **THEN** ninguna columna de texto de ninguna tabla contiene el título ni la ruta de la nota, y `skill_steps.effect_ref` contiene el identificador
