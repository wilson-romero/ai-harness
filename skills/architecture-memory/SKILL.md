---
name: architecture-memory
description: Extrae una decisión de arquitectura de un texto, la muestra entera para aprobarla y solo entonces la guarda como nota nueva en Decisiones/ del vault.
---
# architecture-memory

Registro de una decisión de arquitectura en la memoria del proyecto de la sesión.

- Entrada: `source` (el texto del que sale la decisión: un acta, un hilo, un HLS; como mucho
  64 KiB).
- Pasos: `extract` pide al proveedor un único objeto JSON con `title`, `context`, `decision`,
  `alternatives`, `consequences` y `assumptions`; `check` lo valida con un esquema cerrado (un
  campo no declarado, un tipo distinto o un tamaño fuera de límites termina en `failed`); `save`
  prepara la nota, la muestra completa con su ruta y su hash, y pide una aprobación humana con
  el efecto `vault.save_decision`.
- Efecto: una nota nueva `Decisiones/YYYY-MM-DD-<slug>-<id8>.md`. El proyecto sale de la sesión y
  la ruta la calcula el harness; ningún texto del modelo, de la fuente o de la memoria los elige.
  Nunca sobrescribe ni edita una nota; si la decisión ya está registrada, falla con
  `duplicate_decision` sin pedir aprobación.

Uso: `skill run architecture-memory --session ID --input-file source=RUTA` en una sesión creada
con `--project`, y la aprobación en una terminal interactiva (`skill resume RUN_ID`).
