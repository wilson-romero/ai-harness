# Spec Delta

## ADDED Requirements

### Requirement: Resultados de herramientas enmascarados
Todo texto devuelto por una herramienta MCP que el sistema imprime, incluidos los nombres y los valores de un resultado estructurado a cualquier profundidad, SHALL pasar por el mismo tratamiento que el texto del vault: quitar primero los caracteres de control y de formato y después sustituir cada credencial con un formato conocido por `[REDACTED:<tipo>]`, con los mismos formatos y el mismo límite declarado.

#### Scenario: Credencial en la clave y en el valor de un resultado estructurado
- **WHEN** una herramienta MCP devuelve un objeto con un token de GitHub como nombre de un campo y una clave de AWS con un carácter de ancho cero dentro como valor de otro, anidado en una lista
- **THEN** `mcp call` imprime `[REDACTED:github]` y `[REDACTED:aws]` en su lugar y ninguno de los dos tokens aparece en stdout ni en stderr

#### Scenario: Recuento de sustituciones de un resultado
- **WHEN** el resultado de una herramienta contiene dos credenciales de formato conocido
- **THEN** stderr indica que se enmascararon dos y la salida estándar no contiene ninguna de ellas
