# Decisión sintética D-5K2 tras leer la revisión de R1-7Q4

Proyecto `demo-alpha`. Leída la revisión, se elige la alternativa A: el orquestador publica un
evento por pedido aceptado en una cola gestionada, porque el equipo no opera infraestructura
propia de mensajería y la memoria del proyecto ya registra una cola gestionada para los eventos
de ventas. Se descarta la tabla leída por sondeo porque no cumple la latencia p95 de 300 ms.

Consecuencia aceptada: el canal de ventas tiene que ignorar los eventos repetidos.
