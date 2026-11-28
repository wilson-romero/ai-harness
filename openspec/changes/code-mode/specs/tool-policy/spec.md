# tool-policy (delta)

## ADDED Requirements

### Requirement: Llamadas de un plan aprobado
Además de la CLI, una llamada a herramienta SHALL poder pedirse como paso de un plan de code mode aprobado por una persona, o por la regla `auto_read` que la persona escribió en su lista local para esa lectura. Esa llamada SHALL pasar las mismas comprobaciones y dejar la misma auditoría que `mcp call`. Un plan SHALL NOT llamar a una herramienta `write` y SHALL NOT abrir ningún canal de escucha.

#### Scenario: Escritura en un plan
- **WHEN** un plan nombra `set_project_metadata`
- **THEN** se rechaza al leerlo, antes de arrancar ningún servidor, y `starts.log` del servidor sintético queda vacío

#### Scenario: Misma auditoría
- **WHEN** un plan aprobado de dos pasos termina
- **THEN** `tool_calls` tiene dos filas con el mismo `plan_id`, el HMAC de sus argumentos y ningún contenido

### Requirement: El bucle de code mode no es recursión
En un bucle `/agent`, cada turno SHALL ser una pregunta del harness al proveedor y cada plan SHALL aprobarse y ejecutarse como uno de `/plan`. Un servidor SHALL NOT poder pedir un turno, una pregunta ni una llamada: lo que devuelve solo vuelve como dato, en el turno siguiente.

#### Scenario: Un resultado que pide otra llamada
- **WHEN** un resultado trae un plan escrito y una orden de llamar a otra herramienta
- **THEN** esa herramienta no se llama y el plan no se lee

