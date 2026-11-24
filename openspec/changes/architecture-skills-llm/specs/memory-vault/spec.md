# Spec Delta

## Purpose

Ajusta la garantía de `memory-vault` de que el harness no modifica el vault a la única escritura que introduce este change: una nota de decisión nueva en `Decisiones/`, solo como efecto de una aprobación (`decision-notes`). Los comandos `memory …` siguen sin escribir nada.

## MODIFIED Requirements

### Requirement: El harness no copia, sincroniza ni modifica el vault
El sistema SHALL NOT copiar, subir ni sincronizar el vault, y ningún comando de memoria SHALL crear, modificar, mover ni borrar nada en el vault ni fuera del directorio de datos. La única escritura del harness en el vault SHALL ser una nota de decisión nueva en `Decisiones/` (y la carpeta si falta) tras una aprobación, según `decision-notes`. Un comando que usa la memoria SHALL rechazar con un error controlado un directorio de datos dentro de la raíz del vault.

#### Scenario: Ninguna nota existente cambia tras una decisión
- **WHEN** se aprueba y se escribe una decisión sobre el vault sintético
- **THEN** todas las entradas que existían antes conservan ruta, tamaño y contenido, y la única novedad está en `Decisiones/`

#### Scenario: Ningún comando de memoria escribe fuera del directorio de datos
- **WHEN** se ejecutan todos los comandos de memoria sobre el vault sintético
- **THEN** el vault queda idéntico (mismas rutas, tamaños y contenidos) y no se crea ningún fichero fuera del directorio de datos

#### Scenario: Directorio de datos dentro del vault
- **WHEN** `HARNESS_DATA_DIR` es una carpeta dentro de `HARNESS_VAULT_ROOT` (directamente o a través de un enlace) y el usuario ejecuta un comando `memory …` o `ask --project`
- **THEN** el sistema lo rechaza con un error controlado y el vault queda idéntico; con el vault dentro del directorio de datos, el comando funciona
