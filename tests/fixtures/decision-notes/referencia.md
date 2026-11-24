---
type: decision
decision_id: dec-b20925399f56d81f
project_slug: demo-alpha
status: accepted
created: 2026-11-20
updated: 2026-11-20
tags: [decision, demo-alpha]
source: ai-harness
skill: architecture-memory@1.0.0
run_id: 01900000-0000-7000-8000-000000000001
---
# Cola gestionada para eventos de ventas

## Contexto

El orquestador sintético publica eventos de ventas.

## Decisión

Se usa una cola gestionada.

## Alternativas consideradas

- Bus propio sobre la base de datos.
- Sondeo de una tabla.

## Consecuencias

- No hay infraestructura propia que operar.

## Supuestos

Ninguno declarado.

## Procedencia

- Skill `architecture-memory` 1.0.0 (sha256 abababab), ejecución 01900000-0000-7000-8000-000000000001.
- Notas de memoria consultadas: `Decisiones/alpha-mensajeria.md` (sha256 cdcdcdcd), `projects/demo-alpha/_project.md` (sha256 efefefef).
- Fuente: 1234 bytes (sha256 12121212).
- Credenciales enmascaradas: 0.
