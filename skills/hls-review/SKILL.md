---
name: hls-review
description: Revisa un documento de diseño de alto nivel (HLS) con la memoria del proyecto de la sesión. No escribe nada.
---
# hls-review

Revisión asistida de un HLS: alternativas, restricciones, requisitos no funcionales, supuestos y
preguntas pendientes, con el contexto de memoria del proyecto de la sesión.

- Entrada: `document` (el HLS, en texto o Markdown, como mucho 64 KiB).
- Pasos: una pregunta al proveedor (`review`) y una comprobación de estructura (`check`) que
  exige las seis secciones.
- Salida: la revisión por stdout. No tiene pasos de aprobación ni efectos: no escribe en el vault
  ni fuera del directorio de datos.

Uso: `skill run hls-review --session ID --input-file document=RUTA` en una sesión creada con
`--project`.
