# Spec Delta

## Purpose

Define qué es un Skill en disco, cuándo el harness lo acepta como válido y cuándo lo rechaza por malicioso o mal formado, y cómo se identifica una versión concreta de un Skill mediante su hash.

## ADDED Requirements

### Requirement: Estructura de un Skill
Un Skill SHALL ser una carpeta directa de la raíz de Skills cuyo nombre coincide exactamente con el campo `name` del frontmatter de su `SKILL.md`, y que contiene `SKILL.md` y `workflow.json`. El nombre SHALL usar solo minúsculas, dígitos y guiones, empezar por letra o dígito, tener como mucho 64 caracteres y no ser un nombre reservado de Windows.

#### Scenario: Skill válido listado
- **WHEN** la raíz de Skills contiene un Skill sintético bien formado y el usuario ejecuta `skill list`
- **THEN** la salida muestra su nombre, su versión, su descripción y el estado `valid`, con código 0

#### Scenario: Nombre de carpeta distinto del frontmatter
- **WHEN** la carpeta se llama `demo-uno` y su `SKILL.md` declara `name: demo-dos`
- **THEN** `skill list` muestra el Skill como `invalid` con el motivo, y `skill run demo-uno` se rechaza sin crear ninguna ejecución

#### Scenario: Falta workflow.json
- **WHEN** un Skill tiene `SKILL.md` pero no `workflow.json`
- **THEN** el Skill se muestra como `invalid` y no se puede ejecutar

### Requirement: Solo ficheros declarativos permitidos
Un Skill SHALL contener solo `SKILL.md`, `workflow.json` y ficheros `.md` dentro de `templates/` o `references/`. Cualquier otro fichero o carpeta visible, incluido cualquier script o programa, SHALL invalidar el Skill entero. Las entradas cuyo nombre empieza por punto SHALL ignorarse sin leerse.

#### Scenario: Script dentro de un Skill
- **WHEN** un Skill contiene `scripts/run.sh` o `templates/helper.py`
- **THEN** el Skill se muestra como `invalid` con el motivo «unexpected file» y ninguna ejecución lo usa

#### Scenario: Fichero oculto ignorado
- **WHEN** un Skill válido contiene además `.DS_Store`
- **THEN** el Skill sigue siendo `valid` y su hash es el mismo que sin ese fichero

### Requirement: Enlaces y traversal rechazados
El harness SHALL rechazar un Skill que contenga un enlace simbólico, una unión de directorio o un fichero con más de un enlace duro, y SHALL rechazar cualquier ruta declarada en `workflow.json` que no sea relativa, que contenga `..` o que no resuelva dentro de la carpeta del Skill. Un nombre de Skill pedido en la CLI con separadores o `..` SHALL rechazarse antes de tocar el disco.

#### Scenario: Plantilla enlazada fuera de la raíz
- **WHEN** `templates/review.md` de un Skill es un enlace simbólico a un fichero fuera de la raíz de Skills
- **THEN** el Skill se muestra como `invalid` con el motivo «link» y el contenido del fichero de fuera no aparece en ninguna salida

#### Scenario: Ruta de plantilla con traversal
- **WHEN** un paso declara `"template": "templates/../../secreto.md"`
- **THEN** el Skill se muestra como `invalid` y no se lee ese fichero

#### Scenario: Nombre de Skill con traversal en la CLI
- **WHEN** el usuario ejecuta `skill show ../otro` o `skill run ..\otro --session ID`
- **THEN** el sistema rechaza el nombre con un error controlado y código distinto de 0, sin crear ninguna ejecución

### Requirement: Workflow declarativo y cerrado
`workflow.json` SHALL ser JSON estricto (sin claves duplicadas ni `NaN`) con un esquema cerrado: cualquier campo desconocido o tipo de paso distinto de `llm`, `validate` y `approval` SHALL invalidar el Skill. Los identificadores de paso SHALL ser únicos y la secuencia SHALL ser lineal.

#### Scenario: Paso de tipo desconocido
- **WHEN** un paso declara `"kind": "tool"`, `"kind": "shell"` o `"kind": "script"`
- **THEN** el Skill se muestra como `invalid` con el motivo «unknown step kind» y no se ejecuta

#### Scenario: Campo desconocido
- **WHEN** un paso `llm` declara además `"command": "..."`
- **THEN** el Skill se muestra como `invalid` y el campo no tiene ningún efecto

#### Scenario: Clave duplicada en el JSON
- **WHEN** `workflow.json` repite la clave `steps`
- **THEN** el Skill se muestra como `invalid` en lugar de quedarse con una de las dos

### Requirement: Referencias resueltas al cargar
Toda referencia de una plantilla o de un paso SHALL tener una de las formas `{{inputs.NOMBRE}}`, `{{steps.ID.output}}` o `{{steps.ID.fields.CAMPO}}` y SHALL apuntar a una entrada declarada, a un paso anterior o a un campo declarado de un paso `validate` anterior. Cualquier otra forma entre `{{` y `}}` SHALL invalidar el Skill.

#### Scenario: Referencia a un paso posterior
- **WHEN** el primer paso usa `{{steps.final.output}}` y `final` es el último paso
- **THEN** el Skill se muestra como `invalid` con el motivo y la referencia

#### Scenario: Expresión en una plantilla
- **WHEN** una plantilla contiene `{{ inputs.doc.upper() }}` o `{{ 1 + 1 }}`
- **THEN** el Skill se muestra como `invalid` y nada se evalúa

### Requirement: Límites de un Skill en disco
Un Skill SHALL invalidarse si supera 32 ficheros permitidos, 64 KiB en un fichero, 512 KiB en total, 12 pasos u 8 entradas declaradas, o si un paso declara un plazo fuera de 1–600 segundos. Ningún fichero que supere su límite SHALL leerse entero.

#### Scenario: Demasiados pasos
- **WHEN** `workflow.json` declara 13 pasos
- **THEN** el Skill se muestra como `invalid` con el motivo «too many steps» y no se ejecuta

#### Scenario: Plantilla demasiado grande
- **WHEN** una plantilla ocupa 65 537 bytes
- **THEN** el Skill se muestra como `invalid` con el motivo del tamaño

### Requirement: Hash y versión del Skill
Cada Skill válido SHALL tener una versión declarada en `workflow.json` y un hash SHA-256 calculado sobre la lista ordenada de sus ficheros permitidos y su contenido con finales de línea normalizados. El hash SHALL cambiar si cambia cualquier fichero permitido y SHALL ser el mismo en macOS y en Windows para el mismo contenido.

#### Scenario: Cambiar una plantilla cambia el hash
- **WHEN** se modifica un carácter de `templates/review.md` de un Skill válido
- **THEN** `skill show` muestra un hash distinto del anterior y la misma versión

#### Scenario: Finales de línea CRLF
- **WHEN** los ficheros de un Skill se guardan con `\r\n` en lugar de `\n`
- **THEN** el hash del Skill es el mismo

### Requirement: Mostrar un Skill sin ejecutarlo
`skill show NAME` SHALL imprimir la descripción, la versión, el hash, las entradas declaradas y la lista de pasos con su tipo y sus referencias, sin llamar a ningún proveedor ni crear ninguna ejecución. Un Skill inválido SHALL mostrarse con todos sus motivos y código distinto de 0.

#### Scenario: Show sin efectos
- **WHEN** el usuario ejecuta `skill show` sobre un Skill válido
- **THEN** la salida lista sus pasos en orden y la tabla `skill_runs` no gana ninguna fila
