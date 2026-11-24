## Resumen
Evidencia: el documento propone un servicio sintético de pedidos que publica un evento por pedido.

## Alternativas
- Evidencia: cola gestionada (A) o tabla con sondeo (B).
- Propuesta: A encaja con la decisión de mensajería registrada en la memoria del proyecto.

## Restricciones
- Evidencia: el equipo no opera infraestructura propia de mensajería.

## Requisitos no funcionales
- Evidencia: 200 pedidos por minuto y p95 por debajo de 300 ms.

## Supuestos
- Supuesto: el volumen no crece más de un orden de magnitud este año.

## Preguntas pendientes
- ¿Qué pasa con un evento que no se puede publicar?
