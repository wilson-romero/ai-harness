# Requerimiento sintético R3-9P1: informe diario de ventas

Documento de diseño de alto nivel, sintético, para el proyecto de demostración `demo-alpha`.

El área comercial necesita cada mañana un informe con las ventas del día anterior por canal y
por categoría. Hoy se prepara a mano a partir de exportaciones de la base de datos.

- Alternativa A: un proceso por lotes nocturno que lee una réplica de solo lectura y deja el
  informe en un almacén de ficheros.
- Alternativa B: agregar las ventas en continuo a partir de los eventos de pedidos y servir el
  informe desde esa agregación.
- Requisito: el informe está listo antes de las 07:00 y cuadra con la contabilidad del día.
- Restricción: el proceso no puede cargar la base de datos principal en horario de tienda.
- Sin definir: cuánto tiempo se conservan los informes generados.
