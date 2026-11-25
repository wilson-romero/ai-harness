# Spec Delta

## Purpose

Mide a mano, en el equipo de la persona, si su edición de Enterprise Architect permite la Automation Interface y cómo se comporta, sin tocar sus modelos ni su EA abierto, y devuelve un resumen que se puede pegar sin revelar nada del entorno.

## ADDED Requirements

### Requirement: Arranca y termina sin traza en cualquier equipo
La sonda SHALL ejecutarse hasta el final e imprimir su resumen aunque falte `pywin32`, falte EA o el sistema no tenga COM, y SHALL terminar con código 0 si llegó al final, aunque fallaran pasos. No SHALL decidir nada según el nombre de la plataforma: detecta si puede importar `pywin32` y si puede crear el objeto COM.

#### Scenario: Sin pywin32
- **WHEN** la sonda se ejecuta en un entorno donde `import win32com.client` falla
- **THEN** imprime el resumen con `pywin32: no` y cada paso de COM como no ejecutado con ese motivo, no imprime ninguna traza de Python y termina con código 0

#### Scenario: EA no instalado
- **WHEN** `pywin32` está disponible pero crear `EA.Repository` y `EA.App` falla con «clase no registrada»
- **THEN** el resumen lo dice con la categoría y el código del error COM, los pasos siguientes figuran como no ejecutados y el código de salida es 0

### Requirement: Un paso que falla no detiene la sonda
Cada paso SHALL ejecutarse con su propio control de errores y un plazo; un paso que falla o vence su plazo SHALL quedar registrado con su categoría y su duración, y la sonda SHALL seguir con los pasos que no dependen de él.

#### Scenario: Paso que lanza un error COM
- **WHEN** crear el modelo nuevo falla con un error COM
- **THEN** ese paso queda `fail` con su código, los pasos que necesitan el modelo quedan como no ejecutados y los de cierre y recuento de procesos se ejecutan

#### Scenario: Paso que se cuelga
- **WHEN** una llamada COM no vuelve dentro de su plazo
- **THEN** ese paso queda `timeout`, la sonda no hace ninguna otra llamada COM, imprime el resumen y termina

### Requirement: Solo toca lo que crea
La sonda SHALL crear su propia instancia de EA y un modelo nuevo dentro de un directorio temporal fuera del repositorio. SHALL NOT abrir ningún modelo existente, adjuntarse a un EA en ejecución, ni cerrar o terminar ningún proceso que no haya creado; si el objeto creado ya tiene un modelo abierto, SHALL soltarlo sin cerrarlo y no usarlo.

#### Scenario: El objeto creado resulta ser un EA ajeno
- **WHEN** el objeto COM creado tiene ya una cadena de conexión no vacía
- **THEN** la sonda lo registra como `attached_to_existing: yes`, no llama a `CloseFile` ni a `Exit` sobre él y no usa ese objeto para nada más

#### Scenario: EA abierto por la persona
- **WHEN** antes de empezar hay procesos de EA en ejecución
- **THEN** el resumen informa del recuento antes y después y la sonda no cierra ni termina ninguno

### Requirement: Mide crear, guardar, reabrir y leer por GUID
Con COM disponible, la sonda SHALL intentar crear un modelo nuevo con un paquete, dos elementos, un conector y un diagrama con los dos elementos, cerrarlo, reabrirlo y leer por GUID el paquete, el diagrama, los elementos y el conector, y SHALL informar de cada paso con sí o no y su duración, y de los recuentos de objetos y de enlaces del diagrama leídos.

#### Scenario: Modelo creado y releído
- **WHEN** la edición permite la Automation Interface
- **THEN** el resumen da `yes` en crear, poblar, reabrir y leer por GUID, con dos objetos de diagrama y un conector leídos

### Requirement: Resumen que se puede pegar
La sonda SHALL imprimir un bloque entre `---- ea probe summary (paste only this) ----` y `---- end of summary ----` que contenga solo booleanos, recuentos, duraciones, la versión y la edición de EA y categorías y códigos de error COM. El bloque SHALL NOT contener rutas, nombres de usuario, GUID, contenido de un modelo ni texto de un mensaje de error.

#### Scenario: Ningún dato del entorno en el resumen
- **WHEN** la sonda termina con pasos correctos y fallidos y el directorio temporal está bajo la carpeta del usuario
- **THEN** el bloque no contiene la ruta del directorio temporal, ni la del directorio de datos, ni el nombre del usuario, ni ningún texto con forma de GUID, ni el texto del mensaje de ningún error

### Requirement: Detalle guardado fuera del alcance de Git
La sonda SHALL guardar el detalle en un fichero JSON bajo `HARNESS_DATA_DIR/ea/` (por defecto `./data/ea/`) y SHALL negarse a escribir en un directorio que Git podría versionar, sin escribir nada.

#### Scenario: Directorio de datos versionable
- **WHEN** `HARNESS_DATA_DIR` apunta a una carpeta dentro de un repositorio Git que no la ignora
- **THEN** la sonda termina con código 1 y un mensaje que lo explica, sin crear ningún fichero

#### Scenario: Directorio de datos ignorado
- **WHEN** `HARNESS_DATA_DIR` es el `./data` por defecto, ignorado por `.gitignore`
- **THEN** la sonda escribe `data/ea/probe-<fecha>.json` y el resumen dice que el detalle se guardó, sin la ruta completa
