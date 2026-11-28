# Seguridad

Este repositorio es **público**. El código está pensado para trabajar con sistemas corporativos, pero nada de esos sistemas vive aquí.

## Qué no entra nunca

- Secretos: contraseñas, tokens, claves, cadenas de conexión, cookies o estado de sesión del navegador.
- Datos reales: prompts o respuestas de Copilot, notas del vault de trabajo, modelos de Enterprise Architect (`.qea`, `.eap`, `.eapx`, `.feap`), bases SQLite, logs.
- Lo que identifica a una organización: nombres de empresa, clientes o sistemas, URL de tenant, GUID de modelos reales, correos, rutas personales, direcciones IP.
- Evidencia capturada sobre sistemas reales: capturas de pantalla, trazas, HAR o vídeos de Playwright.

Las pruebas y los ejemplos usan solo datos sintéticos. Lo que se mide sobre un sistema real (selectores, URL, identificadores) se guarda fuera del repo, en `HARNESS_DATA_DIR`.

## Cómo se comprueba

`scripts/check_public_safety.py` rechaza ficheros prohibidos, patrones de secretos, rutas personales, correos, IP y los términos de una lista local. Se ejecuta en tres sitios:

1. **Antes de cada commit**, con el hook de `.githooks/`. Se activa una vez por clon:

   ```sh
   git config core.hooksPath .githooks
   ```

2. **En `scripts/verify.sh`**, que es la puerta antes de un merge.
3. **En GitHub**, con secret scanning y push protection activados en el repositorio.

### Lista local de términos

Los nombres de empresa, clientes y sistemas no se pueden escribir en un repo público ni siquiera para prohibirlos. Van en un fichero **fuera del repo**, un término por línea:

```
~/.config/ai-harness/public-denylist.txt
```

Cada término se compara como palabra completa y sin distinguir mayúsculas. Si un nombre es además una palabra corriente, se escribe con el prefijo `cs:` y la mayúscula exacta (`cs:Nombre`): así solo coincide escrito de esa forma y no marca la palabra en minúscula.

La ruta se puede cambiar con `HARNESS_PUBLIC_DENYLIST`. Si el fichero no existe, el guard lo avisa en cada ejecución: sin él, esos nombres no se están comprobando.

### Excepciones

Una línea revisada a propósito lleva el marcador `public-safety: allow`. Cada uso se justifica en el PR.

## Límites

El guard reconoce formatos conocidos; no detecta un secreto con forma desconocida ni un dato sensible escrito en prosa. No sustituye a leer el diff antes de publicar.

## Aprobaciones de Skills

Una aprobación se concede solo en una terminal interactiva, escribiendo los 8 primeros caracteres del hash de la propuesta o, en la pantalla completa de `chat`, pulsando «Approve» en su caja (desde el 2026-11-27). Se registra el usuario local del sistema operativo que la concedió, y cómo se concedió (`means=code` o `means=button` en la auditoría). **Esa identidad no es una autenticación.**

Se garantiza:

- El código se deriva del contenido exacto que se muestra (y de su destino, la ejecución, el paso y el Skill). Lo mostrado, lo hasheado y lo aplicado son los mismos bytes: sin caracteres de control ni de formato, con los demás invisibles escritos como `<U+XXXX>`; un destino que no se puede mostrar tal cual se rechaza.
- El código, o cualquier parte del hash, solo aparece dentro de la pregunta interactiva, junto al contenido. El mensaje de espera (código 3) y `skill status` muestran el identificador de la aprobación, su estado y su caducidad.
- No se aprueba con stdin redirigido, con el fin de la entrada, con Enter, con una opción de la CLI ni con una variable de entorno; ningún texto de un modelo, nota o fichero aprueba.
- Una aprobación está ligada a una propuesta, caduca (una respuesta después de la caducidad no la concede) y se usa una vez. Un efecto interrumpido se reconcilia antes de seguir y nunca se aplica dos veces.
- En la conversación (`chat`, desde el 2026-11-25) el aviso es el mismo y se contesta en la misma terminal. Una línea escrita en el indicador normal es una pregunta o un comando, nunca una aprobación, aunque sea el código; no hay comando `/approve`, y Ctrl+C en el aviso lo deja sin decidir. Lo prueban `tests/unit/test_shell_skills.py` (con su control negativo) y la terminal real se cubre con la demo manual: no hay pseudoterminal portable para probarla en Windows.

- En la pantalla completa, el botón responde a la misma pregunta del motor, ligado al mismo hash: la caducidad, el uso único y la comprobación antes del efecto son las mismas. La pulsación es un objeto que solo devuelve la caja que se abrió para ese hash; ningún texto (escrito, pegado, de un modelo o de un fichero) lo es, y en texto plano y en la CLI esa vía no existe. Lo que protegen las reglas de la caja:
  - un Enter de más: el foco empieza en la propuesta;
  - lo escrito por adelantado y el clic antes de leer: los botones están deshabilitados el primer medio segundo;
  - aprobar sin haber visto el final: «Approve» espera a que el final se muestre;
  - un pegado: no hay dónde escribir;
  - un rechazo por un clic de más: «Reject» pregunta otra vez;
  - el texto ajeno que dibuja botones: es texto en su recuadro, y los botones reales están fijos abajo.

  Lo prueban `tests/unit/test_shell_tui_buttons.py` y `tests/unit/test_skill_approval_buttons.py`.

**No** se garantiza que haya una persona delante. Un botón no lo cambia: un programa que maneje tu terminal con tu cuenta puede pulsarlo (Tab y Enter, o un clic enviado como secuencia de ratón) igual que podía escribir el código. Un proceso que corre con tu misma cuenta y maneja una pseudoterminal puede leer la propuesta y escribir el código: puede hacerse pasar por ti. Si alguien o algo controla tu cuenta, las aprobaciones no lo detienen. Decidido el 2026-11-24: se acepta este límite para el MVP, también para el efecto que escribe en el vault; un canal más fuerte (un diálogo del sistema operativo, un segundo dispositivo) se abriría con un change propio.

## La única escritura en el vault

El harness lee el vault y no lo copia, sube ni sincroniza. Escribe en él **una sola cosa**: una nota de decisión nueva del Skill `architecture-memory`, con estas condiciones, todas comprobadas por tests:

- Solo como efecto de una aprobación concedida en una terminal, vigente, no usada y cuyo hash coincide con la nota que se muestra; los bytes escritos son exactamente los mostrados.
- Solo en `Decisiones/` directamente bajo la raíz real del vault (`HARNESS_VAULT_ROOT` resuelta). Si esa carpeta es un enlace, una unión, no es una carpeta o sale de la raíz, se rechaza antes de pedir la aprobación. Si falta, se crea solo en la primera escritura aprobada. Un directorio de datos dentro del vault se rechaza, igual que para leer.
- El nombre y el proyecto los calcula el harness (fecha, slug del título, identificador); ningún texto del modelo, de la fuente ni de la memoria elige carpeta, nombre ni proyecto, y ningún valor del frontmatter viene del modelo. El texto del modelo pasa por el saneado y la redacción de credenciales antes de mostrarse.
- El texto del modelo se escribe inerte para Obsidian: `&`, `<`, `` ` ``, `~~`, `%%`, `![`, `[[` y `::` se escriben como entidades HTML (`&amp;`, `&lt;`, `&#96;`, `~&#126;`, `%&#37;`, `!&#91;`, `[&#91;`, `:&#58;`). Eso neutraliza: bloques de código con o sin lenguaje (```` ``` ```` y `~~~`, incluidos `dataview` y `dataviewjs`), código en línea (`` `= …` ``, `` `$= …` ``), Templater (`<% %>`, `<%* %>`), HTML crudo y `<script>`, comentarios `<!-- -->` y `%% %%`, imágenes y embebidos (`![…](…)`, `![[…]]`), enlaces internos `[[…]]` y campos en línea de Dataview `clave:: valor`. Un test por construcción lo comprueba sobre los bytes del fichero escrito. **Supuesto:** ningún plugin instalado actúa sobre otra sintaxis; un plugin con una sintaxis que no está en la lista no está cubierto.
- Nunca sobrescribe, edita, mueve ni borra una nota: el temporal oculto se crea con creación exclusiva y se publica con un enlace duro, que falla si el nombre existe. Solo borra su propio temporal.
- Un proceso que muere a mitad nunca deja dos notas, ni una nota sin una aprobación consumida, ni un temporal que la memoria lea: `skill resume` reconcilia por identificador y SHA-256 sin escribir.
- Con un proveedor real, SQLite guarda de la nota solo su identificador, su SHA-256 y su tamaño.
- `harness/memory/decisions.py` es el único módulo de `harness/memory/` que puede escribir. Lo que prueban los tests, y nada más: (1) estructural: cada primitiva de escritura de ese fichero está en la función donde debe y con un número exacto de apariciones (`os.open` exclusivo, `os.write` y `os.fsync` solo en `_write_temp`; `os.link` una vez en `_publish`; `os.unlink` una vez en `_drop_temp`, que solo borra un nombre con la forma del temporal propio, y una vez en `_take_back`, que solo retira el nombre que `_publish` acaba de publicar y comprobar; `os.mkdir` una vez en `write_decision`), y lo mismo para cada llamada a esas funciones; la mutación con la que la revisión independiente burló la versión anterior (un bucle que borra todos los `.md`, un `os.mkdir` o un `os.open` + `os.write` en otra función) hace fallar el test; (2) de comportamiento: tras una ejecución aprobada, con títulos y textos hostiles (rutas con `../`, nombres reservados, el nombre del temporal, órdenes de borrar), la huella del vault es la de antes más exactamente un fichero nuevo en `Decisiones/`, sin nada borrado ni cambiado; (3) ningún comando `memory …` carga el módulo. No prueban lo que haría un código que cambie esas tablas a la vez que el módulo: eso se ve en el diff del test.

Los límites (sistemas de ficheros sin enlaces duros, otros programas que escriben en el vault a la vez, cortes de luz) están en el README, en [Skills de arquitectura](README.md#skills-de-arquitectura).

## Servidores MCP

Lo que el harness garantiza con un servidor MCP:

- Solo arranca los servidores de tu lista local. Usa la orden exacta que escribiste, sin shell.
- El servidor recibe solo las variables de entorno nombradas en la lista y las básicas para arrancar un proceso.
- El servidor recibe solo los argumentos declarados.
- Toda herramienta que escribe se deniega en este corte.
- El harness no tiene ninguna superficie de entrada: no abre ningún socket que acepte conexiones de otros, y solo habla con sus servidores por los tubos que él mismo crea. Lo que sí pasa en Windows (revisado el 2026-11-25): al arrancar, el bucle de eventos de la biblioteca estándar crea su par de sockets interno con la emulación de `socketpair` de Python, que escucha un instante en `127.0.0.1` con un puerto efímero, acepta una sola conexión, comprueba que es la suya (las direcciones de los dos extremos) y cierra esa escucha antes de devolver el par. En macOS y Linux ese par es un `socketpair` nativo, sin puerto. Lo comprueban estos tests:
  - un audit hook sobre la creación de cada socket (`socket.__new__`) y cada `socket.bind`, en el proceso del harness y en su proceso de sesión, durante un `mcp call`. Solo acepta los sockets cuya pila de llamadas es la del bucle (`_make_self_pipe` de asyncio llamando a `socketpair` o a `_fallback_socketpair` de `socket.py`); la dirección sola no basta: la misma emulación llamada desde otro sitio cuenta como socket ajeno. Corre también con la emulación forzada en macOS, que reproduce la condición de Windows;
  - controles que el oráculo tiene que señalar: un socket atado a `127.0.0.1:0` que escucha, la emulación llamada fuera del bucle y, donde el sistema lo permite, un `listen()` sin `bind` (Windows lo rechaza);
  - uno estructural sobre `harness/mcp/`.

  Lo que no prueban: sockets creados por código nativo que no pase por el módulo `socket` de Python (ninguna dependencia del harness lo hace hoy, pero el hook no lo vería), ni lo que hagan los servidores MCP, que son otros procesos. Durante ese instante de escucha en Windows otro proceso local podría conectarse antes que el bucle; la biblioteca estándar lo detecta al comparar direcciones y falla, así que el comando termina con error y esa conexión nunca llega al harness.

  La autorización de clientes (SEC-09) llegará con el servidor MCP propio, en un corte posterior. Hoy no hay ningún cliente que autorizar.
- Lo que devuelve un servidor (resultados, descripciones, nombres, errores) se trata como datos no confiables:
  - se mide antes de leerlo (también su stderr: se guarda 1 MiB por sesión y pasado 64 MiB se detiene el servidor);
  - nunca se interpreta: el harness no evalúa ningún patrón, formato ni esquema que mande el servidor, y el SDK no valida resultados en el proceso del harness;
  - se sanea y se redacta antes de imprimirlo o auditarlo;
  - sus resultados, descripciones y errores nunca se guardan. Lo único del servidor que se guarda es su stderr, en `HARNESS_DATA_DIR/logs/mcp/` (como mucho 1 MiB escrito, 65 536 líneas y 4 MiB redactados por sesión), línea a línea y con las credenciales de formato conocido ya sustituidas por `[REDACTED:<tipo>]`, aunque un token llegue partido en varias lecturas (revisado el 2026-11-25). Una línea de más de 16 KiB se descarta entera, con una marca: una credencial en ella no se escribe, y el resto de esa línea tampoco. Una clave PEM se sustituye por una marca y sus líneas se descartan hasta la línea END, como mucho 32 KiB; después una marca lo dice y el log sigue en la línea siguiente. Pasado el tope o un presupuesto no se escribe nada más, tampoco la línea a medias, y la última línea del log dice por qué; una ráfaga de líneas vacías termina así el log de la sesión. Un fallo del registro no corta la sesión ni escribe nada sin redactar. Lo que no cubre: una credencial de formato desconocido, una clave de más de 32 KiB, una credencial cuyo comienzo se tragó otra (el resto de un JWT tras una clave de Anthropic o de Slack), una cadena hecha a mano de más de cuatro credenciales pegadas (las primeras) y, si el proceso de sesión muere sin cerrar el log, su última línea sin final. Las secuencias de escape de la terminal se quitan de cada línea antes de redactarla (revisión de seguridad del 2026-11-27: una credencial pegada a un código de color no casaba); el resto del texto se guarda como lo escribió el servidor, sin sanear otros caracteres de control.

Lo que **no** garantiza:

- Un servidor de terceros corre con los permisos de tu usuario y puede hacer cualquier cosa dentro de su proceso: leer tus ficheros, abrir conexiones o lanzar otros procesos. El harness decide qué arranca, qué le pasa, cuánto espera y qué deja salir, pero no lo encierra. Añade a la lista solo servidores en los que confías.
- El harness termina siempre el árbol del proceso de sesión (grupo de procesos o Job Object), que incluye al servidor y a lo que este lance. Un proceso que el servidor lance en otra sesión o grupo (`setsid`, un demonio) o fuera del Job Object escapa, y el harness no lo ve.
- La lista local se rechaza si otro usuario, el grupo u otros pueden escribirla en macOS y Linux. En Windows no se comprueban las ACL.
- La marca de recursión (`AI_HARNESS_MCP_CHILD`) evita encadenamientos accidentales. No detiene a un servidor malicioso que la borre.

### Planes de lectura (`/plan`, rama `feature/code-mode-plan`)

Lo que el harness garantiza:

- Solo la respuesta a un `/plan` escrito entero se lee como plan. Una respuesta normal con un plan dentro es texto.
- Ningún paso arranca nada antes de una aprobación de una persona en una terminal interactiva. Un Ctrl+C en el aviso del código deja el plan sin aprobar aunque después se teclee el código. La aprobación está ligada al hash del plan canónico (que incluye el nonce de la pregunta), al de su caja, a la sesión y a la solicitud; caduca y vale una vez. Si cambia un byte de lo ejecutado, de lo registrado o de lo mostrado, se deniega.
- Cada paso pasa por la pasarela de `mcp call`, que decide otra vez la política al ejecutar. Un plan nunca llama a una herramienta `write`.
- Ningún texto del modelo ni de una herramienta aprueba, cambia el plan o dibuja una línea del harness: llegan siempre como texto ajeno, marcado.
- Una sola pregunta por `/plan`: los resultados no vuelven al proveedor.

Lo que **no** garantiza: que un modelo real proponga el plan que la pregunta necesita, ni que una lectura permitida sea inocua para tus datos. La orden que arranca cada servidor no entra en el hash aprobado; la caja lo dice con una línea por servidor. El plan solo lee lo que tu lista permite; lo que el servidor haga con esa lectura es cosa del servidor.

Desde A2 (rama `feature/code-mode-loop`):

- Una lectura marcada `auto_read` en tu lista se ejecuta sin la caja cuando **todos** los pasos del plan lo son; se ve antes (`running plan:`) y queda auditada con el medio `rule`. Solo vale en herramientas `read`; las escrituras siguen denegadas por la pasarela. `/plan --box` la apaga para una pregunta y `HARNESS_AUTO_READ=off`, para todas.
- Lo que la lista decía de cada paso al leer el plan (orden de arranque y sus argumentos, entorno, carpeta, plazos, operación, `auto_read`, tope y argumentos) queda atado por un hash. Si cambia antes de ese paso, el paso no se llama (`list_changed`). Probado con siete cambios distintos, con su control (la misma lista escrita otra vez corre).
- Lo que **no** cubre: quien pueda escribir tu lista puede marcar `auto_read`. La lista tiene que ser solo tuya; en Windows el harness no mira sus ACL.

Desde A3 (`/agent`, rama `feature/code-mode-loop`), los resultados **sí** pueden volver al proveedor. Lo anterior sigue valiendo para `/plan`, que envía una sola pregunta. Lo que el harness garantiza para `/agent`, cada punto con su test:

- Nada sale sin dos consentimientos: `/agent` escrito entero y `HARNESS_LOOP_PROVIDERS` con el nombre del proveedor. Sin ellos no se registra ni se envía nada (`test_without_consent_nothing_leaves_the_machine`).
- Nada que no sea una lectura `auto_read` corre sin la caja, en ningún turno: cada plan pasa por la misma aprobación de `/plan` (`test_a_plan_that_is_not_by_rule_asks_the_box_every_turn`). Dentro de `/agent`, además, cada argumento declarado de cada paso tiene que estar acotado (`enum`, `integer`, `boolean` o `string` con `pattern` y `max_length` ≤ 64); con uno de texto libre, el plan entero va a la caja y su línea `why:` lo dice (`test_a_read_by_rule_with_a_free_text_argument_asks_the_box_in_a_loop`).
- Con un proveedor que no es sintético (Copilot), el primer envío con resultados de cada bucle pide la caja con el texto exacto, ligado a su hash; sin aprobarla no se envía nada (`test_a_provider_outside_the_machine_asks_once_with_the_exact_text`, `test_a_send_not_approved_sends_nothing_and_stops`).
- Lo que se envía es lo que se mostró, byte a byte (`test_what_is_sent_is_exactly_what_was_shown`). Va limpio, con las credenciales enmascaradas también después del corte por el medio (`test_a_credential_the_cut_reveals_is_masked_in_what_is_sent`), y acotado: 4 096 bytes por paso, 12 288 por plan y 28 000 caracteres por turno (`test_mcp_loop.py`). Un turno que la limpieza de la pantalla cambiaría no se envía (`test_a_turn_the_screen_would_change_is_never_sent`).
- Tras un bucle que envió resultados, la conversación los contiene: el harness lo dice una vez y en `/status`, y en esa sesión `/plan` también exige argumentos acotados para correr por regla (`test_after_results_were_sent_the_session_says_so_and_plan_needs_bounded_args`). `/new` empieza limpia.
- Un resultado no cierra su bloque ni imita el aviso, una cabecera del harness o la gramática: cada línea lleva un prefijo, `<<<`/`>>>` se cambian y la marca es nueva en cada turno (`test_a_hostile_result_stays_inside_its_block`). Un plan escrito dentro de un resultado nunca se lee (`test_a_plan_inside_a_result_is_never_the_model_s`), y un nonce que trae un resultado se rechaza (`test_a_nonce_injected_by_a_result_is_refused`).
- N turnos son N preguntas. Tras el tope, un solo turno de cierre, cuya respuesta nunca se lee como plan. Una respuesta `uncertain`, fallida o truncada para el bucle sin leerse ni reenviarse, aunque traiga un plan válido (`test_a_reply_not_completed_is_never_read_even_with_a_valid_plan_in_it`). Ctrl+C durante una pregunta o un paso para el bucle y no se envía nada más; en el aviso del código deja la aprobación `undecided`, como en `/plan`.
- `/agent --box` lleva a la caja todo plan del bucle (`test_box_sends_every_plan_of_the_loop_to_the_box`).
- No se guarda el texto de ningún turno ni ningún resultado, solo tamaños y un HMAC.

Lo que **no** garantiza:

- El nonce no protege de una inyección **dentro del mismo turno**. El resultado y el nonce nuevo viajan juntos, y un resultado puede convencer al modelo de proponer un plan válido. Ese plan pasa la misma política y, si no es de lecturas por regla con argumentos acotados, la caja. Con `auto_read`, una lectura así corre sin preguntar: es lo que la persona permitió al marcarla.
- **Lo que aún puede salir sin la caja**: los valores acotados que elige el modelo van como argumentos al servidor de esa lectura (qué proyecto de un `enum`, qué número de un rango, qué texto que cumple un `pattern`). Es un canal pequeño, no ninguno. Tú decides qué herramientas llevan `auto_read`, y el harness no juzga un `pattern`: `.*` con 64 caracteres deja pasar 64 caracteres cualesquiera.
- Lo que el proveedor haga con los resultados que recibe es cosa suya. Con Copilot, salen de la máquina.

## Matriz SEC y deuda conocida

Qué propiedad de seguridad (SEC-01..SEC-15) prueba qué test, con su control negativo y sus límites, está en [`docs/security/sec-matrix.md`](docs/security/sec-matrix.md); `scripts/verify.sh` comprueba que lo que cita existe. Lo que no se hace o no se prueba, con su decisión, está en [`docs/security/known-debt.md`](docs/security/known-debt.md).

## Perfil dedicado de Edge (Copilot Web)

Estado (2026-11-27): el proveedor de Copilot Web está en `develop` (no en `main` ni en la versión 0.2.1), probado contra la página real solo en macOS. En Windows, los tests que lanzan Edge no se han ejecutado (NOT RUN).

El harness lanza Edge con su sandbox activado y sin las opciones de Playwright que solo apagan protecciones de fondo (bloqueo de ventanas emergentes, actualización de componentes y de listas de protección). Coste medido (macOS, Edge 158): con la red en segundo plano activa, Edge tarda unos 10 s en cerrarse en cada pregunta con `ask` (en una conversación de `main.py chat`, una vez al salir), frente a 0,1 s con `--disable-background-networking`. Volver a poner esa opción ahorra ese tiempo, pero Edge deja de actualizar en segundo plano sus listas de protección. Lo decide Wilson. Dos opciones predeterminadas de Playwright se mantienen por decisión de Wilson (2026-11-25), para conservar la sesión iniciada: `--password-store=basic` y `--use-mock-keychain`. En macOS hacen que las cookies del perfil dedicado, y con ellas la sesión de Copilot, se cifren con una clave fija en vez de con el llavero del sistema. Consecuencia: **quien pueda leer el directorio del perfil puede descifrar las cookies de sesión y usar la sesión**. Por eso:

- Mantén `HARNESS_DATA_DIR` (el perfil está en `HARNESS_DATA_DIR/edge-profile`) en un disco local, legible solo por tu usuario, y fuera de copias de seguridad compartidas y de carpetas sincronizadas.
- En macOS y Linux, el harness crea el directorio de datos, la base de datos (con sus `-wal` y `-shm`), los bloqueos y `copilot/login.json` solo para su dueño (0700/0600; revisión de seguridad del 2026-11-27). Un directorio o fichero que ya existía conserva sus permisos: si el tuyo se creó antes, estréchalo tú (`chmod -R go-rwx` sobre `HARNESS_DATA_DIR`). En Windows esos modos no se usan y el harness no fija ACL: lo creado hereda los permisos de la carpeta padre.
- El harness crea el directorio del perfil con permisos solo para su dueño (0700) y estrecha a 0700 uno suyo que ya existiera. Eso no protege de otro proceso que corra con tu mismo usuario.
- En Windows no aplica la clave fija: el cifrado usa DPAPI, y el directorio hereda las ACL de su carpeta padre.

**Qué queda en disco (precisión del 2026-11-26).** La base de datos del harness no guarda preguntas ni respuestas de Copilot, y sus logs tampoco. **El perfil dedicado es un perfil de navegador**: Edge guarda en él su caché, IndexedDB, almacenamiento local, historial y cookies, y la página de Copilot puede dejar ahí el texto de las conversaciones. El harness no lo lee ni lo borra. Protege la carpeta del perfil como protegerías el perfil de tu navegador, y bórrala entera (con Edge cerrado) si quieres quitar lo que contiene; después hará falta `copilot login` otra vez.

La decisión se puede revisar cuando la sesión caduque y haya que iniciar sesión de nuevo de todas formas.

## Si algo se filtra

Un secreto publicado se da por comprometido aunque se borre el commit: primero se **revoca o rota**, después se limpia el historial. Para avisar de un problema de seguridad, usa los *security advisories* privados de GitHub en este repositorio, no un issue público.
