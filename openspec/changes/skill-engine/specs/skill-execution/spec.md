# Spec Delta

## Purpose

Define cómo se ejecuta un Skill dentro de una sesión: pasos lineales, referencias sin evaluación, comprobaciones deterministas, persistencia del estado, parada ante límites, estado incierto, reanudación y cancelación.

## ADDED Requirements

### Requirement: Ejecutar un Skill en una sesión
`skill run NAME --session ID` SHALL crear una ejecución ligada a esa sesión existente, con el nombre, la versión y el hash del Skill, y SHALL ejecutar sus pasos en el orden declarado usando el proveedor de la sesión. Al completarse SHALL imprimir por stdout la salida declarada del Skill y terminar con código 0.

#### Scenario: Ejecución completa con el Mock
- **WHEN** el usuario ejecuta un Skill sintético `llm` → `validate` con respuestas guionizadas que pasan la comprobación
- **THEN** la ejecución termina en `completed`, stdout contiene la salida del paso `validate` y `SELECT status FROM skill_steps` devuelve `completed` para los dos pasos

#### Scenario: Sesión inexistente
- **WHEN** el usuario ejecuta `skill run demo-echo --session` con un UUID que no existe
- **THEN** el sistema termina con un error controlado y `skill_runs` no gana ninguna fila

#### Scenario: Skill inválido no se ejecuta
- **WHEN** el usuario ejecuta `skill run` sobre un Skill marcado `invalid`
- **THEN** el sistema termina con código distinto de 0, sin llamar al proveedor y sin crear ninguna ejecución

### Requirement: Una ejecución abierta por sesión
Una sesión SHALL tener como mucho una ejecución en estado `pending`, `running`, `awaiting_approval` o `uncertain`. Una segunda `skill run` en esa sesión SHALL rechazarse hasta que la primera termine o se cancele.

#### Scenario: Segunda ejecución rechazada
- **WHEN** una sesión tiene una ejecución en `awaiting_approval` y el usuario lanza otra `skill run` en la misma sesión
- **THEN** el sistema la rechaza nombrando la ejecución abierta, sin llamar al proveedor

### Requirement: Entradas declaradas y acotadas
Las entradas SHALL pasarse con `--input NOMBRE=VALOR` o `--input-file NOMBRE=RUTA`, SHALL coincidir con las declaradas por el Skill y SHALL respetar 64 KiB por entrada y 128 KiB en total. El contenido de las entradas SHALL NOT guardarse en SQLite; se guardan su SHA-256 y su tamaño.

#### Scenario: Entrada no declarada
- **WHEN** el usuario pasa `--input extra=x` a un Skill que no declara `extra`
- **THEN** el sistema rechaza la ejecución antes de crearla

#### Scenario: Entrada demasiado grande
- **WHEN** el usuario pasa con `--input-file` un fichero de 65 537 bytes
- **THEN** el sistema rechaza la ejecución sin leerlo entero y sin llamar al proveedor

#### Scenario: Entrada que no es un fichero regular
- **WHEN** el usuario pasa con `--input-file` una tubería con nombre, un dispositivo o una carpeta
- **THEN** el sistema la rechaza enseguida, sin esperar a que nadie escriba en ella y sin crear la ejecución

#### Scenario: Entrada que no es Unicode válido
- **WHEN** el usuario pasa con `--input` un valor con un byte que no es UTF-8
- **THEN** el sistema rechaza la ejecución con un error controlado antes de crearla

#### Scenario: Canario de una entrada fuera de SQLite
- **WHEN** una ejecución con el Mock completa un paso `llm` cuya entrada contiene un canario
- **THEN** el canario no aparece en ninguna columna de texto de ninguna tabla, y `skill_runs` guarda el SHA-256 de la entrada

### Requirement: Referencias sustituidas literalmente
Las referencias de una plantilla SHALL sustituirse en una sola pasada por el valor literal referido; un valor insertado SHALL NOT volver a interpretarse, aunque contenga `{{...}}`. Cada valor insertado SHALL ir marcado como datos, con un delimitador que su contenido no pueda cerrar.

#### Scenario: Valor con forma de referencia
- **WHEN** una entrada contiene el texto `{{inputs.secreto}}` y la plantilla la inserta
- **THEN** el prompt enviado contiene ese texto literal y ninguna otra sustitución

#### Scenario: Delimitador falsificado en una entrada
- **WHEN** una entrada contiene el marcador de cierre de datos
- **THEN** el marcador de cierre aparece en el prompt enviado una sola vez por cada valor insertado y el texto de la entrada queda dentro

### Requirement: Paso llm a través de la sesión
Un paso `llm` SHALL enviar su prompt a través de la sesión con la misma conducta de plazo que `ask`: vencido antes del envío el paso falla, vencido después queda `uncertain`. Del texto enviado SHALL guardarse solo una marca con el Skill y el paso; la respuesta SHALL guardarse solo si el proveedor es sintético.

#### Scenario: Historial de la sesión con un paso de Skill
- **WHEN** una ejecución completa un paso `llm` con el Mock
- **THEN** `history` de la sesión muestra la marca del paso como pregunta y la respuesta del Mock, y el prompt compuesto no aparece en SQLite

#### Scenario: Paso llm con memoria del proyecto
- **WHEN** un paso declara memoria del proyecto y la sesión se creó con `--project demo-alpha`
- **THEN** el proveedor recibe el bloque de contexto de `demo-alpha` antes del prompt y `request_context` registra las notas usadas

#### Scenario: Paso llm con memoria en una sesión sin proyecto
- **WHEN** un paso declara memoria del proyecto y la sesión no tiene proyecto
- **THEN** la ejecución se rechaza antes de llamar al proveedor

### Requirement: Comprobaciones deterministas de validate
Un paso `validate` SHALL comprobar la salida de un paso anterior solo con reglas declaradas: tamaño mínimo y máximo, encabezados Markdown obligatorios, o JSON estricto que sea un objeto con campos declarados, tipados y acotados, sin campos extra. Si una regla falla, el paso y la ejecución SHALL terminar en `failed` nombrando la regla, sin repetir el paso anterior.

#### Scenario: Encabezado obligatorio ausente
- **WHEN** la respuesta guionizada no contiene el encabezado `## Preguntas pendientes` que exige el paso
- **THEN** el paso queda `failed` con la regla incumplida, la ejecución queda `failed` y el proveedor recibió una sola pregunta

#### Scenario: Encabezado solo dentro de un bloque de código
- **WHEN** la respuesta contiene el encabezado exigido solo dentro de un bloque de código (por ejemplo, entre dos líneas de tres acentos graves), o después de una valla que no se cierra
- **THEN** el encabezado no cuenta y el paso queda `failed` con la regla `required_headings` (añadido el 2026-11-26)

#### Scenario: Bloque json con una valla más larga
- **WHEN** la respuesta lleva prosa y un único bloque `json` abierto y cerrado con cuatro acentos graves (o con virgulillas)
- **THEN** se analiza el interior de ese bloque; dos bloques `json` o uno sin cerrar dejan el paso `failed` con `json_block` (añadido el 2026-11-26)

#### Scenario: JSON con campo extra o tipo erróneo
- **WHEN** la respuesta es un objeto JSON con un campo no declarado o con un número donde se espera texto
- **THEN** el paso queda `failed` nombrando el campo

#### Scenario: JSON con claves duplicadas o NaN
- **WHEN** la respuesta contiene `{"a": 1, "a": 2}` o un valor `NaN`
- **THEN** el paso queda `failed` en lugar de aceptar uno de los valores

#### Scenario: Misma salida, mismo resultado
- **WHEN** se valida dos veces la misma salida con las mismas reglas
- **THEN** los dos resultados son idénticos byte a byte

### Requirement: Límites de ejecución
Una ejecución SHALL detenerse cuando un prompt compuesto supere 64 KiB sin contar la memoria, una respuesta supere 128 KiB, un paso agote su plazo o la invocación supere 1800 segundos. La parada SHALL dejar el paso y la ejecución en `failed` con el límite nombrado, o en `uncertain` si el plazo venció tras el envío, y no ejecutar ningún paso posterior.

#### Scenario: Respuesta demasiado grande
- **WHEN** la respuesta guionizada ocupa 131 073 bytes
- **THEN** el paso queda `failed` con el límite `response_bytes`, ningún paso posterior se ejecuta y el paso no guarda salida; la respuesta queda en el historial de la sesión como cualquier respuesta de `ask`, solo si el proveedor es sintético

#### Scenario: Plazo del paso tras el envío
- **WHEN** el Mock está en `timeout_after_send` y el paso declara un plazo de 1 segundo
- **THEN** el paso y la ejecución quedan `uncertain`, el proveedor recibió una sola pregunta y el comando termina con código distinto de 0

#### Scenario: Prompt demasiado grande
- **WHEN** la plantilla con sus valores insertados supera 64 KiB
- **THEN** el paso queda `failed` sin llamar al proveedor

### Requirement: Estado consultable sin contenido
`skill status RUN_ID` SHALL mostrar el Skill, su versión y hash, la sesión, el estado de la ejecución y de cada paso con su intento, y la aprobación pendiente si la hay, sin imprimir entradas ni salidas. Con `--output` SHALL imprimir la salida final si está guardada, o indicar que no se guardó.

#### Scenario: Estado tras reinicio
- **WHEN** una ejecución quedó en `awaiting_approval` y se consulta su estado desde otro proceso
- **THEN** la salida muestra `awaiting_approval`, el paso y la caducidad de la aprobación, sin el texto de la propuesta

#### Scenario: Secuencias de escape en la salida
- **WHEN** la salida final de un Skill (aunque nombre un paso `llm`) contiene ESC, BEL, U+202E o U+200B
- **THEN** ni `skill run` ni `skill status --output` imprimen esos caracteres

### Requirement: Paso incierto nunca se repite solo
Una ejecución `uncertain` SHALL NOT reanudarse sin una decisión explícita: `skill resume RUN_ID` SHALL rechazarse explicando qué paso es incierto, y solo `skill resume RUN_ID --retry-step ID`, con el identificador exacto de ese paso, SHALL repetirlo como un intento nuevo, con un máximo de 3 intentos por paso.

#### Scenario: Reanudar sin reconciliar
- **WHEN** el usuario ejecuta `skill resume` sobre una ejecución con un paso `llm` incierto
- **THEN** el sistema se niega, nombra el paso y la opción `--retry-step`, y el proveedor no recibe nada

#### Scenario: Reintento explícito
- **WHEN** el usuario ejecuta `skill resume RUN_ID --retry-step draft` sobre ese paso incierto
- **THEN** se crea el intento 2 del paso, el intento 1 conserva su estado `uncertain` y el proveedor recibe una pregunta

#### Scenario: Reintento de otro paso
- **WHEN** el usuario pasa `--retry-step` con un paso que no es el incierto
- **THEN** el sistema se niega sin cambiar nada

### Requirement: Recuperación de ejecuciones interrumpidas
Al arrancar, una ejecución `running`, o no terminal con un paso `running` o `applying`, cuya sesión no tiene un proceso vivo SHALL pasar a `uncertain` si tenía un paso `llm` o `approval` en curso, o a `pending` si estaba entre pasos o en un paso `validate`. Un paso `validate` interrumpido SHALL poder repetirse porque no tiene efectos fuera.

#### Scenario: Proceso muerto durante un paso llm
- **WHEN** se mata el proceso de `skill run` mientras el Mock espera tras el envío y se ejecuta después cualquier comando
- **THEN** la ejecución y el paso quedan `uncertain` y la solicitud de la sesión también

#### Scenario: Paso applying en una ejecución que espera aprobación
- **WHEN** un paso `approval` quedó `applying` en una ejecución `awaiting_approval` y se ejecuta la recuperación
- **THEN** el paso y la ejecución quedan `uncertain`

#### Scenario: Ejecución viva no se toca
- **WHEN** una ejecución está en curso en otro proceso y se ejecuta `skill status` sobre ella
- **THEN** su estado sigue siendo `running`

### Requirement: Reanudar con el mismo Skill y las mismas entradas
`skill resume` SHALL continuar desde el primer paso no completado solo si el hash actual del Skill coincide con el registrado y las entradas que el usuario vuelve a pasar tienen el mismo SHA-256. Si no, SHALL negarse sin cambiar la ejecución.

#### Scenario: Skill cambiado en disco
- **WHEN** se modifica una plantilla del Skill entre `skill run` y `skill resume`
- **THEN** `skill resume` se niega nombrando los dos hashes y la ejecución conserva su estado

#### Scenario: Entrada distinta al reanudar
- **WHEN** el usuario reanuda pasando con `--input-file` un fichero distinto del original
- **THEN** el sistema se niega sin llamar al proveedor

#### Scenario: Salidas no guardadas por proveedor no sintético
- **WHEN** una ejecución con un proveedor que no declara contenido sintético se interrumpió después de completar un paso `llm`
- **THEN** `skill resume` se niega porque las salidas no se guardaron, y la ejecución pasa a `failed`

### Requirement: Proveedor no sintético exige terminal si hay aprobación
Si el proveedor de la sesión no declara contenido sintético y el Skill tiene un paso `approval`, `skill run` SHALL exigir una terminal interactiva y SHALL rechazar la ejecución antes de la primera pregunta si no la hay, porque esa ejecución no se podrá reanudar en otro proceso.

#### Scenario: Proveedor no sintético sin terminal
- **WHEN** se ejecuta `skill run` con stdin redirigido, un proveedor de prueba no sintético y un Skill con paso `approval`
- **THEN** el sistema se niega con un error controlado, el proveedor no recibe nada y no se crea ninguna ejecución

### Requirement: Cancelar una ejecución
`skill cancel RUN_ID` SHALL pasar a `cancelled` una ejecución `pending`, `awaiting_approval` o `uncertain`, y SHALL revocar su aprobación pendiente o concedida. Antes, SHALL reconciliar cada paso de aprobación `uncertain` con su efecto y decir si su contenido está en el destino, si no se aplicó nada o si hay otra cosa; cancelar SHALL NOT deshacer un efecto aplicado. Una ejecución terminada o en curso en otro proceso SHALL NOT cambiar.

#### Scenario: Cancelar con aprobación pendiente
- **WHEN** el usuario cancela una ejecución en `awaiting_approval`
- **THEN** la ejecución queda `cancelled`, su aprobación queda `revoked` y la sesión admite una ejecución nueva

### Requirement: Respuestas guionizadas del Mock
Con `HARNESS_MOCK_RESPONSES` apuntando a un fichero JSON local de pares texto → respuesta, el Mock SHALL responder con la respuesta del primer texto, en orden alfabético, contenido en el prompt, y con su respuesta determinista habitual si ninguno coincide. El fichero SHALL validarse (objeto de cadenas, máximo 1 MiB) y su contenido SHALL seguir contando como sintético.

#### Scenario: Respuesta elegida por el texto del prompt
- **WHEN** el fichero contiene `{"tarea: demo-echo/draft": "## Resumen\nok"}` y la plantilla del paso contiene `tarea: demo-echo/draft`
- **THEN** el paso recibe exactamente `## Resumen\nok`

#### Scenario: Fichero de respuestas inválido
- **WHEN** `HARNESS_MOCK_RESPONSES` apunta a un JSON que no es un objeto de cadenas
- **THEN** el comando termina con un error controlado antes de crear ninguna ejecución
