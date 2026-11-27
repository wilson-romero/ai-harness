# Spec Delta

## ADDED Requirements

### Requirement: JSON de extracción en una sola línea
La plantilla de `architecture-memory/extract` SHALL pedir el objeto JSON minificado en una sola línea. La validación SHALL seguir aceptando el mismo objeto con sangría o dentro de un único bloque cercado, y las tres formas SHALL dar la misma salida validada.

#### Scenario: Lo que se pide
- **WHEN** se ejecuta `architecture-memory` con una fuente sintética
- **THEN** el texto enviado al proveedor pide un objeto JSON minificado en una sola línea

#### Scenario: Minificado, con sangría o en un bloque
- **WHEN** la respuesta guionizada es `decision-mock-min.json`, `decision-mock.json` con sangría o ese JSON dentro de un único bloque ```` ```json ````
- **THEN** la ejecución llega a la aprobación y el hash de la salida validada es el mismo en los tres casos
