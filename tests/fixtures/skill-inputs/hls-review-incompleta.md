## Resumen
Evidencia: el documento propone un servicio sintético de pedidos que publica un evento por pedido.

## Alternativas
- Evidencia: cola gestionada (A) o tabla con sondeo (B).

## Restricciones
- Evidencia: el equipo no opera infraestructura propia de mensajería.

## Requisitos no funcionales
- Evidencia: 200 pedidos por minuto y p95 por debajo de 300 ms.

## Supuestos
- Supuesto: el volumen no crece más de un orden de magnitud este año.
