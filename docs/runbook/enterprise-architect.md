# Runbook: sonda de Enterprise Architect

Este runbook es para ti, Wilson, en tu equipo Windows con tu edición de demostración de Enterprise Architect. Responde a la primera pregunta del Corte 5: **¿tu edición deja que un programa la maneje por la Automation Interface (COM)?** Si la respuesta es no, los cortes 5, 6 y 7 se replantean contigo antes de escribir nada más.

Nada de lo que hagas aquí entra en el repo. El detalle se queda en `HARNESS_DATA_DIR` (por defecto `.\data`, ignorado por Git) y lo único que me pegas es el resumen que imprime la sonda.

## Qué hace la sonda y qué no

- Crea **su propia** instancia de EA por COM. No se engancha a un EA que tengas abierto.
- Crea un **modelo nuevo** en una carpeta temporal de Windows (fuera del repo), le añade un paquete, dos elementos, un conector y un diagrama con los dos elementos, lo cierra, lo vuelve a abrir y lo lee por GUID. Al terminar borra esa carpeta.
- Comprueba si se puede crear una **segunda** instancia a la vez, y la cierra.
- Cuenta los procesos `EA.exe` antes y después (con `tasklist`), para saber si al cerrar deja alguno vivo.
- **No abre ningún modelo tuyo**, no cierra ni termina ningún EA que no haya creado ella, no ejecuta SQL y no se conecta a ningún repositorio de servidor.
- Solo trata como suyo un objeto que cumple dos condiciones a la vez: no tiene ningún modelo abierto y, al crearlo, apareció un `EA.exe` nuevo en el recuento.
- Si el objeto que le da Windows resulta ser un EA que ya estaba en marcha, lo suelta sin crear, abrir ni cerrar nada en él y lo apunta (`attached_to_existing: yes`). Eso vale para un EA con un modelo abierto y también para uno **sin** modelo abierto. Revisada el 2026-11-24, tras una revisión independiente: antes, un EA tuyo sin modelo abierto se habría tomado por propio, y la sonda habría creado un modelo en él y lo habría cerrado con `Exit()`.
- Si no puede contar los procesos, no tiene prueba de que el objeto sea suyo y lo suelta igual (`own_instance_unproven: count_unavailable`).

## 0. Antes de empezar

- Windows con Enterprise Architect instalado y abierto **al menos una vez a mano** (para que la prueba esté activada).
- `uv` instalado y el repo clonado. Mejor en una carpeta que **no** esté dentro de OneDrive.
- PowerShell abierto **en la raíz del repo**.
- **Cierra tu EA** para la primera ejecución: así la medida es limpia. (El paso 3 opcional mide qué pasa con un EA abierto.)

No hace falta `uv sync`: la sonda solo usa la biblioteca estándar de Python y `pywin32`, que `uv` añade para esta ejecución sin tocar `uv.lock` ni `pyproject.toml`.

## 1. El comando

```powershell
uv run --with pywin32 python scripts/ea_probe.py
```

Opciones, por si hacen falta:

| Opción | Para qué |
|---|---|
| `--create-timeout 300` | Si EA tarda en arrancar más de 3 minutos (el valor por defecto es 180 s). |
| `--step-timeout 120` | Si algún paso tarda más de 60 s. |
| `--keep-model` | Guarda una copia del modelo sintético que crea en `.\data\ea\` (sirve para las pruebas siguientes; no contiene nada tuyo). |

## 2. Qué vas a ver y cuánto tarda

- Primero, `ea probe: running; ...` en la terminal.
- **No está medido** cuánto tarda; lo esperable es entre unos segundos y un par de minutos, casi todo en arrancar EA. Si un paso se cuelga, la sonda espera como mucho su plazo (3 minutos para arrancar EA, 1 minuto para los demás) y sigue o termina.
- Puede que aparezca una ventana o un **diálogo de EA** (por ejemplo, el aviso de días de prueba). Si aparece, apunta qué tipo de diálogo era (sin captura) y acéptalo para que la sonda siga. Un diálogo así puede bloquear la automatización: es justo una de las cosas que queremos saber.
- No uses las ventanas de EA que abra la sonda.
- Al final imprime el resumen. El código de salida es 0 aunque algún paso haya fallado (eso es un resultado, no un error de la sonda).

Para abortar: `Ctrl+C`. La sonda intenta cerrar su propia instancia, imprime lo que tenga y termina con 130.

## 3. (Opcional) Con tu EA abierto

Solo si el paso 1 funcionó. Abre EA a mano con **un modelo vacío o de ejemplo, nunca uno de la empresa**, déjalo abierto y repite el comando del paso 1. Esto mide si la sonda recibe su propia instancia o la tuya (`attached_to_existing`), y si tu EA sigue vivo al final (`preexisting_still_running`). Tu EA no se debería cerrar; si se cierra, dímelo: es un dato importante.

## 4. Qué me pegas de vuelta

1. El bloque entre `---- ea probe summary (paste only this) ----` y `---- end of summary ----` de cada ejecución. Lleva sí/no, recuentos, tiempos, la versión y la edición de EA como números y códigos de error COM. No lleva rutas, usuario, GUID ni contenido de ningún modelo. Léelo antes de pegarlo.
2. Dos respuestas: ¿apareció alguna ventana o diálogo de EA? (sí/no y de qué tipo) ¿Tenías EA abierto antes de empezar?
3. La versión de EA que ves en *Help > About* (por ejemplo, «17.1, build 1710»), y si es la prueba de 30 días o la edición gratuita de solo lectura.

**No** pegues el fichero `data\ea\probe-*.json` ni capturas de pantalla.

## Cómo leer el resumen (orientativo)

| Línea | Qué significa |
|---|---|
| `pywin32: no import_error` | `uv` no pudo instalar `pywin32` para tu Python. Pégame el error de `uv`. |
| `create_repository: FAIL class_not_registered` | EA no está registrado para COM en esta cuenta. Prueba a abrir EA una vez a mano y repite. |
| `create_repository: FAIL server_exec_failure` o `TIMEOUT` | EA no arrancó por COM o se quedó esperando (¿un diálogo?). |
| `own_instance: yes` | La sonda tuvo su propia instancia, como se quiere. |
| `own_instance: no` con `own_instance_unproven: no_new_process` | Windows le dio un EA que ya estaba en marcha, sin modelo abierto. La sonda no hizo nada con él. Dímelo: es un dato importante para el Corte 5. |
| `own_instance_unproven: count_unavailable` | No se pudo contar `EA.exe`, así que la sonda no probó nada. Pégame el resumen igual. |
| `create_model_qea: FAIL` y `create_model_eapx: yes` | Tu versión crea modelos `.eapx` pero no `.qea` por COM. Es un dato, no un problema. |
| `read_back: yes` con `elements_by_guid: 2` | La lectura por GUID funciona: el Corte 5 es viable. |
| `ea_processes_left_behind: 1` o más | Al cerrar quedó algún `EA.exe` vivo. |

## Si queda un EA.exe vivo

La sonda nunca termina procesos. Si `ea_processes_left_behind` es mayor que 0:

- Si **no** tenías EA abierto antes, cualquier `EA.exe` que veas en el Administrador de tareas es de la sonda: puedes finalizarlo ahí.
- Si **sí** lo tenías, cierra primero tu EA de forma normal (guardando lo tuyo) y después finaliza los `EA.exe` que queden.

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| `ea probe: refused: HARNESS_DATA_DIR is inside a Git work tree and not ignored` | `HARNESS_DATA_DIR` apunta a una carpeta de un repo que podría versionarse. Quita la variable (`Remove-Item Env:HARNESS_DATA_DIR`) para usar `.\data`, o apúntala fuera de cualquier repo. |
| `No solution found when resolving --with dependencies` | `uv` no encuentra `pywin32` para tu Python. Comprueba que estás en Windows y con el Python del proyecto (`uv run python --version` debe decir 3.14). |
| `temp_dir_removed: FAIL` | Algo tenía abierto el modelo temporal (EA, un antivirus). Se puede borrar a mano: la carpeta empieza por `ea-probe-` dentro de `%TEMP%`. |
