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

Una aprobación se concede solo en una terminal interactiva, escribiendo los 8 primeros caracteres del hash de la propuesta, y se registra el usuario local del sistema operativo que la concedió. **Esa identidad no es una autenticación.**

Se garantiza:

- El código se deriva del contenido exacto que se muestra (y de su destino, la ejecución, el paso y el Skill). Lo mostrado, lo hasheado y lo aplicado son los mismos bytes: sin caracteres de control ni de formato, con los demás invisibles escritos como `<U+XXXX>`; un destino que no se puede mostrar tal cual se rechaza.
- El código, o cualquier parte del hash, solo aparece dentro de la pregunta interactiva, junto al contenido. El mensaje de espera (código 3) y `skill status` muestran el identificador de la aprobación, su estado y su caducidad.
- No se aprueba con stdin redirigido, con el fin de la entrada, con Enter, con una opción de la CLI ni con una variable de entorno; ningún texto de un modelo, nota o fichero aprueba.
- Una aprobación está ligada a una propuesta, caduca (una respuesta después de la caducidad no la concede) y se usa una vez. Un efecto interrumpido se reconcilia antes de seguir y nunca se aplica dos veces.
- En la conversación (`chat`, desde el 2026-11-25) el aviso es el mismo y se contesta en la misma terminal. Una línea escrita en el indicador normal es una pregunta o un comando, nunca una aprobación, aunque sea el código; no hay comando `/approve`, y Ctrl+C en el aviso lo deja sin decidir. Lo prueban `tests/unit/test_shell_skills.py` (con su control negativo) y la terminal real se cubre con la demo manual: no hay pseudoterminal portable para probarla en Windows.

**No** se garantiza que haya una persona delante. Un proceso que corre con tu misma cuenta y maneja una pseudoterminal puede leer la propuesta y escribir el código: puede hacerse pasar por ti. Si alguien o algo controla tu cuenta, las aprobaciones no lo detienen. Decidido el 2026-11-24: se acepta este límite para el MVP, también para el efecto que escribe en el vault; un canal más fuerte (un diálogo del sistema operativo, un segundo dispositivo) se abriría con un change propio.

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
- El harness no tiene ninguna superficie de entrada: no abre puertos ni sockets de escucha, y solo habla con sus servidores por los tubos que él mismo crea. Lo comprueban dos tests:
  - uno con un audit hook sobre la creación de cada socket (`socket.__new__`) y cada `socket.bind`, en el proceso del harness y en su proceso de sesión, durante un `mcp call`;
  - uno estructural sobre `harness/mcp/`.

  La autorización de clientes (SEC-09) llegará con el servidor MCP propio, en un corte posterior. Hoy no hay ningún cliente que autorizar.
- Lo que devuelve un servidor (resultados, descripciones, nombres, errores) se trata como datos no confiables:
  - se mide antes de leerlo (también su stderr: se guarda 1 MiB por sesión y pasado 64 MiB se detiene el servidor);
  - nunca se interpreta: el harness no evalúa ningún patrón, formato ni esquema que mande el servidor, y el SDK no valida resultados en el proceso del harness;
  - se sanea y se redacta antes de imprimirlo o auditarlo;
  - nunca se guarda.

Lo que **no** garantiza:

- Un servidor de terceros corre con los permisos de tu usuario y puede hacer cualquier cosa dentro de su proceso: leer tus ficheros, abrir conexiones o lanzar otros procesos. El harness decide qué arranca, qué le pasa, cuánto espera y qué deja salir, pero no lo encierra. Añade a la lista solo servidores en los que confías.
- El harness termina siempre el árbol del proceso de sesión (grupo de procesos o Job Object), que incluye al servidor y a lo que este lance. Un proceso que el servidor lance en otra sesión o grupo (`setsid`, un demonio) o fuera del Job Object escapa, y el harness no lo ve.
- La lista local se rechaza si otro usuario, el grupo u otros pueden escribirla en macOS y Linux. En Windows no se comprueban las ACL.
- La marca de recursión (`AI_HARNESS_MCP_CHILD`) evita encadenamientos accidentales. No detiene a un servidor malicioso que la borre.

## Si algo se filtra

Un secreto publicado se da por comprometido aunque se borre el commit: primero se **revoca o rota**, después se limpia el historial. Para avisar de un problema de seguridad, usa los *security advisories* privados de GitHub en este repositorio, no un issue público.
