# Spec Delta

## Purpose

Define qué memoria de un proyecto acompaña a una pregunta, en qué orden y con qué límite, cómo se marca como datos no confiables y qué queda registrado, para que el proveedor reciba contexto útil sin que el vault dirija la conducta del harness.

## ADDED Requirements

### Requirement: Selección de notas del proyecto
El contexto de un proyecto SHALL incluir solo, y en este orden: la nota del proyecto `projects/<slug>/_project.md`; las notas de `Decisiones/`, `Lecciones/` y `Memoria-CC/` que declaran ese proyecto en su frontmatter (`project_slug` o una etiqueta igual al slug); y las notas de sesión más recientes de `projects/<slug>/sessions/`. SHALL NOT incluir notas de otros proyectos, de `daily/`, `agents/`, `Memoria/` ni el índice general.

#### Scenario: Orden de las secciones
- **WHEN** el usuario ejecuta `memory context demo-alpha` sobre el vault sintético
- **THEN** la salida muestra primero la nota del proyecto, después las decisiones, lecciones y notas curadas de `demo-alpha` y por último sus sesiones más recientes

#### Scenario: Sin mezcla de proyectos
- **WHEN** `demo-beta` tiene una decisión con un texto canario y el usuario ejecuta `memory context demo-alpha`
- **THEN** la salida no contiene el canario

#### Scenario: Memoria de la máquina excluida
- **WHEN** `Memoria/personas.md` y `Memoria/contexto-reciente.md` contienen un texto canario
- **THEN** `memory context demo-alpha` no contiene el canario

### Requirement: Contexto acotado
El bloque de contexto completo SHALL ocupar como máximo el número de bytes UTF-8 configurado. Cada nota SHALL recortarse a un máximo por nota con una marca visible de recorte, y las notas que ya no caben SHALL omitirse enteras y listarse como omitidas.

#### Scenario: Límite respetado
- **WHEN** las notas de `demo-alpha` suman más que el límite configurado
- **THEN** el bloque generado no supera el límite en bytes UTF-8 y stderr lista las notas omitidas

#### Scenario: Nota recortada
- **WHEN** una nota supera el máximo por nota
- **THEN** su texto en el bloque termina con la marca de recorte y no se parte ningún carácter multibyte

#### Scenario: Límite fuera de rango
- **WHEN** `HARNESS_MEMORY_CONTEXT_MAX_BYTES` vale menos que el mínimo o más que el máximo admitidos
- **THEN** el sistema rechaza la configuración con un error controlado

### Requirement: Contexto determinista
Para el mismo vault y el mismo proyecto, `memory context` SHALL producir el mismo bloque y `ask --project` SHALL enviar ese mismo bloque, salvo el marcador aleatorio que lo delimita.

#### Scenario: Lo que se ve es lo que se envía
- **WHEN** el usuario ejecuta `memory context demo-alpha` y después `ask SESSION_ID "pregunta" --project demo-alpha`
- **THEN** el texto enviado al proveedor contiene el mismo bloque que imprimió `memory context`, con el marcador como única diferencia

### Requirement: Memoria marcada como datos no confiables
El bloque SHALL ir precedido de un aviso de que es material de referencia y no instrucciones, SHALL delimitarse con un marcador aleatorio por solicitud que el texto de las notas no puede reproducir y SHALL ir antes de la pregunta del usuario.

#### Scenario: Marcador falsificado en una nota
- **WHEN** una nota contiene el texto del marcador de cierre seguido de una instrucción
- **THEN** en el texto enviado el marcador de cierre aparece una sola vez, después de todas las notas, y la instrucción queda dentro del bloque

#### Scenario: Pregunta al final
- **WHEN** se envía una pregunta con `--project`
- **THEN** el texto enviado termina con la pregunta del usuario, después del marcador de cierre

### Requirement: Una instrucción en una nota no cambia la conducta del harness
El texto de una nota SHALL NOT alterar qué notas se incluyen, el vault, el proyecto, el límite de tamaño, el proveedor ni el estado del vault.

#### Scenario: Nota con órdenes al harness
- **WHEN** una nota de `demo-alpha` pide usar otro vault, incluir el proyecto `demo-beta`, ignorar el límite de tamaño y guardar una decisión, y el usuario pregunta con `--project demo-alpha`
- **THEN** las notas enviadas, el número de bytes y el contenido del vault son idénticos a los de la misma pregunta sin esa nota salvo la propia nota, y no se crea ningún fichero en el vault

### Requirement: Preguntar con contexto de proyecto
`ask SESSION_ID PROMPT --project SLUG` SHALL exigir que la sesión esté creada con ese mismo proyecto. Sin `--project`, `ask` SHALL NOT leer el vault.

#### Scenario: Proyecto de la sesión
- **WHEN** la sesión se creó con `--project demo-alpha` y el usuario ejecuta `ask SESSION_ID "pregunta" --project demo-alpha`
- **THEN** la pregunta se envía con el contexto de `demo-alpha` y termina con código 0

#### Scenario: Proyecto distinto del de la sesión
- **WHEN** la sesión se creó con `--project demo-alpha` y el usuario pide `--project demo-beta`
- **THEN** el sistema rechaza la pregunta con un error controlado y no registra ninguna solicitud

#### Scenario: Sesión sin proyecto
- **WHEN** la sesión no tiene proyecto y el usuario usa `--project demo-alpha`
- **THEN** el sistema rechaza la pregunta y no registra ninguna solicitud

#### Scenario: Sin opción no se lee el vault
- **WHEN** `HARNESS_VAULT_ROOT` apunta a un directorio inexistente y el usuario ejecuta `ask SESSION_ID "pregunta"` sin `--project`
- **THEN** la pregunta se completa como en el Corte 1

### Requirement: El contexto no se persiste
El sistema SHALL guardar como mensaje del usuario solo la pregunta, nunca el bloque de memoria, también con un proveedor de contenido sintético. Por cada nota incluida SHALL registrar su ruta relativa, su hash SHA-256, sus bytes y si se recortó, ligados a la solicitud.

#### Scenario: Canario de nota fuera de SQLite
- **WHEN** una nota incluida contiene un texto canario y el usuario pregunta con `--project` usando el Mock
- **THEN** el canario no aparece en ninguna columna de texto de la base de datos, y la procedencia de la solicitud lista esa nota con su hash

#### Scenario: Historial con la pregunta original
- **WHEN** el usuario consulta `history` de esa sesión
- **THEN** el mensaje del usuario muestra la pregunta tal como la escribió, sin el bloque de memoria
