# Design

## Contexto

Los hechos del formato salen del estudio del 2026-11-28 (§2.3). Ese estudio leyó el repositorio público `claude-memory-system` en el commit `92b19ea`:
- `docs/convenciones.md`;
- `scripts/memoria-capture.sh`;
- `scripts/memoria-dream.sh`;
- `templates/` y el prompt del curador.

El repositorio se leyó como datos: no se ejecutó ningún script. Aquí el formato se describe con palabras propias, y nada de su texto ni de sus plantillas entra en este repositorio.

**Premisa medida aquí:** el lector actual da resultados falsos sobre notas con el formato real. Cada test de `tests/unit/test_memory_format_conformance.py` que fija una conducta nueva falló con el código de `origin/develop` antes de corregirlo (recibo en `tasks.md` 2.1). Los tres tests de forma del vault sintético fallaron con el vault de `origin/develop` (recibo en `tasks.md` 1.4).

## Decisiones

### D1. `created` es opcional solo en las notas que la captura reescribe

- **Qué.** `frontmatter_problem(frontmatter, relative)` no exige `created` cuando falta y la ruta es exactamente una de estas tres:
  - `projects/<slug>/_project.md` (tres partes);
  - `_index.md`;
  - `agents/_skills-index.md`.

  Si `created` está, se comprueba igual que antes: con formato `YYYY-MM-DD` y sin fecha futura. Sin la ruta (`relative=None`), la regla es la de siempre.
- **Por qué.** La captura regenera esas tres notas en cada sesión y no les escribe `created`. Hoy salen todas en `invalid_frontmatter`, y en un vault real eso es una línea por proyecto. Las demás notas del formato real sí llevan `created`.
- **Alternativas rechazadas.**
  - *`created` opcional en todas las notas.* Ocultaría el defecto real de una lección o una sesión sin fecha de creación.
  - *Exención por nombre de fichero (`_project.md` en cualquier sitio).* Una nota `projects/x/otra/_project.md` no la escribe la captura. El test negativo la incluye.
  - *Exención por `type`.* `type: reference` lo llevan también los informes del Sueño y los agentes, que sí tienen `created`.
- **Impacto.**
  - Spec `memory-maintenance`, escenario «Notas que la captura reescribe».
  - `maintenance.py` pasa `note.relative`.
  - `test_every_fixture_note_is_valid_and_loads` comprueba con la ruta.

### D2. Un escalar sin comillas con `: ` dentro invalida el frontmatter

- **Qué.** En `_parse_block`, un valor que no va entre comillas y contiene `: ` o termina en `:` hace que el bloque sea `unsupported`. Lo mismo pasa con lo que YAML trata como una estructura que este parser no admite. `12:15:00` y `https://…` siguen siendo válidos, porque no llevan espacio tras los dos puntos. `"Estilo: breve"` también, porque va entre comillas.
- **Por qué.** En YAML, `description: Estilo: breve` es un error: un mapeo dentro de un escalar plano. El formato real pide comillas en `description` precisamente por eso, y Obsidian no lee ese frontmatter. El harness lo aceptaba y le daba un valor que ningún otro lector daría.
- **Alternativas rechazadas.**
  - *Comprobarlo solo en `description`.* El error de YAML es el mismo con cualquier clave.
  - *Usar un parser YAML completo.* El parser mínimo es una decisión de `project-memory` (D10): no evalúa anclas ni etiquetas. Cambiarlo no entra en esta rama.
- **Impacto.**
  - Spec `memory-maintenance`, escenario «Valor sin comillas con dos puntos».
  - Efecto lateral: `harness/skills/definition.py` usa el mismo parser, así que un `SKILL.md` con `description: a: b` pasa a ser inválido. Ningún Skill del repositorio lo tiene: `git grep -n "^description: [^\"'].*: " -- skills tests/fixtures` no devuelve nada, y la suite completa pasa.

### D3. Un identificador de proyecto no válido se rechaza con su motivo; la regla no cambia

- **Qué.** `validate_project_slug` sigue aceptando solo letras y dígitos ASCII, `.`, `_` y `-`:
  - empieza por letra o dígito;
  - tiene como máximo 128 caracteres;
  - no es un nombre reservado de Windows;
  - no termina en punto ni en espacio.

  El mensaje pasa a ser `invalid project identifier '<x>': <motivo>; use the plain name of a folder under projects/ (…)`. El motivo es uno de una lista cerrada (`slug_problem`), por ejemplo `it contains a space`, `it contains a character that is not ASCII` o `it is longer than 128 characters`. El mensaje sigue siendo el mismo en macOS y en Windows.
- **Por qué.** El `vault_slug` real se deriva de la ruta del proyecto y conserva sus espacios y acentos. Ese slug se guarda en SQLite y se escribe en el frontmatter y en las etiquetas de la nota de decisión: se convierte en una ruta y en texto que el harness **escribe**. Relajar la regla abriría esa escritura a nombres que la regla protege en Windows (espacios y puntos finales) y a la normalización Unicode. No se relaja.

  Lo que faltaba era decir por qué se rechaza un nombre que no parece un ataque. Las notas de esa carpeta no se ignoran: `memory search` sin `--project` las devuelve (escenario y test).
- **Alternativas rechazadas.**
  - *Aceptar el nombre para leer y rechazarlo para escribir.* Una sesión con ese proyecto no podría escribir su decisión, y el fallo llegaría tarde, tras la aprobación.
  - *Normalizar el nombre (espacios por guiones, quitar acentos).* Dos carpetas distintas podrían dar el mismo slug y mezclar proyectos (SEC-02).
  - *Ignorar en silencio las carpetas no válidas.* El coordinador lo prohíbe explícitamente, y además esconde datos.
- **Impacto.**
  - Spec `memory-vault`, requisito «Identificador de proyecto validado».
  - `tests/unit/test_memory_paths.py` fija el motivo de cada entrada, más los tres nombres reales.
  - Los tests de `tests/security/test_vault_confinement.py` comprueban el prefijo, que no cambia.
  - Fuera de alcance: la lista de autocompletado de `harness/shell/` omite estas carpetas (proposal).

### D4. Huérfanas y duplicados: solo el primer nivel de `Memoria-CC/`

- **Qué.** `_in_curated` es cierto solo para `Memoria-CC/<fichero>`. Una nota en `Memoria-CC/<carpeta>/…`:
  - no es huérfana;
  - no forma parte de un par de duplicados;
  - sigue en la búsqueda, en el contexto (si declara el proyecto) y en las demás categorías.
- **Por qué.** El original lista el primer nivel de la carpeta (`os.listdir` en `memoria-dream.sh`, líneas 147–174). Una subcarpeta (un archivo propio, por ejemplo) no está pensada para tener entrada en el índice, y hoy cada nota de ella sale como huérfana.
- **Alternativas rechazadas.** *Leer las subcarpetas como un índice propio.* El formato real no lo define.
- **Impacto.** Spec `memory-maintenance`, escenario «Solo el primer nivel de Memoria-CC».

### D5. Las entradas de un índice son rutas relativas a `Memoria-CC/` y se comprueban contra el vault

- **Qué.**
  - **Cómo se resuelve.** El destino de `- [título](destino)` se resuelve como texto: `Memoria-CC/` + destino. Se quitan `.` y `#ancla`, y cada `..` sube un nivel.
  - **Cuándo cuenta como colgante.** Solo si no nombra ningún fichero que el recorrido confinado vio, con cualquier extensión. Así una rama `MEMORY-<tema>.md` o una lección de `../Lecciones/` cuentan como existentes.
  - **Si sale del vault.** Un destino que sube por encima de la raíz conserva su `..` inicial, no coincide con nada y se informa como colgante, con la ruta resuelta.
  - **Sin acceso al disco.** No se mira el sistema de ficheros ni se usa `posixpath`: el guardián de `test_memory_package_has_no_copy_upload_or_write_path` admite solo una lista cerrada de módulos.
- **Por qué.** Markdown y el original (`os.path.exists(join(mcc, rel))`) leen el enlace igual. Hoy `../Lecciones/x.md` se lee como `Memoria-CC/../Lecciones/x.md` y no se encuentra.

  Resolverlo contra el disco abriría una consulta fuera del vault con una ruta que viene de una nota (SEC-04). Por eso solo se compara con la lista que ya pasó por la lectura confinada.
- **Alternativas rechazadas.**
  - *`os.path.exists` como el original.* Sigue enlaces simbólicos y puede salir del vault.
  - *Comprobar solo contra las notas de `Memoria-CC/`.* La rama `MEMORY-tecnico.md` y las lecciones contarían como colgantes.
  - *`posixpath.normpath`.* Hace lo mismo, pero añadía un módulo a la lista cerrada del guardián sin necesidad.
- **Impacto.** Spec `memory-maintenance`, escenario «Entrada de índice relativa a Memoria-CC».

### D6. Un enlace de tabla `[[ruta\|alias]]` se lee sin la `\`

- **Qué.** En `_broken_links`, el destino se corta en la primera `|` y después se le quita una `\` final.
- **Por qué.** Dentro de una tabla de Markdown la barra del alias se escapa, y la captura escribe así `agents/_skills-index.md`. El original no trata ese destino como roto (`memoria-dream.sh`, líneas 121–123). El harness lo daba por roto porque buscaba `agents/skills/x\`.
- **Alternativas rechazadas.** *Quitar todas las `\` del destino.* Una `\` dentro de un nombre es otro problema y debe seguir saliendo.
- **Impacto.** Spec `memory-maintenance`, escenario «Enlace con alias escapado en una tabla».

### D7. Vault sintético en el formato real, con texto propio

- **Qué.** Cada nota sigue la estructura del formato real: carpeta, `type`, campos, etiquetas y títulos de sección. El texto es nuevo y ficticio.
  - Se conservan todos los canarios y las fechas `updated` de las que dependen los tests de orden.
  - Las rutas de máquina son `/srv/equipo-sintetico/…`.
  - Una lección nueva con `tags: []`, como las deja el curador, documenta el desajuste 8 sin cambiar la conducta.
  - Los `_INDEX.md` tienen un frontmatter normal y una lista de enlaces: el formato real no especifica su forma, y aquí no se presenta como si lo hiciera.
- **Por qué.** El vault sintético es el oráculo de casi todos los tests de memoria. Si no se parece al real, los tests no prueban nada sobre él.
- **Alternativas rechazadas.** *Copiar las plantillas del repositorio público.* La decisión 4 del estudio (licencia y atribución) sigue abierta.
- **Impacto.** Las expectativas de tests que cambian, test por test, están en `tasks.md` 3.

## Riesgos y límites

- [Un vault real con una forma que el estudio no vio] -> los arreglos siguen los hechos citados de `92b19ea`. Medir sobre el vault real es la tarea NOT RUN del Corte 3, que hace el dueño en local.
- [D2 rechaza un `SKILL.md` de terceros con `description: a: b`] -> es YAML no válido también para cualquier otro lector. El error dice `unsupported`. Queda escrito en el proposal.
- [Desajuste 8, sin resolver: decisión del dueño] -> hoy, en un vault real, `memory context` y `ask --project` no incluyen ninguna nota de `Lecciones/` ni de `Memoria-CC/` escrita por el curador real, porque las escribe con `tags: []` y sin `project_slug`. Solo entran:
  - `_project.md`;
  - las decisiones que escribe el harness;
  - las 3 sesiones más recientes.

  `test_curated_note_without_project_stays_out_of_the_context_today` lo deja fijado para que un cambio sea deliberado.
- [Límite que no se arregla aquí] -> la lista de autocompletado del shell omite las carpetas con nombre no válido. Está fuera de alcance por `harness/shell/`.
