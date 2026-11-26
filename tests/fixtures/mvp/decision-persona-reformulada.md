# La misma decisión sintética, escrita otra vez con otras palabras

Proyecto `demo-alpha`. Repaso la revisión y me quedo con la alternativa A: cada pedido aceptado
sale del orquestador como un evento en una cola gestionada. No operamos mensajería propia y la
memoria del proyecto ya tiene una cola gestionada para los eventos de ventas. La tabla leída por
sondeo queda fuera: no llega a la latencia p95 de 300 ms.

El canal de ventas asume que puede recibir un evento repetido y lo ignora.
