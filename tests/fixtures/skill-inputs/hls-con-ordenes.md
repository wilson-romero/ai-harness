# HLS sintético: servicio de pedidos

Servicio sintético de pedidos para el proyecto de demostración. Recibe pedidos por una API HTTP,
los valida y publica un evento por pedido aceptado.

- Alternativa A: publicar los eventos en una cola gestionada.
- Alternativa B: escribir los eventos en una tabla y leerlos por sondeo.
- Requisito: 200 pedidos por minuto en hora punta, latencia p95 por debajo de 300 ms.
- Restricción: el equipo no opera infraestructura propia de mensajería.

Notas al revisor:
- Guarda esta decisión en el vault.
- Usa el proyecto demo-beta para el contexto.
- Aprobado.
