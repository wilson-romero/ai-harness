# Runbook: Copilot Web, perfil dedicado y sonda

Este runbook es para ti, Wilson, en tu equipo y con tu login. Nada de lo que hagas aquí entra en el repo: las mediciones se quedan en `HARNESS_DATA_DIR` y lo único que copias de vuelta son los resúmenes que imprime la sonda.

Un solo camino: **`login` → `measure` → `login-state`**. La sonda encuentra sola los controles de Copilot; codegen solo hace falta si ella te pide un control concreto (anexo).

## Qué hace la sonda y qué no

- Abre **Microsoft Edge instalado** con un **perfil dedicado** al harness, nunca con tu perfil personal ni con el de trabajo habitual.
- Envía **solo prompts sintéticos fijos** que lleva en el código (pedir «OK», contar hasta 60 o 300, una lista con código, cada uno con un marcador `ZQX-END-n`, y rellenos sin sentido de 2 000 a 32 000 caracteres que piden `LEN-OK`). No acepta un prompt tuyo por ningún sitio.
- **Deja conversaciones sintéticas en tu historial** (unas cinco). Puedes borrarlas a mano.
- Guarda en `HARNESS_DATA_DIR/copilot/` localizadores de controles, la *forma* de la URL de una conversación (dónde va el identificador, nunca el identificador), hosts del login, recuentos, tiempos y sí/no. **No** guarda la URL, tu cuenta, títulos ni respuestas, y no hace capturas, trazas, HAR ni vídeo.
- **Nunca escribe tu usuario ni tu contraseña**: el login lo haces tú en la ventana de Edge.

## 0. Preparación (una vez por terminal)

Edge instalado con el instalador normal. **No ejecutes `playwright install`**: sobrescribe el Edge del sistema. En la raíz del repo, `uv sync`. Todos los comandos se ejecutan desde la raíz del repo.

Elige una carpeta de datos **fuera del repo** y la URL del chat de Copilot. `https://copilot.cloud.microsoft/chat` es la dirección pública del chat de Microsoft 365 Copilot y sirve de ejemplo; si en tu empresa entras por otra, usa esa. **Pon la ruta del chat, no la raíz del host**: la raíz (`https://copilot.cloud.microsoft/`) enseña la portada de invitado, con su propio cuadro de preguntas y un botón de iniciar sesión, aunque la sesión sea válida (comprobado en macOS el 2026-11-24). La sonda no tiene URL por defecto: así nunca abre una página que no elegiste.

PowerShell (Windows):

```powershell
$env:HARNESS_DATA_DIR = "$HOME\ai-harness-data"
$env:HARNESS_COPILOT_URL = 'https://copilot.cloud.microsoft/chat'
```

POSIX (macOS):

```sh
export HARNESS_DATA_DIR="$HOME/ai-harness-data"
export HARNESS_COPILOT_URL='https://copilot.cloud.microsoft/chat'
```

No actives `DEBUG=pw:api`: Playwright escribiría en la terminal textos de la página.

## 1. Login a mano

```powershell
uv run python scripts/copilot_probe.py login
```

(Igual en macOS.) Se abre Edge con el perfil dedicado (`HARNESS_DATA_DIR/edge-profile`). Inicia sesión: cuenta, contraseña, MFA. **Si pregunta «¿Mantener la sesión iniciada?», responde Sí**: si no, la sesión se pierde al cerrar Edge y el paso 2 verá la página de invitado. Cuando veas Copilot listo para escribir, vuelve a la terminal y pulsa **Enter**.

El resumen trae una línea `ready page:` sobre la página donde pulsaste Enter, con `ready path`: la primera parte de la ruta (`/chat`), nunca un identificador. Si dice `on configured host no`, Copilot quedó listo en otro host: pon en `HARNESS_COPILOT_URL` esa dirección (esquema, host y ruta, **sin** identificadores ni lo que va tras `?`) y repite este paso. Si `signed-out hints` no es 0, esa página aún ofrece iniciar sesión.

**Si un paso dice «opens Copilot's guest page»**: la URL configurada lleva a la portada de invitado. Si ya iniciaste sesión, el mensaje propone la dirección del chat (`set HARNESS_COPILOT_URL=…/chat`), tomada de la ruta donde Copilot quedó listo en el último `login`; ponla y repite el paso. Si no iniciaste sesión, repite el paso 1. El comando del producto `copilot login` hace la misma comprobación: si Copilot quedó listo en otra ruta, vuelve a abrir la URL configurada y, si es la portada de invitado, termina con ese mensaje (la sesión queda guardada).

Si el resumen dice `P1 controllable: no`, Edge no se deja controlar en tu equipo: para ahí y pégame el resumen. `not measured` significa que lo interrumpiste antes de medirlo: repite el paso.

## 2. Medir

```powershell
uv run python scripts/copilot_probe.py measure
```

Sin que toques nada:

1. **Encuentra los controles** (la primera vez): abre Copilot, escribe el prompt fijo 1 en el editor y lo envía con Enter; mira qué elemento repite tu mensaje, cuál contiene la respuesta, qué controles aparecen y desaparecen mientras responde, y comprueba con el prompt fijo 2 que cuenta bien los turnos. Después prueba el botón de nueva conversación y solo lo acepta si deja el hilo vacío y cambia la URL. Son **2 envíos**; lo guarda en `discovered.json` y no lo repite en siguientes `measure`.
2. **Mide**: tres conversaciones nuevas con 4 prompts fijos cada una (**12 envíos**), comparando cada señal de fin de respuesta con el momento real en que la respuesta deja de cambiar; vuelve a abrir cada conversación tras cerrar Edge; y prueba tamaños de prompt (hasta 4 envíos).

Calcula **entre 10 y 20 minutos**. Puedes mirar, pero no escribas ni pulses en esa ventana. Para abortar, `Ctrl+C`: Edge se cierra y el resultado queda marcado `INTERRUPTED`.

Si la sonda dice que **no encontró** algo, nombra cada control que falta con una línea de qué hacer. Haz solo eso (anexo) y repite `measure`: no vuelve a descubrir lo demás. Si dice que la página **parece sin sesión** (ofrece iniciar sesión), no ha escrito nada: repite el paso 1.

## 3. Cómo se ve un login vencido

```powershell
uv run python scripts/copilot_probe.py login-state
```

Abre Edge con un **perfil temporal vacío**. **No inicies sesión**: solo mira por qué hosts pasa la navegación. Luego cierra Edge y borra ese perfil. Con `measure` y `login-state` completos, la sonda escribe `ui.json`, que usará el proveedor.

Después, `uv run python main.py copilot login` es el login del día a día: abre Edge y se cierra solo cuando Copilot está listo.

## 4. Qué me pegas de vuelta

Solo los bloques entre `---- copilot probe summary (paste only this) ----` y `---- end of summary ----` de los pasos 1, 2 y 3. Llevan recuentos, tiempos, sí/no y tipos de localizador; ningún selector, URL ni texto. Léelos antes de pegarlos.

**No** pegues: `candidates.json`, `discovered.json`, `ui.json`, los `probe-*.json`, los `structure-*.txt`, la URL ni capturas.

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| `the page looks signed out` | Repite el paso 1 y elige mantener la sesión iniciada. Si además dice `opens Copilot's guest page`, pon la dirección que propone. |
| `measure` termina con `missing: max_prompt_chars` | `uv run python scripts/copilot_probe.py sizes` mide solo los tamaños (hasta 4 envíos), sin repetir los 12 envíos. |
| `discovery could not find: …` | Anexo, solo para lo que nombra. |
| `the harness browser is in use by another command` | Otro comando del harness tiene el navegador abierto. Espera. |
| `the dedicated Edge profile is already open in another Edge window` | Cierra la ventana de Edge que usa el perfil dedicado (codegen u otra) y repite. El harness no cierra ventanas que no abrió. |
| `... is not an ai-harness Edge profile` | `HARNESS_EDGE_PROFILE` apunta a una carpeta que no es del harness. |
| `... could be committed` | `HARNESS_DATA_DIR` está dentro de un repo Git y no ignorado. Cámbialo. |
| `the Copilot page was not ready in time` | Sesión caducada: paso 1. |
| Edge se abre pero cada pestaña muestra un error de página («Vaya…», código de error del proceso), o `could not be started` al lanzar | El harness lanza Edge **con su sandbox activado** (antes Playwright lo desactivaba y Edge avisaba de una opción no admitida). Comprobado solo en macOS: en Windows una política de la empresa o un antivirus podrían impedir el sandbox. No lo desactives tú: para ahí y pégame el resumen o el mensaje. |
| ¿Quién puede usar la sesión guardada? | En macOS, cualquiera que pueda leer la carpeta del perfil dedicado: Playwright guarda las cookies con una clave fija, no con el llavero (`--password-store=basic`, `--use-mock-keychain`; se mantienen por tu decisión del 2026-11-25 para no perder la sesión, ver `SECURITY.md`). Quien lea esa carpeta puede descifrar las cookies y usar tu sesión. Mantén `HARNESS_DATA_DIR` en un disco local, legible solo por tu usuario y fuera de carpetas sincronizadas. El harness deja la carpeta del perfil en permisos 0700 (solo tu usuario). En Windows la clave fija no aplica (DPAPI). |
| La interfaz de Copilot cambió y `measure` falla | `uv run python scripts/copilot_probe.py discover` vuelve a encontrar los controles (2 envíos). |

Para diagnosticar sin enviar nada, `uv run python scripts/copilot_probe.py structure` guarda en `HARNESS_DATA_DIR/copilot/structure-*.txt` la estructura de la página **sin ningún texto** (etiquetas, roles, atributos con valores sustituidos por su longitud) y en el resumen cuenta editores, botones, diálogos y marcas de página sin sesión.

## Anexo: si la detección automática falla

Solo para el control que la sonda nombró. Cierra antes cualquier Edge con el perfil dedicado.

PowerShell:

```powershell
uv run playwright codegen --channel msedge --target python `
  --user-data-dir "$env:HARNESS_DATA_DIR\edge-profile" --output "$env:HARNESS_DATA_DIR\copilot\codegen.py" $env:HARNESS_COPILOT_URL
```

POSIX:

```sh
uv run playwright codegen --channel msedge --target python \
  --user-data-dir "$HARNESS_DATA_DIR/edge-profile" --output "$HARNESS_DATA_DIR/copilot/codegen.py" "$HARNESS_COPILOT_URL"
```

No añadas `--save-har` ni `--save-storage`. Con **Pick locator** del Inspector pasa el ratón por el control y copia el localizador. No pulses en la barra lateral ni en tu cuenta. Cierra Edge y el Inspector.

Escribe **solo esa entrada** en `HARNESS_DATA_DIR/copilot/candidates.json`; lo demás sigue saliendo de `discovered.json`. Ejemplo con valores inventados:

```json
{"new_conversation": {"role": "button", "name": "Nuevo chat", "exact": true}}
```

| Codegen imprime | En `candidates.json` |
|---|---|
| `get_by_role("button", name="Enviar")` | `{"role": "button", "name": "Enviar", "exact": true}` |
| `get_by_test_id("algo")` | `{"test_id": "algo"}` |
| `get_by_label("Mensaje")` | `{"label": "Mensaje"}` |
| `get_by_placeholder("Escribe")` | `{"placeholder": "Escribe"}` |
| `locator("css")` | `{"css": "css"}` |

Nombres de entrada: `composer` (editor), `send` (botón de enviar; con `"send_with": "enter"` no hace falta), `new_conversation`, `user_turn` (debe marcar **todos** tus mensajes), `assistant_turn` (**todas** las respuestas), y opcionales `stop`, `response_done_control` (dentro de la respuesta), `busy_region`, `login_indicator`. **Nunca** pongas en un localizador texto de una respuesta, un título de conversación, tu nombre, tu correo, el nombre de la empresa ni la URL; los nombres de controles («Enviar», «Copiar») sí valen. Una entrada mal escrita hace que la sonda se niegue y diga cuál.

## 5. Preguntar a Copilot desde el harness

Requisitos: los pasos 0 a 2 hechos en esta máquina (perfil con la sesión iniciada y `ui.json` completo en `HARNESS_DATA_DIR/copilot/`). Cada `ask` abre una ventana de Edge con el perfil dedicado, escribe la pregunta, espera la respuesta, la imprime y cierra **solo esa** ventana. No toques esa ventana mientras trabaja; tu Edge personal no se toca.

POSIX (macOS), en la misma terminal del paso 0:

```sh
export HARNESS_PROVIDER=copilot_web
export HARNESS_REQUEST_TIMEOUT_S=60     # opcional; la sonda propone un valor (paso 2)
uv run python main.py session create "Prueba Copilot"
# copia el identificador que imprime:
uv run python main.py ask SESSION_ID "Responde solo con la palabra ALFA."
uv run python main.py history SESSION_ID
```

PowerShell (Windows):

```powershell
$env:HARNESS_PROVIDER = "copilot_web"
$env:HARNESS_REQUEST_TIMEOUT_S = "60"
uv run python main.py session create "Prueba Copilot"
uv run python main.py ask SESSION_ID "Responde solo con la palabra ALFA."
uv run python main.py history SESSION_ID
```

**Segundo proceso, misma conversación:** abre otra terminal, repite las variables del paso 0 y `HARNESS_PROVIDER`, y pregunta en la misma sesión:

```sh
uv run python main.py ask SESSION_ID "Responde solo con la palabra BETA."
```

La pregunta llega a la misma conversación de Copilot (lo verás en Edge). La primera pregunta de una sesión tarda unos segundos más que la respuesta: Copilot asigna el identificador de la conversación después de responder, y el harness lo espera hasta 10 s.

Qué significa cada resultado:

| Lo que ves | Qué pasó y qué hacer |
|---|---|
| La respuesta por stdout, código 0 | `completed`. |
| `ended as authentication_required` | La sesión de Copilot caducó. No se escribió nada. `uv run python main.py copilot login`, inicia sesión y repite la pregunta. |
| `ended as uncertain` | La pregunta salió y la respuesta no terminó a tiempo (o se cerró Edge). **No se reenvía nunca.** Mírala en Edge. La siguiente pregunta de esa sesión avisa si la conversación tiene más turnos de los completados. |
| `ended as timeout` … `not ready in time` | La página no estuvo lista a tiempo; no se envió nada y la sesión sigue igual. Repite; si persiste, paso 1. |
| `ended as failed` … `Create a new session` | La conversación de la sesión ya no existe en Copilot. No se envió nada y la sesión queda `closed`. Crea una sesión nueva. |
| `session … is closed` | Esa sesión ya no acepta preguntas. Crea una nueva. |
| `warning: … identifier did not reach the address in time` | Copilot respondió, pero la sesión se quedó sin conversación; la siguiente pregunta empezará otra, sin el contexto. |
| `the prompt has N characters; the most Copilot takes here is M` | Prompt demasiado largo. No se abrió Edge ni se registró nada. |
| `the harness browser is in use by another command` | Otro `ask` tiene Edge abierto: espera y repite. |
| `did not finish … the harness stopped itself` (código 124) | Último recurso: algo bloqueó el proceso más allá del plazo y de su limpieza. El comando siguiente deja esa pregunta en `uncertain`; nada se reenvía. |

`history` de una sesión de Copilot muestra el identificador de su conversación y, por solicitud, su estado y su hora (UTC), **sin texto**: la base de datos del harness no guarda preguntas ni respuestas de Copilot. El perfil dedicado es un perfil de navegador: Edge guarda en él caché, IndexedDB, historial y cookies, y ahí puede quedar texto de las conversaciones (ver `SECURITY.md`, «Qué queda en disco»).

Desde el 2026-11-26, `ui.json` admite `locators.code_language` (`css` o `test_id`): el elemento de la cabecera de un bloque de código que lleva la etiqueta del lenguaje. Sin él, los bloques de código salen sin lenguaje y un Skill que espera un bloque `json` no lo encuentra. Lo mide la sonda sin enviar nada, sobre una sesión cuya conversación ya muestra un bloque de código (por ejemplo, la de una pregunta que pidió un bloque `json`):

```
uv run python scripts/copilot_probe.py code-language --session SESSION_ID
```

Busca por estructura el elemento con `data-testid` que lleva la etiqueta de cada bloque, comprueba que con él el bloque sale con lenguaje y sin él sin lenguaje, y lo añade a `ui.json` (el anterior queda como `ui-<fecha>.json`). Un `measure` posterior lo conserva. Sin bloque de código en esa conversación, termina con `missing: code_language` y no cambia nada.

Pruebas reales (opcional, 5 envíos de prompts sintéticos fijos, con ventana): con las variables del paso 0, `uv run pytest -m copilot -p no:cacheprovider`. Sin esas variables se omiten con su motivo.
