# Requerimiento sintético R2-3M8: lecturas del catálogo de productos

Documento de diseño de alto nivel, sintético, para el proyecto de demostración `demo-alpha`.

Cada pedido consulta el servicio de catálogo para validar precios y existencias. En hora punta
el catálogo responde con una latencia p95 de 180 ms y es la mayor parte del tiempo del pedido.

- Alternativa A: una caché en memoria dentro de cada instancia del orquestador, con caducidad
  de 60 segundos.
- Alternativa B: una caché compartida gestionada entre todas las instancias, invalidada por un
  evento cuando cambia un precio.
- Requisito: un precio cambiado no puede aplicarse a un pedido más de 2 minutos después.
- Restricción: el orquestador corre en 3 instancias sin afinidad de sesión.
- Sin definir: si las existencias admiten el mismo retraso que los precios.
