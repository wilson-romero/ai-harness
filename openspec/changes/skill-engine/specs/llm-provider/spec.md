# Spec Delta

## Purpose

Añade a `llm-provider` qué pasa con un texto que no es Unicode válido. Lo encontró la revisión independiente del 2026-11-24: un sustituto suelto en un prompt o en una respuesta terminaba en una traza de Python y dejaba la solicitud sin estado final, un fallo que ya estaba en el Corte 1 y que los Skills heredan.

## ADDED Requirements

### Requirement: Texto que no es Unicode válido
Un prompt que no se puede codificar en UTF-8 (por ejemplo, con un sustituto suelto que deja en `argv` un byte que no es UTF-8) SHALL rechazarse con un error controlado antes de registrar ninguna solicitud. Una respuesta del proveedor que no se puede codificar en UTF-8 SHALL dejar la solicitud en `failed` con el código `invalid_text`, sin guardar la respuesta y sin terminar en una traza de Python.

#### Scenario: Prompt con un byte que no es UTF-8
- **WHEN** el usuario ejecuta `ask SESSION_ID` con un prompt que contiene el byte `0xFF`
- **THEN** el sistema informa del error por stderr sin traza, termina con código 1 y no registra ninguna solicitud

#### Scenario: Respuesta con un sustituto suelto
- **WHEN** el proveedor devuelve un texto con U+D800
- **THEN** la solicitud queda `failed` con `invalid_text`, el historial solo tiene la pregunta y un paso de Skill que la hizo queda `failed`
