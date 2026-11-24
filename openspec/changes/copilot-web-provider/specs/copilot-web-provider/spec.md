# Spec Delta

## Purpose

Permite preguntar a Microsoft Copilot Web desde una sesión local del harness, cada sesión en su propia conversación remota, sin enviar nunca dos veces la misma pregunta y sin guardar contenido real.

## ADDED Requirements

### Requirement: Proveedor de Copilot seleccionable
El sistema SHALL ofrecer el proveedor `copilot_web` por configuración. Una pregunta en una sesión de ese proveedor SHALL rechazarse, sin registrar ninguna solicitud ni abrir el navegador, cuando falten la URL de Copilot, el perfil dedicado o una medición completa de la sonda.

#### Scenario: Sesión creada con el proveedor de Copilot
- **WHEN** el proveedor configurado es `copilot_web` y el usuario ejecuta `session create "Integraciones"`
- **THEN** la sesión queda asociada al proveedor `copilot_web` sin abrir el navegador

#### Scenario: Falta la medición de la sonda
- **WHEN** no existe un fichero de medición completo y el usuario ejecuta `ask` en una sesión de `copilot_web`
- **THEN** el sistema indica qué falta, termina con código distinto de 0, no abre el navegador y no registra ninguna solicitud

### Requirement: Una conversación remota por sesión
Una pregunta en una sesión que aún no tiene referencia remota SHALL abrir una conversación remota nueva, y el sistema SHALL guardar su referencia en la sesión en cuanto la verifique. Las preguntas siguientes de esa sesión SHALL enviarse a esa misma conversación y nunca a la de otra sesión.

#### Scenario: Tres sesiones, tres conversaciones
- **WHEN** el usuario pregunta una vez en cada una de tres sesiones de `copilot_web`
- **THEN** cada sesión tiene una referencia remota distinta y cada conversación remota contiene solo la pregunta de su sesión

#### Scenario: Segunda pregunta en la misma conversación
- **WHEN** el usuario pregunta por segunda vez en una sesión que ya tiene referencia remota
- **THEN** la pregunta llega a la conversación de esa referencia y la referencia de la sesión no cambia

### Requirement: Recuperación de la conversación tras reiniciar
Tras cerrar y volver a abrir el navegador o el proceso, el sistema SHALL reabrir la conversación de la sesión a partir de su referencia y SHALL verificar que es la misma antes de enviar. Si la conversación no se encuentra, el sistema SHALL NOT enviar la pregunta, SHALL registrar la solicitud como `failed` y SHALL dejar la sesión en `closed`. Un fallo transitorio de carga SHALL terminar la solicitud en `timeout` o `failed`, sin envío, sin cerrar la sesión y sin cambiar su referencia.

#### Scenario: Conversación recuperada en un proceso nuevo
- **WHEN** el usuario pregunta en una sesión, termina el proceso y pregunta de nuevo en otro proceso
- **THEN** la segunda pregunta llega a la misma conversación remota que la primera

#### Scenario: Conversación remota desaparecida
- **WHEN** la conversación de la sesión ya no existe y el usuario ejecuta `ask` en esa sesión
- **THEN** la solicitud queda en `failed` sin que se envíe nada, la sesión queda en `closed` y el mensaje indica que hay que crear una sesión nueva

#### Scenario: Pregunta en una sesión cerrada
- **WHEN** el usuario ejecuta `ask` en una sesión en estado `closed`
- **THEN** el sistema lo rechaza con código distinto de 0 sin abrir el navegador ni registrar ninguna solicitud

#### Scenario: Página que no carga
- **WHEN** la página de la conversación no termina de cargar dentro del plazo de arranque
- **THEN** la solicitud queda en `timeout` sin envío y la sesión conserva su estado y su referencia

### Requirement: Respuesta completa detectada por señal observada
El sistema SHALL considerar terminada una respuesta solo cuando aparece una respuesta nueva posterior al envío y se cumple la señal de fin medida por la sonda, y SHALL devolver el texto de esa respuesta nueva, nunca el de una anterior.

#### Scenario: Respuesta que se escribe por partes
- **WHEN** la página escribe la respuesta en varios fragmentos y después cumple la señal de fin
- **THEN** el sistema devuelve la respuesta entera

#### Scenario: Una respuesta anterior no cuenta
- **WHEN** la conversación ya tiene respuestas anteriores y la nueva tarda en empezar
- **THEN** el sistema no devuelve el texto de ninguna respuesta anterior

### Requirement: Login vencido pide intervención humana
Cuando la página muestra que hace falta iniciar sesión, el sistema SHALL registrar la solicitud como `authentication_required` sin enviar nada, SHALL dejar la sesión en `authentication_required`, SHALL indicar el comando de login manual y SHALL NOT escribir ni pulsar nada en la página de login. La sesión SHALL volver a `active` con la siguiente pregunta completada.

#### Scenario: Sesión de Copilot caducada
- **WHEN** el usuario ejecuta `ask` y la página redirige a la página de login
- **THEN** la solicitud queda en `authentication_required`, la sesión queda en `authentication_required`, el mensaje nombra `copilot login` y el código es distinto de 0

#### Scenario: El harness no toca la página de login
- **WHEN** el sistema llega a una página de login sintética que registra cada pulsación y cada clic
- **THEN** la página registra cero pulsaciones y cero clics

#### Scenario: Vuelta a activa tras el login manual
- **WHEN** Wilson inicia sesión con `copilot login` y después pregunta en esa sesión
- **THEN** la pregunta se completa y la sesión vuelve a `active`

### Requirement: Plazo vencido tras el envío sin reenvío
Si el plazo vence o la respuesta no termina después de que el prompt haya salido, el sistema SHALL registrar `uncertain` y SHALL NOT volver a enviar el prompt, ni en esa ejecución ni en las siguientes. En la siguiente pregunta de esa sesión SHALL avisar si la conversación visible tiene más turnos de los que el harness completó.

#### Scenario: Respuesta que no termina
- **WHEN** la página recibe el prompt y nunca cumple la señal de fin antes del plazo
- **THEN** la solicitud queda en `uncertain` y la página ha recibido el prompt exactamente una vez

#### Scenario: Aviso de turno no registrado
- **WHEN** la sesión tiene una solicitud `uncertain` cuyo prompt sí llegó y el usuario hace una pregunta nueva
- **THEN** el sistema avisa por stderr de que la conversación tiene un turno más de los completados, envía solo la pregunta nueva y la solicitud anterior sigue en `uncertain`

### Requirement: Pérdida del navegador según el punto de fallo
Si el navegador se cierra o cae antes de que el prompt salga, la solicitud SHALL quedar en `failed`; si cae después, SHALL quedar en `uncertain`. En ambos casos el sistema SHALL NOT reenviar.

#### Scenario: Navegador cerrado antes del envío
- **WHEN** el navegador se cierra mientras la página de la conversación carga
- **THEN** la solicitud queda en `failed` y la página no ha recibido ningún prompt

#### Scenario: Navegador cerrado durante la respuesta
- **WHEN** el navegador se cierra después de que la página reciba el prompt
- **THEN** la solicitud queda en `uncertain` y la página ha recibido el prompt exactamente una vez

### Requirement: Sin contenido real guardado
El sistema SHALL NOT guardar el texto de prompts ni respuestas de una sesión de `copilot_web` en el almacenamiento, en la auditoría ni en ficheros de registro. `history` de esa sesión SHALL mostrar la referencia de la conversación remota y, por cada solicitud, su estado y fecha sin texto.

#### Scenario: Canario ausente del almacenamiento
- **WHEN** el usuario pregunta en una sesión de `copilot_web` con un texto canario y la página sintética responde con otro canario
- **THEN** ninguno de los dos canarios aparece en la base de datos ni en ningún fichero bajo el directorio de datos
- **AND** el sistema imprime la respuesta por stdout

#### Scenario: Historial sin texto
- **WHEN** el usuario ejecuta `history` de una sesión de `copilot_web` con dos preguntas completadas
- **THEN** la salida muestra la referencia remota y dos solicitudes `completed` sin texto de pregunta ni de respuesta

### Requirement: Límite de tamaño del prompt
El sistema SHALL rechazar, antes de registrar ninguna solicitud y sin abrir el navegador, un prompt cuya longitud supere el máximo configurado para Copilot.

#### Scenario: Prompt demasiado largo
- **WHEN** el usuario ejecuta `ask` con un prompt de un carácter más que el máximo configurado
- **THEN** el sistema informa del máximo, termina con código distinto de 0 y no registra ninguna solicitud

#### Scenario: Prompt en el límite
- **WHEN** el usuario ejecuta `ask` con un prompt exactamente del máximo configurado contra la página sintética
- **THEN** la página recibe el prompt completo, sin truncar
