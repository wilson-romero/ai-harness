## ADDED Requirements

### Requirement: Tiempos por fases sin texto
Cada pregunta a Copilot Web SHALL registrar la duración de cada fase, el camino, cómo terminó la respuesta y el resultado, solo con números y palabras de listas cerradas: nunca el prompt, la respuesta, la URL ni nombres. La persona SHALL verlo con `history SESSION_ID --timings` y, con `HARNESS_COPILOT_TIMINGS=on`, como un aviso de cada pregunta. Un registro que no se puede escribir no SHALL cambiar la pregunta.

#### Scenario: Cada pregunta deja sus fases
- **WHEN** el usuario hace dos preguntas a Copilot Web en una sesión
- **THEN** hay dos registros, cada uno con las fases de navegar, chat listo, asentarse, guarda, escribir, enviar, inicio y fin de la respuesta, lectura y comprobaciones finales, y ninguno contiene el texto del prompt ni de la respuesta

#### Scenario: La persona ve los tiempos de una sesión
- **WHEN** el usuario ejecuta `history SESSION_ID --timings`
- **THEN** cada solicitud muestra una línea con resultado, camino, fin, total y la duración de cada fase, y sin `--timings` esas líneas no aparecen

#### Scenario: Un registro manipulado no llega a la terminal
- **WHEN** el fichero de tiempos contiene una línea con caracteres de control, una fase desconocida o un motivo que no es de la lista
- **THEN** esa línea no se muestra

### Requirement: Pestaña de confianza
Con la reutilización medida y encendida, una pregunta SHALL hacerse sin recargar solo si la pestaña es de confianza: la que respondió la pregunta anterior de esta sesión en esta conversación hace menos de 120 s, con su dirección en el host configurado, el chat listo, los mismos turnos que mostraba, sin respuesta en curso y con el editor vacío. Ante cualquier duda SHALL recargar. Toda guarda del camino de siempre SHALL valer también en la pestaña reutilizada.

#### Scenario: Las guardas siguen en la pestaña reutilizada
- **WHEN** el usuario pide un modo de respuesta en una pregunta hecha en la pestaña reutilizada
- **THEN** el modo se pone y se confirma antes de escribir, se envía una sola vez y la respuesta es la del prompt nuevo

#### Scenario: Una conversación sin cambios no recarga
- **WHEN** el usuario hace tres preguntas seguidas en una sesión y nadie toca la pestaña
- **THEN** la página se carga una sola vez, la segunda y la tercera pregunta no navegan ni esperan a que la página se asiente, y cada una recibe su respuesta completa

#### Scenario: La pestaña se llevó a otra dirección
- **WHEN** la persona abre un chat nuevo en la pestaña entre dos preguntas
- **THEN** la pregunta siguiente recarga la conversación de la sesión y no escribe en el chat nuevo

#### Scenario: La pestaña la usó otra sesión
- **WHEN** entre dos preguntas de la sesión A se hace una pregunta de la sesión B
- **THEN** la pregunta siguiente de A recarga su propia conversación

#### Scenario: La página cerró la sesión
- **WHEN** entre dos preguntas la pestaña pasa a pedir inicio de sesión
- **THEN** la pregunta termina en `authentication_required` sin escribir nada

#### Scenario: La conversación se borró en otro sitio
- **WHEN** entre dos preguntas la conversación se borra y la pestaña sale de ella
- **THEN** la pregunta no escribe nada y la sesión se da por perdida, como al recargar

#### Scenario: Otro dispositivo añadió un turno
- **WHEN** entre dos preguntas aparece en la pestaña un turno que el harness no envió
- **THEN** la pregunta recarga, avisa del turno de más y devuelve la respuesta a su propio prompt

#### Scenario: Demasiado tiempo sin usar
- **WHEN** la pestaña lleva más tiempo sin responder que el límite de inactividad
- **THEN** la pregunta recarga

### Requirement: Fin por señal positiva
Con una regla de fin rápido medida en `ui.json` y encendida, una respuesta SHALL darse por terminada antes de la ventana de estabilidad solo si la señal medida se vio ocupada después de enviar, luego libre sin interrupción, y el texto no cambió durante la ventana corta de confirmación. En cualquier otro caso SHALL decidir la ventana de estabilidad de siempre. Una respuesta que aún crece no SHALL devolverse como `completed`.

#### Scenario: La señal termina antes que la ventana
- **WHEN** una respuesta termina y su señal medida queda libre
- **THEN** la respuesta completa se devuelve tras la ventana corta, al menos 2,5 s antes que sin la regla

#### Scenario: Una pausa con la respuesta aún ocupada
- **WHEN** la página deja de escribir 1,5 s a mitad de la respuesta con la señal todavía ocupada
- **THEN** la respuesta se devuelve entera

#### Scenario: Una señal que parpadea
- **WHEN** durante una pausa la señal pasa a libre y vuelve a ocupada
- **THEN** la respuesta se devuelve entera

#### Scenario: Una señal que nunca aparece
- **WHEN** la página no muestra nunca la señal ocupada
- **THEN** decide la ventana de estabilidad y la respuesta se devuelve entera

#### Scenario: Una respuesta muy lenta
- **WHEN** la respuesta llega en trozos separados por 0,8 s
- **THEN** la respuesta se devuelve entera

#### Scenario: Un bloque añadido tras la señal
- **WHEN** la página añade un bloque en varios trozos después de que la señal quede libre
- **THEN** la respuesta devuelta incluye el bloque entero

### Requirement: Interruptores
Cada optimización SHALL actuar solo si la sonda la midió y su interruptor (`HARNESS_COPILOT_REUSE_TAB`, `HARNESS_COPILOT_FAST_END`, `on` u `off`, `on` si está vacío) está encendido. Sin la medida, el camino y las esperas SHALL ser los de antes de este cambio. Un valor que no sea `on` ni `off` SHALL rechazarse como error de configuración.

#### Scenario: Sin medida, como antes
- **WHEN** `ui.json` no tiene regla de fin rápido ni reutilización y los interruptores están encendidos
- **THEN** cada pregunta recarga, espera a que la página se asiente y termina por la ventana de estabilidad

#### Scenario: Cada interruptor apaga solo lo suyo
- **WHEN** las dos optimizaciones están medidas y una de las dos se apaga
- **THEN** esa vuelve a la conducta de antes y la otra sigue actuando

### Requirement: Sin ventana solo si se pide
Las preguntas SHALL hacerse con la ventana de Edge visible salvo que la persona pida lo contrario con `HARNESS_COPILOT_HEADLESS=on`. El inicio de sesión SHALL usar siempre una ventana. Sin ventana, el sandbox de Edge SHALL seguir activado. Si sin ventana la página pide iniciar sesión o no llega a ser el chat medido, la pregunta SHALL fallar con `authentication_required` o como página no lista, sin escribir nada.

#### Scenario: Por defecto, con ventana
- **WHEN** el usuario hace una pregunta sin `HARNESS_COPILOT_HEADLESS`
- **THEN** la página se carga en un Edge con ventana

#### Scenario: Sin ventana cuando se pide
- **WHEN** el usuario hace una pregunta con `HARNESS_COPILOT_HEADLESS=on`
- **THEN** la página se carga en un Edge sin ventana y la respuesta llega completa

#### Scenario: Sin ventana la página pide iniciar sesión
- **WHEN** sin ventana la página muestra una página de inicio de sesión
- **THEN** la pregunta termina en `authentication_required` y no se escribe nada

#### Scenario: Sin ventana la página es otra
- **WHEN** sin ventana la página no tiene la estructura medida
- **THEN** la pregunta falla como página no lista y no se escribe nada

#### Scenario: Iniciar sesión siempre con ventana
- **WHEN** el usuario ejecuta el inicio de sesión con `HARNESS_COPILOT_HEADLESS=on`
- **THEN** Edge se abre con ventana

### Requirement: Medida en un solo comando
El paso `speed` de la sonda SHALL medir en un solo comando las reglas de fin rápido y las preguntas con las optimizaciones apagadas, encendidas y encendidas sin ventana, con prompts de la lista fija y como mucho los envíos que anuncia (8 más 3 por pregunta). SHALL imprimir la tabla por fases y guardar solo duraciones, caminos, recuentos y hashes. En `ui.json` SHALL escribir solo lo confirmado. Sin ventana, una pregunta que no llega entera SHALL dar «not usable», no un tiempo.

#### Scenario: Una medida completa
- **WHEN** el coordinador ejecuta `speed --questions 2` sobre una página que se comporta bien
- **THEN** la página recibe exactamente 14 prompts, todos de la lista fija, `ui.json` gana la regla de fin rápido y la reutilización, y ni el resumen ni el resultado contienen texto de las respuestas

#### Scenario: Una regla que cortaría un bloque tardío
- **WHEN** la página añade un bloque 1,5 s después del fin de cada respuesta
- **THEN** ninguna regla de fin rápido es válida, `ui.json` no la gana y las respuestas de las variantes llegan enteras

#### Scenario: Sin ventana la página es distinta
- **WHEN** sin ventana la página pide iniciar sesión o tiene otra estructura
- **THEN** la variante sin ventana no escribe nada en la página y el resumen dice «not usable» en lugar de un tiempo

#### Scenario: Sin medida previa no envía
- **WHEN** no hay `ui.json`
- **THEN** el paso termina con error sin enviar nada
