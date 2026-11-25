## Resumen
Evidencia: el documento propone avisar al canal de ventas de cada pedido aceptado del orquestador.

## Alternativas
- Evidencia: cola gestionada (A) o tabla leída por sondeo (B).
- Propuesta: A encaja con la decisión de mensajería registrada en la memoria del proyecto.

## Restricciones
- Evidencia: el equipo no opera infraestructura propia de mensajería.

## Requisitos no funcionales
- Evidencia: 200 pedidos por minuto y p95 por debajo de 300 ms.

## Supuestos
- Supuesto: el canal de ventas tolera recibir un mismo evento dos veces.

## Preguntas pendientes
- ¿Qué pasa con un evento que no se puede publicar?
