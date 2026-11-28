# Spec Delta

## ADDED Requirements

### Requirement: Índices de Memoria-CC con el formato real
Una entrada de un índice `Memoria-CC/MEMORY*.md` SHALL leerse como una ruta relativa a `Memoria-CC/`, con `.` y `..` resueltos como texto, y SHALL contar como colgante solo si no nombra ningún fichero que la lectura confinada vio. Las huérfanas y los candidatos a duplicado SHALL buscarse solo en el primer nivel de `Memoria-CC/`.

#### Scenario: Entrada de índice relativa a Memoria-CC
- **WHEN** un índice de `Memoria-CC/` enlaza `../Lecciones/<nota>.md` que existe, una rama `MEMORY-<tema>.md` que existe, `../Lecciones/<otra>.md` que no existe y `../../<fuera>.md`
- **THEN** `index_dangling` lista solo las dos últimas, con su ruta resuelta (`Lecciones/<otra>.md` y `../<fuera>.md`), y no se consulta ninguna ruta fuera del vault

#### Scenario: Solo las entradas que terminan en .md
- **WHEN** un índice enlaza `..`, `../Lecciones/`, `/Lecciones/<nota>.md` que existe bajo la raíz del vault y `../Memoria/Archivo/<nota>.md`
- **THEN** `index_dangling` no lista las dos primeras, y lista `/Lecciones/<nota>.md` tal como está escrita y `Memoria/Archivo/<nota>.md`

#### Scenario: Solo el primer nivel de Memoria-CC
- **WHEN** `Memoria-CC/` tiene una nota sin entrada en el índice y una subcarpeta con una nota del mismo nombre que otra del primer nivel
- **THEN** `index_orphans` lista solo la nota del primer nivel y `duplicate_candidates` no lista ningún par

### Requirement: Frontmatter y enlaces con el formato real
Las notas `projects/<slug>/_project.md`, `_index.md` y `agents/_skills-index.md` SHALL poder omitir `created`; cualquier otra nota SHALL seguir necesitándolo. Un enlace `[[<ruta>\|<alias>]]` escrito en una tabla SHALL resolverse sin la `\` que precede a la `|`; sin `|`, la `\` SHALL seguir formando parte de la ruta.

#### Scenario: Notas que la captura reescribe
- **WHEN** el vault sintético tiene `_project.md`, `_index.md` y `agents/_skills-index.md` sin `created`
- **THEN** `invalid_frontmatter` no lista ninguna de ellas, y una lección o una sesión sin `created`, o `projects/<slug>/otra/_project.md`, sí sale

#### Scenario: Enlace con alias escapado en una tabla
- **WHEN** una tabla contiene `[[agents/skills/revisor\|revisor]]`, que existe, y `[[agents/skills/no-existe\|otro]]`
- **THEN** `broken_links` lista solo la nota por el segundo enlace

#### Scenario: Barra sin alias
- **WHEN** una nota contiene `[[agents/skills/revisor\]]`
- **THEN** `broken_links` la lista, con `agents/skills/revisor.md` como corrección

### Requirement: Línea del frontmatter que YAML rechaza
`memory maintain` SHALL listar en `invalid_frontmatter`, con el motivo `a value is not valid YAML`, una nota con una línea `clave: valor` sin sangría de una de dos formas: un valor plano (sin comillas ni `[`) que, sin su comentario (desde un espacio o tabulador seguido de `#`), tiene `:` seguido de espacio o tabulador o acaba en `:`; o un escalar entre comillas cerrado en la línea y seguido de algo que no es espacio, tabulador ni comentario.

#### Scenario: Valor sin comillas con dos puntos
- **WHEN** una nota de `Memoria-CC/` declara `description: Estilo: breve`, `tab: a:<TAB>b`, `h: a#b: c` o `k: "a" b: "c"`
- **THEN** `invalid_frontmatter` la lista con `a value is not valid YAML`, y con `description: "Estilo: breve"`, `h: a # b: c`, `k: 'it''s: fine'`, `hora: 12:15:00` o `source: https://…` no sale

### Requirement: La regla de YAML solo informa
Los campos del frontmatter SHALL leerse igual con o sin una línea que YAML rechaza, de modo que esa línea no cambie qué notas entran en el contexto o en la búsqueda por proyecto, sus cabeceras ni el reconocimiento de una nota de decisión.

#### Scenario: Una línea que YAML rechaza no cambia la selección
- **WHEN** una nota de `Memoria-CC/` con `tags: [demo-alpha]` y `description: Estilo: breve`, y una sesión con `project: Cliente: X/demo-alpha`, están en el vault de `demo-alpha`
- **THEN** `memory context demo-alpha` da el mismo bloque, byte a byte con el mismo marcador, que el código de `origin/develop` `e2ce87f` sobre ese vault; `memory search --project demo-alpha` devuelve la nota; y una nota de decisión con una línea así sigue reconocida por su `decision_id`

#### Scenario: Vault sintético con el formato real
- **WHEN** el usuario ejecuta `memory maintain --dry-run` sobre el vault sintético, que tiene el formato de `claude-memory-system` en el commit `92b19ea`
- **THEN** todas las categorías aparecen con recuento 0
