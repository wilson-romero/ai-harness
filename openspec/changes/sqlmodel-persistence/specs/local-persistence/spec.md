# Spec Delta

## Purpose

Garantías de la base de datos local del harness: compatibilidad con las bases ya creadas, sentencias que nunca se construyen con datos, atomicidad de cada transacción y un esquema esperado por el código que coincide con el que producen las migraciones numeradas.

## ADDED Requirements

### Requirement: Una base existente abre sin cambios
El sistema SHALL abrir y usar una base de datos creada y poblada por una versión anterior del harness con el mismo esquema, sin reescribir sus filas ni su esquema, y SHALL leer cada dato con el mismo valor que escribió aquella versión.

#### Scenario: Base sintética de la versión anterior
- **WHEN** el harness arranca sobre un directorio de datos sintético creado y poblado (sesiones, solicitudes, mensajes, ejecuciones de Skills, aprobaciones, llamadas MCP) por la versión anterior del harness
- **THEN** no aplica ninguna migración, `session list` y `history` muestran los mismos datos que mostraba la versión anterior, y el volcado de cada tabla es idéntico antes y después de leerlo

#### Scenario: Identificadores y fechas conservan su forma
- **WHEN** el harness escribe una sesión nueva en una base creada por la versión anterior
- **THEN** su identificador y sus fechas se guardan con la misma forma textual que las filas que ya había, y las consultas que filtran o comparan por esos campos encuentran tanto las filas nuevas como las antiguas

### Requirement: Ninguna sentencia SQL se construye con datos
El sistema SHALL ejecutar sobre su base de datos solo sentencias cuyo texto está fijado en el código fuente; todo valor que provenga de la persona, del proveedor, de una herramienta, de una nota o de un fichero SHALL llegar a la base como parámetro, nunca como parte del texto de la sentencia. La comprobación SHALL rechazar el código que construya el texto de una sentencia en tiempo de ejecución.

#### Scenario: Valor hostil como dato
- **WHEN** se crea una sesión con el nombre `x'); DROP TABLE sessions; --` y se pregunta en ella
- **THEN** la sesión aparece con ese nombre literal en `session list` y todas las tablas siguen existiendo

#### Scenario: La comprobación rechaza una sentencia construida
- **WHEN** el código del harness contiene una sentencia SQL cuyo texto se forma interpolando o concatenando un valor no literal
- **THEN** la comprobación del repositorio falla y nombra el fichero y la línea

### Requirement: Una transacción fallida no deja nada escrito
El sistema SHALL agrupar en una sola transacción las escrituras que forman un mismo paso de estado y SHALL deshacerlas todas si cualquiera falla; otro proceso SHALL NOT ver escrituras de una transacción que no ha terminado.

#### Scenario: Fallo a mitad de un paso
- **WHEN** una escritura falla después de que otra del mismo paso ya se ejecutó
- **THEN** ninguna de las dos queda en la base y el estado previo sigue intacto

#### Scenario: Otro proceso no ve una transacción abierta
- **WHEN** un proceso tiene una transacción abierta con escrituras pendientes y otro proceso lee la misma base
- **THEN** el segundo proceso no ve esas escrituras hasta que la transacción termina con éxito

### Requirement: El esquema esperado coincide con el migrado
El sistema SHALL tener una única fuente del esquema, las migraciones numeradas, y nunca SHALL crear ni alterar tablas de una base real a partir de otra descripción. La comprobación del repositorio SHALL fallar cuando la descripción de las tablas que usa el código y el esquema que producen las migraciones divergen en tablas, columnas, nulabilidad, claves o índices.

#### Scenario: Esquemas iguales
- **WHEN** se migra una base vacía con todas las migraciones y se compara con la descripción de tablas del código
- **THEN** coinciden tablas, columnas, nulabilidad, claves primarias, claves ajenas e índices, incluidos los índices únicos parciales

#### Scenario: Una migración sin su descripción
- **WHEN** se añade una migración que crea o cambia una columna y la descripción de tablas del código no se actualiza
- **THEN** la comprobación falla y nombra la tabla y la columna que divergen
