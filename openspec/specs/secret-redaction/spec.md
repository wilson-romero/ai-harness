# secret-redaction Specification

## Purpose

Evita que una credencial con formato conocido guardada en una nota salga del vault hacia la terminal o hacia el proveedor de lenguaje, y deja escrito qué no puede detectar.

## Requirements

### Requirement: Formatos conocidos enmascarados
Todo texto leído del vault que el sistema imprime, envía al proveedor o guarda, incluidos rutas relativas, cabeceras y valores del frontmatter, SHALL quitar primero los caracteres de control y de formato y después sustituir cada credencial con un formato conocido por `[REDACTED:<tipo>]`. Los formatos SHALL detectarse por prefijo de proveedor y forma exacta: clave privada PEM, Anthropic, OpenAI, GitHub, GitLab, AWS, Google, Slack, DigitalOcean, Stripe y JWT.

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

### Requirement: La prosa no se marca como secreto
La redacción SHALL NOT alterar texto que no coincide con un formato conocido, aunque parezca aleatorio o contenga palabras como `key=` o `password`.

#### Scenario: Texto parecido sin formato conocido
- **WHEN** una nota contiene `sk-learn-pipeline`, un hash SHA-256 en hexadecimal y la frase `password: ver gestor`
- **THEN** `memory context` muestra esos textos sin cambios

### Requirement: Límite declarado de la redacción
El sistema SHALL informar del número de sustituciones hechas en cada comando, y la documentación SHALL declarar que una credencial de formato desconocido no se detecta.

#### Scenario: Recuento de sustituciones
- **WHEN** `memory context demo-alpha` enmascara dos credenciales
- **THEN** stderr indica que se enmascararon dos y la salida estándar no contiene ninguna de ellas
