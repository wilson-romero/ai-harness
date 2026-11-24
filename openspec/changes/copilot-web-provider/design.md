# Design

## Context

Motivación y alcance en `proposal.md`; conducta en `specs/`. Este change se enchufa en lo que dejó `session-core` (rama `feature/session-core`, SHA `0c14f33`):

- `LLMProvider` (`harness/providers/base.py`) es un `Protocol` con `name`, `synthetic_content` y `ask(request, on_sent) -> str`. El servicio (`harness/core/service.py`) aplica el plazo con `asyncio.timeout`: vencido antes de `on_sent` → `timeout`, después → `uncertain`; cualquier excepción del proveedor → `failed`, **también después de `on_sent`** (el Mock con `fail` llama a `on_sent` y luego falla, y `session-core` lo espera como `failed`).
- D5 de `session-core`: solo se guarda texto si `synthetic_content` es `True`. D6 dejó `create_session/recover/close` sin definir hasta medir Copilot. D7: bloqueo exclusivo por sesión, que se está reimplementando sobre SQLite en otra rama para quitar sus ramas `fcntl`/`msvcrt`; aquí solo se usa «existe un bloqueo por sesión y un mecanismo de bloqueo con nombre». D8: `authentication_required` y `closed` existen en el tipo y en el `CHECK` de SQLite, pero nada los produce.
- `sessions.remote_ref` existe en el esquema 001 y nadie lo escribe (grep del 2026-11-24). **No hace falta migración.**
- `registry.provider_factory` construye el proveedor por defecto también en `session create` y al principio de cada `ask`: construir un proveedor tiene que ser barato y no abrir nada.
- Cada comando de la CLI es un proceso.

### Premisas comprobadas (2026-11-24)

| Premisa | Cómo se comprobó |
|---|---|
| `playwright` 1.65.2 (publicada el 2026-11-14) declara `requires_python >=3.10` y el clasificador 3.14; publica wheels `py3-none` para `macosx_11_0_arm64`, `macosx_10_13_x86_64`, `win_amd64` y `win_arm64`. Su única dependencia es `greenlet>=3.1.1,<4`. | JSON de PyPI (`pypi.org/pypi/playwright/json`). |
| `greenlet` 3.5.6 publica wheels `cp314` para macOS (`universal2`) y Windows (`win_amd64`, `win_arm64`). | JSON de PyPI. |
| `launch_persistent_context(user_data_dir, channel="msedge", ...)` existe; «los navegadores no permiten lanzar varias instancias con el mismo User Data Directory»; cerrar ese contexto cierra el navegador; plazo de arranque por defecto 180 000 ms; `headless` es un parámetro. | Documentación de Playwright para Python vía context7 (`/websites/playwright_dev_python`, página `class-browsertype`). |
| Desde Chrome 136 el directorio de datos por defecto no se puede automatizar; Playwright recomienda un directorio propio. | Misma fuente (páginas `class-browsertype` y `codegen`). |
| `playwright install msedge` instala Edge en la ubicación global **sobrescribiendo** la instalación existente. | Misma fuente (página `browsers`). Por eso no se usa. |
| `playwright codegen` acepta `--user-data-dir` y reutiliza la sesión de ese perfil. | Misma fuente (página `codegen`). |
| **Edge no está instalado en la Mac de desarrollo.** | `ls /Applications ~/Applications` y `mdfind` por `com.microsoft.edgemac`: sin resultado. |
| El código del harness tiene ramas de plataforma solo en `harness/storage/locks.py` y en un `skipif` de `tests/integration/test_recovery.py`. | `grep -rn "sys.platform\|os.name\|msvcrt\|fcntl" harness tests`. |

### Premisas NO medidas

Nadie en esta planificación ha visto la UI real. Cada premisa tiene la tarea que la mide; ninguna decisión de abajo se da por buena hasta entonces.

| Id | Premisa | La mide |
|---|---|---|
| P1 | Edge, gestionado por la empresa, permite que Playwright lo controle (una política corporativa podría prohibir el protocolo de depuración). Si no lo permite, el corte queda **BLOCKED** y no se busca rodeo. | 3.2 (sonda) |
| P2 | Una conversación tiene una referencia estable visible en la URL, que aparece al primer envío y que reabre la conversación tras cerrar y abrir el navegador. | 3.2 (sonda) |
| P3 | Tras reabrir una conversación se ven todos sus turnos de usuario (sin lista virtualizada que oculte los antiguos), al menos hasta el número de turnos de la sonda. | 3.2 (sonda) |
| P4 | Existe al menos una señal de fin de respuesta que nunca se adelanta (ver D1). | 3.2 (sonda) |
| P5 | Un login vencido se reconoce porque la navegación termina en otro host o porque falta el editor y aparece un indicador de login. | 3.2 (sonda) |
| P6 | El editor acepta el prompt completo hasta cierto tamaño sin truncar. | 3.2 (sonda) |
| P7 | Lanzar Edge, cargar la conversación y tener el editor listo tarda un tiempo tolerable por pregunta (umbral de D3). | 3.2 (sonda) |
| P8 | Cómo falla un segundo lanzamiento sobre un perfil ya abierto (error inmediato o espera), en macOS. | 2.3 |
| P9 | Si el proceso de Python muere con `kill -9`, el Edge que lanzó se cierra solo (el driver de Playwright pierde su canal). | 2.4 |
| P10 | `playwright` 1.65.x funciona en ejecución sobre CPython 3.14.8 con `asyncio` (hoy solo consta en metadatos). | 1.2 |

## Goals / Non-Goals

**Goals:**

- Que el proveedor no contenga ningún dato de la UI real: todo lo que depende de Copilot sale del fichero de medición local.
- Que cada conducta de las specs se pruebe con páginas sintéticas en local y que la aceptación real sea una demo de Wilson.
- Un único camino de código en macOS y Windows.

**Non-Goals:**

- Robustez frente a cambios de la UI de Copilot: cuando cambie, se repite la sonda; el proveedor falla de forma controlada, no se adapta.
- Rendimiento: una pregunta a la vez, con el navegador abierto y cerrado en cada una.
- Copiar la respuesta con formato (portapapeles, Markdown original).

## Decisions

### D1 · La sonda: Wilson la ejecuta, mide contra una verdad sintética y nunca guarda contenido

- **Qué:** `scripts/copilot_probe.py`, en cuatro pasos que Wilson ejecuta a mano con el perfil dedicado y el navegador visible:
  1. **Arranque y login** (`probe login`): abre Edge con el perfil dedicado en `HARNESS_COPILOT_URL`, Wilson inicia sesión y pulsa Enter en la terminal. Registra si Playwright pudo controlar el navegador (P1) y el tiempo hasta el primer evento de carga.
  2. **Descubrimiento** (manual, sin código nuevo): `uv run playwright codegen --channel msedge --user-data-dir <perfil> --output <data>/copilot/codegen.py <url>`. Wilson pulsa el editor, escribe un prompt sintético, envía, pulsa «nueva conversación», el botón de detener mientras se genera y un control que aparezca al terminar una respuesta (copiar, valorar). Con los localizadores que genera codegen rellena `<data>/copilot/candidates.json` siguiendo el esquema versionado (`composer`, `send`, `new_conversation`, `user_turn`, `assistant_turn`, `stop` opcional, `response_done_control` opcional, `login_indicator` opcional). Regla del runbook: un localizador no puede incluir texto de una respuesta, un título de conversación ni un nombre de cuenta.
  3. **Medición** (`probe measure`): con los candidatos, abre 3 conversaciones nuevas y envía en cada una los mismos 4 prompts fijos (respuesta corta, cuenta de 1 a 60, cuenta de 1 a 300, una lista con un bloque de código), cada uno terminado en un marcador conocido `ZQX-END-<n>` que se pide a Copilot repetir al final. **12 envíos.** Para cada envío muestrea cada 100 ms: recuento de turnos, longitud del texto del último turno de asistente, si contiene el marcador, y el estado de cada candidato. **La verdad** es el instante en que el texto contiene el marcador y no vuelve a cambiar. Candidatos comparados, todos implementados como un conjunto cerrado en el proveedor:
     - `stop_hidden`: el botón de detener aparece tras enviar y luego desaparece.
     - `send_ready`: el editor o el botón de enviar vuelven a estar habilitados.
     - `done_control`: aparece el control de fin dentro del último turno de asistente.
     - `aria_busy`: el último turno (o su contenedor) pasa de `aria-busy="true"` a otro valor, solo si el atributo existe.
     - `text_stable(w)`: el texto no cambia durante `w` ∈ {1000, 2000, 4000} ms.
     Una señal es válida si se cumplió en 12/12 envíos y nunca antes de la verdad; se registra cuántas veces se adelantó y el retraso medio respecto a la verdad. Además mide: forma de la referencia de conversación (D6), reapertura tras cerrar y abrir el navegador con recuento de turnos visibles (P2, P3), tiempo de arranque hasta editor listo en cada una de las 6 aperturas (P7), duración máxima de respuesta, y tamaño de prompt: envía rellenos sintéticos de 2 000, 8 000, 16 000 y 32 000 caracteres pidiendo responder `LEN-OK`, y compara la longitud leída del editor con la escrita (P6).
  4. **Login vencido** (`probe login-state`): abre un perfil temporal vacío (sin sesión) en la URL y registra solo los **nombres de host** por los que pasa la navegación y si aparece el editor o el indicador de login (P5). El perfil temporal se borra al terminar.
  El resultado se escribe en `<HARNESS_DATA_DIR>/copilot/probe-<UTC>.json`; si está completo y la señal elegida es válida, también en `<HARNESS_DATA_DIR>/copilot/ui.json` (el anterior se renombra con su fecha). Al final la sonda imprime un **resumen sin datos del tenant** (qué señales fueron válidas, si la identidad es recuperable, recuentos y tiempos, versión de Edge y plataforma) que es lo único que Wilson copia a `tasks.md` o al agente.
- **Por qué:** el plan maestro pide «señales observadas, no solo sleep» y el plan de cortes pide empezar por una sonda. Medir contra un marcador conocido convierte «parece que terminó» en una comparación con verdad, y la condición 12/12 sin adelantos es un control que sabe decir NO. Codegen es la herramienta oficial de Playwright para descubrir localizadores y deja a Wilson el control de qué se registra.
- **Alternativas rechazadas:**
  - Que la sonda descubra sola los localizadores recorriendo el árbol de accesibilidad: los nombres accesibles de la barra lateral son títulos de conversaciones corporativas; filtrarlos de forma fiable es más difícil que dejar que Wilson elija.
  - Guardar una captura o una traza de Playwright para analizarla después: identifica al tenant y contiene contenido; prohibido en el repo y en el agente.
  - Observar el tráfico de red para saber cuándo termina el streaming: es mirar endpoints privados, fuera de lo autorizado.
  - Una sola conversación con muchos envíos: no mide la identidad entre conversaciones ni el arranque repetido.
- **Impacto:** spec `copilot-ui-probe` completa. Tareas grupo 3. Los grupos 4 y 5 y la demo 7.5 quedan **BLOCKED** hasta que Wilson aporte el resumen (tarea 3.2) y se pase la revisión de la tarea 3.3.

### D2 · Las mediciones viven en el directorio de datos, nunca en el repo

- **Qué:** el repo contiene el código de la sonda, el **esquema** Pydantic del fichero de medición (`harness/providers/copilot_ui.py`, con versión de esquema) y un fichero de medición **sintético** para las páginas de prueba (`tests/fixtures/copilot_ui/ui.json`). El proveedor lee `<HARNESS_DATA_DIR>/copilot/ui.json` al empezar cada `ask` y lo valida contra el esquema; incompleto, de otra versión de esquema o ausente → error controlado antes de registrar la solicitud. La sonda se niega a escribir si el fichero de destino lo podría versionar Git: si `git -C <destino> rev-parse --is-inside-work-tree` dice que sí y `git check-ignore -q <fichero>` dice que no está ignorado. El `./data` por defecto está ignorado por `.gitignore` (`data/`) y pasa; un `HARNESS_DATA_DIR` mal puesto en una carpeta versionada no. La URL completa vive solo en `.env` local; la referencia remota completa, solo en SQLite local. Ni la sonda ni el proveedor crean capturas, trazas, vídeos, HAR o `storage_state`; no se pasa ninguna de las opciones `record_*` de Playwright.
- **Por qué:** el repo es público. Con esto nada de lo versionado identifica a la empresa, y el guardián `scripts/check_public_safety.py` no necesita excepciones: el único JSON nuevo versionado es sintético, no hay binarios y los canarios de las pruebas son cadenas inventadas.
- **Alternativas rechazadas:**
  - Versionar `ui.json` tras una revisión de Wilson: los localizadores pueden llevar atributos propios del tenant y la revisión manual es el control que antes se olvida.
  - Cifrar `ui.json` en el repo: obliga a gestionar una clave para algo que no necesita compartirse.
- **Impacto:** spec `copilot-ui-probe` («La medición vive fuera del repositorio», «La medición no contiene datos…»). Tareas 1.3, 3.1 y 7.2.

### D3 · Un Edge por invocación de la CLI

- **Qué:** cada `ask` de una sesión de Copilot lanza `launch_persistent_context(perfil, channel="msedge", headless=False)`, hace su trabajo y cierra el contexto en un `finally`. No hay proceso de fondo. El login dura entre invocaciones porque vive en el perfil persistente.
- **Por qué:** la CLI ya es un proceso por comando, y el bloqueo, la recuperación y la liberación de recursos de `session-core` están pensados para eso. Un navegador lanzado por el propio proceso muere con él (P9 lo confirma) y no deja nada que vigilar.
- **Alternativas rechazadas:**
  - **Navegador de fondo de larga vida** (un demonio con Edge abierto y la CLI hablándole por un socket local): ahorra el arranque, pero añade un proceso que arrancar, vigilar y parar, un canal local que autenticar (superficie de SEC-09) y un estado más que recuperar tras una caída. Es lo que el plan aplaza hasta el MCP Server del harness.
  - **Conectarse con `connect_over_cdp` a un Edge abierto por Wilson con puerto de depuración:** cualquier proceso local podría manejar la sesión corporativa por ese puerto, y es la vía más fácil para acabar tocando el Edge personal.
- **Impacto:** spec `dedicated-edge-browser` («Solo se liberan recursos propios»). Si P7 mide más de **20 s** de mediana hasta editor listo, se reabre esta decisión con Wilson antes de la tarea 4.1.

### D4 · Perfil dedicado con marca y un único navegador a la vez

- **Qué:** el perfil es `HARNESS_EDGE_PROFILE`, por defecto `<HARNESS_DATA_DIR>/edge-profile`. Se acepta solo si no existe, está vacío o contiene el fichero `ai-harness-profile.txt` que el harness escribe al crearlo. Para el navegador hay un bloqueo con nombre `browser`, del mismo mecanismo que el bloqueo por sesión. Orden fijo: primero el de la sesión (lo toma el servicio), después el del navegador (lo toma el proveedor dentro de `ask`, **antes** de `on_sent`), sin interbloqueo posible. `ask` espera el del navegador sondeando cada 250 ms hasta su plazo; si vence esperando, es `timeout` porque nada salió. `copilot login` lo intenta una vez y, si está ocupado, falla. Un fallo de Playwright al abrir el perfil (p. ej. Wilson lo tiene abierto a mano) se traduce en `failed` con «el perfil está en uso» (la forma exacta del error es P8).
- **Por qué:** el bloqueo propio evita que dos procesos del harness choquen sobre el perfil; el de Edge solo protege de forma tardía y con un error de forma desconocida. La marca hace imposible apuntar por error al perfil personal o al de trabajo, que nunca están vacíos ni tienen la marca, **sin** conocer las rutas por defecto de Edge en cada sistema (eso exigiría ramas por plataforma).
- **Alternativas rechazadas:**
  - Rechazar las rutas por defecto de Edge: distintas en macOS y Windows; viola la regla de un solo camino de código y no protege de un perfil copiado.
  - Rechazar la segunda pregunta en vez de esperar: rompería «Preguntas en sesiones distintas SHALL poder completarse» de `session-core`.
- **Impacto:** spec `dedicated-edge-browser` («Solo un perfil dedicado», «Un solo navegador a la vez»). Depende de que el mecanismo de bloqueo admita un nombre además de un `session_id`; si la reimplementación sobre SQLite solo ofrece bloqueo por sesión, la tarea 2.2 añade el bloqueo con nombre con el mismo mecanismo.

### D5 · La interfaz de proveedor crece lo justo

- **Qué:** cambios en `harness/providers/base.py`:
  - `LLMRequest` gana `remote_ref: str | None` y `completed_turns: int` (solicitudes `completed` de la sesión), que el servicio rellena.
  - `ask(request, on_sent, *, events=None)`: `events` es opcional y ofrece `bound(remote_ref)` (el servicio guarda la referencia en su propia transacción en ese momento) y `warn(texto)` (el servicio lo añade a `LLMResponse.warnings`). El Mock no lo usa.
  - `check(prompt) -> None`: validación previa sin efectos (configuración, medición, tamaño). El servicio la llama antes de insertar la solicitud. En el Mock no hace nada.
  - Excepciones nuevas, todas subclase de `ProviderError`: `AuthenticationRequired` (el servicio registra `authentication_required` y pone la sesión en `authentication_required`), `RemoteConversationLost` (`failed` y sesión `closed`) y `ProviderUncertain` (`uncertain`). Si cualquiera llega después de `on_sent`, prevalece `uncertain` salvo `ProviderError` simple, que sigue siendo `failed` como hoy.
  - El servicio rechaza `ask` en una sesión `closed` antes de registrar nada.
  - El proveedor de Copilot convierte **toda** excepción inesperada posterior a `on_sent` en `ProviderUncertain`, y llama a `on_sent` **justo antes** de pulsar enviar, no después: un fallo durante el clic cuenta como posiblemente enviado.
  - `create_session`, `recover` y `close` de §9 del plan maestro **no** se añaden: la conversación remota se crea en la primera pregunta (D6), la recuperación es parte de cada `ask` y cerrar es lo que hace el `finally` del navegador.
- **Por qué:** es lo mínimo para que el servicio sepa la referencia remota en cuanto existe (aunque luego venza el plazo), produzca los dos estados que D8 de `session-core` dejó sin productor y distinga una caída tras el envío. El parámetro opcional y la excepción nueva dejan intactos el Mock y los tests de `session-core`.
- **Alternativas rechazadas:**
  - Que toda excepción tras `on_sent` sea `uncertain` en el servicio: cambiaría el escenario «Error del proveedor» de `llm-provider` para el Mock.
  - Devolver la referencia remota en el valor de retorno: se perdería si vence el plazo después de enviar, justo cuando más falta hace.
  - Abrir la conversación remota en `session create`: lanzaría Edge para crear una conversación vacía que quizá ni tenga referencia hasta el primer mensaje (P2).
- **Impacto:** `harness/providers/base.py`, `harness/core/service.py`, `harness/core/contracts.py`. Specs `copilot-web-provider` («Login vencido…», «Pérdida del navegador…», «Recuperación…»). Sin delta sobre `llm-provider` (ver proposal).

### D6 · Identidad remota: referencia de la URL, verificada antes de cada envío

- **Qué:** la sonda registra **en qué parte de la URL** está el identificador de la conversación (índice de segmento de ruta o nombre de parámetro), nunca su valor. Primera pregunta de una sesión sin `remote_ref`: abrir conversación nueva, enviar y, cuando la URL contiene un identificador según esa forma, llamar a `events.bound(url)`. `remote_ref` es la URL completa, guardada solo en SQLite local. Pregunta con `remote_ref`: navegar a ella y **verificar** antes de enviar: (a) la página está lista (D7); (b) el identificador extraído de la URL final es el mismo que el guardado; (c) si P3 se midió como cierta, los turnos de usuario visibles son ≥ `completed_turns`. Si (b) o (c) fallan con la página lista → `RemoteConversationLost` (sesión `closed`, mensaje: crear una sesión nueva). Si la página no llega a estar lista → `timeout` o `failed` sin tocar la sesión. Si una primera pregunta queda `uncertain` sin haber llegado a `bound`, la siguiente abre una conversación nueva y lo avisa: la anterior pudo quedar huérfana en Copilot.
- **Por qué:** no inventar selectores ni asumir URLs (§9 del plan maestro) significa que la forma de la referencia es un dato medido. Cerrar la sesión en vez de abrir otra conversación en silencio evita que Wilson crea que sigue un hilo cuyo contexto ya no existe. La comprobación de turnos es la única verificación posible sin leer contenido.
- **Alternativas rechazadas:**
  - Identificar la conversación por su título en la barra lateral: el título lo genera Copilot a partir del contenido; leerlo es leer contenido corporativo y no es único.
  - Insertar una marca del harness en el primer prompt: mezcla control con contenido, lo que el resto del sistema evita.
  - Abrir una conversación nueva automáticamente si no se encuentra: pierde el contexto sin que nadie lo decida.
- **Impacto:** spec `copilot-web-provider` («Una conversación remota por sesión», «Recuperación…»). **Puerta de decisión:** si la sonda mide que la URL no lleva identificador o que no reabre la conversación (P2 falsa), las tareas 5.x quedan **BLOCKED** y Wilson decide entre recortar el alcance (sin recuperación tras reinicio) o pedir otra vía; esta decisión se reescribe en su sitio.

### D7 · Estado de la página y login vencido

- **Qué:** tras navegar, el proveedor clasifica la página, con espera acotada por `HARNESS_COPILOT_READY_TIMEOUT_S`, en: `ready` (el editor medido es visible y habilitado y el host es el de `HARNESS_COPILOT_URL`), `login` (el host final está en el conjunto de hosts de login medido o aparece el indicador de login medido) o `unknown` (ninguna de las dos al vencer → `timeout`, nada enviado). `login` → `AuthenticationRequired`. El proveedor **solo** escribe en el localizador del editor y **solo** si el estado es `ready` y el host coincide; no hay ningún otro `fill`, `type` ni `press` en el código. `copilot login` abre el navegador visible y espera a que el estado sea `ready` o a que Wilson cierre la ventana, sin interactuar.
- **Por qué:** SEC-06 pide intervención humana; la comprobación de host antes de escribir garantiza que un prompt nunca acaba en un formulario de login aunque la UI cambie.
- **Alternativas rechazadas:**
  - Detectar el login por texto de la página («Iniciar sesión»): depende del idioma y es leer contenido.
  - Abrir el navegador para login automáticamente desde `ask`: mezcla un comando que pregunta con uno que espera a una persona, sin plazo claro.
- **Impacto:** spec `copilot-web-provider` («Login vencido…»), spec `dedicated-edge-browser` («Login manual»). Tareas 4.3 y 2.5.

### D8 · Respuesta nueva y su final

- **Qué:** antes de enviar se cuentan los turnos de asistente; la respuesta nueva es el turno de índice `n+1`. Se espera a que exista y después a la señal medida en `ui.json`; si la señal elegida no es `text_stable`, se exige además `text_stable` con la ventana mínima que la sonda midió sin adelantos. El texto se lee con `inner_text()` del turno nuevo. Esperas con la API de localizadores de Playwright, sin inyectar scripts propios en la página ni escuchar la red.
- **Por qué:** contar turnos evita devolver una respuesta anterior; combinar una señal estructural con estabilidad cubre el caso de que la señal medida en 12 envíos se adelante en el 13.º.
- **Alternativas rechazadas:**
  - Esperar un tiempo fijo: lo prohíbe el plan maestro.
  - Leer la respuesta por el botón de copiar y el portapapeles: permisos de portapapeles distintos por sistema y toca el portapapeles del usuario.
- **Impacto:** spec `copilot-web-provider` («Respuesta completa…»). Tarea 4.4.

### D9 · `uncertain` tras el envío y reconciliación solo como aviso

- **Qué:** se mantiene la regla de `session-core`: vencido el plazo tras `on_sent`, `uncertain`, sin reenvío, nunca. No hay reconciliación automática del estado ni del texto. En la siguiente pregunta de la sesión, si los turnos de usuario visibles son más que `completed_turns`, el proveedor emite `events.warn("la conversación tiene N turnos más de los completados; una solicitud incierta pudo llegar")`. La solicitud incierta sigue `uncertain`; Wilson puede ver la respuesta en Edge.
- **Por qué:** cambiar el estado de una solicitud a partir de un recuento contradiría «la solicitud anterior sigue en `uncertain`» de `request-recovery` y daría por cierto algo que solo es probable (Wilson pudo escribir a mano en esa conversación).
- **Alternativas rechazadas:**
  - Recuperar el texto de la respuesta incierta de la página: sería guardar o mostrar contenido sin una pregunta que lo pida, y emparejar turno y solicitud no es seguro.
  - Comando `session resolve`: D8 de `session-core` lo dejó para cuando hiciera falta con datos reales; con un aviso basta en este corte.
- **Impacto:** spec `copilot-web-provider` («Plazo vencido tras el envío sin reenvío»). Tarea 5.3.

### D10 · Caída del navegador y liberación de lo propio (SEC-10)

- **Qué:** el proveedor abre el contexto dentro de `async with` y lo cierra en `finally` con un plazo propio corto, protegido frente a la cancelación del plazo general (`asyncio.shield` más `asyncio.timeout`). Un `TargetClosedError` o cierre de página antes de `on_sent` → `ProviderError` (`failed`); después → `ProviderUncertain`. El harness nunca busca ni mata procesos por nombre ni por PID: solo cierra el contexto que obtuvo de Playwright. Si el proceso muere con `kill -9`, lo que pase con Edge es P9; el escenario «Proceso del harness matado» admite los dos resultados controlados.
- **Por qué:** matar por nombre (`msedge`) cerraría el Edge personal de Wilson y además exigiría código distinto por plataforma.
- **Alternativas rechazadas:**
  - Guardar el PID de Edge y matarlo en la siguiente invocación: los PID se reutilizan y podría ser otro proceso.
- **Impacto:** specs `copilot-web-provider` («Pérdida del navegador…») y `dedicated-edge-browser` («Solo se liberan recursos propios»). Tareas 2.4 y 4.5.

### D11 · Retención: no se guarda contenido real

- **Qué:** `CopilotWebProvider.synthetic_content = False`. Con D5 de `session-core`, los mensajes se guardan con `content = NULL`. `history` de una sesión de Copilot muestra la referencia remota y, por solicitud, estado y fecha. La respuesta solo se imprime por stdout. El proveedor no escribe logs con texto y el runbook avisa de no activar `DEBUG=pw:api` con contenido real (Playwright registraría los textos). Sin variable de entorno que lo cambie.
- **Por qué:** la política corporativa de retención no está aportada (dependencia externa del plan de cortes, «se resuelve en el Corte 2»): se resuelve tomando la opción que no necesita la política. SQLite sigue sin cifrar, y la referencia remota no es contenido.
- **Alternativas rechazadas:**
  - Guardar el contenido cifrado ya: exige decidir clave y custodia sin política que lo pida.
  - Variable `HARNESS_PERSIST_CONTENT`: rechazada en D5 de `session-core` por el mismo motivo.
- **Impacto:** spec `copilot-web-provider` («Sin contenido real guardado»). Si Wilson aporta una política que permita guardar, será un change nuevo con su decisión de cifrado.

### D12 · Límites y configuración

- **Qué:** variables nuevas, sin valor real en `.env.example`: `HARNESS_COPILOT_READY_TIMEOUT_S` (por defecto 60) y `HARNESS_COPILOT_MAX_PROMPT_CHARS` (por defecto, el mayor tamaño que la sonda midió sin truncar; la variable solo puede bajarlo). `HARNESS_REQUEST_TIMEOUT_S` sigue siendo el plazo total (espera del navegador, arranque, envío y respuesta); la sonda imprime un valor recomendado: arranque máximo + 2 × la respuesta más larga medida. Antes de enviar, el proveedor comprueba que el editor contiene exactamente la longitud del prompt; si no, `failed` sin enviar.
- **Por qué:** los números salen de la medición, no se estiman. Comprobar la longitud en el editor es lo que convierte el límite en una garantía contra el truncado silencioso.
- **Alternativas rechazadas:**
  - Partir un prompt largo en varios mensajes: cambia lo que se pregunta y multiplica los puntos de `uncertain`.
- **Impacto:** spec `copilot-web-provider` («Límite de tamaño del prompt»). Tareas 1.3 y 4.4.

### D13 · Pruebas contra páginas sintéticas locales

- **Qué:** `tests/fixtures/copilot_ui/` contiene una pequeña app HTML+JS sintética (editor, enviar, detener, turnos, nueva conversación con identificador en la URL guardado en `localStorage` del origen local para que sobreviva al reinicio del perfil temporal, página de login que cuenta pulsaciones y clics) y su `ui.json` sintético con sus propios localizadores, que no tienen nada que ver con los de Copilot. La sirve `http.server` en la interfaz de loopback con puerto libre; la página de login se sirve con otro nombre de host de loopback (la dirección numérica frente a `localhost`), que el navegador trata como otro host. Si el guardián del repo público rechaza direcciones IP literales, el código las obtiene con `socket` en vez de escribirlas. El servidor cuenta los prompts recibidos (la página los envía por `POST`): ese contador es el oráculo de «exactamente una vez». Parámetros de la URL de la prueba eligen el comportamiento: respuesta en fragmentos, señal que se adelanta, respuesta que no termina, conversación inexistente, redirección a login, cierre del navegador. Los tests con navegador llevan el marcador nuevo `edge` (necesitan Edge instalado; si no está, se omiten con motivo visible) y usan `HARNESS_TEST_HEADLESS=1`; el canal es siempre `msedge`. El marcador `copilot` queda para la demo real.
- **Por qué:** una integración real no se verifica con mocks, pero las conductas sí se pueden probar sin Copilot; el contador del lado servidor no depende del proveedor que se está probando.
- **Alternativas rechazadas:**
  - `playwright install chromium` para las pruebas: descarga otro navegador (§5 del plan maestro: no instalar navegadores si hay Edge) y probaría otro binario que el de la demo.
  - Mockear Playwright: probaría el mock.
- **Impacto:** tareas de verificación de los grupos 2 a 6; `pyproject.toml` gana el marcador `edge`.

### D14 · Un solo camino de código para macOS y Windows

- **Qué:** el código de este change usa solo `pathlib`, la API de Playwright y SQLite (a través del bloqueo). Nada de `sys.platform`, `os.name`, `msvcrt`, `fcntl`, señales por sistema, rutas por defecto de Edge, ni comandos de shell propios de un sistema (la única orden externa es `git`, igual en los dos, en la comprobación de D2). El oráculo es un `grep` que no devuelve nada sobre los ficheros de este change (tarea 7.1). La demo de Windows es una confirmación opcional de Wilson, no una puerta del corte.
- **Por qué:** regla de Wilson: lo que pasa en el Mac funciona en Windows. Las diferencias que quedan (cómo Edge bloquea su perfil, P8; si muere con el proceso, P9) están dentro de Edge y Playwright, y el diseño las trata igual en las dos plataformas.
- **Alternativas rechazadas:**
  - Mantener una prueba obligatoria en Windows: Wilson la retiró como puerta el 2026-11-24.
- **Impacto:** tarea 7.1 y 7.4.

## Risks / Trade-offs

- [La política corporativa de Edge impide la automatización (P1)] → la sonda lo detecta en su primer paso; el corte queda BLOCKED y se replantea con Wilson. No se busca rodeo. Límite que no se arregla.
- [La UI de Copilot cambia y los localizadores dejan de valer] → `check()` y la clasificación de página fallan de forma controlada (`timeout`/`failed`, nunca un envío a ciegas); se repite la sonda. No se arregla en este corte.
- [La señal de fin, válida en 12 envíos, se adelanta en real] → se exige además estabilidad del texto (D8); si aun así se detecta un corte, se sube la ventana y se repite la sonda con más envíos.
- [P2 falsa: sin referencia de conversación en la URL] → puerta de decisión de D6; no se implementa recuperación tras reinicio sin una referencia medida.
- [P3 falsa: turnos antiguos no visibles tras reabrir] → se omite la comprobación de turnos y la verificación queda solo en el identificador; se documenta como verificación más débil.
- [Arrancar Edge en cada pregunta es lento] → umbral de 20 s de D3 para reabrir la decisión; por debajo, se acepta.
- [`kill -9` deja Edge abierto sobre el perfil (P9)] → la siguiente pregunta falla con «perfil en uso» y el runbook dice cerrar esa ventana a mano; el harness no mata procesos.
- [Cerrar el navegador bajo cancelación puede colgarse] → cierre con su propio plazo protegido (D10); si vence, el proceso termina y entra P9.
- [Una solicitud `uncertain` sin `bound` deja una conversación huérfana en Copilot] → aviso en la siguiente pregunta; Wilson la borra a mano si quiere. No se arregla.
- [Wilson escribe a mano en una conversación del harness] → el aviso de turnos de más lo señala; la conducta sigue siendo correcta (no se reenvía). Se documenta en el runbook.
- [Las conversaciones de la sonda quedan en el historial de Copilot de Wilson] → el runbook lo dice; son sintéticas.
- [Edge no está en la Mac de desarrollo] → los tests `edge` se omiten con motivo visible hasta instalarlo con el instalador normal de Microsoft (no con `playwright install`); la tarea 1.1 lo deja anotado.
- [Las pruebas de páginas sintéticas en headless y la demo en visible difieren] → la demo real es visible; la sonda también. Diferencia aceptada.

## Migration Plan

Sin migración de esquema (`remote_ref`, `authentication_required` y `closed` ya existen en 001). Desplegar es añadir la dependencia y configurar `.env`. Volver atrás es `HARNESS_PROVIDER=mock`: las sesiones de Copilot existentes quedan en la base y sus `ask` fallan de forma controlada si se borra `ui.json`.

## Open Questions

- ¿Se borran a mano las conversaciones sintéticas de la sonda o se dejan? No cambia specs ni tareas.
