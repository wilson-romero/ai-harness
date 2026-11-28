# Runbook: herramientas de la carpeta de trabajo (tramos B1 y B2)

El harness lee ficheros de una **carpeta de trabajo** que tú eliges: desde la CLI (B1, `main.py workspace … --root`) y desde la conversación (B2, `/workspace`), donde `/plan` y `/agent` la leen con `workspace.read` y `workspace.list`. Todavía no hay escrituras. Diseño: `openspec/changes/workspace-tools/design.md`.

## Las órdenes

```sh
uv run python main.py workspace check --root <carpeta>
uv run python main.py workspace read <ruta-relativa> --root <carpeta> [--offset N] [--limit N]
uv run python main.py workspace list [<carpeta-relativa>] --root <carpeta> [--depth 1..3]
```

- `--root` es obligatorio en cada orden. No hay variable de entorno ni valor por defecto.
- **Salida:**
  - por stdout va el texto del fichero o el listado, cada línea tras `| `, como `mcp call`;
  - por stderr van las líneas del harness: el resumen, los rechazos y los avisos. Nunca llevan texto del fichero.
- **Códigos de salida:**
  - `0`: hecho;
  - `1`: rechazado, con la línea `error: refused: <motivo>: …`;
  - `2`: mal uso (un rango fuera de límites).

## Qué carpeta se acepta

Se rechazan, con su motivo:
- una ruta que no es absoluta (`not_absolute`);
- una que no existe (`root_not_found`);
- un fichero (`not_a_directory`);
- un enlace o una unión (`link`);
- el repo del harness, el directorio de datos o el vault: siendo ellos, estando dentro o conteniéndolos (`harness_repo`, `data_dir`, `vault`);
- la carpeta personal misma (`home`);
- la raíz del sistema (`filesystem_root`).

Una carpeta bajo un enlace del sistema (en macOS, `/tmp` → `/private/tmp`) se acepta y se muestra resuelta.

## Qué ruta se acepta

Solo rutas relativas con `/`. Se rechazan, sin abrir nada y igual en macOS y en Windows:
- `..` y `.`;
- `/x`, `C:\x`, `C:x` y `\\servidor\x`;
- `\` y `:` (unidades y flujos alternativos);
- `<>"|?*`;
- invisibles y controles;
- lo que no está en NFC;
- un componente que acaba en punto o en espacio;
- los nombres reservados de Windows (`CON`, `NUL`, `COM1`, `con.txt`…);
- más de 1 024 caracteres, o más de 255 bytes en un componente.

Cada componente tiene que llamarse **exactamente** como lo lista su carpeta, así que `src/App.py` no abre `src/app.py`. Ningún componente puede ser un enlace ni una unión. Tampoco se abre un fichero con dos enlaces duros. Si el fichero cambia entre la comprobación y la apertura, se rechaza (`changed`).

## Lo que nunca se lee

Hay dos grupos de reglas:
- **Por nombre:** `.git/`, `.ssh/`, `.aws/` y los demás componentes de la lista; `.env` y `.env.*` (salvo `.env.example`, `.env.sample` y `.env.template`); `.npmrc`, `.netrc` y `.pypirc`; `id_rsa*`; `*.pem`, `*.key`, `*.p12` y el resto de la lista de `harness/workspace/rules.py`.
- **Por contenido o tamaño:** un fichero con una credencial de forma conocida (`credential_in_file`), un binario o un fichero que no es UTF-8 (`binary`) y uno de más de 256 KiB (`too_large`).

**Lo que esto NO protege.** Un secreto con forma desconocida dentro de un fichero normal (una contraseña en `config.py`) se lee y se muestra. En B1 no sale de tu máquina: no hay bucle ni proveedor.

## Cómo se ve un fichero

`read` da 200 líneas por defecto y 400 como máximo. Cada línea va numerada, cortada a 500 caracteres, y la salida no pasa de 16 KiB. Todo carácter invisible o de control se escribe como `<U+XXXX>`, también el tabulador y ESC. Una secuencia de escape o un carácter bidi se ve, no actúa. Las credenciales se enmascaran.

`list` no sigue enlaces ni abre ficheros. Marca `[link]`, `[denied: …]` y `[unusable name: …]`, y no pasa de 500 entradas.

## Auditoría

Cada `read` o `list` deja dos filas:
- una en `tool_calls` (`server = 'workspace'`), con el HMAC de los argumentos;
- otra en `workspace_events`, con el motivo exacto y el HMAC de la ruta.

Ninguna guarda una ruta, un nombre ni texto del fichero. El texto leído no se guarda en ninguna parte.

## Probarlo con la carpeta sintética

```sh
w="$(mktemp -d)"
uv run python -c 'import importlib.util,sys; s=importlib.util.spec_from_file_location("b","tests/fixtures/workspace/build.py"); m=importlib.util.module_from_spec(s); sys.modules["b"]=m; s.loader.exec_module(m); print(m.build(__import__("pathlib").Path(sys.argv[1])/"base").root)' "$w"
export HARNESS_DATA_DIR="$w/data"
root="$w/base/demo-alpha"
uv run python main.py workspace check --root "$root"
uv run python main.py workspace list --root "$root" --depth 2
uv run python main.py workspace read src/app.py --root "$root" --offset 4 --limit 2
uv run python main.py workspace read hostile.txt --root "$root"
uv run python main.py workspace read .env --root "$root"; echo "código $?"
uv run python main.py workspace read ../outside/secret.txt --root "$root"; echo "código $?"
uv run python main.py workspace read src/App.py --root "$root"; echo "código $?"
uv run python main.py workspace read README.md --root "$PWD"; echo "código $?"
```

La demo completa, con todos los casos negativos, es `uv run python scripts/demo_workspace.py` y termina en `demo: PASS`.

## En la conversación (tramo B2)

```text
/workspace                 muestra la carpeta de esta sesión y el consentimiento de envío
/workspace <ruta>          la elige (absoluta; ~/ vale); las mismas reglas que --root
/workspace off             la quita: workspace.read y workspace.list desaparecen del catálogo
/workspace send on|off     da (con su caja) o revoca el consentimiento para este proveedor
```

- La carpeta vale para esta sesión y solo mientras dura el `chat`: no se guarda en la base de datos. `/new` y `/resume` empiezan sin carpeta. No se puede cambiar con un `/plan` o un `/agent` en marcha (`workspace_busy`).
- Se ve en el panel lateral (`Workspace`) y en `/status` (`workspace: …, send: …`).
- Con carpeta, el catálogo de `/plan` y `/agent` gana dos líneas fijas: `workspace.list(depth, path)` y `workspace.read(limit, offset, path)`. La ruta va relativa a la carpeta, con `/`, como mucho 64 caracteres de `A-Z a-z 0-9 . _ -`. Las dos son lecturas por regla: corren sin caja (salvo `/plan --box` o `HARNESS_AUTO_READ=off`).
- **Consentimiento.** Con el Mock no hace falta. Con un proveedor que no es sintético, `/agent` no envía nada de la carpeta hasta `/workspace send on`, y para con `not sent: no consent for this folder`. Dado el consentimiento, la caja de la primera vuelta con resultados de cada `/agent` se sigue pidiendo. `/workspace send off` lo revoca.
- Si la carpeta se sustituye por otra después de elegirla, queda suspendida (`workspace_changed`) hasta otro `/workspace`.

Probarlo a mano con el Mock (zsh), sin red y en una carpeta temporal:

```sh
d="$(mktemp -d)"
uv run python scripts/demo_workspace.py --prepare "$d"
# copia y ejecuta la línea `HARNESS_DATA_DIR=… uv run python main.py chat` que imprime, y escribe:
#   /workspace <la ruta que imprime>
#   /plan ¿qué hace el módulo de demo?
#   /agent dime ¿qué hace el módulo de demo?
#   /status
```

## Windows

Es el mismo código, sin ramas por plataforma. En Windows queda **NOT RUN** hasta ejecutarlo en el PC de pruebas (`openspec/changes/workspace-tools/tasks.md` 8.1 y 8.2). Las órdenes, en PowerShell:

```powershell
uv run pytest tests/unit/test_workspace_paths.py tests/unit/test_workspace_root.py tests/unit/test_workspace_rules.py tests/unit/test_workspace_output.py tests/unit/test_workspace_audit.py tests/security/test_workspace_confinement.py tests/integration/test_workspace_cli.py tests/unit/test_workspace_shell.py -rs
uv run python scripts/demo_workspace.py
```

Qué hay que mirar allí:
- las uniones de directorio reales: `mklink /J` en `cmd` y después `workspace read` a través de ella;
- `st_nlink` de un enlace duro de NTFS (`mklink /H`);
- un `a.txt:x` y un `NUL` reales: se rechazan por la forma antes de tocar el disco;
- un nombre corto 8.3: `dir /x` lo muestra, y tiene que dar `not_found`;
- una raíz de más de 240 caracteres.

Los tests de enlaces simbólicos se omiten si la cuenta no puede crearlos.
