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

### Requirement: Stderr del servidor guardado enmascarado
El stderr de un servidor MCP que el sistema guarda en su log SHALL tener cada credencial de formato conocido sustituida por `[REDACTED:<tipo>]` antes de escribirse, aunque llegue partida en varias lecturas (añadido el 2026-11-25, D3).

#### Scenario: Credencial partida en el stderr del servidor
- **WHEN** un servidor MCP escribe en stderr una línea con un token de GitHub en dos escrituras separadas, cortada por la mitad del token
- **THEN** su log contiene `[REDACTED:github]` y ninguna de las dos mitades del token

#### Scenario: Clave privada en el stderr del servidor
- **WHEN** el stderr de un servidor MCP contiene un bloque de clave privada PEM completo, leído en trozos de cualquier tamaño
- **THEN** su log contiene `[REDACTED:private-key]` en lugar de todo el bloque y el texto que lo sigue sin cambios

#### Scenario: Credencial en el corte de una línea larga sin final
- **WHEN** un servidor MCP escribe en stderr una línea de 70 000 bytes sin salto con un token de GitHub que cruza el punto donde la línea se suelta por partes, o una barra de progreso que separa cada actualización con un CR suelto (revisada el 2026-11-25)
- **THEN** su log contiene `[REDACTED:github]` en cada aparición y ningún fragmento del token

#### Scenario: Cabecera de clave privada sin final en el stderr del servidor
- **WHEN** el stderr de un servidor MCP contiene la línea de inicio de una clave privada PEM sin su línea END, seguida de mucho más texto (revisada el 2026-11-25)
- **THEN** su log contiene `[REDACTED:private-key]`, oculta como mucho 32 KiB en bytes desde el comienzo de la cabecera aunque lleguen en una sola línea, dice que el registro se reanuda y guarda redactado lo que sigue, y la línea final cuenta lo oculto como ausente del log

#### Scenario: Bytes de continuación UTF-8 en el stderr del servidor
- **WHEN** un servidor MCP escribe en stderr 70 000 bytes de continuación UTF-8 (`0x80`) sin salto de línea (revisada el 2026-11-25)
- **THEN** la sesión termina con normalidad y el log guarda esos bytes sin cambios

#### Scenario: Credencial más larga que el límite de una línea
- **WHEN** un servidor MCP escribe en stderr un token de Slack de 100 000 caracteres leído en trozos de 4 KiB (revisada el 2026-11-25)
- **THEN** su log contiene `[REDACTED:slack]` y ningún carácter del token

#### Scenario: Formatos que se solapan
- **WHEN** un texto contiene una clave de Anthropic o de Slack cuya cola es el comienzo de un JWT completo (revisada el 2026-11-25)
- **THEN** la redacción deja una sola marca y ninguna parte del JWT, también en el log del stderr de un servidor
