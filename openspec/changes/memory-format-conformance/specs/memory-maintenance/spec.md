# Spec Delta

## ADDED Requirements

### Requirement: Índices de Memoria-CC con el formato real
Una entrada de un índice `Memoria-CC/MEMORY*.md` SHALL leerse como una ruta relativa a `Memoria-CC/`, con `.` y `..` resueltos como texto, y SHALL contar como colgante solo si no nombra ningún fichero que la lectura confinada vio. Las huérfanas y los candidatos a duplicado SHALL buscarse solo en el primer nivel de `Memoria-CC/`.

#### Scenario: Entrada de índice relativa a Memoria-CC
- **WHEN** un índice de `Memoria-CC/` enlaza `../Lecciones/<nota>.md` que existe, una rama `MEMORY-<tema>.md` que existe, `../Lecciones/<otra>.md` que no existe y `../../<fuera>.md`
- **THEN** `index_dangling` lista solo las dos últimas, con su ruta resuelta (`Lecciones/<otra>.md` y `../<fuera>.md`), y no se consulta ninguna ruta fuera del vault

#### Scenario: Solo el primer nivel de Memoria-CC
- **WHEN** `Memoria-CC/` tiene una nota sin entrada en el índice y una subcarpeta con una nota del mismo nombre que otra del primer nivel
- **THEN** `index_orphans` lista solo la nota del primer nivel y `duplicate_candidates` no lista ningún par

### Requirement: Frontmatter y enlaces con el formato real
Las notas `projects/<slug>/_project.md`, `_index.md` y `agents/_skills-index.md` SHALL poder omitir `created`; cualquier otra nota SHALL seguir necesitándolo. Un valor sin comillas que contiene `: ` o termina en `:` SHALL contar como frontmatter no válido. Un enlace `[[<ruta>\|<alias>]]` escrito en una tabla SHALL resolverse sin la `\` final de la ruta.

#### Scenario: Notas que la captura reescribe
- **WHEN** el vault sintético tiene `_project.md`, `_index.md` y `agents/_skills-index.md` sin `created`
- **THEN** `invalid_frontmatter` no lista ninguna de ellas, y una lección o una sesión sin `created`, o `projects/<slug>/otra/_project.md`, sí sale

#### Scenario: Valor sin comillas con dos puntos
- **WHEN** una nota de `Memoria-CC/` declara `description: Estilo: breve`
- **THEN** `invalid_frontmatter` la lista como `unsupported`, y la misma nota con `description: "Estilo: breve"` no sale

#### Scenario: Enlace con alias escapado en una tabla
- **WHEN** una tabla contiene `[[agents/skills/revisor\|revisor]]`, que existe, y `[[agents/skills/no-existe\|otro]]`
- **THEN** `broken_links` lista solo la nota por el segundo enlace

#### Scenario: Vault sintético con el formato real
- **WHEN** el usuario ejecuta `memory maintain --dry-run` sobre el vault sintético, que tiene el formato de `claude-memory-system` en el commit `92b19ea`
- **THEN** todas las categorías aparecen con recuento 0
