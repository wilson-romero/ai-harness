# Estudio: ¿un formato más corto que JSON para hablar con Copilot?

Fecha: 2026-11-26. Repo leído en `origin/develop` (y, solo para ver cómo se lee la respuesta, `feature/copilot-web-provider:harness/providers/copilot_web.py`). Nada se envió a Copilot ni se abrió el navegador. Solo fixtures sintéticas.

Etiquetas: **[M]** medido aquí · **[C]** citado (fuente al final) · **[I]** inferencia, no medida. Cada afirmación lleva una. «Medido» quiere decir medido sobre las fixtures sintéticas del repo con `tiktoken` y una simulación del render; **nada de este estudio se midió contra Copilot real**, y el tokenizador de Copilot no es público.

**Estado y decisión (2026-11-26).** El dueño del proyecto decidió guardar este estudio y aplicar cuatro ahorros, que recoge el change `openspec/changes/prompt-economy/`: (1) pedir el JSON de `extract` en una sola línea; (2) cabeceras de nota más cortas en el bloque de memoria; (3) un aviso fijo del harness para que el modelo responda de forma concisa; (4) memoria por deltas dentro de una misma conversación remota (solo diseño por ahora). El hallazgo de que `innerText` quita los `##` de los encabezados (resumen, punto 7, y §4) es una **inferencia** sobre una simulación, **no** una medida con Copilot: se verifica aparte con una sonda sintética y este estudio no la da por cierta.

## Resumen (10 líneas)

1. **[M]** El harness **no envía JSON a Copilot**: memoria, entradas y plantillas ya van como texto/Markdown con marcas `<<<… nonce`. El único JSON del intercambio es la **respuesta** de `architecture-memory/extract` (~150–190 tokens).
2. **[M]** Un mensaje real del MVP ocupa **3 482–3 618 caracteres (≈11 % de los 32 000)**. De eso, el bloque de memoria es el 42–44 % y la frase propia del formato JSON son **89 caracteres (19 tokens)**.
3. **[M]** Para el objeto de decisión, YAML, TOON, `clave: valor` y secciones Markdown cuestan **lo mismo que JSON minificado (±1 %)**. El texto en español domina y la sintaxis pesa poco.
4. **[M]** El ahorro real en la respuesta es pedir **JSON minificado** en lugar de *pretty*: **−16 % a −21 % de tokens** (−29 a −31 tokens por respuesta), sin tocar el parser estricto.
5. **[M]** Explicar otro formato cuesta más de lo que ahorra: la regla de TOON son 72 tokens frente a 19 la de JSON, y la de `clave: valor` 55. En `extract`, **cambiar de formato da pérdida neta**.
6. **[M]** La respuesta se lee con `innerText` del Markdown ya renderizado. En la simulación (CommonMark más `innerText`), fuera de un bloque de código solo **JSON** sobrevive siempre; YAML no parsea y TOON, `clave: valor` y Markdown parsean con **datos distintos**.
7. **[I]** Hallazgo colateral, más grave que los tokens: `innerText` **quita los `##`** de los encabezados. El check `required_headings` de `hls-review` probablemente falle con Copilot real. **Es una inferencia sobre la simulación, no una medida con Copilot: se está verificando aparte con una sonda sintética.**
8. **[M]** Donde sí compensa un formato compacto es en los **datos estructurados que el harness envíe en el futuro** (resultados MCP/EA): con 20 filas uniformes, TSV/TOON/«columnas+filas» ahorran **22–28 % frente a JSON minificado** y **47–51 % frente a pretty** (hoy `mcp/render.py` usa `indent=2`).
9. **Recomendación.** En la respuesta: JSON estricto minificado (alternativa: el JSON actual). En el envío: no reenviar la memoria entera en cada turno y acortar las cabeceras de nota. Para datos tabulares futuros, una tabla compacta generada por el harness. El *pretty* solo para mostrar.
10. **No hacer:** YAML/TOON/TOML/CSV en respuestas que se validan, claves cortas o posicionales, ni binario en base64 (**+213 % a +297 % de tokens**).

## 1. Método

- **Payloads [M]:** `tests/fixtures/skill-inputs/decision-ok.json`, `tests/fixtures/mvp/decision-mock.json` (es la respuesta *mock* de `extract`), un bloque de memoria real construido con `harness.memory.context.build_context` sobre `tests/fixtures/vault-synthetic` (proyecto `demo-alpha`, tope 8 192 bytes), las plantillas reales renderizadas con `harness.skills.references.render` y dos casos sintéticos (20 registros uniformes `{id, fecha, estado, proyecto, titulo}` y un objeto anidado de 3 niveles con listas).
- **Tokens:** `tiktoken` 0.14.0, `o200k_base` y `cl100k_base`. **El tokenizador de Copilot no es público.** Estos números son una aproximación; lo que el harness controla de verdad son los **caracteres** (límite medido de unos 32 000 por mensaje). Por eso doy ambos.
- **Codificadores:** `json` stdlib; PyYAML 6.0.4 `safe_dump`; `tomli-w`; `toon-format` 1.2.0 (spec TOON 4.4); `msgpack` y `cbor2` más base64; y XML, S-expresiones, `clave: valor`, Markdown e INI escritos a mano.
- **Render [M, aproximado]:** `markdown-it-py` (CommonMark, HTML crudo escapado) más un `innerText` aproximado según la especificación HTML (`<p>` = 2 saltos, otros bloques = 1, `<li>` sin viñeta, espacios colapsados fuera de `<pre>`). **No es el renderizador de Copilot.** Sirve para mostrar el mecanismo, no como prueba.
- Scripts desechables de medición (tres ficheros de Python en un directorio temporal de la máquina de desarrollo, con su propio entorno virtual para `tiktoken`, PyYAML, `toon-format`, `msgpack`, `cbor2` y `markdown-it-py`). **No se versionan**: no son parte del harness ni de sus dependencias. Quien quiera repetir una cifra la reconstruye con la descripción de este apartado; el change `prompt-economy` repite las de cabeceras con el mismo método y deja su procedimiento en su `design.md`.

## 2. Tablas por payload [M]

«vs pretty» y «vs min» se calculan sobre tokens `o200k`. La línea base honesta es **JSON minificado**.

### 2.1 Respuesta de `extract`: `decision-ok.json`

| formato | chars | bytes | tok o200k | tok cl100k | vs pretty | vs min |
|---|---:|---:|---:|---:|---:|---:|
| json claves cortas | 414 | 418 | 92 | 109 | −38 % | −21 % |
| json posicional | 469 | 474 | 102 | 120 | −31 % | −13 % |
| yaml bloque | 523 | 528 | 116 | 135 | −22 % | −1 % |
| **json minificado** | 542 | 547 | **117** | 133 | −21 % | 0 % |
| toon | 521 | 526 | 117 | 135 | −21 % | 0 % |
| clave: valor (RFC-822) | 540 | 545 | 118 | 136 | −20 % | +1 % |
| markdown secciones | 540 | 545 | 118 | 137 | −20 % | +1 % |
| ini | 532 | 537 | 121 | 139 | −18 % | +3 % |
| s-expresiones | 542 | 547 | 123 | 140 | −17 % | +5 % |
| toml | 572 | 577 | 131 | 148 | −11 % | +12 % |
| json minificado ASCII (`á`) | 567 | 567 | 135 | 150 | −9 % | +15 % |
| **json pretty (indent 2)** | 601 | 606 | **148** | 165 | 0 % | +26 % |
| xml | 620 | 625 | 153 | 168 | +3 % | +31 % |
| cbor+base64 | 700 | 700 | 463 | 494 | +213 % | +296 % |
| msgpack+base64 | 700 | 700 | 465 | 498 | +214 % | +297 % |

### 2.2 Respuesta *mock* del MVP: `mvp/decision-mock.json`

| formato | chars | bytes | tok o200k | tok cl100k | vs pretty | vs min |
|---|---:|---:|---:|---:|---:|---:|
| json claves cortas | 604 | 609 | 140 | 154 | −25 % | −11 % |
| json posicional | 622 | 628 | 142 | 157 | −24 % | −10 % |
| yaml bloque | 676 | 682 | 155 | 171 | −17 % | −1 % |
| clave: valor | 681 | 687 | 155 | 170 | −17 % | −1 % |
| **json minificado** | 695 | 701 | **157** | 170 | −16 % | 0 % |
| toon | 676 | 682 | 157 | 173 | −16 % | 0 % |
| markdown secciones | 693 | 699 | 157 | 173 | −16 % | 0 % |
| ini | 686 | 692 | 160 | 175 | −14 % | +2 % |
| s-expresiones | 695 | 701 | 162 | 176 | −13 % | +3 % |
| toml | 720 | 726 | 169 | 183 | −9 % | +8 % |
| json ASCII | 725 | 725 | 181 | 193 | −3 % | +15 % |
| **json pretty** | 749 | 755 | **186** | 200 | 0 % | +18 % |
| xml | 769 | 775 | 189 | 201 | +2 % | +20 % |
| cbor/msgpack+base64 | 908 | 908 | 601–602 | 647–648 | +223 % | +283 % |

### 2.3 Sintético: 20 registros uniformes (5 campos escalares)

| formato | chars | bytes | tok o200k | tok cl100k | vs pretty | vs min |
|---|---:|---:|---:|---:|---:|---:|
| tsv | 1 787 | 1 847 | 575 | 601 | −51 % | −28 % |
| csv | 1 787 | 1 847 | 581 | 606 | −51 % | −27 % |
| json columnas+filas `{"cols":[…],"rows":[[…]]}` | 2 016 | 2 076 | 613 | 642 | −48 % | −23 % |
| toon (tabular `[20]{…}:`) | 1 833 | 1 893 | 624 | 649 | −47 % | −22 % |
| tabla markdown | 2 060 | 2 120 | 637 | 677 | −46 % | −20 % |
| **json minificado** | 2 796 | 2 856 | **798** | 828 | −32 % | 0 % |
| clave: valor por bloques | 2 513 | 2 573 | 814 | 854 | −31 % | +2 % |
| yaml bloque | 2 735 | 2 795 | 895 | 935 | −24 % | +12 % |
| s-expresiones | 2 796 | 2 856 | 895 | 925 | −24 % | +12 % |
| toml (`[[r]]`) | 2 894 | 2 954 | 955 | 985 | −19 % | +20 % |
| json ASCII | 3 096 | 3 096 | 1 058 | 1 108 | −10 % | +33 % |
| xml | 3 382 | 3 442 | 1 095 | 1 124 | −7 % | +37 % |
| **json pretty** | 3 517 | 3 577 | **1 177** | 1 207 | 0 % | +47 % |
| msgpack/cbor+base64 | 3 288–3 292 | 3 288–3 292 | 2 123–2 153 | 2 296–2 339 | +80 % | +166 % |

### 2.4 Sintético: objeto anidado (sistema → 3 componentes → interfaces → consumidores)

| formato | chars | bytes | tok o200k | tok cl100k | vs pretty | vs min |
|---|---:|---:|---:|---:|---:|---:|
| markdown secciones | 971 | 976 | 249 | 274 | −44 % | −4 % |
| **json minificado** | 889 | 894 | **260** | 243 | −42 % | 0 % |
| yaml bloque | 1 016 | 1 021 | 265 | 297 | −40 % | +2 % |
| toon | 1 081 | 1 086 | 269 | 298 | −40 % | +3 % |
| json ASCII | 914 | 914 | 279 | 263 | −37 % | +7 % |
| s-expresiones | 889 | 894 | 281 | 272 | −37 % | +8 % |
| toml | 1 212 | 1 217 | 360 | 351 | −19 % | +38 % |
| **json pretty** | 1 805 | 1 810 | **445** | 436 | 0 % | +71 % |
| xml | 1 328 | 1 333 | 445 | 425 | 0 % | +71 % |
| clave: valor (claves con puntos) | 1 768 | 1 773 | 500 | 513 | +12 % | +92 % |
| msgpack/cbor+base64 | 968 | 968 | 644–648 | 690–699 | +45 % | +148 % |

Con `cl100k`, JSON minificado gana a todos en el anidado (243). TOON pierde frente a JSON minificado en anidado, como reconocen sus propios autores **[C1]**.

### 2.5 Dónde van los caracteres de un mensaje real [M]

Mensaje = `compose_prompt(bloque de memoria, render(plantilla, entrada))`, tal como lo construye `engine._llm`.

| parte | extract + `fuente-decision.md` | extract + `decision-persona.md` | hls-review + `requerimiento-1` |
|---|---:|---:|---:|
| **mensaje completo** | **3 482 ch / 936 tok (10,9 % de 32 000)** | **3 559 / 957 (11,1 %)** | **3 618 / 971 (11,3 %)** |
| bloque de memoria (7 notas) | 1 537 / 455 (44 %) | 1 537 / 455 (43 %) | 1 537 / 455 (42 %) |
| · de ello, cabeceras `--- nota: …` | 527 / 187 (15 %) | 527 / 187 | 527 / 187 |
| aviso `DATA_NOTICE` | 227 / 54 (7 %) | 227 / 54 | 227 / 54 |
| plantilla (sin la entrada) | 1 206 / 294 (35 %) | 1 206 / 294 | 1 015 / 248 (28 %) |
| · lista de campos + regla de formato | 573 / 148 (16 %) | 573 / 148 | n/a |
| · de ello, la frase propia de JSON | 89 / 19 | 89 / 19 | n/a |
| entrada de la persona | 444 / 108 | 521 / 129 | 769 / 189 |

- La memoria sintética usa 1 556 de los **8 192 bytes** del tope por defecto (`CONTEXT_DEFAULT_BYTES`). Con un vault real lleno, el bloque puede llegar a **~8 000 caracteres = 25 % del presupuesto en cada mensaje [I]**. Además se **reenvía entero en cada pregunta** de la misma conversación, como ya señala `docs/estudios/2026-11-25-arquitectura-opencode.md`.
- Las cabeceras `--- nota: projects/demo-alpha/sessions/2026-11-21-121500.md (session, 2026-11-21)` cuestan ~75 caracteres por nota. Una forma más corta (`## sessions/2026-11-21-121500 2026-11-21`, sin el prefijo del proyecto, sin `.md` y sin repetir el tipo) baja de **527 a 299 caracteres (−228 ch, −59 tok, −43 %)** en estas 7 notas **[M]**.
- Las respuestas *mock* miden 627 caracteres / 156 tokens (hls-review) y 750 / 186 (extract en *pretty*). La respuesta **no cuenta para el límite de 32 000**, que es de entrada. Solo influye en la latencia y en el tope de lectura de 200 000 caracteres **[I]**.

### 2.6 Coste de explicar el formato al modelo [M]

Solo la frase de formato. La lista de campos (title ≤ 120, etc.) la necesitan todos los formatos por igual.

| regla | chars | tok o200k | extra vs JSON actual |
|---|---:|---:|---:|
| JSON (actual: «Devuelve solo un objeto JSON…») | 89 | 19 | — |
| JSON en un único bloque ```json | 123 | 26 | +7 |
| Markdown secciones `## campo` y `- ` | 145 | 36 | +17 |
| YAML en bloque, textos entre comillas | 154 | 41 | +22 |
| `campo: valor`, repetir campo por elemento, línea final `fin: ok` | 228 | 55 | +36 |
| TOON (sintaxis `[N]`, comillas y escapes) | 277 | 72 | +53 |

En `extract` ningún formato alternativo ahorra más de 2 tokens frente a JSON minificado (§2.1 y §2.2). **Todos dan pérdida neta** una vez sumada su explicación. JSON no necesita explicarse: el modelo ya lo conoce.

## 3. Comportamiento de los parsers [M]

| prueba | resultado |
|---|---|
| YAML `pais: NO` | `False` (el «problema de Noruega», YAML 1.1 de PyYAML) |
| YAML `version: 1.10` | `1.1` (float) |
| YAML `fecha: 2026-11-26` | `datetime.date` (no `str`) |
| YAML `hora: 12:30:00` | `45000` (sexagesimal) |
| YAML `a: 1\na: 2` | `{'a': 2}`: la clave duplicada se acepta y gana la última |
| YAML `titulo: Decisión: usar cola` | `ScannerError` (un `: ` dentro de un texto sin comillas rompe) |
| TOML clave duplicada (`tomllib`) | error (bien) |
| TOON clave duplicada | error (bien) |
| TOON campo desconocido `extra: x` | se acepta: lo tiene que rechazar el validador (igual que hoy con JSON) |
| TOON `[2]` con 3 elementos (coma sin comillas) | error «Declared length 2 but found 3» (bien) |

**Truncado** (corte en fin de línea al 50 % y al 85 %):

| formato | decisión | 20 filas |
|---|---|---|
| JSON (pretty y min) | **error** en los dos cortes | **error** |
| YAML | parsea (truncado invisible) | parsea |
| TOON | parsea (los objetos no llevan longitud) | **error** (la longitud `[20]` lo delata) |
| `clave: valor` / Markdown secciones | parsea | n/a |

Con JSON, una respuesta cortada siempre falla. Con los formatos por líneas, cortar justo antes de `assumptions` (que es opcional) o a mitad de una lista pasa el validador. Detectarlo exigiría una línea de cierre (`fin: ok`), y eso se suma al coste de explicar el formato.

## 4. Supervivencia en la UI de chat [M aproximado + I]

`copilot_web.py` lee la respuesta con **`innerText`** del turno renderizado (diseño de copilot-web-provider, línea 223; «copiar el Markdown original» es un *non-goal*). Simulación con el objeto `decision-ok`:

| formato | sin bloque, salto = espacio | sin bloque, salto = `<br>` | dentro de ```` ``` ```` |
|---|---|---|---|
| json minificado | sobrevive | sobrevive | sobrevive |
| json pretty | sobrevive (los saltos colapsan, sigue siendo JSON válido) | sobrevive | sobrevive |
| yaml | **no parsea** | **no parsea** (las `- ` se vuelven `<li>` sin viñeta) | sobrevive |
| toon | **parsea, datos distintos** | sobrevive | sobrevive |
| clave: valor | **parsea, datos distintos** (líneas unidas) | sobrevive | sobrevive |
| markdown secciones | **parsea, datos distintos** (`##` y `- ` desaparecen) | idem | sobrevive |

- **[M, en la simulación]** El énfasis también rompe JSON fuera de un bloque: `"Usar snake_case_id y *cola* gestionada"` se lee como `… y cola gestionada`. JSON sigue parseando, pero el dato cambia sin aviso. Dentro de un bloque de código no pasa.
- **[M, solo en la simulación]** `## Resumen` se lee con `innerText` como `Resumen`, sin `##`, y `checks._headings` exige `#`. **[I, pendiente de la sonda que lo verifica aparte]** Si Copilot renderiza así los encabezados (lo normal), **`hls-review` fallará con `validation_failed:required_headings`** con el proveedor real. Hay que verificarlo con una respuesta sintética antes de nada más. Es un problema de corrección, no de tokens.
- **[I]** Dentro de un bloque de código, la UI de Copilot suele poner una cabecera con el lenguaje y un botón «Copiar». Si ese texto entra en `innerText` (no está oculto con 1 px), la respuesta llega como `json\nCopiar\n{…}`, sin las líneas ```` ``` ```` (que nunca llegan a `innerText`). Entonces `_json_body` no encuentra el bloque y `loads_strict` falla. **No verificado**: hace falta una sonda sintética.
- **[I]** En el envío, `composer.fill()` escribe en un editor enriquecido. Una sangría inicial (YAML/TOON anidado) o un tabulador (TSV) pueden alterarse o colapsar. Para el envío, eso favorece formatos sin sangría significativa: JSON minificado, CSV o `|`.

## 5. Cada candidato frente a lo que importa aquí

| candidato | tamaño vs JSON min (obj / tabla / anidado) | explicación | emisión fiable (evidencia) | UI / `innerText` | parser stdlib estricto | inyección / truncado | veredicto |
|---|---|---|---|---|---|---|---|
| **JSON minificado** | 0 / 0 / 0 | 19 tok, conocido | el mejor en generación plana **[C3]**; Text→JSON 81 de media **[C4]** | robusto incluso sin bloque | `json` + `strict_json` (ya existe) | duplicados, NaN y profundidad ya rechazados; truncado → error | **Respuesta: sí** |
| JSON claves cortas / posicional | −11…−21 % / −23 % (cols+filas) | +campos a explicar | [I] más errores de mapeo (orden o letra equivocados) | igual que JSON | igual | posicional: un elemento desplazado pasa como otro campo | respuesta: no; envío tabular: aceptable |
| YAML | −1 % / +12 % / +2 % | +22 tok | Text→YAML 79 **[C4]**; [M] Noruega, fechas, `: ` | no parsea fuera de bloque | **no hay en stdlib**; un parser propio seguro no es pequeño | duplicados aceptados, multi-documento `---`, anclas/alias; truncado invisible | **no** |
| YAML «plano» restringido (propio) | ≈ `clave: valor` | +36 tok | [I] el modelo deriva a YAML completo | igual que YAML | parser propio de ~60 líneas | truncado invisible sin centinela | no compensa |
| TOML | +8–12 % / +20 % / +38 % | ? | Text→TOML 42 de media, el peor **[C4]** | frágil | `tomllib` (solo lectura, rechaza duplicados) | `[tabla]` inyectada | **no** |
| TOON 4.4 | 0 % / −22 % / +3 % | +53 tok | proveedor: +0,8 pp en lectura **[C1]**; independientes: mezclado o peor **[C2][C3][C5]** | sin bloque, datos distintos | **no en stdlib**; librería de terceros o parser propio (spec larga) | acepta campos extra; truncado detectado solo en tablas `[N]` | respuesta: **no**; envío tabular: posible |
| CSV/TSV | n/a / −27…−28 % / n/a | corta para tablas | Text→CSV 89 **[C4]** (tablas simples) | en bloque sí; fuera, las líneas se unen | `csv` (laxo: no valida columnas) | comas, comillas o saltos sin escapar desplazan columnas | envío tabular: sí; respuesta con texto libre: no |
| `clave: valor` / RFC-822 | +1 % / +2 % / +92 % | +36 tok | [I] razonable | depende de los `<br>` | `email.parser` no sirve (pliegues, duplicados); propio de ~40 líneas | sin centinela, truncado invisible | no compensa |
| Markdown secciones | +1 % / n/a / −4 % | +17 tok | el modelo lo emite de forma natural | **`##` y `- ` se pierden con `innerText`** | propio (ya existe para encabezados) | el texto puede traer su propio `## campo` | solo para prosa (hls-review), y hay que revisar §4 |
| XML / pseudo-XML | +20–31 % / +37 % / +71 % | +tags | Text→XML 61 **[C4]** | HTML crudo escapado o eliminado | `xml.etree` (sin XXE en 3.14, pero sin esquema) | etiquetas inyectadas | **no** |
| INI | +2–3 % | +? | [I] listas sin estándar | frágil | `configparser` (interpolación, pliegues) | `[sección]` inyectada | no |
| S-expresiones | +3–5 % / +12 % / +8 % | +? | [I] poco entrenado | `(` y `"` sobreviven | propio | — | no |
| MessagePack/CBOR + base64 | **+166…+297 %** | — | el modelo no puede escribirlo con fiabilidad | — | — | — | **descartado (números en §2)** |

## 6. Por dirección: dónde está el ahorro

### Harness → Copilot (lo controla el harness, nada lo vuelve a parsear)

- **[M]** Hoy no viaja JSON. El texto está en memoria, avisos y plantillas. Ahorros posibles, de mayor a menor:
  1. **No reenviar el bloque de memoria entero en cada turno** de la misma conversación: hasta ~8 000 caracteres por mensaje (25 % del límite) con un vault real **[I]**. El diseño ya está esbozado en el estudio de OpenCode (deltas por hash con `request_context`).
  2. **Cabeceras de nota más cortas:** −33 caracteres por nota (−43 % de las cabeceras) **[M]**.
  3. Avisos (`NOTICE` + `DATA_NOTICE` ≈ 380 caracteres): margen pequeño. No los recortaría, porque son la defensa contra la inyección **[I]**.
- **Futuro (resultados MCP/EA enviados a Copilot):** `mcp/render.py` serializa con `indent=2`. Pasar a minificado ahorra **32 % (tabla) y 42 % (anidado)** de tokens **[M]**. Para arrays uniformes, una tabla compacta ahorra otro **22–28 %** sobre minificado **[M]**. Coincide con lo que publican los autores de TOON y con el informe de Apify: la ganancia está en lo tabular, y en anidado sale igual o peor **[C1][C2]**.

### Copilot → harness (se parsea, valida, canonicaliza y su hash se aprueba)

- **[M]** El formato apenas importa en tamaño: ±1 % entre JSON minificado, YAML, TOON y `clave: valor`. Lo que se gana es **el espaciado**: *pretty* → minificado = −29/−31 tokens por respuesta. La frase actual no fija el espaciado, y el parser estricto acepta los dos.
- La respuesta no cuenta para los 32 000. El ahorro en salida es latencia, no presupuesto **[I]**.
- Cambiar a otro formato cuesta: un parser nuevo (YAML/TOON no están en stdlib), una explicación más larga, truncado invisible y supervivencia peor en `innerText`. Y lo que se aprueba seguiría siendo JSON canónico (`checks.py` y `approvals.py`), así que no se gana nada aguas abajo.

**Cambio con mayor ahorro y menor riesgo:** en el envío, memoria por deltas, y además cabeceras cortas, que son triviales. En la respuesta, pedir JSON en una sola línea, una frase sin tocar código.

## 7. Recomendación

| dirección | principal | alternativa |
|---|---|---|
| **Respuesta (Copilot → harness)** | **JSON estricto, minificado.** Cambiar en `skills/architecture-memory/templates/extract.md` la regla de formato a «un objeto JSON en una sola línea, sin espacios fuera de los textos». Sin código nuevo: `loads_strict` y `checks._json` siguen igual. Test: una respuesta *mock* minificada en `tests/fixtures/mvp/respuestas-mock.json` (el *pretty* actual debe seguir pasando). | **El JSON actual** (*pretty*): cuesta +16–21 % de una respuesta de ~150 tokens, nada relevante. Si una sonda demuestra que `innerText` mete la cabecera del bloque de código, mejor pedir JSON **sin** bloque (sobrevive en la simulación) que cambiar de formato. |
| **Envío (harness → Copilot)** | **Memoria por deltas en la misma conversación** (cambio de diseño en `memory/context.py`, `core/service.py`, con decisión en el spec `memory-vault`; tests de «nota sin cambios no se reenvía»). Además, **cabeceras cortas** en `context._render` (tocar los tests que fijan el formato de cabecera). | Si los deltas no se aprueban: solo las cabeceras cortas y bajar `HARNESS_MEMORY_CONTEXT_MAX_BYTES` por proyecto. |
| **Datos estructurados futuros** (MCP/EA → Copilot) | **JSON minificado** por defecto para lo que vaya al modelo (`mcp/render.py` puede seguir con `indent=2` para la terminal). | Para arrays uniformes de ≥ ~10 filas, una **tabla compacta generada por el harness**: «columnas+filas» en JSON (−23 %, sin explicación, parser stdlib si alguna vez vuelve) o **TOON tabular / tabla `|`** con un codificador propio de ~30 líneas (−20…−22 %). Sin dependencia nueva. Sin tabuladores (TSV) por el riesgo de `fill()` en el editor. |

**Antes de todo (corrección, no tokens):** una sonda sintética con el proveedor real que pida (a) una respuesta con `## Resumen` y (b) un bloque ```json, y registre qué devuelve `innerText`. Si los `##` desaparecen, `hls-review` necesita otra regla: encabezados como texto plano, o validar la línea exacta del encabezado sin `#`. Esa decisión de diseño va en `skill-engine` D6.

**Lo que se pierde:** con minificado, la respuesta es menos legible en la página (el harness ya la canonicaliza, así que da igual). Con cabeceras cortas, el tipo de nota deja de ser visible para el modelo (se puede mantener con 1–2 tokens). Con deltas, la conversación depende del historial de Copilot, que el harness no controla. Por eso hace falta un reenvío completo cuando no consten turnos completados.

**No hacer:**
- YAML en respuestas: sin parser en stdlib, Noruega, duplicados aceptados, truncado invisible, no sobrevive fuera de bloque.
- TOON en respuestas: no ahorra en objetos, explicarlo cuesta +53 tokens, sin stdlib, y la evidencia independiente de generación es floja.
- TOML: el peor en generación **[C4]** y +8–38 % más largo.
- XML: +20–71 %.
- Claves cortas o posicionales en respuestas: ahorran ~20 tokens a cambio de errores de mapeo silenciosos.
- CSV para texto libre: comas, comillas y saltos.
- Binario en base64: 3–4 veces más tokens.
- Recortar los avisos anti-inyección para ganar caracteres.

## 8. Fuentes

- **[C1]** toon-format/toon, README y benchmark (**del proveedor**). Spec v4.4. 244 preguntas de recuperación, 4 modelos, `o200k_base`. TOON 72,2 % frente a JSON 71,4 % de acierto. Mixto: TOON **+1,6 %** de tokens frente a JSON compacto. Solo tabular: −35,2 % frente a JSON compacto y +5,9 % frente a CSV. Los autores advierten: «For deeply nested or non-uniform data, JSON may be more efficient». Mide **lectura**, no generación. https://github.com/toon-format/toon (consultado el 2026-11-26).
- **[C2]** Kopecky y Spilka (Apify), «We added TOON to our MCP server, then removed it», 2026-10-30 (**independiente, usuario en producción**). Tablas planas: −35,3 %. Anidado o semiuniforme: +14,7 % frente a JSON compacto. A/B con Claude Haiku 4.5: diferencias menores que el ruido entre ejecuciones. Revertido a JSON. https://aaif.io/blog/we-added-toon-to-our-mcp-server-then-removed-it
- **[C3]** I. Matveev, «Token-Oriented Object Notation vs JSON: A Benchmark of Plain and Constrained Decoding Generation», arXiv:2603.03306, 2026-02-08 (**independiente, generación**). JSON plano da el mejor acierto a la primera y final. El ahorro de TOON se lo come el «prompt tax» en contextos cortos. Solo leí el resumen. https://arxiv.org/abs/2603.03306
- **[C4]** StructEval, arXiv:2505.20139 v3 (ICLR 2026), tabla 8, generación StructEval-T. Medias de 12 modelos calculadas a partir de la tabla: CSV 88,9; JSON 81,3; YAML 79,1; XML 60,6; TOML 42,2. Son modelos de 2024–2025, no Copilot. https://arxiv.org/html/2505.20139v3
- **[C5]** Kutschka y Geiger, arXiv:2605.29676 (mayo de 2026), uso agéntico de herramientas: hasta −18 % de tokens con hasta −9 pp de acierto frente a JSON, y peor en varios turnos. **Citado a través de [C2] y del buscador; no lo leí.** https://arxiv.org/abs/2605.29676
- Análisis crítico en DEV Community (no revisado por pares): https://dev.to/ikaganacar/toon-benchmarks-a-critical-analysis-of-different-results-5h66
- Repo: `harness/core/strict_json.py`, `harness/skills/checks.py`, `harness/memory/context.py`, `harness/skills/references.py`, `harness/skills/engine.py` (`_llm`, `_values`), `harness/mcp/render.py`, `harness/memory/config.py` (`CONTEXT_DEFAULT_BYTES = 8192`), `skills/*/workflow.json` y plantillas, `openspec/changes/copilot-web-provider/design.md` (líneas 55 y 223, rama `feature/copilot-web-provider`), `docs/estudios/2026-11-25-arquitectura-opencode.md`.
