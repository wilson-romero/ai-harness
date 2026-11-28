# Spec Delta

## MODIFIED Requirements

### Requirement: Identificador de proyecto validado
El sistema SHALL aceptar como proyecto solo un nombre simple que corresponda exactamente, incluidas mayúsculas, a una carpeta existente bajo `projects/`. SHALL rechazar separadores de ruta de cualquier plataforma, `..`, unidades, rutas de red, nombres reservados de Windows y nombres que acaben en punto o espacio. El rechazo SHALL nombrar el motivo.

#### Scenario: Traversal en el proyecto
- **WHEN** el usuario ejecuta `memory context ../../etc`
- **THEN** el sistema rechaza el identificador con un error controlado y no lee ningún fichero

#### Scenario: Forma de ruta de Windows rechazada
- **WHEN** el proyecto es `..\otro`, `C:\vault`, `\\servidor\recurso` o `CON`
- **THEN** el sistema rechaza el identificador en macOS y en Windows con el mismo mensaje

#### Scenario: Mayúsculas distintas
- **WHEN** existe `projects/demo-alpha/` y el usuario pide el proyecto `Demo-Alpha`
- **THEN** el sistema informa de que el proyecto no existe, aunque el sistema de ficheros no distinga mayúsculas

#### Scenario: Proyecto inexistente
- **WHEN** el usuario pide un proyecto válido sin carpeta en `projects/`
- **THEN** el sistema informa de que no existe y termina con código distinto de 0

#### Scenario: Carpeta de proyecto con espacios
- **WHEN** existe `projects/<nombre con un espacio>/_project.md` y el usuario ejecuta `memory context` con ese nombre
- **THEN** el sistema lo rechaza con un mensaje que dice que contiene un espacio, sin mostrar texto de la nota, y `memory search` sin `--project` sigue devolviendo esa nota
