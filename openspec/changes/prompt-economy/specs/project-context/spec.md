# Spec Delta

## MODIFIED Requirements

### Requirement: Contexto determinista
Para el mismo vault y el mismo proyecto, `memory context` SHALL producir el mismo bloque y `ask --project` SHALL enviar ese mismo bloque, salvo el marcador aleatorio que lo delimita. Cuando el aviso de respuesta concisa está activo (capacidad `answer-style`), `memory context` SHALL imprimirlo antes del bloque, separado por una línea en blanco, igual que se envía.

#### Scenario: Lo que se ve es lo que se envía
- **WHEN** el usuario ejecuta `memory context demo-alpha` y después `ask SESSION_ID "pregunta" --project demo-alpha`
- **THEN** el texto enviado al proveedor es exactamente lo que imprimió `memory context` (aviso de respuesta concisa incluido, si está activo), seguido de una línea en blanco y la pregunta, con el marcador como única diferencia

## ADDED Requirements

### Requirement: Cabecera de nota corta
Cada nota del bloque SHALL empezar con una cabecera de una sola línea `--- <ruta> (<type>, <updated>)`, donde la ruta es la del vault sin el prefijo `projects/<slug>/` y sin la extensión `.md`, de modo que la ruta del vault se recupera sin ambigüedad. La ruta y el tipo SHALL pasar por la misma limpieza, redacción y neutralización que el resto del texto del vault.

#### Scenario: Cabecera corta sin pérdida
- **WHEN** el usuario ejecuta `memory context demo-alpha` sobre el vault sintético
- **THEN** las siete cabeceras son `--- _project (project, 2026-11-21)`, `--- Decisiones/alpha-mensajeria (decision, 2026-11-16)`, `--- Lecciones/2026-11-10-reintentos-idempotentes (lesson, 2026-11-10)`, `--- Memoria-CC/project_alpha-integraciones (project, 2026-11-15)` y las tres sesiones como `--- sessions/<fichero> (session, <fecha>)`, suman 383 caracteres (384 hasta el 2026-11-28, cuando `memory-format-conformance` dio a la lección del vault sintético su tipo real, `lesson`), y la ruta del vault reconstruida desde cada una es la registrada en la procedencia de la solicitud

### Requirement: Memoria por deltas en la misma conversación remota
Con un proveedor que conserva la conversación, una pregunta suelta con proyecto SHALL enviar en lugar del bloque una línea del harness que dice que la memoria no ha cambiado, o solo las notas nuevas entre delimitadores con marcador nuevo, solo si hay una base (un bloque completo) en la sesión, todas las solicitudes desde la base terminaron `completed` en la misma conversación remota con la misma huella, y todas las notas de la base siguen con el mismo hash de lo enviado.

#### Scenario: Segunda pregunta sin cambios en la misma conversación
- **WHEN** con un proveedor de prueba que conserva la conversación, una sesión de `demo-alpha` completa una pregunta y hace otra sin que cambie el vault
- **THEN** el segundo texto enviado no contiene el marcador `<<<MEMORIA` ni el texto de ninguna nota, contiene la línea de memoria sin cambios, y la solicitud queda con modo `unchanged`

#### Scenario: Nota nueva entre dos preguntas
- **WHEN** entre dos preguntas se añade una decisión de `demo-alpha` que entra en el bloque sin cambiar las demás notas enviadas
- **THEN** el segundo texto enviado contiene solo esa nota entre delimitadores con un marcador nuevo, y `request_context` de la solicitud lista todas las notas vigentes con `in_message` 1 solo para la nueva

### Requirement: Vuelta al bloque completo
En cualquier otro caso la pregunta SHALL enviar el bloque completo. Los pasos LLM de un Skill SHALL enviar siempre el bloque completo. La persona SHALL poder forzarlo.

#### Scenario: Vuelta al bloque completo
- **WHEN** antes de la segunda pregunta ocurre uno de estos hechos: la conversación remota es otra o está vacía, la sesión está cerrada, una solicitud posterior a la base no terminó `completed`, el proveedor no conserva la conversación (Mock), cambió el proveedor o el límite de contexto, una nota de la base se editó, se borró o se omitió, o cambió el número de credenciales redactadas
- **THEN** el texto enviado contiene el bloque completo, precedido de la frase de que sustituye a la memoria anterior cuando ya había base, y la solicitud registra modo `full` con el motivo correspondiente

#### Scenario: Paso de Skill con memoria
- **WHEN** un paso LLM de `architecture-memory` se ejecuta en una sesión con base
- **THEN** envía el bloque completo y la procedencia de la decisión lista todas las notas del bloque

#### Scenario: Reenvío completo forzado
- **WHEN** la persona escribe `/context --full` en la conversación, o usa `ask … --project demo-alpha --full-memory`
- **THEN** la pregunta siguiente envía el bloque completo con motivo `forced`

### Requirement: Registro y vista de los deltas
El sistema SHALL registrar por solicitud el modo, el motivo, la huella (proveedor, proyecto, límite, versión del formato y número de redacciones) y el hash de la referencia remota, y por nota el hash de lo enviado y si su texto iba en el mensaje, nunca el texto. `/context` SHALL mostrar el modo, el motivo y el texto exacto que enviaría la próxima pregunta.

#### Scenario: Lo que se ve es lo que se envía con deltas
- **WHEN** la persona escribe `/context` en una sesión con base y después hace una pregunta
- **THEN** el texto enviado es lo que mostró `/context` bajo la línea de modo, más una línea en blanco y la pregunta, con el marcador como única diferencia

#### Scenario: Sin contenido en la base de datos
- **WHEN** tras una pregunta con modo `delta` se busca el texto canario de una nota en todas las columnas de texto de SQLite
- **THEN** no aparece, y por cada nota solo constan su ruta, sus hashes, sus bytes, el recorte y `in_message`
