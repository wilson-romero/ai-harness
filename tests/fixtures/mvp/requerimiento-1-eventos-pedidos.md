# Requerimiento sintético R1-7Q4: eventos de pedidos del orquestador

Documento de diseño de alto nivel, sintético, para el proyecto de demostración `demo-alpha`.

El orquestador de pedidos tiene que avisar al canal de ventas de cada pedido aceptado. Hoy el
canal consulta el orquestador cada minuto y ve los pedidos con retraso.

- Alternativa A: publicar un evento por pedido aceptado en una cola gestionada.
- Alternativa B: escribir los eventos en una tabla del orquestador y que el canal la lea por
  sondeo.
- Requisito: 200 pedidos por minuto en hora punta; latencia p95 por debajo de 300 ms entre la
  aceptación y el aviso.
- Restricción: el equipo no opera infraestructura propia de mensajería.
- Sin definir: qué pasa con un evento que no se puede publicar.
