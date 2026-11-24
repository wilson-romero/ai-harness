# Runbook: Copilot Web, perfil dedicado y sonda

Este runbook es para ti, Wilson, en tu equipo y con tu login. Nada de lo que hagas aquí entra en el repo: las mediciones se quedan en `HARNESS_DATA_DIR` (por defecto `./data`, ignorado por Git) y lo único que copias de vuelta es el resumen que imprime la sonda.

Sirve igual en macOS y en Windows. Donde los comandos cambian, van las dos versiones: **POSIX** (zsh o bash en macOS) y **PowerShell** (Windows).

## Qué hace la sonda y qué no

- Abre **Microsoft Edge instalado** (el tuyo de siempre como programa) con un **perfil dedicado** al harness, nunca con tu perfil personal ni con el de trabajo habitual.
- Envía a Copilot **solo prompts sintéticos fijos** que lleva dentro del código: pedir «OK», contar de 1 a 60, contar de 1 a 300, una lista con un bloque de código, cada uno terminado en un marcador `ZQX-END-n`, y unos rellenos sin significado de 2 000 a 32 000 caracteres que piden responder `LEN-OK`. No acepta un prompt tuyo por ningún sitio.
- **Deja conversaciones sintéticas en tu historial de Copilot**: tres de la medición y una de tamaños. Puedes borrarlas a mano después.
- Guarda localizadores de controles, la *forma* de la URL de una conversación (en qué posición va el identificador, nunca el identificador), los nombres de host del login, recuentos, tiempos y booleanos. **No** guarda la URL, tu cuenta, títulos de conversaciones ni texto de respuestas, y no hace capturas, trazas, HAR, vídeo ni `storage_state`.
- El harness **nunca escribe tu usuario ni tu contraseña** y no toca el MFA: el login lo haces tú en la ventana de Edge.

## 0. Antes de empezar

- Edge instalado con el instalador normal de Microsoft. **No ejecutes `playwright install`** (ni `playwright install msedge`): sobrescribe la instalación de Edge del sistema.
- En la raíz del repo: `uv sync`.
- Todos los comandos se ejecutan **desde la raíz del repo**.
- No actives `DEBUG=pw:api` mientras uses Copilot real: Playwright escribiría en la terminal los textos que pasan por la página.

Pon la URL con la que abres Copilot en tu trabajo. Solo vive en tu terminal (o en tu `.env` local, que no se versiona); no la pegues en ningún otro sitio.

POSIX:

```sh
export HARNESS_COPILOT_URL='https://...tu URL de Copilot...'
```

PowerShell:

```powershell
$env:HARNESS_COPILOT_URL = 'https://...tu URL de Copilot...'
```

Por defecto los datos van a `./data` y el perfil dedicado a `./data/edge-profile`. Si cambias `HARNESS_DATA_DIR`, que sea una carpeta fuera del repo o ignorada por Git: la sonda se niega a escribir donde Git podría versionar el resultado.

## 1. Perfil dedicado y login manual

```sh
uv run python scripts/copilot_probe.py login
```

(El mismo comando en PowerShell.)

1. Si `./data/edge-profile` no existe, se crea con la marca `ai-harness-profile.txt`. Si apuntas `HARNESS_EDGE_PROFILE` a una carpeta con ficheros y sin esa marca, el comando se niega: así es imposible usar por error tu perfil de siempre.
2. Se abre Edge en la URL de Copilot. Inicia sesión a mano: cuenta, contraseña, MFA, lo que pida tu empresa.
3. Cuando veas Copilot listo para escribir, vuelve a la terminal y pulsa **Enter**. Edge se cierra.

Si cierras la ventana sin pulsar Enter, el paso queda como no confirmado. Si Edge no se deja controlar (una política de la empresa puede impedirlo), el resumen dice `P1 controllable: no`: para ahí y pégame el resumen; no hay que buscar un rodeo.

> `uv run python main.py copilot login` es el comando de login del harness para el día a día. Necesita la medición (`ui.json`) para saber cuándo Copilot está listo, así que solo funciona **después** de la sonda (paso 6). Para el primer login usa este paso 1.

## 2. Descubrir los localizadores con codegen

`playwright codegen` es la herramienta oficial de Playwright para ver localizadores. Se abre con el **perfil dedicado**, que ya tiene tu sesión.

POSIX:

```sh
uv run playwright codegen --channel msedge --target python \
  --user-data-dir data/edge-profile --output data/copilot/codegen.py "$HARNESS_COPILOT_URL"
```

PowerShell:

```powershell
uv run playwright codegen --channel msedge --target python `
  --user-data-dir data\edge-profile --output data\copilot\codegen.py $env:HARNESS_COPILOT_URL
```

No añadas `--save-har` ni `--save-storage`. Se abren dos ventanas: Edge y el Inspector de Playwright. En Edge:

1. Pulsa el editor de mensajes y escribe un prompt sintético, por ejemplo `Responde solo OK`. Envíalo.
2. Mientras responde, fíjate en el botón de detener (no hace falta pulsarlo).
3. Cuando termine, fíjate en un control que aparezca al final de la respuesta (copiar, me gusta).
4. Pulsa «nueva conversación».

Con **Pick locator** del Inspector, pasa el ratón por cada control y copia el localizador que propone. En el campo de localizador del Inspector puedes escribir uno y ver qué resalta en la página: así compruebas que el de «turno de usuario» marca **todos** los mensajes tuyos y el de «turno del asistente» **todas** las respuestas.

No pulses en la barra lateral de conversaciones ni en el menú de tu cuenta: codegen lo apuntaría en `codegen.py`. Ese fichero se queda en `data/`, pero mejor que no contenga nada tuyo.

**Cierra Edge y el Inspector** antes de seguir: el perfil no puede estar abierto dos veces.

## 3. Escribir `candidates.json`

Crea `data/copilot/candidates.json` (en PowerShell, `data\copilot\candidates.json`). Cada localizador se escribe con **una** de estas formas, que salen directas de lo que imprime codegen:

| Codegen imprime | En `candidates.json` |
|---|---|
| `get_by_role("button", name="Enviar")` | `{"role": "button", "name": "Enviar", "exact": true}` |
| `get_by_test_id("algo")` | `{"test_id": "algo"}` |
| `get_by_label("Mensaje")` | `{"label": "Mensaje"}` |
| `get_by_placeholder("Escribe")` | `{"placeholder": "Escribe"}` |
| `locator("css")` | `{"css": "css"}` |

Campos (los cinco primeros son obligatorios):

| Campo | Qué control |
|---|---|
| `composer` | El editor donde escribes el mensaje. |
| `send` | El botón de enviar. |
| `new_conversation` | El botón de nueva conversación. |
| `user_turn` | Un localizador que marque **todos** tus mensajes de la conversación. |
| `assistant_turn` | Un localizador que marque **todas** las respuestas de Copilot. |
| `stop` | Opcional. El botón de detener mientras responde. |
| `response_done_control` | Opcional. Un control que aparece **dentro** de una respuesta cuando termina; se busca dentro de `assistant_turn`. |
| `login_indicator` | Opcional. Algo que solo aparece en la página de login. Si no lo tienes, déjalo fuera: el paso 5 mide los hosts del login. |

Ejemplo de forma (los valores son inventados; pon los tuyos):

```json
{
  "composer": {"role": "textbox", "name": "Mensaje", "exact": true},
  "send": {"role": "button", "name": "Enviar", "exact": true},
  "new_conversation": {"role": "button", "name": "Nuevo chat", "exact": true},
  "user_turn": {"css": "[data-ejemplo='mensaje-usuario']"},
  "assistant_turn": {"css": "[data-ejemplo='mensaje-asistente']"},
  "stop": {"role": "button", "name": "Detener", "exact": true},
  "response_done_control": {"role": "button", "name": "Copiar"}
}
```

**Qué no se escribe nunca en un localizador:** texto de una respuesta, el título de una conversación, tu nombre, tu correo, el nombre de la empresa o del tenant, ni la URL. Los nombres de controles («Enviar», «Copiar») sí valen. Si un localizador solo funciona con algo de eso, busca otro (rol, `data-testid`, `aria-label` del control).

Un campo de más o mal escrito hace que la sonda se niegue y diga cuál.

## 4. Medir

```sh
uv run python scripts/copilot_probe.py measure
```

(El mismo comando en PowerShell.)

Qué pasa, sin que toques nada:

- Abre Edge **tres veces**, una conversación nueva en cada una, y envía los **4 prompts fijos**: **12 envíos**. Durante cada respuesta mira la página cada 100 ms y compara las señales candidatas de fin de respuesta (botón de detener que desaparece, botón de enviar disponible, control de fin, `aria-busy`, texto estable 1/2/4 s) con la verdad: el momento en que la respuesta contiene su marcador `ZQX-END-n` y deja de cambiar.
- Cierra Edge y vuelve a abrir cada una de las tres conversaciones por su URL para ver si se recupera y cuántos de tus mensajes se ven.
- Abre una cuarta conversación y prueba tamaños de prompt (2 000, 8 000, 16 000 y 32 000 caracteres de relleno); para en el primero que el editor no acepte entero o que no se responda.

Calcula **entre 10 y 20 minutos** (estimación: depende de lo que tarde Copilot en responder; contra las páginas sintéticas de prueba tarda menos de un minuto). Puedes mirar, pero no escribas ni pulses en esa ventana.

**Para abortar:** `Ctrl+C` en la terminal. Edge se cierra, el resultado se guarda marcado como incompleto (`INTERRUPTED`) y no se escribe `ui.json`. Si cierras la ventana de Edge a mano, pasa lo mismo con un error.

Si dice que la página no está lista, la sesión ha caducado: repite el paso 1.

## 5. Cómo se ve un login vencido

```sh
uv run python scripts/copilot_probe.py login-state
```

(El mismo comando en PowerShell.)

Abre Edge con un **perfil temporal vacío**, sin tu sesión, en la URL de Copilot. **No inicies sesión**: solo mira por qué hosts pasa la navegación y si aparece el editor o el indicador de login. Espera como mucho `HARNESS_COPILOT_READY_TIMEOUT_S` (60 s por defecto), cierra Edge y borra el perfil temporal.

Cuando `measure` y `login-state` están completos, la sonda escribe `data/copilot/ui.json` (el anterior, si lo hay, se renombra con su fecha). Es lo que usará el proveedor.

## 6. Comprobar el login del harness

```sh
uv run python main.py copilot login
```

(El mismo comando en PowerShell.)

Con `ui.json` ya escrito, abre Edge con el perfil dedicado y se cierra solo en cuanto Copilot está listo (código 0). Si la sesión ha caducado, inicia sesión en esa ventana y se cierra solo al terminar. Si cierras la ventana sin iniciar sesión, termina con código 1 y «not signed in». Este es el comando para renovar el login cuando caduque.

## 7. Qué me pegas de vuelta

Solo los bloques entre `---- copilot probe summary (paste only this) ----` y `---- end of summary ----` de los pasos 1, 4 y 5. Llevan recuentos, tiempos, sí/no, versión de Edge y plataforma; nada del tenant. Antes de pegarlos, léelos.

**No** pegues ni subas: `codegen.py`, `candidates.json`, `ui.json`, los `probe-*.json`, la URL, capturas de pantalla ni mensajes de error de Playwright (pueden contener la URL de tu tenant; la sonda lo avisa).

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| `the harness browser is in use by another command` | Otro comando del harness tiene el navegador abierto. Espera a que termine. |
| `the dedicated Edge profile is already open in another Edge window` | Hay una ventana de Edge (codegen, o una que abriste a mano) usando el perfil dedicado. Ciérrala y repite. El harness no cierra ventanas que no abrió. |
| `... is not an ai-harness Edge profile` | `HARNESS_EDGE_PROFILE` apunta a una carpeta que no es del harness. Usa una nueva o vacía. |
| `... could be committed` | `HARNESS_DATA_DIR` está dentro de un repo Git y no ignorado. Cámbialo. |
| `the Copilot page was not ready in time` | Sesión caducada o `composer` mal elegido. Repite el paso 1; si sigue, revisa `composer` en codegen. |
| `no candidates.json` / `candidates.json is not valid` | Paso 3: falta el fichero o tiene un campo mal escrito (el error dice cuál). |
| `P1 controllable: no` | Edge no se deja automatizar en tu equipo. Para y pégame el resumen. |

## Cuando exista el proveedor (grupos 4 y 5 del change)

El proveedor `copilot_web` todavía no está implementado: depende de lo que mida esta sonda. Su diseño (`openspec/changes/copilot-web-provider/design.md`) fija ya estas conductas, que este runbook detallará cuando lleguen:

- `authentication_required`: la sesión de Copilot caducó y no se envió nada. Ejecuta `copilot login` y repite la pregunta.
- «perfil en uso»: como en la tabla de arriba.
- Sesión `closed`: la conversación remota ya no se encuentra; crea una sesión nueva.
- `uncertain`: venció el plazo después de enviar; la pregunta pudo llegar. El harness no la reenvía; mírala en Edge.
