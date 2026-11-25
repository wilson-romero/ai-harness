# Spec Delta

## MODIFIED Requirements

### Requirement: Formatos conocidos enmascarados
Todo texto leído del vault que el sistema imprime, envía al proveedor o guarda, incluidos rutas relativas, cabeceras y valores del frontmatter, SHALL quitar primero las secuencias de escape enteras y los caracteres de control y de formato, y después sustituir cada credencial con un formato conocido por `[REDACTED:<tipo>]`. Los formatos SHALL detectarse por prefijo y forma exacta: clave privada PEM, Anthropic, OpenAI, GitHub, GitLab, AWS, Google, Slack, DigitalOcean, Stripe y JWT.

#### Scenario: Token en una nota enviada al proveedor
- **WHEN** una nota de `demo-alpha` contiene un token con formato de GitHub y el usuario pregunta con `--project demo-alpha`
- **THEN** el texto que recibe el proveedor contiene `[REDACTED:github]` y no contiene el token

#### Scenario: Clave privada de varias líneas
- **WHEN** una nota contiene un bloque de clave privada PEM completo
- **THEN** `memory context` muestra `[REDACTED:private-key]` en lugar de todo el bloque

#### Scenario: Credencial con un carácter invisible dentro
- **WHEN** una nota de `demo-alpha` contiene un token de GitHub con un carácter de control dentro, un JWT con `\x7f` dentro o una clave de AWS con un carácter de ancho cero dentro
- **THEN** ni `memory context`, ni `memory search`, ni el texto que recibe el proveedor contienen el token recompuesto, y en su lugar aparece `[REDACTED:<tipo>]`

#### Scenario: Credencial en el nombre de un fichero
- **WHEN** el nombre de una nota de `demo-alpha` contiene un token de GitHub y su `type` una clave de AWS
- **THEN** ni `memory context`, ni `memory search`, ni `memory maintain --dry-run`, ni el texto enviado, ni `request_context` contienen los tokens, y `maintain` lista esa nota en `secrets_found`

#### Scenario: Clave privada sin final
- **WHEN** una nota contiene la línea de inicio de una clave privada PEM (`BEGIN … PRIVATE KEY` entre guiones) sin su línea END
- **THEN** `memory context` muestra `[REDACTED:private-key]` desde esa línea hasta el final de la nota

#### Scenario: Entrada adversaria de 1 MiB
- **WHEN** un texto de 1 MiB repite el comienzo de un JWT, la cabecera de una clave privada o la palabra `MEMORIA`
- **THEN** su redacción y su neutralización terminan en menos de 2 segundos

#### Scenario: Credencial pegada a una secuencia de escape
- **WHEN** una nota de `demo-alpha` contiene `\x1b[31m` o `\x1b(B\x1b[m` justo antes de un token de GitHub
- **THEN** ni `memory context`, ni `memory search`, ni el texto que recibe el proveedor contienen el token ni el resto de la secuencia, y en su lugar aparece `[REDACTED:github]`

## ADDED Requirements

### Requirement: Resultados de herramientas enmascarados
Todo texto devuelto por una herramienta MCP que el sistema imprime, incluidos los nombres y los valores de un resultado estructurado a cualquier profundidad, SHALL quitar enteras las secuencias de escape de terminal (revisada el 2026-11-24, D7) y después recibir el mismo tratamiento que el texto del vault: quitar los caracteres de control y de formato y sustituir cada credencial con un formato conocido por `[REDACTED:<tipo>]`.

#### Scenario: Credencial en la clave y en el valor de un resultado estructurado
- **WHEN** una herramienta MCP devuelve un objeto con un token de GitHub como nombre de un campo y una clave de AWS con un carácter de ancho cero dentro como valor de otro, anidado en una lista
- **THEN** `mcp call` imprime `[REDACTED:github]` y `[REDACTED:aws]` en su lugar y ninguno de los dos tokens aparece en stdout ni en stderr

#### Scenario: Recuento de sustituciones de un resultado
- **WHEN** el resultado de una herramienta contiene dos credenciales de formato conocido
- **THEN** stderr indica que se enmascararon dos y la salida estándar no contiene ninguna de ellas
