# Spec Delta

## Purpose

Define qué vault de Markdown lee el harness, con qué perfil de confidencialidad, y garantiza que la lectura no sale de su raíz ni mezcla perfiles, y que un vault de trabajo no se usa desde una ubicación que sincroniza fuera de la máquina.

## ADDED Requirements

### Requirement: Vault configurado y válido
Los comandos de memoria y `ask --project` SHALL exigir una raíz de vault configurada, absoluta, existente y que sea un directorio. Si falta o no es válida, SHALL terminar con un error controlado sin leer ninguna nota ni registrar ninguna solicitud.

#### Scenario: Vault sin configurar
- **WHEN** `HARNESS_VAULT_ROOT` está vacía y el usuario ejecuta `memory search arquitectura`
- **THEN** el sistema informa por stderr de que falta el vault, termina con código distinto de 0 y no imprime resultados

#### Scenario: Raíz relativa rechazada
- **WHEN** `HARNESS_VAULT_ROOT` es una ruta relativa y el usuario ejecuta `memory context demo-alpha`
- **THEN** el sistema rechaza la configuración con un error controlado y código distinto de 0

### Requirement: Perfil de confidencialidad
El sistema SHALL aceptar los perfiles `work` y `personal`, SHALL usar `work` cuando no se configure ninguno y SHALL rechazar cualquier otro valor con un error controlado.

#### Scenario: Perfil por defecto
- **WHEN** `HARNESS_PROFILE` no está definida y el usuario ejecuta un comando de memoria
- **THEN** el sistema aplica las reglas del perfil `work`

#### Scenario: Perfil desconocido
- **WHEN** `HARNESS_PROFILE=casa` y el usuario ejecuta un comando de memoria
- **THEN** el sistema informa del error, termina con código distinto de 0 y no lee el vault

### Requirement: Directorio de datos ligado a un perfil y un vault
El primer uso de la memoria SHALL ligar el directorio de datos al perfil y a la raíz de vault resuelta. Un uso posterior con otro perfil u otra raíz sobre el mismo directorio de datos SHALL rechazarse sin leer el vault.

#### Scenario: Cambio de perfil rechazado
- **WHEN** el directorio de datos se usó con el perfil `work` y el usuario ejecuta `memory search arquitectura` con `HARNESS_PROFILE=personal`
- **THEN** el sistema rechaza el comando indicando el perfil ligado y que se use otro directorio de datos, y termina con código distinto de 0

#### Scenario: Cambio de vault rechazado
- **WHEN** el directorio de datos se ligó al vault A y el usuario ejecuta `memory context demo-alpha` con la raíz apuntando al vault B
- **THEN** el sistema rechaza el comando y no imprime ninguna nota de B

#### Scenario: Mismo perfil y vault aceptados
- **WHEN** el usuario repite un comando de memoria con el mismo perfil y la misma raíz
- **THEN** el comando se ejecuta con normalidad

### Requirement: Un vault de trabajo no se usa desde una ubicación sincronizada
Con el perfil `work`, el sistema SHALL negarse a leer un vault, y a usar un directorio de datos, situados en una ruta de red o dentro de una carpeta de sincronización reconocida. El sistema SHALL NOT sincronizar ni copiar el vault a ningún destino.

#### Scenario: Vault work en carpeta sincronizada
- **WHEN** el perfil es `work` y la raíz del vault está dentro de una carpeta reconocida como sincronizada
- **THEN** el sistema rechaza el comando nombrando el motivo, termina con código distinto de 0 y no lee ninguna nota

#### Scenario: Vault work en ruta de red
- **WHEN** el perfil es `work` y la raíz del vault es una ruta UNC de red
- **THEN** el sistema rechaza el comando sin leer ninguna nota

#### Scenario: Vault personal en carpeta sincronizada
- **WHEN** el perfil es `personal` y la raíz del vault está dentro de una carpeta reconocida como sincronizada
- **THEN** el comando se ejecuta con normalidad

#### Scenario: Ningún comando de memoria escribe fuera del directorio de datos
- **WHEN** se ejecutan todos los comandos de memoria sobre el vault sintético
- **THEN** el vault queda idéntico (mismas rutas, tamaños y contenidos) y no se crea ningún fichero fuera del directorio de datos

### Requirement: Lectura confinada a la raíz del vault
El sistema SHALL leer solo ficheros regulares cuya ruta real esté dentro de la raíz real del vault. SHALL ignorar enlaces simbólicos, uniones de directorio y ficheros con más de un enlace duro, y SHALL informar de cuántas entradas ignoró.

#### Scenario: Enlace simbólico hacia fuera ignorado
- **WHEN** el vault contiene un enlace simbólico a un fichero fuera de la raíz que contiene la palabra buscada
- **THEN** `memory search` no devuelve ese fichero ni su contenido, e informa de una entrada ignorada

#### Scenario: Directorio enlazado hacia fuera ignorado
- **WHEN** el vault contiene un directorio enlazado a otro directorio fuera de la raíz
- **THEN** ningún comando de memoria lee ficheros de ese directorio

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
