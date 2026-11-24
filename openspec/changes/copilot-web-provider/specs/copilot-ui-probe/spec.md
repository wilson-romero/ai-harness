# Spec Delta

## Purpose

Mide en la interfaz real de Copilot Web, con contenido sintético y por mano de Wilson, todo lo que el proveedor necesita saber de esa interfaz, y deja la medición en local, fuera del repositorio público.

## ADDED Requirements

### Requirement: Solo prompts sintéticos fijos
La sonda SHALL enviar a Copilot únicamente los prompts sintéticos fijos que trae consigo y SHALL NOT aceptar un prompt libre por argumento, entorno ni entrada estándar.

#### Scenario: La sonda no acepta un prompt propio
- **WHEN** Wilson ejecuta la sonda pasando un texto propio como argumento
- **THEN** la sonda termina con código distinto de 0 sin abrir el navegador

#### Scenario: Prompts enviados en una ejecución contra páginas sintéticas
- **WHEN** la sonda se ejecuta contra las páginas sintéticas de prueba
- **THEN** cada prompt que reciben las páginas pertenece a la lista fija de la sonda

### Requirement: La medición vive fuera del repositorio
La sonda SHALL escribir su resultado dentro del directorio de datos configurado y SHALL negarse a escribirlo en una ruta que Git pueda versionar, es decir, dentro de un árbol de trabajo de Git y no ignorada por él.

#### Scenario: Resultado en el directorio de datos
- **WHEN** la sonda termina una medición con el directorio de datos por defecto, ignorado por Git
- **THEN** existe un fichero de medición nuevo bajo el directorio de datos y `git status --porcelain` del repositorio no muestra ningún fichero nuevo

#### Scenario: Directorio de datos versionable
- **WHEN** el directorio de datos configurado está dentro de un árbol de trabajo de Git y no está ignorado
- **THEN** la sonda termina con código distinto de 0 antes de abrir el navegador y no escribe nada

### Requirement: La medición no contiene datos de la empresa ni del contenido
El fichero de medición SHALL contener solo localizadores de controles, la forma de la referencia de conversación con el identificador sustituido por un marcador, nombres de host de redirección de login, recuentos, tiempos, booleanos y la versión de navegador y plataforma. SHALL NOT contener la URL completa configurada, identificadores de conversación reales, nombres de cuenta ni de tenant, texto de respuestas, títulos de conversaciones, capturas, trazas, HAR ni estado de almacenamiento.

#### Scenario: Canarios ausentes de la medición
- **WHEN** la sonda mide páginas sintéticas cuya URL, nombre de cuenta, títulos de conversación y respuestas contienen cadenas canario
- **THEN** ninguna cadena canario aparece en el fichero de medición

#### Scenario: Sin artefactos binarios
- **WHEN** la sonda termina
- **THEN** no ha creado ninguna captura, traza, vídeo, HAR ni fichero de estado de almacenamiento

### Requirement: Candidatos de fin de respuesta comparados con una verdad conocida
La sonda SHALL registrar, para cada envío, el instante en que se cumple cada señal candidata de fin de respuesta y el instante en que la respuesta contiene su marcador final esperado y deja de cambiar, y SHALL marcar como válida solo una señal que no se haya cumplido antes de ese instante en ningún envío y se haya cumplido en todos.

#### Scenario: Señal prematura descartada
- **WHEN** una página sintética hace aparecer una señal candidata antes de terminar de escribir la respuesta
- **THEN** la medición marca esa señal como no válida y anota cuántas veces se adelantó

#### Scenario: Señal fiable elegida
- **WHEN** una señal candidata se cumple después del final en todos los envíos medidos
- **THEN** la medición la marca como válida

### Requirement: Identidad de conversación medida tras reiniciar el navegador
La sonda SHALL medir si una conversación creada en una ejecución del navegador se vuelve a abrir, con sus turnos visibles, en una ejecución posterior a partir de su referencia, y SHALL registrar el resultado como sí o no.

#### Scenario: Conversación reabierta
- **WHEN** las páginas sintéticas conservan la conversación tras cerrar y reabrir el navegador
- **THEN** la medición registra que la identidad es recuperable y cuántos turnos se veían

#### Scenario: Conversación no recuperable
- **WHEN** las páginas sintéticas no conservan la referencia de la conversación
- **THEN** la medición registra que la identidad no es recuperable

### Requirement: Medición incompleta declarada como tal
La sonda SHALL marcar la medición como incompleta cuando falte cualquiera de sus partes obligatorias, y el proveedor SHALL negarse a usar una medición incompleta.

#### Scenario: Wilson interrumpe la sonda a mitad
- **WHEN** la sonda se interrumpe antes de medir la señal de fin de respuesta
- **THEN** el fichero de medición queda marcado como incompleto y `ask` con el proveedor de Copilot lo rechaza nombrando la parte que falta
