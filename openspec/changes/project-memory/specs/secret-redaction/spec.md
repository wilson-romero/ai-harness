# Spec Delta

## Purpose

Evita que una credencial con formato conocido guardada en una nota salga del vault hacia la terminal o hacia el proveedor de lenguaje, y deja escrito qué no puede detectar.

## ADDED Requirements

### Requirement: Formatos conocidos enmascarados
Todo texto leído del vault que el sistema imprime o envía al proveedor SHALL sustituir cada credencial con un formato conocido por `[REDACTED:<tipo>]`. Los formatos SHALL detectarse por prefijo de proveedor y forma exacta: clave privada PEM, Anthropic, OpenAI, GitHub, GitLab, AWS, Google, Slack, DigitalOcean, Stripe y JWT.

#### Scenario: Token en una nota enviada al proveedor
- **WHEN** una nota de `demo-alpha` contiene un token con formato de GitHub y el usuario pregunta con `--project demo-alpha`
- **THEN** el texto que recibe el proveedor contiene `[REDACTED:github]` y no contiene el token

#### Scenario: Clave privada de varias líneas
- **WHEN** una nota contiene un bloque de clave privada PEM completo
- **THEN** `memory context` muestra `[REDACTED:private-key]` en lugar de todo el bloque

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
