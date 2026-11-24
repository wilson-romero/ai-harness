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
El bloque de contexto completo SHALL ocupar como máximo el número de bytes UTF-8 configurado. Cada nota SHALL recortarse a un máximo por nota con una marca visible de recorte, y las notas que no entran SHALL listarse como omitidas.

#### Scenario: Límite respetado
- **WHEN** las notas de `demo-alpha` suman más que el límite configurado
- **THEN** el bloque generado no supera el límite en bytes UTF-8 y stderr lista las notas omitidas

#### Scenario: Nota recortada
- **WHEN** una nota supera el máximo por nota
- **THEN** su texto en el bloque termina con la marca de recorte y no se parte ningún carácter multibyte

#### Scenario: Límite fuera de rango
- **WHEN** `HARNESS_MEMORY_CONTEXT_MAX_BYTES` vale menos que el mínimo o más que el máximo admitidos
- **THEN** el sistema rechaza la configuración con un error controlado

### Requirement: Reparto del presupuesto entre secciones
El presupuesto del bloque SHALL repartirse entre las secciones con notas, en su orden: cada sección SHALL disponer al menos de una parte igual de lo que quedaba cuando le tocó, y lo que no gaste SHALL pasar a las siguientes. La nota del proyecto y la sesión más reciente SHALL entrar siempre, recortadas si hace falta, salvo que su cabecera y la marca de recorte no quepan en su parte.

#### Scenario: Ninguna sección deja sin sitio a las demás
- **WHEN** `demo-alpha` tiene seis decisiones grandes y una nota de proyecto grande, y el límite es 1024, 2048 o 8192 bytes
- **THEN** el bloque incluye la nota del proyecto y la sesión más reciente, recortadas si hace falta, y no supera el límite

#### Scenario: Orden dentro de una sección
- **WHEN** una decisión grande no cabe entera en la parte de `Decisiones/` y la siguen decisiones pequeñas
- **THEN** la grande se recorta a su hueco y las que la siguen en esa sección se omiten aunque quepan, mientras las sesiones siguen entrando

### Requirement: Fechas futuras sin prioridad
Una nota cuya fecha `updated` es posterior a hoy SHALL ordenarse dentro de su sección como si no tuviera fecha.

#### Scenario: Fecha futura no adelanta una nota
- **WHEN** tres decisiones de unos 3 KB declaran `demo-alpha` y `updated: 2099-12-31`
- **THEN** con el límite por defecto el bloque sigue incluyendo la decisión real fechada antes, la lección, la nota de `Memoria-CC/` y las tres sesiones, y la decisión real va antes que las fechadas en el futuro

### Requirement: Contexto determinista
Para el mismo vault y el mismo proyecto, `memory context` SHALL producir el mismo bloque y `ask --project` SHALL enviar ese mismo bloque, salvo el marcador aleatorio que lo delimita.

#### Scenario: Lo que se ve es lo que se envía
- **WHEN** el usuario ejecuta `memory context demo-alpha` y después `ask SESSION_ID "pregunta" --project demo-alpha`
- **THEN** el texto enviado al proveedor contiene el mismo bloque que imprimió `memory context`, con el marcador como única diferencia

### Requirement: Memoria marcada como datos no confiables
El bloque SHALL ir precedido de un aviso de que es material de referencia y no instrucciones, SHALL delimitarse con un marcador aleatorio por solicitud que el texto de las notas no puede reproducir y SHALL ir antes de la pregunta del usuario. Ni el cuerpo ni la cabecera de una nota SHALL contener la secuencia `<<<` ni `>>>`.

#### Scenario: Marcador falsificado en una nota
- **WHEN** una nota contiene el texto del marcador de cierre seguido de una instrucción
- **THEN** en el texto enviado el marcador de cierre aparece una sola vez, después de todas las notas, y la instrucción queda dentro del bloque

#### Scenario: Imitación de los delimitadores
- **WHEN** una nota contiene `MEMORIA <x>` y `>>>` en dos líneas, una `М` cirílica tras `<<<`, un carácter de ancho cero entre `<<<` y `MEMORIA`, o `<<<` y `>>>` sueltos
- **THEN** el bloque contiene `<<<` y `>>>` solo en sus propios marcadores de apertura y cierre

#### Scenario: Cabecera sin saltos de línea
- **WHEN** el nombre de un fichero de nota contiene un salto de línea seguido de lo que parece otra cabecera
- **THEN** la cabecera de esa nota ocupa una sola línea y no aparece ninguna cabecera falsa

#### Scenario: Pregunta al final
- **WHEN** se envía una pregunta con `--project`
- **THEN** el texto enviado termina con la pregunta del usuario, después del marcador de cierre

### Requirement: Una instrucción en una nota no cambia la conducta del harness
El texto y el frontmatter de una nota SHALL NOT alterar qué notas son candidatas, el vault, el proyecto, el límite de tamaño, el proveedor ni el estado del vault, ni SHALL NOT adelantar la nota en su sección con una fecha futura. El tamaño de una nota SHALL poder reducir solo el sitio de las notas que la siguen en su propia sección y el sobrante que heredarían las secciones posteriores, nunca la parte propia de estas.

#### Scenario: Nota con órdenes al harness
- **WHEN** una nota de `demo-alpha` pide usar otro vault, incluir el proyecto `demo-beta`, ignorar el límite de tamaño y guardar una decisión, y el usuario pregunta con `--project demo-alpha`
- **THEN** las notas enviadas, el número de bytes y el contenido del vault son idénticos a los de la misma pregunta sin esa nota salvo la propia nota, y no se crea ningún fichero en el vault

#### Scenario: Nota con órdenes que llena el presupuesto
- **WHEN** tres notas de `Decisiones/` con esas órdenes, unos 3 KB cada una y `updated: 2099-12-31`, declaran `demo-alpha`, y el usuario pregunta con `--project demo-alpha`
- **THEN** las notas de las demás secciones enviadas son las mismas, con el mismo hash, que sin esas notas, la decisión real va antes que ellas, el bloque no supera el límite y el vault no cambia

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

#### Scenario: Rechazo auditado sin contenido
- **WHEN** una pregunta con `--project` se rechaza porque el identificador no es válido, el vault no está configurado, el proyecto no existe o no es el de la sesión
- **THEN** no se registra ninguna solicitud ni ningún mensaje, y queda un único evento de auditoría `memory.context` con resultado `denied`, sin rutas ni texto

#### Scenario: Sin opción no se lee el vault
- **WHEN** `HARNESS_VAULT_ROOT` apunta a un directorio inexistente y el usuario ejecuta `ask SESSION_ID "pregunta"` sin `--project`
- **THEN** la pregunta se completa como en el Corte 1

### Requirement: El contexto no se persiste
El sistema SHALL guardar como mensaje del usuario solo la pregunta, nunca el bloque de memoria, también con un proveedor de contenido sintético. Por cada nota incluida SHALL registrar su ruta relativa (saneada y redactada como el resto del texto del vault), su hash SHA-256, sus bytes y si se recortó, ligados a la solicitud.

#### Scenario: Canario de nota fuera de SQLite
- **WHEN** una nota incluida contiene un texto canario y el usuario pregunta con `--project` usando el Mock
- **THEN** el canario no aparece en ninguna columna de texto de la base de datos, y la procedencia de la solicitud lista esa nota con su hash

#### Scenario: Historial con la pregunta original
- **WHEN** el usuario consulta `history` de esa sesión
- **THEN** el mensaje del usuario muestra la pregunta tal como la escribió, sin el bloque de memoria
