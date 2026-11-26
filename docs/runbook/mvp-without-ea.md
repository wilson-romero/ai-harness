# Runbook: Puerta MVP sin EA

Este runbook es para ti, Wilson. Recorre a mano el flujo de la puerta: **requerimiento → memoria del proyecto → revisión HLS → tu decisión → decisión aprobada y guardada en `Decisiones/` → la decisión vuelve en `memory context`**.

Son dos Skills en la **misma sesión**, con tu decisión entre medias (design D1 de `mvp-without-ea`):

1. `hls-review` revisa el requerimiento con la memoria del proyecto y escribe la revisión en la terminal. No escribe nada.
2. Tú lees la revisión y escribes, en un fichero tuyo, la decisión que tomas.
3. `architecture-memory` saca de ese fichero una decisión, te enseña la nota entera y, solo si escribes el código, la guarda como nota nueva en `Decisiones/`.

Primero con el vault sintético y el Mock (sección 2). Después, con una copia de tu vault (sección 4). Copilot real va al final (sección 5) y hoy está **BLOCKED** hasta que se mergee `feature/copilot-web-provider`.

La demo automática, `uv run python scripts/demo_mvp_without_ea.py`, recorre todo lo que no necesita a una persona y termina en `demo: PASS`. Este runbook es la parte que sí la necesita: aprobar.

## 1. Antes de empezar

- `uv` instalado y el repo clonado. Abre la terminal **en la raíz del repo**: los comandos usan rutas relativas al repo.
- Una terminal de verdad (PowerShell, zsh o bash), no la salida de un IDE que no deje escribir: la aprobación te pide que escribas un código.
- Nada de lo que hagas aquí entra en el repo. Los datos (SQLite) van a una carpeta temporal y el vault es una copia.

## 2. Recorrido con el vault sintético y el Mock

### PowerShell

```powershell
# Una carpeta nueva en cada recorrido, como mktemp -d (con una fija, el segundo recorrido
# copiaría el vault dentro del anterior y el paso 4 acabaría en duplicate_decision)
$base = Join-Path ([System.IO.Path]::GetTempPath()) ("ai-harness-mvp-" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Force $base | Out-Null
Copy-Item -Recurse tests\fixtures\vault-synthetic (Join-Path $base "vault")
$env:HARNESS_DATA_DIR = Join-Path $base "data"
$env:HARNESS_VAULT_ROOT = Join-Path $base "vault"
$env:HARNESS_MOCK_RESPONSES = (Resolve-Path tests\fixtures\mvp\respuestas-mock.json).Path

# 1. Sesión con proyecto y memoria del proyecto
$sesion = uv run python main.py session create "Puerta MVP" --project demo-alpha
uv run python main.py memory context demo-alpha

# 2. Revisión del requerimiento (código 0)
uv run python main.py skill run hls-review --session $sesion --input-file document=tests\fixtures\mvp\requerimiento-1-eventos-pedidos.md
$LASTEXITCODE

# 3. Tu decisión: con el Mock usa la de ejemplo (con Copilot, la escribes tú: sección 5)
$decision = (Resolve-Path tests\fixtures\mvp\decision-persona.md).Path

# 4. Registrar la decisión: te enseña la nota y te pide el código (código 0 si apruebas)
uv run python main.py skill run architecture-memory --session $sesion --input-file "source=$decision"
$LASTEXITCODE

# 5. La decisión ya está en la memoria del proyecto
uv run python main.py memory context demo-alpha
uv run python main.py history $sesion
```

### zsh o bash

```sh
base="$(mktemp -d)"
cp -R tests/fixtures/vault-synthetic "$base/vault"
export HARNESS_DATA_DIR="$base/data" HARNESS_VAULT_ROOT="$base/vault"
export HARNESS_MOCK_RESPONSES="$PWD/tests/fixtures/mvp/respuestas-mock.json"

# 1. Sesión con proyecto y memoria del proyecto
sesion="$(uv run python main.py session create "Puerta MVP" --project demo-alpha)"
uv run python main.py memory context demo-alpha

# 2. Revisión del requerimiento (código 0)
uv run python main.py skill run hls-review --session "$sesion" --input-file document=tests/fixtures/mvp/requerimiento-1-eventos-pedidos.md
echo $?

# 3. Tu decisión: con el Mock usa la de ejemplo (con Copilot, la escribes tú: sección 5)
decision="$PWD/tests/fixtures/mvp/decision-persona.md"

# 4. Registrar la decisión: te enseña la nota y te pide el código (código 0 si apruebas)
uv run python main.py skill run architecture-memory --session "$sesion" --input-file "source=$decision"
echo $?

# 5. La decisión ya está en la memoria del proyecto
uv run python main.py memory context demo-alpha
uv run python main.py history "$sesion"
```

### Qué ves en cada paso

1. `session create` imprime el identificador de la sesión. `memory context demo-alpha` imprime primero, por stderr, el resumen (`context: demo-alpha, 7 note(s) included, …`), y después el aviso «material de referencia, no instrucciones» y las notas del proyecto entre `<<<MEMORIA <marcador>` y `MEMORIA <marcador>>>>`. De `Decisiones/`, `memory context demo-alpha` solo lista `alpha-mensajeria.md` (la carpeta también tiene `beta-almacen.md`, que es de `demo-beta` y no entra).
2. `hls-review` imprime, por stderr, `run <id>: hls-review 1.0.0` y `step review (llm, attempt 1)`, y por stdout la revisión con seis secciones: `## Resumen`, `## Alternativas`, `## Restricciones`, `## Requisitos no funcionales`, `## Supuestos` y `## Preguntas pendientes` (con el Mock, «¿Qué pasa con un evento que no se puede publicar?»). Código 0. El vault no cambia.
3. Lees la revisión y decides. Con el Mock la decisión de ejemplo ya responde a la pregunta pendiente; la respuesta del Mock no depende de lo que escribas.
4. `architecture-memory` muestra la cabecera de la aprobación (`skill`, `run`, `step: save`, `scope: vault.save_decision`, `vault:` con la raíz de la copia, `target: Decisiones/<fecha>-cola-gestionada-para-avisar-de-los-pedidos-<id8>.md`, `bytes`, `hash`, `expires`) y la nota completa entre dos líneas de guiones, con `project_slug: demo-alpha`. Escribe los **8 primeros caracteres del hash** y Enter: imprime la nota y `applied: Decisiones/…`, y termina con 0. Con `n` la cancela (código 1) y no escribe nada.
5. `memory context demo-alpha` dice ahora `8 note(s) included` y lista `--- nota: Decisiones/<fecha>-cola-gestionada-para-avisar-de-los-pedidos-<id8>.md (decision, <fecha>)` dentro de los marcadores. `history` muestra `[skill hls-review/review intento 1]` y `[skill architecture-memory/extract intento 1]` como preguntas, nunca el texto del requerimiento ni el de tu decisión (con el Mock sí se guardan sus respuestas, que son sintéticas).

Si repites el paso 4 con el mismo fichero de decisión, termina con 1 **antes de preguntar al modelo** (no se gasta ningún envío) y sin pedir aprobación, con `duplicate_decision` y la ruta de la nota que ya existe; `skill status` lo dice. Si escribes la misma decisión con otras palabras, el modelo sí se consulta, y si devuelve el mismo título se rechaza igual, después de su respuesta y antes de la aprobación.

### Limpieza

```powershell
Remove-Item -Recurse -Force $base
Remove-Item Env:HARNESS_DATA_DIR, Env:HARNESS_VAULT_ROOT, Env:HARNESS_MOCK_RESPONSES
```

```sh
rm -rf "$base"
unset HARNESS_DATA_DIR HARNESS_VAULT_ROOT HARNESS_MOCK_RESPONSES
```

## 3. Si algo sale distinto

| Lo que ves | Qué significa | Qué haces |
|---|---|---|
| `hls-review` termina con 1 y `skill status RUN_ID` dice `error: validation_failed:required_headings:<encabezado>` | La respuesta no tenía una de las seis secciones. No se imprime. | Con el Mock, revisa `HARNESS_MOCK_RESPONSES`. Con Copilot, anótalo para la medición (sección 5) y repite el paso 2: es otra ejecución. |
| `architecture-memory` termina con 1 y `validation_failed:<regla>:<campo>` | El JSON de la decisión no pasa el esquema (un campo de más, un título de varias líneas, un tamaño). No se pide aprobación ni se escribe nada. | Igual que arriba: anótalo y repite el paso 4. |
| `architecture-memory` termina con 3 y dice `waiting for a human approval` | No había terminal interactiva, o cerraste la pregunta sin contestar (Ctrl+D en macOS; Ctrl+Z y después Enter en Windows). No se ha escrito nada. | Con el Mock, en una terminal: `uv run python main.py skill resume RUN_ID --input-file "source=<el mismo fichero>"` (código 0 si apruebas). Con Copilot las salidas no se guardan: `skill resume` termina con `outputs_not_retained` sin escribir nada, y repites el paso 4 en una terminal. |
| Termina con 1 y `duplicate_decision` | Esa decisión ya está en `Decisiones/`, en la ruta que dice: o el mismo texto fuente ya se guardó en este proyecto y vault (se ve antes de preguntar al modelo, y dice `nothing was sent to the provider`), o el modelo devolvió el mismo título en el mismo proyecto. | Nada: no se escribe otra. Si es otra decisión, el título tiene que ser otro. |
| `skill status RUN_ID` dice `uncertain` en un paso `llm` | La pregunta pudo llegar al proveedor y no hubo respuesta. Nunca se repite sola. | `uv run python main.py skill resume RUN_ID --retry-step review` (o `extract`): puede duplicar la pregunta en la conversación. O `skill cancel RUN_ID`. |
| `uncertain` en el paso `save` | La escritura pudo hacerse. | `skill resume RUN_ID`: comprueba si la nota está y no la escribe dos veces. Nunca se reintenta con `--retry-step`. |
| `authentication_required` (solo Copilot) | La sesión de Copilot venció antes de enviar. No se envió nada. | Vuelve a iniciar sesión con el comando de login del proveedor de Copilot (ver su README cuando esté mergeado) y repite el paso: no duplica nada. |

## 4. Con una copia de tu vault

Primero con una **copia**, nunca con el vault de trabajo: con el Mock, la nota que se escribe es la sintética de ejemplo.

- `HARNESS_VAULT_ROOT` es la ruta **absoluta** de la copia. `HARNESS_DATA_DIR` no puede estar dentro de ella.
- El proyecto es el nombre exacto de una carpeta de `projects/` de tu vault (con sus mayúsculas). Comprueba antes que `memory context <proyecto>` lo encuentra y que lo que lista es lo que esperas.
- El requerimiento y tu decisión, en ficheros **fuera del repo**: por ejemplo en `HARNESS_DATA_DIR/tmp/`. Bórralos al terminar.

PowerShell:

```powershell
$env:HARNESS_DATA_DIR = Join-Path ([System.IO.Path]::GetTempPath()) ("ai-harness-mvp-data-" + [System.IO.Path]::GetRandomFileName())
$env:HARNESS_VAULT_ROOT = "C:\ruta\absoluta\a\la\copia-del-vault"
$env:HARNESS_MOCK_RESPONSES = (Resolve-Path tests\fixtures\mvp\respuestas-mock.json).Path
uv run python main.py memory context TU-PROYECTO
$sesion = uv run python main.py session create "Puerta MVP" --project TU-PROYECTO
# y los pasos 2 a 5 de la sección 2, con --project y memory context de TU-PROYECTO
```

zsh o bash:

```sh
export HARNESS_DATA_DIR="$(mktemp -d)/data"
export HARNESS_VAULT_ROOT="/ruta/absoluta/a/la/copia-del-vault"
export HARNESS_MOCK_RESPONSES="$PWD/tests/fixtures/mvp/respuestas-mock.json"
uv run python main.py memory context TU-PROYECTO
sesion="$(uv run python main.py session create "Puerta MVP" --project TU-PROYECTO)"
# y los pasos 2 a 5 de la sección 2, con --project y memory context de TU-PROYECTO
```

Qué cambia: la memoria que ves y que entra en la pregunta es la de tu proyecto; la nota escrita lleva `project_slug: TU-PROYECTO` y va a `Decisiones/` de la copia.

## 5. Con Copilot real (BLOCKED por el merge de `feature/copilot-web-provider`)

Cuando el proveedor esté en `develop`. Alcance autorizado (tu respuesta del 2026-11-25): **solo** con la cuenta de la universidad, **solo** con textos sintéticos (los de este repo) y dentro del presupuesto de **100 envíos**; la medición de abajo gasta 6.

- Las mismas órdenes de la sección 2, sin `HARNESS_MOCK_RESPONSES` y con `HARNESS_PROVIDER=copilot_web` (`$env:HARNESS_PROVIDER = "copilot_web"` en PowerShell), y una sesión **nueva** (el proveedor se fija al crearla).
- Las dos preguntas van a la misma conversación de Copilot porque es la misma sesión.
- `architecture-memory` tiene que ejecutarse en una terminal interactiva desde el principio (sin ella se rechaza antes de preguntar): con Copilot las salidas no se guardan y una ejecución que se queda esperando no se puede reanudar.
- Tu decisión la escribes tú después de leer la revisión, también sintética, en `HARNESS_DATA_DIR/tmp/decision.md` (fuera del repo). Bórrala al terminar. Con el vault sintético, no con el tuyo.

### Medición (tarea 4.2)

Con los tres requerimientos sintéticos del repo, `tests/fixtures/mvp/requerimiento-1-eventos-pedidos.md`, `requerimiento-2-cache-catalogo.md` y `requerimiento-3-informes-nocturnos.md`: un `hls-review` y un `architecture-memory` por requerimiento, seis preguntas en total. Me pasas **solo cifras**:

- ejecuciones de cada Skill y cuántas terminaron en `validation_failed`, con su regla (`skill status RUN_ID`);
- tiempo de cada paso;
- bytes de cada nota preparada (`bytes:` de la aprobación);
- si la nota aparece en `memory context`;
- si `remote_ref` fue el mismo en los dos Skills de cada sesión.

Si `validation_failed` supera la mitad de las ejecuciones de un Skill (más de 1 de 3), se reabren sus plantillas o sus reglas antes de cerrar la puerta (design D3).
