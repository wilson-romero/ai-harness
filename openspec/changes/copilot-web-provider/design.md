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
| ~~Edge no está instalado en la Mac de desarrollo.~~ **Actualizado el 2026-11-24:** Wilson instaló Microsoft Edge 158.0.4370.33 con el instalador normal; Playwright lo encuentra con `channel="msedge"` sin descargar nada. | Antes: `ls /Applications ~/Applications` y `mdfind`, sin resultado. Después: `defaults read "/Applications/Microsoft Edge.app/Contents/Info" CFBundleShortVersionString` → `158.0.4370.33`, y la fixture `edge_ready` de `tests/conftest.py` lanza Edge headless con perfil temporal. |
| ~~El código del harness tiene ramas de plataforma solo en `harness/storage/locks.py` y en un `skipif` de `tests/integration/test_recovery.py`.~~ **Actualizado el 2026-11-24:** con el bloqueo sobre SQLite ya en `develop`, `harness/`, `main.py` y `scripts/copilot_probe.py` no tienen ninguna; lo comprueba `tests/unit/test_portability.py`. | `grep -rn "sys.platform\|os.name\|msvcrt\|fcntl" harness tests`. |

### Premisas NO medidas

Nadie en esta planificación ha visto la UI real. Cada premisa tiene la tarea que la mide; ninguna decisión de abajo se da por buena hasta entonces.

| Id | Premisa | La mide |
|---|---|---|
| P1 | Edge, gestionado por la empresa, permite que Playwright lo controle (una política corporativa podría prohibir el protocolo de depuración). Si no lo permite, el corte queda **BLOCKED** y no se busca rodeo. **Medida el 2026-11-24 con `probe login`: cierta en Windows 11 AMD64** (Python 3.14.10, Edge 158; segundo intento: `P1 controllable: yes`, `launch_ms 1404`, `first_load_ms 1776`, confirmado por Wilson; el primer intento se interrumpió durante la carga, ver tarea 8.3) **y en macOS arm64** (Python 3.14.8, Edge 158; `launch_ms 5627`, `first_load_ms 5206`, con una cuenta de prueba de Wilson que muestra la misma interfaz). Ojo: en macOS, al volver a abrir el perfil, la URL configurada mostró la página de invitado, también después de un segundo login respondiendo Sí a «mantener la sesión iniciada» (tarea 8.4): era la raíz del host, que enseña la portada de invitado aunque haya sesión; con la ruta `/chat` la sesión se conservó y P2–P7 se midieron en macOS (D7 revisada). | 3.2 (sonda) |
| P2 | Una conversación tiene una referencia estable visible en la URL, que aparece al primer envío y que reabre la conversación tras cerrar y abrir el navegador. **Medida el 2026-11-24 en macOS arm64** (Python 3.14.8, Edge 158, cuenta de prueba universitaria, `HARNESS_COPILOT_URL=…/chat`): **cierta.** `path_segment 2` con segmentos fijos `chat/conversation`; el identificador aparece en la URL ~5 s tras enviar, después de terminar la primera respuesta (ver D6 revisada); 3/3 conversaciones reabiertas desde el identificador solo. Windows: sin medir. | 3.2 (sonda) |
| P3 | Tras reabrir una conversación se ven todos sus turnos de usuario (sin lista virtualizada que oculte los antiguos), al menos hasta el número de turnos de la sonda. **Medida el 2026-11-24 en macOS arm64** (Python 3.14.8, Edge 158, cuenta de prueba universitaria, `HARNESS_COPILOT_URL=…/chat`): **cierta** hasta 4 turnos: `[4, 4, 4]` de 4 tras reabrir (los turnos están en un feed virtualizado; con más turnos podría no cumplirse). Windows: sin medir. | 3.2 (sonda) |
| P4 | Existe al menos una señal de fin de respuesta que nunca se adelanta (ver D1). **Medida el 2026-11-24 en macOS arm64** (Python 3.14.8, Edge 158, cuenta de prueba universitaria, `HARNESS_COPILOT_URL=…/chat`): **cierta.** Válidas, 12/12 sin adelantos: `stop_hidden` (retraso medio 1217 ms, elegida), `done_control` (1217 ms), `aria_busy` (1906 ms) y `text_stable_4000`; no válidas `text_stable_1000` (7 adelantos) y `text_stable_2000` (1); `send_ready` nunca se cumple (el editor sigue editable mientras responde). Windows: sin medir. | 3.2 (sonda) |
| P5 | Un login vencido se reconoce porque la navegación termina en otro host o porque falta el editor y aparece un indicador de login. **Medida el 2026-11-24 en macOS arm64** (Python 3.14.8, Edge 158, cuenta de prueba universitaria, `HARNESS_COPILOT_URL=…/chat`): **cierta.** Un perfil vacío termina en un host de login (`login_host`, 1 host visto); no se vio indicador en la página de Copilot. Windows: sin medir. | 3.2 (sonda) |
| P6 | El editor acepta el prompt completo hasta cierto tamaño sin truncar. **Medida el 2026-11-24 en macOS arm64** (Python 3.14.8, Edge 158, cuenta de prueba universitaria, `HARNESS_COPILOT_URL=…/chat`): **cierta hasta 32000 caracteres** (2000, 8000, 16000, 32000 aceptados; no se probó más). El editor añade dos caracteres de anchura cero (U+200B, U+200C) que no cuentan. Windows: sin medir. | 3.2 (sonda) |
| P7 | Lanzar Edge, cargar la conversación y tener el editor listo tarda un tiempo tolerable por pregunta (umbral de D3). **Medida el 2026-11-24 en macOS arm64** (Python 3.14.8, Edge 158, cuenta de prueba universitaria, `HARNESS_COPILOT_URL=…/chat`): **cierta.** Arranque hasta editor listo: mediana 4356 ms, máximo 4600 ms (n=7), lejos del umbral de 20 s de D3. Windows: sin medir. | 3.2 (sonda) |
| P8 | Cómo falla un segundo lanzamiento sobre un perfil ya abierto (error inmediato o espera), en macOS. **Medida el 2026-11-24, macOS arm64, Edge 158.0.4370.33, Playwright 1.65.2:** error inmediato, 0,11 s, `playwright.async_api.Error` con «Failed to create a ProcessSingleton for your profile directory», seguido del registro de llamada con la línea de órdenes completa (incluye la ruta del perfil, por eso el harness no la muestra). El lanzador lo traduce a «perfil en uso» (`ProfileInUse`); test `test_profile_open_in_another_edge_is_reported_as_in_use`. | 2.3 |
| P9 | Si el proceso de Python muere con `kill -9`, el Edge que lanzó se cierra solo (el driver de Playwright pierde su canal). **Medida el 2026-11-24, macOS arm64, Edge 158, headless:** cierta. Tras `kill -9` del proceso que tenía Edge abierto sobre un perfil temporal, a 1 s ya no quedaba ningún proceso de Edge con ese perfil (comprobado cada segundo durante 10 s) y `main.py copilot login` sobre el mismo perfil terminó con código 0, sin traza. No medida con la ventana visible ni en Windows. | 2.4 |
| P10 | `playwright` 1.65.x funciona en ejecución sobre CPython 3.14.8 con `asyncio` (hoy solo consta en metadatos). **Medida el 2026-11-24, macOS arm64:** cierta. `uv add playwright` resolvió `playwright 1.65.2` y `greenlet 3.5.6`; con CPython 3.14.8 la API async lanza Edge 158 headless en 0,76 s con perfil temporal y lee el título de una página local. Nota: `playwright.__version__` no existe; la versión se lee con `importlib.metadata.version("playwright")`. | 1.2 |

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
     **Revisada el 2026-11-24 (tarea 8.4): descubrimiento por comportamiento en vez de codegen.** Motivo: en Windows Wilson no pudo completar el paso manual (de codegen a `candidates.json`) y preguntó por qué no era automático; además su codegen mostró que el editor real es un párrafo dentro de un área editable y que envía con Enter, sin botón que codegen registrara. Ahora `measure`, si no hay localizadores completos y nunca se descubrieron, ejecuta antes `discover` (también se puede ejecutar solo): abre Copilot con el perfil dedicado, toma como editor el elemento editable visible mayor (`textarea`, `contenteditable`, `role=textbox`), escribe el prompt fijo 1 y lo envía con **Enter**; si Enter no envía, pulsa solo el botón que escribir habilitó (nunca otro). Busca por texto, dentro del navegador, el elemento que repite el prompt (turno de usuario) y el que contiene el marcador `ZQX-END-1` (turno de asistente); sube por sus ancestros hasta antes del ancestro común y, para cada nivel, deriva selectores CSS de atributos estables (`data-*`, `role`, `id`, `type`, `contenteditable`, clases), nunca del texto y nunca de un valor con dígitos o que aparezca también en el texto o en un atributo legible de la página. Mientras la respuesta se escribe vigila cada 100 ms los controles que aparecen al enviar y desaparecen al final (`stop`), los que aparecen al final dentro del turno (`response_done_control`), el `aria-busy` que cambia en la respuesta o un ancestro (`busy_region`, campo opcional nuevo) y el botón que escribir habilitó (`send`, opcional con Enter: alimenta `send_ready`). Con el prompt fijo 2 comprueba que los selectores de turno cuentan exactamente 2 y elige el nivel más alto que lo cumple. Por último prueba como «nueva conversación» los controles cuyo nombre accesible coincide con un patrón en varios idiomas o cuyos atributos lo indican, y solo acepta uno si, tras pulsarlo, el hilo queda con 0 turnos y la URL cambia. De la URL guarda solo la forma (`path_segment` con su índice). Todo se escribe en `<data>/copilot/discovered.json`; `candidates.json` sigue funcionando y prevalece entrada a entrada (puede contener solo lo que faltó). Si algo no se identifica, la sonda lo nombra y pide ese único elemento con una línea; `measure` no vuelve a descubrir ni envía nada hasta tenerlo. Si la página muestra elementos visibles marcados como de invitado o de inicio de sesión (`unauth`, `sign in`, `login` en `id`, clases o `data-*`), ni el descubrimiento ni la medición escriben en ella. **Lo que no garantiza:** solo está probado contra dos formas sintéticas de página; un selector de clase o de `data-*` puede cambiar en cualquier despliegue de Copilot (se repite la sonda); el patrón de «nueva conversación» cubre unos pocos idiomas; si la respuesta no repite el marcador, no hay turno de asistente; un valor de atributo que sea un nombre propio sin dígitos y que no aparezca en la página pasaría el filtro (el resumen nunca imprime selectores y `discovered.json` vive solo en el directorio de datos).
  3. **Medición** (`probe measure`): con los candidatos, abre 3 conversaciones nuevas y envía en cada una los mismos 4 prompts fijos (respuesta corta, cuenta de 1 a 60, cuenta de 1 a 300, una lista con un bloque de código), cada uno terminado en un marcador conocido `ZQX-END-<n>` que se pide a Copilot repetir al final. **12 envíos.** Para cada envío muestrea cada 100 ms: recuento de turnos, longitud del texto del último turno de asistente, si contiene el marcador, y el estado de cada candidato. **La verdad** es el instante en que el texto contiene el marcador y no vuelve a cambiar. **Revisada el 2026-11-24 (tarea 3.1):** la verdad es el instante en que el texto **hasta el marcador, incluido,** contiene el marcador y no vuelve a cambiar; lo que aparezca después del marcador no cuenta. Motivo: un control de fin que vive dentro del turno (p. ej. «Copiar») añade su etiqueta al texto del turno en el mismo instante en que se cumplen las señales; con la definición anterior, en la app sintética las cuatro señales estructurales salían adelantadas en 1 de 12 envíos por puro orden de lectura dentro de una muestra. Como el prompt pide el marcador al final, todo lo posterior es decoración de la página. Las señales `text_stable(w)` siguen midiéndose sobre el texto completo del turno, que es lo que verá el proveedor. Cada muestra lee el texto **antes** que las señales, así que una señal vista en una muestra cuyo texto aún no es el final cuenta como adelantada. Candidatos comparados, todos implementados como un conjunto cerrado en el proveedor:
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
  - Que la sonda descubra sola los localizadores recorriendo el árbol de accesibilidad: los nombres accesibles de la barra lateral son títulos de conversaciones corporativas; filtrarlos de forma fiable es más difícil que dejar que Wilson elija. **Revertida el 2026-11-24 (tarea 8.4)** en su forma «por comportamiento»: no se recorre el árbol de accesibilidad ni se usan nombres accesibles como localizadores; se parte de lo que la página hace con un prompt fijo, y los títulos de la barra lateral no pueden convertirse en selector porque se excluye todo valor que aparezca en el texto de la página.
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
- Confirmada por Wilson el 2026-11-24 como punto de partida.
- **Revisada el 2026-11-24 (tarea 8.8): sandbox de Edge activado.** Corrección de seguridad.
  - **Qué:** el único lanzador (`harness/browser/edge.py`, que usan la sonda, `copilot login` y el futuro proveedor) pasa `chromium_sandbox=True` a `launch_persistent_context`. Playwright, por defecto, lanza la familia Chromium con `--no-sandbox` (documentación de Playwright para Python: `chromium_sandbox`, «Enable Chromium sandboxing. Defaults to `false`»). Wilson vio por eso el aviso de Edge sobre una opción de línea de comandos no admitida.
  - **Por qué:** este Edge tiene una sesión corporativa iniciada y muestra una página remota. Sin sandbox, un fallo explotable en el renderizador da acceso directo al proceso del usuario y a su perfil. El sandbox es la configuración normal de Edge, y la que debe tener un navegador con esa sesión. No hacía falta `ignore_default_args`: la opción quita `--no-sandbox` por sí sola.
  - **Coste:** ninguno medido en macOS. El arranque, `login`, `structure` y las pruebas `edge` (sin ventana) se comportan igual, y la sesión iniciada se conservó. En Windows **no está comprobado**: una política corporativa o un antivirus pueden impedir que los procesos del sandbox arranquen. En ese caso la pestaña no carga o Edge no se abre, y el runbook dice qué hacer. No se vuelve a `--no-sandbox` sin decisión de Wilson.
  - **Comprobación:** `test_edge_runs_with_its_sandbox_on` lee la línea de comandos en la propia página `edge://version` del Edge lanzado, sin código por plataforma, y exige que no tenga `--no-sandbox`. Control negativo: con `CHROMIUM_SANDBOX = False` el test falla.
  - **Otras opciones que Playwright sigue pasando** (revisadas el 2026-11-24 en `edge://version`; no se quita ninguna sin decisión):
    - **Rebajan la seguridad:**
      - `--password-store=basic` y `--use-mock-keychain` (macOS): las cookies del perfil, y con ellas la sesión, se cifran con una clave fija en vez de con el llavero del sistema. Quien lea el directorio del perfil puede descifrarlas. Quitarlas invalida la sesión guardada (hay que volver a iniciar sesión) y puede hacer que macOS pida acceso al llavero; se deja como decisión pendiente para Wilson. En Windows no aplican: el cifrado usa DPAPI.
      - `--disable-background-networking` y `--disable-component-update`: Edge no actualiza en segundo plano listas como las de protección contra sitios peligrosos.
      - `--disable-popup-blocking`: permite ventanas emergentes.
      - `HttpsUpgrades` y `HttpsFirstBalancedModeAutoEnable`, dentro de `--disable-features`: no convierte enlaces `http` en `https` (Copilot ya es `https`).
      - `--enable-unsafe-swiftshader`: WebGL por software como respaldo.
    - **No rebajan la seguridad:** `--remote-debugging-pipe` (el canal de control es una tubería, no un puerto de red) y `--disable-extensions`. Tampoco el resto: desactivan el primer arranque, la sincronización, las métricas, los informes de fallos y el estrangulamiento de pestañas en segundo plano, o ajustan la apariencia.
    - **Aviso visible:** solo se observó el de `--no-sandbox`. `--disable-infobars` oculta además la barra de «controlado por software automatizado»; ese aviso sería aceptable, pero lo quita Playwright, no el harness.
- **Revisada el 2026-11-25 (petición de Wilson): fuera las opciones que solo apagan protecciones de fondo.**
  - **Qué:** el lanzador pasa `ignore_default_args` con cuatro opciones de Playwright (`DROPPED_DEFAULT_ARGS` en `harness/browser/edge.py`): `--disable-popup-blocking`, `--disable-component-update`, `--disable-background-networking` y `--disable-infobars`. La documentación de Playwright para Python (consultada con context7) dice que una lista en `ignore_default_args` filtra esas opciones exactas de las predeterminadas y deja las demás. Con ello Edge vuelve a bloquear ventanas emergentes, actualiza sus componentes y sus listas de protección, y no oculta la barra de automatización (en Edge esa opción no tiene efecto, según el propio código de Playwright; quitarla no cambia nada visible, pero tampoco hay motivo para pedirla).
  - **Se quedan:**
    - `HttpsUpgrades` y `HttpsFirstBalancedModeAutoEnable`. Van dentro de un único `--disable-features=…` junto con otras doce funciones que Playwright necesita apagar. `ignore_default_args` solo quita opciones completas: quitarlo exigiría copiar la lista interna de Playwright, que cambia con cada versión, y un fallo de esa copia no se notaría. Copilot es `https`, así que la mejora a `https` no tiene nada que hacer allí.
    - `--password-store=basic` y `--use-mock-keychain`. Es decisión de Wilson (ver Open Questions); el coste está en `SECURITY.md` y en el runbook.
    - `--enable-unsafe-swiftshader`: sin cambio, como estaba.
  - **Comprobación:** `test_background_protections_are_not_switched_off` lee `edge://version` del Edge lanzado y exige que las cuatro opciones no estén y que una predeterminada no tocada (`--no-first-run`) siga. Control negativo: sin `ignore_default_args`, el test falla. Las 63 pruebas `edge` pasan, y un `structure` real en macOS con la sesión de prueba sigue con la sesión iniciada: `signed-out hints: 0  on Copilot host: yes  startup_ms: 8011` (sin envíos).

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
- **Revisada el 2026-11-24 (confirmado por Wilson; tarea 8.7): `remote_ref` guarda solo el identificador.**
  - **Qué dijo Wilson:** la URL de una conversación es la base `https://copilot.cloud.microsoft/` + la ruta fija `chat/conversation/` + el identificador como **último** segmento (un valor tipo UUID), y a veces le sigue una consulta (`?fromcode=…&es=…`). El identificador lo genera la plataforma, nunca el harness.
  - **Qué midió la sonda (macOS, cuenta de prueba universitaria, Edge 158, 2026-11-24):**
    - Forma: `path_segment 2` con segmentos fijos `chat`, `conversation`, es decir, el último segmento de `chat/conversation/<id>`. Coincide con lo que dijo Wilson. La consulta no interviene: `identifier_in` lee solo la ruta.
    - Reapertura: las 3 conversaciones se reabrieron desde el identificador solo (`reopened from the id alone: 3/3`), con los 4 turnos de usuario visibles en cada una.
    - **Momento:** en las tres conversaciones, el identificador apareció en la URL a 4986, 4899 y 5533 ms del envío del primer prompt. El primer texto de la respuesta apareció a unos 570 ms y la respuesta terminó (verdad de la sonda) a 3238, 3239 y 3429 ms. **El identificador llega después de que la primera respuesta ha terminado**, unos 1,7-2,1 s más tarde, no al enviar ni al empezar la respuesta. Wilson no dijo cuándo; esto lo añade la medición.
    - Pendiente: confirmarlo en Windows con la cuenta corporativa.
  - **Cambios respecto al texto anterior:**
    1. `sessions.remote_ref` (SQLite local) guarda **solo el identificador** extraído según la forma medida, no la URL completa: ni consulta ni host. La forma (índice de segmento) vive en `ui.json` del directorio de datos. Ninguno de los dos aparece en resúmenes, logs ni en el repo.
    2. Una conversación nueva se abre en la entrada del chat (ruta `chat`, la de `HARNESS_COPILOT_URL`). El harness nunca inventa ni preasigna un identificador: lo **aprende** cuando la URL pasa a llevarlo según la forma medida, y solo entonces llama a `events.bound(id)`.
    3. Ventana antes de `bound`. Según la medición, cubre **toda la primera respuesta** y unos segundos más.
       - Fallo antes de enviar: no hay prompt en Copilot; la pregunta termina `failed` o `timeout` sin tocar la sesión.
       - Fallo después de enviar y antes de que la URL lleve el identificador (caída, plazo vencido, ventana cerrada, aunque la respuesta ya estuviera en pantalla): la solicitud queda `uncertain` y la sesión sigue con `remote_ref` vacío. La siguiente pregunta abre una conversación nueva y avisa de que la anterior pudo quedar huérfana en Copilot.
       - Respuesta completa y el identificador aún sin llegar: el proveedor espera el identificador como mucho 10 s tras la señal de fin (la medida fue de unos 2 s), sin pasar de `HARNESS_REQUEST_TIMEOUT_S`. Si llega, `bound` y la solicitud termina `completed`. Si no llega, la respuesta se entrega igual (`completed`, porque Copilot respondió y la sonda vio terminar la respuesta), la sesión queda sin referencia y se avisa de que la pregunta siguiente empezará una conversación nueva sin el contexto anterior.
       - Ninguna de estas ramas inventa un identificador.
    4. Reabrir es navegar a esquema y host de la URL configurada + los segmentos fijos medidos (`ConversationRef.prefix`, solo palabras simples: `chat`, `conversation`) + el identificador (`ConversationRef.url_for`), y **verificar que la URL final contiene ese identificador** en su sitio (`ConversationRef.identifier_in`, que exige también los segmentos fijos) antes de escribir nada. La consulta de una URL de conversación nunca se lee; solo se conserva la de la propia URL configurada, si la tiene, porque es configuración. La sonda ya reabre así sus conversaciones (`reopened from the id alone` en el resumen), de modo que la medición comprueba este camino y no la URL completa. Si no lo contiene con la página lista → `RemoteConversationLost` (sin cambios en esa regla).
  - **Por qué:** guardar la URL completa guardaba también la consulta, que no identifica nada y puede llevar datos de la plataforma. El identificador basta para reabrir y es lo único que la verificación compara.
- **Impacto:** spec `copilot-web-provider` («Una conversación remota por sesión», «Recuperación…»). **Puerta de decisión:** si la sonda mide que la URL no lleva identificador o que no reabre la conversación (P2 falsa), las tareas 5.x quedan **BLOCKED** y Wilson decide entre recortar el alcance (sin recuperación tras reinicio) o pedir otra vía; esta decisión se reescribe en su sitio.

### D7 · Estado de la página y login vencido

- **Qué:** tras navegar, el proveedor clasifica la página, con espera acotada por `HARNESS_COPILOT_READY_TIMEOUT_S`, en: `ready` (el editor medido es visible y habilitado y el host es el de `HARNESS_COPILOT_URL`), `login` (el host final está en el conjunto de hosts de login medido o aparece el indicador de login medido) o `unknown` (ninguna de las dos al vencer → `timeout`, nada enviado). `login` → `AuthenticationRequired`. El proveedor **solo** escribe en el localizador del editor y **solo** si el estado es `ready` y el host coincide; no hay ningún otro `fill`, `type` ni `press` en el código. `copilot login` abre el navegador visible y espera a que el estado sea `ready` o a que Wilson cierre la ventana, sin interactuar.
- **Por qué:** SEC-06 pide intervención humana; la comprobación de host antes de escribir garantiza que un prompt nunca acaba en un formulario de login aunque la UI cambie.
- **Alternativas rechazadas:**
  - Detectar el login por texto de la página («Iniciar sesión»): depende del idioma y es leer contenido.
  - Abrir el navegador para login automáticamente desde `ask`: mezcla un comando que pregunta con uno que espera a una persona, sin plazo claro.
- **Impacto:** spec `copilot-web-provider` («Login vencido…»), spec `dedicated-edge-browser` («Login manual»). Tareas 4.3 y 2.5.
- **Revisada el 2026-11-24 (tarea 8.6): estado `guest` y ruta del chat guardada en el login.**
  - **Qué:** en macOS, con la cuenta de prueba, la raíz del host de Copilot enseña la portada de invitado (cuadro de preguntas propio, botón de iniciar sesión) aunque la sesión sea válida; el chat con sesión vive bajo `/chat`. Con la raíz configurada, la sonda paraba con «signed out» y `copilot login` esperaba sin explicar nada. Ahora:
    1. Hay un quinto estado, `guest`: la página está en el host configurado pero muestra indicios de «sin sesión» (elementos visibles cuyo `id`, `class` o `data-*` nombra `unauth`, `sign-in` o `login`; solo nombres de atributos que escribió el autor de la página, nunca texto). `guest` gana a `ready`: un cuadro de preguntas de invitado no es el chat, y el proveedor nunca escribe en él.
    2. `copilot login` guarda, al quedar `ready`, la **forma** de la ruta donde ocurrió: solo el primer segmento y solo si es una palabra simple (`/chat`), nunca un identificador ni la consulta, en `HARNESS_DATA_DIR/copilot/login.json`. Si esa ruta no es la configurada, vuelve a abrir la URL configurada (solo mira) y, si es `guest`, termina con un error accionable: la sesión quedó guardada, la URL lleva a la portada de invitado y `set HARNESS_COPILOT_URL=<host>/chat`.
    3. La sonda hace lo mismo en `discover`, `measure` y `structure`: el mensaje propone la ruta guardada por su paso `login` (o por `copilot login`) y, sin ninguna, pone `/chat` como ejemplo.
  - **Por qué guardar la ruta:** sin ella el mensaje solo puede dar un ejemplo, y la ruta correcta depende del despliegue; la persona ya la mostró al iniciar sesión. Guardar solo el primer segmento simple deja fuera identificadores de conversación o de inquilino.
  - **Alternativas rechazadas:**
    - Corregir la URL en silencio (navegar a la ruta guardada): el harness abriría una dirección que nadie configuró, contra «la sonda nunca abre una página que no elegiste».
    - Poner `/chat` por defecto en el código: es la ruta de un producto concreto en una fecha; en otro despliegue sería falsa. Solo aparece como ejemplo en mensajes y runbook.
    - Guardar la ruta completa: incluye el identificador de la conversación.
  - **Impacto:** spec `dedicated-edge-browser` (requisito nuevo «Portada de invitado en la URL configurada»); spec `copilot-ui-probe` («Lo no identificado se pide, no se adivina», escenario nuevo «Dirección configurada que lleva a la portada de invitado»); runbook (ejemplo `/chat`); tarea 8.6.

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

- **Qué:** `tests/fixtures/copilot_ui/` contiene una pequeña app HTML+JS sintética (editor, enviar, detener, turnos, nueva conversación con identificador en la URL guardado en `localStorage` del origen local para que sobreviva al reinicio del perfil temporal (**Revisada el 2026-11-24, tarea 1.4:** las conversaciones se guardan en el servidor de prueba, no en `localStorage`; sobreviven igual al cierre del navegador y a un perfil nuevo, y el servidor es además el oráculo de en qué conversación cae cada prompt), página de login que cuenta pulsaciones y clics) y su `ui.json` sintético con sus propios localizadores, que no tienen nada que ver con los de Copilot. La sirve `http.server` en la interfaz de loopback con puerto libre; la página de login se sirve con otro nombre de host de loopback (la dirección numérica frente a `localhost`), que el navegador trata como otro host. Si el guardián del repo público rechaza direcciones IP literales, el código las obtiene con `socket` en vez de escribirlas. El servidor cuenta los prompts recibidos (la página los envía por `POST`): ese contador es el oráculo de «exactamente una vez». Parámetros de la URL de la prueba eligen el comportamiento: respuesta en fragmentos, señal que se adelanta, respuesta que no termina, conversación inexistente, redirección a login, cierre del navegador. Los tests con navegador llevan el marcador nuevo `edge` (necesitan Edge instalado; si no está, se omiten con motivo visible) y usan `HARNESS_TEST_HEADLESS=1`; el canal es siempre `msedge`. El marcador `copilot` queda para la demo real.
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
- **`--password-store=basic` y `--use-mock-keychain` (decisión de Wilson, abierta el 2026-11-25).** Playwright las pasa por defecto y hoy se quedan.
  - **Mantenerlas (estado actual):** en macOS las cookies del perfil dedicado, y con ellas la sesión de Copilot, se cifran con una clave fija y conocida en vez de con el llavero del sistema. Cualquiera que pueda leer el directorio del perfil (otro proceso con tu usuario, una copia de seguridad, un disco sin cifrar) puede descifrar la sesión y usarla. A cambio, Edge nunca pide acceso al llavero y la sesión actual sigue valiendo. En Windows no aplican: el cifrado usa DPAPI, ligado a la cuenta del usuario.
  - **Quitarlas:** la sesión queda cifrada con el llavero, como en un Edge normal. Coste: la sesión guardada deja de valer y hay que repetir `copilot login`. macOS puede pedir permiso de llavero la primera vez, y quizá en cada arranque si el binario cambia con una actualización, lo que bloquearía un `ask` sin nadie delante. Habría que medir ese comportamiento (sin envíos) antes de decidir.
