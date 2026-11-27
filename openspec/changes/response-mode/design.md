# Design

## Contexto

El proveedor de Copilot Web (`harness/providers/copilot_web.py`) solo usa controles medidos por la sonda (`ui.json` en `HARNESS_DATA_DIR/copilot/`): nada en el repositorio nombra un selector real. Cada pregunta abre su conversación, espera a que la página esté lista, comprueba con `guard` que está en la conversación de la sesión (SEC-02), escribe, llama a `on_sent` justo antes de la pulsación y espera la respuesta. Antes de `on_sent` todo fallo es `failed`/`timeout`; después, `uncertain` sin reenvío (SEC-07). Este change mete un paso nuevo entre «página lista» y «escribir», y otro, de solo lectura, tras la respuesta.

Premisas heredadas, medidas aquí el 2026-11-27 sobre `aa02081`:

- «El servicio llama a `provider.check` antes de registrar nada»: `harness/core/service.py`, `_ask_locked`, la llamada a `check(sent_text)` precede a `repo.insert_request`. Cierto.
- «Los parámetros opcionales del proveedor se detectan por firma»: `accepts_events` usa `inspect.signature`. Cierto; se reutiliza la técnica.
- «`Session(**dict(row))` lee todas las columnas de `sessions`»: `repositories.get_session` hace `SELECT *` y `Session` prohíbe campos extra. Una columna nueva exige el campo en el contrato (si no, toda lectura falla). Cierto: comprobado por los tests de migración de este change.
- «Una medida nueva del control no puede venir del repo»: `copilot-web-provider` D2 y la regla pública del proyecto. Se mantiene.

## Decisiones

### D1 · Interfaz mínima del proveedor

**Qué.** `LLMRequest.mode: ResponseMode = auto`. Dos piezas opcionales del proveedor, detectadas como `check` y `events`: `check_mode(mode)`, que no abre nada y lanza `ModeUnavailable` (un `InvalidInput`) con un mensaje propio si no sabe poner ese modo, y el argumento `on_mode(mode)` de `ask`, con el que informa del modo que confirmó (antes de enviar y, si cambió, tras la respuesta). Sin `check_mode`, el servicio solo acepta `auto`. El Mock tiene las dos: acepta los tres modos, informa del pedido antes de `on_sent` y, en `quick` y `deep`, añade el modo a su respuesta («… in mode deep.»), con lo que la misma pregunta en la misma sesión y el mismo modo sigue dando la misma respuesta.

**Por qué.** El `Protocol` `LLMProvider` no cambia: un proveedor sin modos (el `RecordingProvider` de los tests, un proveedor futuro) sigue funcionando y solo admite `auto`. El modo viaja en la solicitud, que ya es el contrato entre servicio y proveedor.

**Alternativas rechazadas.** (a) Un método `set_mode` del proveedor llamado por `/mode`: obligaría a abrir el navegador al cambiar de modo, que el dueño quiere sin efectos. (b) Añadir `mode_confirmed` a `ProviderEvents`: el Mock no acepta `events`, y hacer que lo acepte cambia avisos ligados a `events` (el de la conversación remota huérfana) en las pruebas del Mock. (c) Devolver el modo con la respuesta (`ask -> (texto, modo)`): rompe el `Protocol` y a todos los proveedores.

**Impacto.** Spec «Solo los modos que el proveedor sabe poner»; tareas 2.x y 3.x.

### D2 · `auto` nunca bloquea

**Qué.** `auto` es «que la página elija». Sin control medido, o si la medida no tiene opción automática, el harness no toca el selector y no registra modo confirmado (el historial no muestra modo; el panel y `/status` dicen `auto`). Si la medida tiene la opción automática, el harness la elige como en los otros modos, pero si no puede confirmarlo **no falla**: avisa y sigue con la página como esté, y registra lo que pudo leer (o nada). Revisado el 2026-11-27 (revisión independiente): dos excepciones, porque escribir sería inseguro y no por el modo. Si la lista de modos sigue abierta tras elegir, la pregunta termina en `failed` sin escribir, en cualquier modo, porque un prompt bajo un menú abierto puede activar una opción con Enter o dejar el clic de enviar sin efecto tras `on_sent`. Si la página cambió de conversación, también. Un selector medido cuyo botón u opción resulta ser otro control no se usa: en `auto` se avisa y la página queda como está.

**Por qué.** `auto` es el modo por defecto de toda sesión: si dependiera del control, un control roto o rediseñado bloquearía todas las preguntas, también las de quien nunca pidió un modo. Pero si `auto` nunca tocara el selector, tras `/mode deep` → `/mode auto` la página seguiría en `deep` (si la página recuerda la elección) y la persona no tendría forma de volver desde el harness. La mitad «mejor esfuerzo» resuelve las dos cosas.

**Alternativas rechazadas.** (a) `auto` = no tocar nunca: deja la página atascada en el último modo elegido. (b) `auto` estricto como `quick`/`deep`: un fallo del control bloquea la conducta por defecto.

**Impacto.** Escenario «Automático siempre funciona». Decisión abierta para el dueño (si prefiere (a)).

### D3 · Poner y confirmar el modo en Copilot, antes de escribir

**Qué.** Tras `open_conversation` (página lista, `guard` superado) y antes de contar turnos y escribir:

1. El control medido debe resolverse en **exactamente un** elemento visible (el botón que lo abre); si no, no se confirma.
2. Se lee el modo actual con la forma medida: `trigger_label` (la etiqueta del botón contiene exactamente una de las etiquetas medidas de las opciones; gana la más larga si una contiene a otra) o `checked_option` (con la lista abierta, la única opción con `aria-checked`, `aria-selected` o `aria-current` a `true`).
3. Si ya es el pedido, se cierra la lista (Escape) y listo. Si no, se abre, se hace clic en la opción medida (exactamente una visible) y se relee hasta `MODE_CONFIRM_S` (5 s): la página puede tardar en aplicarlo.
4. La lista se cierra siempre (`try/finally` en cada método que la abre, también si el clic o la búsqueda fallan) y se comprueba que está cerrada: si sigue abierta, `failed` sin escribir, en cualquier modo. Se comprueba, como en `guard`, que la página sigue en la misma conversación: la misma referencia en la URL y ningún turno de usuario **después** del último que había antes de elegir. Los turnos que aparecen encima (un historial que llega tarde a una lista virtualizada) no cuentan. Si cambió, `failed` («the page changed its conversation while the response mode was set»). Después, `guard`.
5. Si el modo leído no es el pedido: `ModeNotConfirmed` (un `ProviderError`) → `failed`, «nothing was sent», sin escribir nada en el editor.
6. El modo confirmado se guarda en el turno y se informa (`on_mode`) justo antes de `on_sent`. Cada intento de la pestaña retenida empieza sin modo confirmado: un intento que pierde su pestaña antes de escribir no deja su confirmación al siguiente.

La medida se valida al cargarla: el botón y las opciones no pueden ser el mismo localizador que el editor, el botón de enviar, el de parar o el de conversación nueva. Esa comparación es literal, y un localizador escrito de otra forma (`exact: false`, otro nombre) pasa. Por eso, en la página y antes de cualquier clic, ningún elemento visible del botón o de las opciones puede ser, contener o estar dentro de uno de esos controles. Si lo es, no se hace clic en nada: `failed` en `quick`/`deep`, y aviso sin tocar la página en `auto`.

**Por qué.** El dueño pide confirmar en la página antes de enviar. Antes de `on_sent` todo fallo es limpio: no hay `uncertain` posible ni reenvío que evitar. Las comprobaciones 1 y 4 acotan el daño de un localizador que empiece a apuntar a otro control (riesgo N2): con más de un elemento no se hace clic; un clic que cambia de conversación se detecta antes de escribir.

**Alternativas rechazadas.** (a) Poner el modo y no releerlo: no cumple «confirmar». (b) Poner el modo después de escribir el prompt: un clic con el prompt en el editor podría enviarlo (un menú que se cierra con Enter, un foco que vuelve al editor). (c) Reintentar el clic si no se confirma: un control que no responde no se arregla insistiendo, y cada clic es un efecto más en la página real.

**Impacto.** Escenarios «Modo puesto y confirmado», «El modo no se puede confirmar», «El control no está en la página», «Elegir el modo abre otra conversación».

### D4 · Relectura tras la respuesta

**Qué.** Cuando la respuesta está completa y la conversación comprobada (`still_this_conversation`), si se confirmó un modo, se relee con un plazo de 5 s (sin pasar del plazo de la solicitud). Si es otro, `on_mode(releído)` y un aviso: «the page switched the response mode to quick during the answer; the record says quick». Si no se puede leer, aviso y se conserva el confirmado. Ningún fallo de este paso cambia el estado de la solicitud. La lista que abre la relectura con `checked_option` se cierra también si la lectura falla; si sigue abierta, se avisa.

**Por qué.** El dueño pide que, si la página cambia de modo sola (por ejemplo, vuelve a otro), el registro diga el que quedó. Tras el envío, un fallo de una lectura accesoria no puede convertir una respuesta completa en `uncertain`.

**Alternativas rechazadas.** Leer el modo durante la respuesta, a intervalos: más clics en la página real (con `checked_option` leer es abrir la lista) mientras escribe, sin ganar nada para el registro.

**Límite escrito.** Si la página cambia de modo y vuelve antes de la relectura, el registro no lo ve. Con `checked_option`, releer abre y cierra la lista una vez tras la respuesta.

### D5 · Registro (migración 008) y lo que se muestra

**Qué.** `sessions.response_mode TEXT NOT NULL DEFAULT 'auto' CHECK (…)`, `requests.requested_mode` y `requests.confirmed_mode` (`CHECK … IN ('auto','quick','deep')`, nulos permitidos). El modo pedido se escribe con la solicitud; el confirmado, en su propia transacción en cuanto el proveedor lo informa (como `bound`): justo antes de enviar y, si cambia, tras la respuesta. Así una caída posterior no lo pierde, y una solicitud que no llegó a enviarse no guarda un modo confirmado. Cambiar de modo deja un evento de auditoría `session.mode` con el modo como resultado (sin contenido). Se muestra: en el panel lateral siempre (`Mode: deep`, y `deep (last: quick)` si la última solicitud confirmó otro); en `/status` siempre (línea `mode:`); en `/history` y `history`, solo si la solicitud no fue `auto` sin cambios (`[completed, mode quick (asked deep)] user: …`).

**Por qué.** Dos columnas separan lo pedido de lo que la página hizo (la vuelta de D4 se ve). Mostrar el modo solo cuando no es el defecto deja igual las salidas de siempre, que otros tests y scripts leen línea a línea.

**Alternativas rechazadas.** (a) Una columna con el modo «efectivo»: pierde qué se pidió. (b) Guardar el modo en `audit_events`: el historial tendría que juntar tablas y la auditoría no es el lugar del estado. (c) Mostrar el modo en todas las líneas del historial: cambia salidas estables sin informar de nada en el caso por defecto.

**Impacto.** Escenarios «Una base anterior abre sin cambios», «Historial con el modo confirmado», «Panel lateral». `tests/unit/test_storage.py` espera ahora las versiones 1–8.

### D6 · Plazo de `deep`

**Qué.** `HARNESS_DEEP_REQUEST_TIMEOUT_S`, por defecto `3 × HARNESS_REQUEST_TIMEOUT_S` (360 s con el valor por defecto); menor que el normal es un error de configuración. Se aplica a las preguntas en `deep` que no traen plazo propio (`ask`, `chat`). El plazo de toda la pregunta sigue siendo uno: `timeout` si vence antes de `on_sent`, `uncertain` después. El vigilante de la CLI usa el mayor de los dos plazos.

**Por qué.** Las respuestas `deep` tardan más (el modelo razona antes de escribir); con el plazo normal muchas acabarían en `uncertain`, que es el peor estado para la persona (no se sabe si llegó y no se reenvía). El triple es una cota: la sonda mide las respuestas normales (`recommended_timeout_s` = arranque + 2 × la más larga) pero no puede medir `deep` sin enviar. Hasta que se mida una respuesta `deep` real, el valor queda configurable y escrito como decisión, no como medida.

**Alternativas rechazadas.** (a) Mismo plazo para todos: convierte en `uncertain` lo que solo era lento. (b) Sin plazo en `deep`: una página colgada retendría la sesión y el navegador para siempre. (c) Multiplicador configurable: una variable de segundos se entiende y se compara con la otra sin cuentas.

**Límite escrito.** Un paso de Skill con `timeout_s` declarado lo conserva aunque la sesión esté en `deep`: el Skill fija su plazo y su tamaño; si se queda corto, su `timeout` se ve en `skill status`.

### D7 · Medida del control (`copilot_probe.py response-mode`)

**Qué.** Un paso de la sonda que no envía nada:

1. Abre la página configurada con el perfil dedicado y espera a que esté en el host de Copilot y sin indicios de sesión cerrada.
2. Pide a la persona que abra el selector de modo **sin elegir nada** y pulse Enter.
3. Busca, por estructura: el botón con `aria-expanded="true"` visible y la lista visible (`role=menu` o `listbox`) con sus opciones (`menuitemradio`, `menuitemcheckbox`, `menuitem`, `option`, `radio`). Guarda de cada opción su rol, su nombre accesible (cortado a 60 caracteres y limpiado) y si está marcada; del botón, su rol, su `data-testid` si lo tiene y su `aria-label`.
4. Enseña las opciones numeradas y pide a la persona qué número es `auto`, `quick` y `deep` (solo dígitos; vacío = no existe). Nunca se adivina el mapeo.
5. Si el modo en que estaba la página (la opción marcada) no es uno de los mapeados, se detiene sin elegir nada: no podría dejarla como estaba. Sin un `ui.json` previo tampoco sigue: sin los turnos medidos no puede comprobar que elegir no cambia la conversación.
6. Prueba localizadores del botón en este orden: `data-testid`, rol + `aria-label`, rol + nombre exacto. Para cada uno, recorre los modos elegidos, con el de partida al final: lee con las dos formas (`trigger_label`, `checked_option`), abre, elige la opción y relee. Una forma confirma un modo solo si lo lee después de elegirlo **y** leía otra cosa justo antes (revisión del 2026-11-27): una lectura que nunca cambia no distingue modos. Gana el primer localizador con el que todos los modos se confirman, y `trigger_label` si acierta (leer no abre nada), si no `checked_option`.
7. Deja la página en el modo en que la encontró, con el localizador ganador o, si ninguno se confirmó, con la opción marcada y cada localizador probado. Anota si elegir cambió la URL o los turnos.
8. Solo si todo se confirmó, la URL y los turnos no cambiaron y la página quedó como estaba, añade `response_mode` a `ui.json` (el anterior se guarda fechado, como `code-language`) y lo deja en `probe-response-mode-<fecha>.json` para que `measure` lo conserve al rehacer `ui.json`.

`candidates.json` puede traer `response_mode_trigger` (un localizador escrito a mano con codegen) si ninguno de los automáticos sirve.

**Por qué.** El rol y el nombre accesible son lo único que se puede leer sin texto de la página más allá del control; el mapeo a modos lo decide quien ve la página. Confirmar cada modo eligiéndolo es la única prueba de que el localizador y la lectura funcionan; elegir un modo no envía nada.

**Alternativas rechazadas.** (a) Encontrar el control sin persona (por nombres «Auto», «Quick»…): sería adivinar nombres que cambian. (b) Guardar el árbol de accesibilidad de la página: guarda texto de la página. (c) Medir sin elegir: no prueba que el clic y la lectura funcionen.

**Límite escrito.** Si el botón solo se distingue por su nombre y su nombre cambia con el modo (forma `trigger_label`), el localizador «rol + nombre exacto» falla al recorrer: el paso lo dice y pide `response_mode_trigger` en `candidates.json`.

### D8 · Página sintética configurable

**Qué.** `app.html` gana un selector opcional (`modes=menu` o `modes=listbox`) con etiquetas inventadas, y conductas: `mode_start`, `mode_stuck` (elegir no cambia nada), `mode_late_ms` (se aplica tarde), `mode_fallback` (vuelve a otro modo al terminar la respuesta), `mode_newchat` (elegir abre una conversación nueva), `mode_persist` (la elección sobrevive a recargar, como un ajuste del perfil). Desde la revisión del 2026-11-27, también: `mode_sticky` (la lista no se cierra), `mode_disabled` (una opción deshabilitada), `mode_twice` (cada opción dos veces), `mode_reread_fail` (tras la respuesta, el botón aparece dos veces), `mode_history` (al elegir llega un historial encima), `mode_append` (al elegir aparece un turno al final), `mode_navigate` (al elegir cambia la dirección) y `mode_label` (una etiqueta fija en el botón). El servidor recibe también si la lista estaba abierta al enviar. La página envía al servidor el modo en que estaba al recibir cada prompt: el servidor es el oráculo, independiente del código probado. Dos medidas sintéticas del control (`tests/fixtures/copilot_ui/response-mode-*.json`) describen las dos formas.

**Por qué.** Lo que no se puede abrir (Copilot real) se imita en dos formas distintas para que el código no dependa de una; las conductas de fallo son los controles negativos.

**Alternativas rechazadas.** Un selector siempre visible: cambia la página que usan las pruebas de descubrimiento y de estructura.

### D9 · Ficheros compartidos con otras ramas

**Qué.** Revisado el 2026-11-27, tras integrar `command-completion`:
- En `harness/shell/commands.py` (la tabla única de comandos), una entrada `mode` con 0 o 1 argumentos y un tipo de argumento `MODE` cuyos valores salen de `ResponseMode`. La línea de `/help` se escribe desde la tabla.
- En `harness/shell/completion.py`, la rama que ofrece esos valores tras `/mode ` y nada tras uno.
- En `harness/shell/conversation.py`, `_cmd_mode`, dos líneas de `/status`, el modo en `/history` y un campo en `_panel`.
- En `harness/shell/terminal.py`, un campo con valor por defecto en `PanelState`.
- En `harness/shell/tui.py`, una línea del panel. Por debajo de 100 columnas el panel se oculta y el modo se lee en `/status`.

`parser.py` no cambia: toma la tabla. Con `/mode`, `/m` deja de ser `/memory` y es un error que nombra los dos, por la regla «principio único o error».

**Por qué.** Otras ramas cambian el espaciado y la tabla de completado: cambios aditivos y localizados se fusionan sin conflicto o con uno trivial.

### D10 · `ask --mode` recuerda el modo

**Qué.** `ask --mode X` pone el modo de la sesión (como `/mode X`), con la sesión retenida, y pregunta. El modo queda para las siguientes. Se guarda (con su evento `session.mode`) solo cuando la pregunta supera las comprobaciones que la rechazan antes de registrarla: sesión cerrada, tamaño, configuración y modo que el proveedor no sabe poner (revisión del 2026-11-27).

**Por qué.** El modo es de la sesión (decisión del dueño); un modo «solo para esta pregunta» haría que el registro y el panel cuenten dos verdades distintas.

**Alternativas rechazadas.** `--mode` de un solo uso: posible más adelante como `--once`; queda como decisión abierta.

## Riesgos y límites

- Un localizador medido que empiece a apuntar a otro control → exactamente un elemento visible, el botón no puede ser un localizador de los controles de enviar/parar/nueva conversación/editor, y comprobación de conversación y turnos tras el clic, antes de escribir.
- La página real cambia de forma (rediseño) → `quick`/`deep` fallan antes de enviar con un mensaje que manda volver a medir; `auto` sigue funcionando (D2).
- El modo `deep` real tarda más que el triple del plazo normal → `uncertain` sin reenvío, como hoy; se sube `HARNESS_DEEP_REQUEST_TIMEOUT_S`. Sin medida real hasta la demo.
- Una medida nueva (`ui.json` con `response_mode`) leída por un harness anterior a este change → la rechaza por campo desconocido; se vuelve a medir con la versión antigua o se actualiza el harness.
- **No verificado en esta rama:** la forma real del control, sus nombres, si la página recuerda la elección entre recargas o conversaciones, si elegir un modo cambia de conversación y cuánto tarda una respuesta `deep`. Todo eso lo dice la medida y la demo con el dueño.
