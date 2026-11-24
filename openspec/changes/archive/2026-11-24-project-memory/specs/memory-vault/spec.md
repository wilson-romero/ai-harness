# Spec Delta

## Purpose

Define qué vault de Markdown lee el harness y garantiza que la lectura no sale de su raíz y que el harness nunca copia, sincroniza ni modifica el vault.

## ADDED Requirements

### Requirement: Vault configurado y válido
Los comandos de memoria y `ask --project` SHALL exigir una raíz de vault configurada, absoluta, existente y que sea un directorio. Si falta o no es válida, SHALL terminar con un error controlado sin leer ninguna nota ni registrar ninguna solicitud.

#### Scenario: Vault sin configurar
- **WHEN** `HARNESS_VAULT_ROOT` está vacía y el usuario ejecuta `memory search arquitectura`
- **THEN** el sistema informa por stderr de que falta el vault, termina con código distinto de 0 y no imprime resultados

#### Scenario: Raíz relativa rechazada
- **WHEN** `HARNESS_VAULT_ROOT` es una ruta relativa y el usuario ejecuta `memory context demo-alpha`
- **THEN** el sistema rechaza la configuración con un error controlado y código distinto de 0

### Requirement: El harness no copia, sincroniza ni modifica el vault
El sistema SHALL NOT copiar, subir ni sincronizar el vault a ningún destino, y ningún comando de memoria SHALL crear, modificar, mover ni borrar nada en el vault ni fuera del directorio de datos. Un comando que usa la memoria SHALL rechazar con un error controlado un directorio de datos que esté dentro de la raíz del vault.

#### Scenario: Ningún comando de memoria escribe fuera del directorio de datos
- **WHEN** se ejecutan todos los comandos de memoria sobre el vault sintético
- **THEN** el vault queda idéntico (mismas rutas, tamaños y contenidos) y no se crea ningún fichero fuera del directorio de datos

#### Scenario: Directorio de datos dentro del vault
- **WHEN** `HARNESS_DATA_DIR` es una carpeta dentro de `HARNESS_VAULT_ROOT` (directamente o a través de un enlace) y el usuario ejecuta un comando `memory …` o `ask --project`
- **THEN** el sistema lo rechaza con un error controlado y el vault queda idéntico; con el vault dentro del directorio de datos, el comando funciona

### Requirement: Lectura confinada a la raíz del vault
El sistema SHALL leer solo ficheros regulares cuya ruta real esté dentro de la raíz real del vault y que sigan siendo, al leerlos, el mismo fichero que vio el recorrido. SHALL ignorar enlaces simbólicos, uniones de directorio, ficheros con más de un enlace duro, ficheros sustituidos o que superan el límite de tamaño entre el recorrido y la lectura, y directorios que no se pueden listar, y SHALL informar de cuántas entradas ignoró.

#### Scenario: Enlace simbólico hacia fuera ignorado
- **WHEN** el vault contiene un enlace simbólico a un fichero fuera de la raíz que contiene la palabra buscada
- **THEN** `memory search` no devuelve ese fichero ni su contenido, e informa de una entrada ignorada

#### Scenario: Directorio enlazado hacia fuera ignorado
- **WHEN** el vault contiene un directorio enlazado a otro directorio fuera de la raíz
- **THEN** ningún comando de memoria lee ficheros de ese directorio

#### Scenario: Fichero sustituido después del recorrido
- **WHEN** después del recorrido una nota de sesión se sustituye por un enlace a un fichero de fuera con un canario, o crece por encima del límite de tamaño
- **THEN** el contexto no contiene el canario ni el texto añadido, y la nota cuenta como ignorada

#### Scenario: Directorio que no se puede listar
- **WHEN** una carpeta del vault no tiene permiso de lectura
- **THEN** `memory search`, `memory context` y `memory maintain --dry-run` la cuentan como ignorada, y `maintain` nombra su ruta relativa

#### Scenario: Raíz del vault que es un enlace
- **WHEN** la raíz configurada es un enlace simbólico a un directorio que contiene el vault
- **THEN** el sistema lee el vault al que apunta y confina la lectura a esa ruta real

### Requirement: Identificador de proyecto validado
El sistema SHALL aceptar como proyecto solo un nombre simple que corresponda exactamente, incluidas mayúsculas, a una carpeta existente bajo `projects/`. SHALL rechazar separadores de ruta de cualquier plataforma, `..`, unidades, rutas de red, nombres reservados de Windows y nombres que acaben en punto o espacio.

#### Scenario: Traversal en el proyecto
- **WHEN** el usuario ejecuta `memory context ../../etc`
- **THEN** el sistema rechaza el identificador con un error controlado y no lee ningún fichero

#### Scenario: Forma de ruta de Windows rechazada
- **WHEN** el proyecto es `..\otro`, `C:\vault`, `\\servidor\recurso` o `CON`
- **THEN** el sistema rechaza el identificador en macOS y en Windows con el mismo mensaje

#### Scenario: Mayúsculas distintas
- **WHEN** existe `projects/demo-alpha/` y el usuario pide el proyecto `Demo-Alpha`
- **THEN** el sistema informa de que el proyecto no existe, aunque el sistema de ficheros no distinga mayúsculas

#### Scenario: Proyecto inexistente
- **WHEN** el usuario pide un proyecto válido sin carpeta en `projects/`
- **THEN** el sistema informa de que no existe y termina con código distinto de 0

### Requirement: Entradas del vault que no se leen
El sistema SHALL ignorar carpetas y ficheros cuyo nombre empieza por punto, la carpeta `Memoria/Archivo/`, los ficheros que no terminan en `.md` y los mayores del límite de tamaño configurado, y SHALL contarlos como ignorados.

#### Scenario: Temporal de escritura atómica ignorado
- **WHEN** existe en el vault un fichero `.tmp.AbC123` con la palabra buscada
- **THEN** `memory search` no lo devuelve

#### Scenario: Archivo excluido
- **WHEN** una nota de `Memoria/Archivo/` contiene la palabra buscada
- **THEN** `memory search` no la devuelve
