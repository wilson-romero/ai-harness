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

**No** se garantiza que haya una persona delante. Un proceso que corre con tu misma cuenta y maneja una pseudoterminal puede leer la propuesta y escribir el código: puede hacerse pasar por ti. Si alguien o algo controla tu cuenta, las aprobaciones no lo detienen. Un canal más fuerte (un diálogo del sistema operativo, un segundo dispositivo) es una decisión abierta antes del efecto que escribe en el vault.

## Perfil dedicado de Edge (Copilot Web)

El harness lanza Edge con su sandbox activado y sin las opciones de Playwright que solo apagan protecciones de fondo (bloqueo de ventanas emergentes, actualización de componentes y de listas de protección). Dos opciones predeterminadas de Playwright siguen, a la espera de una decisión: `--password-store=basic` y `--use-mock-keychain`. En macOS hacen que las cookies del perfil dedicado, y con ellas la sesión de Copilot, se cifren con una clave fija en vez de con el llavero del sistema: **quien pueda leer el directorio del perfil puede usar la sesión**. Mantén el perfil (por defecto `HARNESS_DATA_DIR/edge-profile`) fuera de copias de seguridad compartidas y de carpetas sincronizadas, y en un disco cifrado. En Windows no aplica: el cifrado usa DPAPI.

## Si algo se filtra

Un secreto publicado se da por comprometido aunque se borre el commit: primero se **revoca o rota**, después se limpia el historial. Para avisar de un problema de seguridad, usa los *security advisories* privados de GitHub en este repositorio, no un issue público.
