# Spec Delta

## Purpose

Permite encontrar desde la CLI las notas del vault local que mencionan unos términos, en todo el vault o dentro de un proyecto, sin red y sin mostrar credenciales.

## ADDED Requirements

### Requirement: Búsqueda por texto
`memory search QUERY` SHALL devolver las notas legibles del vault que contienen todos los términos de la consulta, sin distinguir mayúsculas ni minúsculas. Cada resultado SHALL mostrar la ruta relativa al vault, la fecha `updated` si la nota la declara, el número de coincidencias y un fragmento de una línea.

#### Scenario: Términos encontrados
- **WHEN** el vault sintético tiene dos notas que contienen «orquestador» y «ventas», y el usuario ejecuta `memory search "Orquestador ventas"`
- **THEN** la salida contiene exactamente esas dos rutas relativas y termina con código 0

#### Scenario: Sin resultados
- **WHEN** ninguna nota contiene la consulta
- **THEN** el sistema indica que no hay resultados y termina con código 0

#### Scenario: Consulta vacía
- **WHEN** el usuario ejecuta `memory search ""`
- **THEN** el sistema informa del error, termina con código distinto de 0 y no lee el vault

### Requirement: Orden determinista de resultados
Los resultados SHALL ordenarse por número de coincidencias descendente, después por `updated` descendente y después por ruta, y SHALL limitarse al máximo configurado, indicando cuántos se omitieron.

#### Scenario: Misma consulta, misma salida
- **WHEN** el usuario ejecuta dos veces la misma consulta sobre el mismo vault
- **THEN** las dos salidas son idénticas byte a byte

#### Scenario: Límite de resultados
- **WHEN** hay más coincidencias que el límite pedido con `--limit 3`
- **THEN** la salida muestra tres resultados y avisa por stderr de cuántos se omitieron

### Requirement: Búsqueda dentro de un proyecto
Con `--project SLUG`, la búsqueda SHALL limitarse a las notas que pertenecen a ese proyecto según la misma regla que usa el contexto de proyecto, y SHALL NOT devolver notas de otro proyecto.

#### Scenario: Otro proyecto excluido
- **WHEN** `demo-alpha` y `demo-beta` tienen notas con «latencia» y el usuario ejecuta `memory search latencia --project demo-alpha`
- **THEN** la salida no contiene ninguna ruta de `projects/demo-beta/` ni ninguna nota etiquetada solo con `demo-beta`

### Requirement: Salida segura para la terminal
Los fragmentos SHALL pasar por la redacción de credenciales y SHALL NOT contener caracteres de control salvo el tabulador que separa columnas.

#### Scenario: Secuencia de escape neutralizada
- **WHEN** una nota que coincide contiene una secuencia de escape ANSI
- **THEN** el fragmento impreso no contiene el carácter ESC

#### Scenario: Credencial en un fragmento
- **WHEN** la línea que coincide contiene un token con formato conocido
- **THEN** el fragmento muestra `[REDACTED:<tipo>]` en lugar del token
