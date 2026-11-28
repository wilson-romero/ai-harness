# Design

## Contexto

El proveedor de Copilot Web (`harness/providers/copilot_web.py`) retiene el navegador mientras dura una conversación (`open_resources`/`close_resources`, `copilot-web-provider` D3 revisada) y, por cada pregunta, `_Turn.run` abre la conversación de la sesión (`open_conversation`: navegar, esperar el chat listo, esperar `SETTLE_S` = 2 s sin cambios, esperar el historial, `guard`), pone el modo (`response-mode`), escribe, llama a `on_sent` justo antes de la pulsación, espera la respuesta (`await_reply`: señal medida **y** texto sin cambios durante la ventana de estabilidad) y comprueba el identificador. Este change no cambia ese orden ni lo que resulta de cada fallo: añade un camino que se salta navegar y asentarse cuando es seguro, y una salida antes de la ventana cuando una regla medida lo permite.

Premisas heredadas, comprobadas aquí el 2026-11-27 sobre `a9c51fe`:

- «Una pregunta sigue tardando unos 11 s en una conversación abierta»: `copilot-web-provider` design D3, «Coste medido por pregunta» (2026-11-26, página real). Es la única medida real disponible; esta rama no puede repetirla (no abre la página real). El paso `speed` la repite.
- «`stop_hidden` nunca se adelantó, las ventanas cortas solas sí»: P4 (2026-11-24, macOS arm64): `stop_hidden` 12/12 válida, retraso medio 1217 ms; `text_stable_1000`, 7 adelantos. Cierto en lo medido; no dice nada de «señal + ventana corta», que es otra regla: por eso se mide (D6) y no se supone.
- «La pestaña retenida es la misma entre preguntas»: `_Held.page_for_question` devuelve la misma `Page` mientras no se cierre. Cierto; la memoria de la pestaña se borra cuando la página cambia (D2).
- «`guard` comprueba host, estado e identificador»: `_Turn.guard`, cierto. En el camino rápido se sigue llamando.
- «Playwright con `channel="msedge"` admite `headless` en `launch_persistent_context`»: comprobado en el código instalado (`playwright/driver/package/lib/coreBundle.js`, `Chromium._innerDefaultArgs` y `getExecutableName`): con canal, el ejecutable es el Edge instalado (no el `chromium-headless-shell` de Playwright) y `headless: true` añade `--headless`, `--hide-scrollbars`, `--mute-audio` y `--blink-settings=primaryHoverType=2,availableHoverTypes=2,primaryPointerType=4,availablePointerTypes=4`; el sandbox depende solo de `chromiumSandbox`. Medido con un perfil desechable (2026-11-27, Edge 158): sin ventana el `User-Agent` dice `HeadlessChrome/158…`, con ventana `Chrome/158…`.

## Decisiones

### D1 · Tiempos por fases, solo duraciones

**Qué.** `harness/providers/copilot_timings.py` define `TurnTimings`: `request_id`, `session_id`, `path` (`reload` | `reuse`), `declined` (por qué no se reutilizó la pestaña, una palabra de una lista cerrada), `end` (`window` | `signal` | `none`), `attempts`, `outcome` (`answered` | `uncertain` | `cancelled` | `failed`), `phases_ms` (fase → milisegundos, de una lista cerrada: `reuse_check`, `navigate`, `ready`, `settle`, `history`, `guard`, `mode`, `type`, `send`, `reply_start`, `reply_end`, `read`, `identifier`, `post`, `recheck`), `total_ms` y `early_endings` (D7). El proveedor llena uno por pregunta, lo deja en `last_timings` y lo añade como una línea JSON a `HARNESS_DATA_DIR/copilot/timings.jsonl` (recortado a 1000 líneas al pasar de 512 KB). `history SESSION_ID --timings` muestra, bajo cada solicitud, `timings (s): answered, path reuse, end signal, total 2.3; reuse check 0.04, guard 0.02, …`. Con `HARNESS_COPILOT_TIMINGS=on` la misma línea sale como aviso de la pregunta.

**Por qué.** Sin desglose no se sabe qué ganó cada optimización ni dónde se va el tiempo en la página real. Un fichero aparte evita una migración (otras ramas tienen la 010 y la 011) y nunca contiene texto: solo números y palabras de listas cerradas. `read_for` vuelve a validar cada línea (tipos, fases y palabras conocidas), así que un fichero manipulado no mete texto en la terminal. Escribirlo nunca hace fallar una pregunta.

**Alternativas rechazadas.** (a) Columnas en `requests` (migración 012): toca `harness/storage/` y `service.py`, que otra rama cambia, por un dato de diagnóstico. (b) Solo un aviso por pregunta: se pierde al cerrar la terminal y no se puede comparar. (c) Guardar los tiempos en el log general: mezcla diagnóstico con eventos y no se puede leer por solicitud.

**Impacto.** Requisito «Tiempos por fases sin texto»; tareas 1.x. La barra de progreso y el bucle del agente (ya en `develop`) leen `provider.last_timings`, un atributo **público y estable**: su nombre y su tipo no cambian, vale `None` antes de la primera pregunta y se fija antes de que `ask` devuelva o falle, sea cual sea el resultado (sin tocar `harness/shell/` aquí). Los campos solo se añaden, nunca se quitan ni cambian de tipo.

### D2 · Preguntar en la pestaña de confianza sin recargar

**Qué.** Tras responder, si `tab_reuse` está medido y su interruptor encendido, el proveedor recuerda la pestaña (`_TabMemory`): la `Page`, la sesión, la conversación remota, el número de turnos de usuario y de asistente, el elemento del último turno de usuario y el de la respuesta, y la hora. En la pregunta siguiente, solo en el **primer intento** y solo con el navegador retenido, la pestaña es **de confianza** si se cumple todo, en este orden y sin tocar la página:

1. es la misma `Page` que respondió (si no: `new tab`) y la sesión ya tiene conversación remota (`no conversation`);
2. la memoria es de esta sesión y de esta conversación (`other session`);
3. respondió hace menos de `REUSE_MAX_IDLE_S` = 120 s (`idle`);
4. la dirección lleva el identificador de esa conversación y el host configurado (`address`);
5. `classify` dice chat listo (`page state`: una página de inicio de sesión, de invitado o desconocida);
6. los turnos son exactamente los recordados: el mismo número de cada tipo y el mismo último turno de usuario y la misma respuesta, conectados y en ese orden (`turns`);
7. no hay respuesta en curso (el botón de parar no está visible) y el editor está vacío (`busy`);
8. ninguna lectura falló (`error`; una pestaña cerrada sigue siendo el error de siempre).

Si algo falla, la palabra queda en `declined` y la pregunta sigue por el camino de siempre (recargar). Si todo se cumple, se salta navegar, chat listo, asentarse e historial; **`guard` se llama igual**, y después todo es como siempre: el modo se pone y se confirma antes de escribir, la respuesta se busca por posición después del turno de usuario **nuevo**, el identificador de la dirección se comprueba tras enviar, `on_sent` se llama en el mismo instante y nunca se reenvía. Cualquier respuesta que no sea `answered` borra la memoria.

**Por qué.** Recargar y asentarse cuesta 4–5 s por pregunta (Contexto). La pestaña que acaba de responder ya está donde la recarga la dejaría; lo que hay que demostrar es que nadie la ha movido ni cambiado, y cada punto de la lista lo comprueba un estado visible de la página. Las guardas de la recarga siguen en el camino rápido porque son las que protegen SEC-02, no la recarga en sí.

**Alternativas rechazadas.** (a) Confiar en la pestaña sin comprobar los turnos: un turno añadido desde otro dispositivo, que la página pinta, quedaría sin aviso (con la recarga, el aviso de turnos de más sí sale). (b) Comprobar solo la URL: una persona que borró y escribió en esa conversación no cambia la URL. (c) Sin límite de inactividad: cuanto más tiempo pasa, más probable es un cambio que la pestaña no muestra (límite de abajo). (d) Reutilizar también en el segundo intento: el segundo intento existe precisamente porque la pestaña falló.

**Impacto.** Requisito «Pestaña de confianza» y sus escenarios; tareas 2.x.

**Límite (no se arregla aquí; por eso D8 la deja apagada por defecto).** Un cambio hecho en otro dispositivo que la pestaña abierta **no pinta** (borrar la conversación, añadir un turno) no se ve sin recargar. Si la página real no actualiza la pestaña, el harness escribirá en una conversación que ya no existe (sin la página de «no encontrada» que da `closed`) o sin el aviso de turnos de más; y un aviso de sesión caducada que tape el chat sin el indicador medido deja la pregunta en `uncertain` en lugar de `authentication_required`. Lo acotan los 120 s, la comprobación del identificador tras enviar (otra conversación da `uncertain` sin mostrar respuesta, como hoy) y el interruptor, apagado por defecto. La página sintética con `live=1` imita la conducta que sí actualiza (sale de la conversación borrada, pinta el turno nuevo, muestra la sesión cerrada) y las pruebas comprueban que entonces se rechaza.

### D3 · Fin de la respuesta por una señal positiva medida

**Qué.** `ui.json` acepta `fast_end: {signal, confirm_ms, sends, modes, measured_at}`, con `signal` entre las estructurales (`stop_hidden`, `send_ready`, `done_control`, `aria_busy`; el control que vigila tiene que estar medido) y `confirm_ms` entre 300 y 2000. En `await_reply`, cada vuelta lee primero la señal y luego el texto (como la sonda). La respuesta termina por señal si:

1. la señal se vio **ocupada** después de enviar **y con la respuesta ya en la página** (un botón de parar que nunca aparece, o uno que ya estaba visible antes de que existiera la respuesta, no vale; D7);
2. después está **libre sin interrupción** desde `done_since` (un parpadeo a ocupada lo reinicia);
3. el texto, leído como lo devuelve el proveedor, no ha cambiado desde `since`, y han pasado `confirm_ms` desde el más tardío de `done_since` y `since`.

La condición de siempre (señal medida **y** ventana de estabilidad) se comprueba antes en la misma vuelta y sigue valiendo: si la regla rápida no se cumple nunca, decide la ventana larga. La regla solo actúa en los modos de `modes`, y tras un fin por señal se vuelve a comprobar (D7).

**Ventana corta: 500 ms (o 1000 ms si la sonda lo decide).** La sonda prueba 500 y 1000 ms por cada señal aplicable. 500 ms son cinco lecturas de 100 ms; la regla rápida añade dos condiciones que la ventana sola no tenía (la señal se vio ocupada y sigue libre), y la medida decide: una regla solo vale si en todos los envíos se cumplió y nunca fue temprana (D7). Por debajo de 300 ms el esquema la rechaza (tres lecturas); por encima de 2000 ms no compensa frente a la ventana larga.

**Por qué.** Esperar 4 s después de que el texto deja de cambiar es caro (Contexto). La ventana corta sola se adelantó en la página real; una señal estructural sola no puede ver un bloque añadido después del fin. Juntas, con la verdad de la sonda (texto completo que ya no cambia, incluido lo que llegue después del marcador), se mide si se adelantan.

**Alternativas rechazadas.** (a) Solo la señal: no ve un bloque que se añade tras el fin. (b) Solo una ventana corta: P4 la midió adelantándose 7 de 12 veces. (c) Elegir la ventana a mano sin medir: es la estimación que la regla del proyecto prohíbe. (d) Terminar en la primera lectura con señal libre: un parpadeo cortaría la respuesta.

**Impacto.** Requisito «Fin por señal positiva»; tareas 3.x.

**Límite.** Un bloque que la página real añade **más tarde** que la ventana corta tras el fin cortaría la respuesta. La sonda lo ve (lo cuenta como adelanto, porque su verdad incluye todo lo que llega mientras mide) y entonces no escribe `fast_end`; la prueba `test_speed_refuses_a_fast_end_that_would_cut_a_late_block` lo comprueba con un bloque a 1,5 s. Un bloque que llegue después de lo que la sonda espera (4 s sin cambios) no lo ve nadie, tampoco la ventana de hoy.

### D4 · Interruptores y sin medida, como hoy

**Qué.** `HARNESS_COPILOT_REUSE_TAB` y `HARNESS_COPILOT_FAST_END` aceptan `on`/`off` (vacío: `off` para la pestaña, D8, y `on` para el fin rápido; otro valor: error de configuración). Cada optimización actúa solo si su entrada está en `ui.json` **y** su interruptor está encendido (`speed_for`). Sin `tab_reuse` ni `fast_end` en `ui.json`, el camino y las esperas son los de hoy: así se ve en los tiempos (`path reload`, `end window`, `settle` ≥ 2 s).

**Por qué.** El fin rápido, encendido por defecto porque una medida lo respalda y su comprobación posterior nunca devuelve un texto más corto (D7); sin medida no hay nada que encender. La pestaña, apagada por defecto por lo que no ve (D8). El interruptor deja apagarlo sin tocar `ui.json` si en la página real algo no cuadra.

**Alternativas rechazadas.** (a) El fin rápido apagado por defecto: obligaría a configurarlo tras medirlo, y medir ya es la decisión. (b) Un solo interruptor: si una de las dos falla en la página real, se perdería también la otra.

**Impacto.** Requisito «Interruptores»; tareas 4.x.

### D5 · Sin ventana solo si se pide

**Qué.** `HARNESS_COPILOT_HEADLESS=on` (apagado por defecto) lanza Edge sin ventana para las preguntas: `EdgeLauncher.from_settings(settings, window=False)` usa `headless = browser_headless or copilot_headless`. El inicio de sesión (`harness/browser/login.py`) y los pasos de la sonda que miden la página (`Probe.launcher`) piden `window=True` y siempre tienen ventana. Las banderas que cambian sin ventana son solo las que Playwright añade al pedir `headless` (Contexto): `--headless`, `--hide-scrollbars`, `--mute-audio` y `--blink-settings=…`. El sandbox (`chromium_sandbox=True`) y las opciones por defecto que se quitan (`DROPPED_DEFAULT_ARGS`) no cambian.

Si sin ventana la página se comporta distinto, nada nuevo decide: las guardas de siempre lo ven. Una página de inicio de sesión o verificación da `authentication_required`; una que nunca llega a ser el chat medido (otra estructura) da «not ready in time» (`timeout` antes de enviar). En los dos casos no se escribe nada.

**Por qué.** Sin ventana puede ser más rápido o no, y la página puede tratarlo distinto (el `User-Agent` lo delata, y `--blink-settings` cambia el tipo de puntero). Hace falta la cifra, no una suposición: por eso es una variante más de `speed` y no un cambio del valor por defecto.

**Alternativas rechazadas.** (a) Sin ventana por defecto: el dueño no vería la página, y una verificación que pide interacción quedaría sin resolver. (b) Un `User-Agent` falso: sería ocultar la automatización a la página, y añade una bandera. (c) Iniciar sesión sin ventana: imposible con MFA manual.

**Impacto.** Requisito «Sin ventana solo si se pide»; tareas 5.x.

### D6 · Un solo comando de medida: `speed`

**Qué.** `uv run python scripts/copilot_probe.py speed [--questions N] [--rounds 1|2] [--skip-headless]` (N de 2 a 5, por defecto 5; 2 rondas). Antes de enviar nada dice el número de envíos previsto y espera a que la persona pulse Enter (D7). Necesita un `ui.json` completo (lo deja `measure`). Hace, en este orden:

1. **Reglas de fin rápido**: R conversaciones nuevas × los 6 prompts fijos de `SPEED_PROMPTS` (los 4 de `measure`, uno largo por fases y uno con búsqueda y citas) = **6R envíos**, más **2 en `deep`** si el selector de modo está medido (D7), muestreados cada 100 ms como en `measure` y leyendo también el texto como lo lee el proveedor. Por cada señal aplicable y ventana (500, 1000 ms) calcula cuándo dispararía la regla del proveedor (`fast_fire`, la misma lógica que D3) y si fue antes de la verdad (el marcador está y el texto ya no cambia hasta el final del muestreo). Válida = cumplida en todos los envíos y ninguno temprano (D7); se elige la de menor retraso medio.
2. **Variantes**, cada una en una conversación nueva, con el proveedor de verdad y los prompts fijos `PROMPTS[i % 4]`: optimizaciones **apagadas** con ventana (N envíos), **encendidas** con ventana (N) y **encendidas sin ventana** (N; se omite con `--skip-headless`). Cada respuesta se comprueba en memoria (marcador presente, no cortada) y se descarta. Una variante se para en la primera pregunta que no llega entera; si una variante falla, no se ejecuta la siguiente.

Total: **6R + 3N** envíos (27 por defecto, 29 con `deep` medido; el mínimo que aún escribe las reglas, `--rounds 1 --questions 2 --skip-headless`, son 10, o 12 con `deep`); el resumen dice los usados y los previstos. Escribe `probe-speed-<fecha>.json` (solo duraciones, caminos, palabras fijas, recuentos y hashes; nunca texto, URL ni nombres) e imprime la tabla por fases (mediana de las preguntas 2..N) de las tres variantes. En `ui.json` escribe `fast_end` solo si una regla fue válida, las variantes con ventana llegaron enteras y el proveedor no contó ningún fin temprano en ellas, y `tab_reuse` solo si todas las preguntas 2..N de la variante encendida reutilizaron la pestaña y llegaron enteras; lo que no se confirma se **quita**. La variante sin ventana nunca escribe nada: si no llegó entera, el resumen dice `headless: not usable (<error>)` y la tabla `n/a` en lugar de un tiempo.

**Por qué.** Un solo comando que el coordinador ejecuta con el dueño, con un número de envíos conocido antes de empezar, todos de la lista fija. Medir con el proveedor de verdad (no con una imitación) hace que la cifra sea la del código que se usará.

**Alternativas rechazadas.** (a) Medir las variantes con el muestreador de la sonda: mediría otra cosa que el proveedor. (b) Elegir la regla con las variantes: con 5 preguntas no hay muestra suficiente para afirmar 0 adelantos; los 12 envíos muestreados lo miden con la verdad. (c) Más envíos: cada uno es una pregunta real en la cuenta del dueño.

**Impacto.** Requisito «Medida en un solo comando»; tareas 6.x; runbook.

### D7 · Un fin rápido nunca devuelve un texto más corto (revisión independiente, 2026-11-28)

**Qué.** La revisión independiente midió que con `pause_ms=2000&flicker_ms=800` (el botón de parar se oculta 800 ms entre dos fases) la pregunta terminaba `completed` con 65 de 122 caracteres. Cuatro cambios:

1. **Modos.** `fast_end.modes` dice en qué modos se midió (`auto` cubre la pregunta sin modo). Una pregunta en otro modo termina por la regla de siempre.
2. **Comprobación posterior.** Tras un fin por señal, y tras la espera del identificador y las comprobaciones de después (`identifier`, `post`), `early_end` vuelve a leer la señal y el resumen del texto hasta que pasa `confirm_ms` desde que la regla se cumplió (fase `recheck`). Si el texto cambió o la señal volvió a «ocupado», el fin fue **temprano**: no devuelve el texto, suma `early_endings` en los tiempos, vuelve a esperar con la regla antigua (la ventana de estabilidad) y la regla rápida no vuelve a actuar en esa pregunta.
3. **«Ocupado» solo con la respuesta en la página.** Un botón de parar ya visible antes de que exista la respuesta no cuenta como la respuesta ocupada (lo mismo en el proveedor y en `fast_fire`).
4. **La sonda.** Una regla es temprana si se dispara antes de la verdad, si su señal vuelve a «ocupado» **en cualquier momento** después de dispararse, o si el texto que habría devuelto no coincide con una segunda lectura 5 s después de asentarse. Dos prompts fijos nuevos (uno largo por fases con tabla y código, uno con búsqueda y citas) y dos envíos en `deep` si el modo está medido. Un fin temprano que el proveedor cuente en la variante encendida también impide escribir `fast_end`. Antes de enviar, la sonda dice cuántos envíos hará y espera Enter.

**Coste de la comprobación (≈ 0).** La espera de `recheck` es `max(0, confirm_ms − lo que ya tardaron identifier y post)`. En la página real el identificador llega segundos después de la respuesta, así que la ventana corta ya pasó y `recheck` es una lectura de la señal y del texto (milisegundos). En la página sintética el identificador ya está y `recheck` espera lo que queda de la ventana corta: como mucho `confirm_ms` (500 ms), frente a los 4 s de la ventana antigua. La tabla sintética lo mide (tareas 9.x).

**Por qué.** Un texto cortado es el único fallo que este cambio no puede permitirse: la regla antigua tardaba, pero no cortaba. La comprobación después de la espera del identificador cuesta casi nada porque reutiliza tiempo que ya se gasta, y convierte un corte en una espera más larga. La sonda es la otra mitad: una pausa más larga que el doble de la ventana corta no la ve la comprobación, y por eso la sonda la busca de tres maneras.

**Alternativas rechazadas.** (a) Alargar la ventana corta: a 2 s ya no compensa frente a la ventana larga, y una pausa más larga seguiría cortando. (b) Exigir además la ventana de estabilidad entera: es la regla antigua. (c) Esperar a ciegas tras cada fin rápido: cuesta siempre lo mismo y, sin volver al bucle, solo cambia cuánto se tarda en cortar. (d) Devolver el texto corto con un aviso: un texto incompleto presentado como respuesta.

**Impacto.** Requisito «Fin por señal positiva» (escenarios de pausa entre fases, bloque tardío, señal recreada, respuesta instantánea, señal ocupada antes de enviar, modos) y «Medida en un solo comando»; tareas 9.x.

### D8 · La pestaña reutilizada, apagada por defecto (revisión independiente, 2026-11-28)

**Qué.** `HARNESS_COPILOT_REUSE_TAB` vacío es `off`. Aunque `tab_reuse` esté medido, la pestaña solo se reutiliza si el dueño lo enciende, después de la medida real. El README y el runbook dicen exactamente qué no ve (límite de D2).

**Por qué.** Hay una comprobación barata que no cuesta la recarga (pedir la conversación por su dirección sin navegar), pero la página real no tiene una API medida para ello, y adivinarla sería una suposición. Lo que sí se puede hacer es decir el límite y dejar la decisión al dueño con la cifra delante.

**Alternativas rechazadas.** (a) Una petición a la página para saber si la conversación existe: no está medida, y una petición inventada a un servicio real no es una comprobación. (b) Recargar solo a veces: el caso que importa (una conversación borrada en otro sitio) no avisa de cuándo pasa. (c) Mantenerla encendida con el aviso: el README decía «si ya no existe, no envía nada», y en ese camino no era verdad.

**Impacto.** Requisitos «Pestaña de confianza» e «Interruptores»; README, runbook, `.env.example`; tareas 9.x.

### D9 · Los tiempos nunca cambian el resultado (revisión independiente, 2026-11-28)

**Qué.** `record` captura cualquier `Exception` (nunca `CancelledError` ni `KeyboardInterrupt`, que son `BaseException`) y `ask` vuelve a capturar alrededor de la llamada, solo de la grabación. El recorte lee con `errors="replace"`. La carpeta `copilot/` y el fichero (también la copia recortada) se crean con `private_dir`/`private_file` (0700/0600). Al leer, cada campo se valida por tipo y límites (identificadores imprimibles de hasta 64 caracteres, milisegundos de 0 a 24 h, intentos 0–2, fines tempranos 0–100, fases conocidas, campos conocidos), las líneas de más de 4096 caracteres se saltan y un JSON demasiado anidado (`RecursionError`) también.

**Por qué.** Una pregunta ya enviada que termina `failed` porque el fichero de tiempos estaba corrupto es un resultado falso; y `history --timings` no debe caer por una línea manipulada.

**Alternativas rechazadas.** (a) Capturar alrededor de toda la pregunta: escondería errores de la petición. (b) Borrar el fichero corrupto: es del dueño, y borrarlo esconde que pasó algo.

**Impacto.** Requisito «Tiempos por fases sin texto»; tareas 9.x.

## Riesgos

- [La página real no pinta un cambio hecho en otro dispositivo] → límite de D2: 120 s de inactividad, identificador comprobado tras enviar, y la reutilización apagada por defecto (D8).
- [Una pausa entre fases más larga que el doble de la ventana corta] → la comprobación posterior no la ve; la sonda sí (señal de vuelta a ocupada, lectura 5 s después) y entonces no escribe `fast_end` (D7).
- [La página real añade un bloque después de la ventana corta] → la sonda lo cuenta como adelanto y no escribe `fast_end`; interruptor `HARNESS_COPILOT_FAST_END=off`.
- [La señal medida deja de funcionar tras un rediseño] → sin verla ocupada, la regla rápida no dispara y decide la ventana larga: más lento, nunca cortado.
- [Sin ventana la página pide verificación] → las guardas lo rechazan antes de escribir; la sonda dice «not usable»; apagado por defecto.
- [El fichero de tiempos crece o se corrompe] → se recorta, se valida al leer y su escritura nunca hace fallar una pregunta.
- [Un cambio de `ui.json` entre `measure` y `speed`] → `speed` solo escribe si los localizadores no cambiaron durante la medida, y `measure` conserva `fast_end`/`tab_reuse` solo si el `speed` más reciente midió esos mismos localizadores.
