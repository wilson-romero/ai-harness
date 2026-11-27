# tool-policy (delta)

## ADDED Requirements

### Requirement: Llamadas de un plan aprobado
Además de la CLI, una llamada a herramienta SHALL poder pedirse como paso de un plan de code mode aprobado por una persona. Esa llamada SHALL pasar las mismas comprobaciones y dejar la misma auditoría que `mcp call`. Un plan SHALL NOT llamar a una herramienta `write` y SHALL NOT abrir ningún canal de escucha.

#### Scenario: Escritura en un plan
- **WHEN** un plan nombra `set_project_metadata`
- **THEN** se rechaza al leerlo, antes de arrancar ningún servidor, y `starts.log` del servidor sintético queda vacío

#### Scenario: Misma auditoría
- **WHEN** un plan aprobado de dos pasos termina
- **THEN** `tool_calls` tiene dos filas con el mismo `plan_id`, el HMAC de sus argumentos y ningún contenido
