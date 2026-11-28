# Design

## Context

El motivo y las cifras están en `proposal.md` («Why») y en `docs/estudios/2026-11-27-code-mode.md`, que es la base de este diseño. Su §10.1 recoge lo que el dueño decidió el 2026-11-27:
- un plan JSON interpretado por el harness; Monty no se adopta;
- la aprobación de un plan de solo lectura: con botón en la pantalla completa y con código en el modo plano y en la CLI, siempre ligada al hash exacto;
- el resultado, solo para la persona en el primer corte.

Lo que ya existe y sobre lo que se construye. Cada premisa se midió aquí, en `origin/develop` = `79cde60`:

| Pieza | Dónde | Medido aquí |
|---|---|---|
| Política sin servidor: los motivos 2 a 6 se deciden sin arrancar nada | `harness/mcp/policy.py`, `decide_before_start`, `check_arguments` | Reutilizada tal cual. Los 54 casos de rechazo de `tests/unit/test_mcp_plan.py` pasan sin cambiar la política. |
| JSON estricto | `harness/core/strict_json.py`, `loads_strict` | Casi todo lo que el plan necesita ya se rechazaba; la excepción era un número fuera de rango (`1e400`), que leía como `inf` (revisión independiente, D4). Rechazaba: duplicados, `NaN`/`Infinity`, datos tras el valor, BOM, clave no cadena, control crudo en una cadena, entero de más de 4 300 cifras y profundidad. Faltaban dos cosas: decir **qué** rechazó sin leer el mensaje, y un tope de profundidad más estricto que 32. Además **acepta** `"\ud800"` (sustituto suelto), comprobado con `loads_strict('"\\ud800"')`. El plan lo rechaza aparte (D5). |
| Vallas como las lee CommonMark | `harness/skills/checks.py`, `_split` | Una valla dentro de una cita (`> ```json`) o sangrada 4 espacios **no** es valla para este analizador, igual que para CommonMark. Lo prueban los casos `a plan inside a quote` y `a plan indented as code`. Un bloque `json` dentro de un bloque ```` ````markdown ```` es cuerpo del exterior, no bloque propio. |
| Hash de aprobación con dominio y contenido normalizado | `harness/skills/approvals.py`: `Proposal`, `proposal_hash`, `normalise_content`, `is_invisible` | `is_invisible` se reutiliza. La `Proposal` se usa en el tramo 2. |
| Caja de aprobación de la pantalla completa | `harness/shell/tui.py`: `open_approval(header, content, approval_hash, question)`, `ButtonPress`/`Verdict(means)` | Tramo 2. |
| Nonce por pregunta | `harness/memory/context.py`: `new_nonce`, 16 hexadecimales | El plan usa el mismo formato. `harness/core/service.py` no genera ningún nonce por solicitud: lo genera quien compone el prompt. |
| Estados de una respuesta | `harness/core/contracts.py`: `LLMResponse.status`, `.truncated` | `read_plan_reply` los mira antes de leer. |

## Goals / Non-Goals

**Goals:**
- Que un plan sea un dato cerrado y comprobable entero antes de ejecutar nada. Las llamadas posibles se conocen exactamente de antemano.
- Que lo leído, lo mostrado, lo hasheado, lo aprobado y lo ejecutado sean los mismos bytes.
- Que cada rechazo tenga un motivo estable, de una lista cerrada, que se pueda contar en la medición del tramo 3.

**Non-Goals:**
- Expresividad. Lo que no cabe en una lista de llamadas literales necesita otra pregunta; el tramo 3 mide si eso pesa.
- Reconocer un plan en una respuesta «casi bien escrita». Cero tolerancia, como en `fundamentos-de-un-harness.md` §14.

## Decisions

### D1. Plan JSON interpretado por el harness, en `harness/mcp/plan.py`

- **Qué.** El plan es un objeto JSON y el harness es su único intérprete. El lector vive en `harness/mcp/plan.py`, junto a la política que reutiliza. Es una función pura: `read_plan(text, *, nonce, config)` y `read_plan_reply(response, *, nonce, config)` devuelven `Plan`, `Refusal` o `NoPlan`.
- **Por qué.**
  - Lo decidió el dueño (estudio §10.1, 2).
  - Junto a la política, el plan no puede acabar con una lista de herramientas distinta de la de `mcp call`.
  - Pura, se prueba con textos de fixture sin servidor ni reloj.
- **Alternativas rechazadas.**
  - Un paquete `harness/plans/`: un nivel más para un módulo de unos 300 renglones; la ejecución del tramo 2 vive igualmente en `harness/mcp/`.
  - Leer el plan dentro de `conversation.py`: mezcla la interfaz con la validación y obliga a probar con la conversación entera.
  - Monty, Python en subproceso, WASM o Deno: descartados en el estudio §4, por las reglas del proyecto y por decisión del dueño.
- **Impacto.** Spec `code-mode`, requisito «Leer un plan no tiene efectos»; tareas 2.x. SEC-14 no cambia: no hay código que ejecutar.

### D2. Esquema de la versión 1: lista de llamadas literales, sin referencias

- **Qué.**

  ```json
  {
    "format": "ai-harness/plan/1",
    "nonce": "0123456789abcdef",
    "steps": [
      {"id": "a", "server": "synthetic", "tool": "get_project_metadata", "args": {"project": "demo-alpha"}},
      {"id": "b", "server": "synthetic", "tool": "get_project_metadata", "args": {"project": "demo-beta"}}
    ]
  }
  ```

  El modelo es pydantic cerrado (`extra="forbid"`, `strict=True`):
  - `format` es exactamente `ai-harness/plan/1`;
  - `nonce` es una cadena;
  - `steps` tiene de 1 a 10 pasos;
  - cada paso: `id` (`[a-z][a-z0-9_]{0,15}`, único), `server` y `tool` (1 a 64 caracteres; la lista local decide si existen) y `args` (objeto de hasta 64 claves, `{}` si falta);
  - cada valor de argumento es un literal, que la política comprueba contra el tipo declarado (cadena, entero, booleano o enumerado).

  No hay `$ref`, `for_each`, `select`, `return` ni expresiones. Un argumento con forma `{"$ref": ...}` se rechaza con su propio motivo, `reference_not_supported`, para que la medición distinga «el modelo quiso encadenar» de «el modelo se equivocó de tipo».
- **Por qué no hay referencias en la versión 1.**
  - Una referencia a un campo (`a.status`) solo se puede validar si se conoce la forma del resultado. La lista local no la declara: es la decisión abierta 5 (`result_fields`). El esquema que manda un servidor es dato no confiable y no se evalúa (`policy.py`, `matches_shape`). Sin forma declarada, la referencia se comprobaría solo al ejecutar, y el plan dejaría de ser «validado entero antes de ejecutar».
  - Una referencia hace que un valor leído de un servidor viaje como argumento a otra llamada. Es exactamente la vía de exfiltración de SEC-05 que el estudio deja como resto («una lectura con un argumento de texto libre largo puede sacar datos hacia ese servidor»). Sin referencias, todo argumento es visible en la aprobación.
  - En los tramos 1 y 2 el resultado va solo a la persona, así que `return`/`select` no ahorran ningún envío.
  - Para la tarea tipo del estudio (§2.2, comparar dos proyectos) basta una lista de lecturas.
- **Alternativas rechazadas.**
  - `{"$ref": "paso.campo"}` desde el tramo 1, como esbozaba el estudio §4.2: no es validable sin `result_fields` (arriba).
  - `{"$ref": "paso"}`, el resultado entero como valor: un resultado MCP es texto o JSON de hasta 64 KiB y ningún argumento declarado lo admite. Siempre daría `argument_invalid`.
  - Un campo `call: "servidor.herramienta"`: obliga a partir una cadena. Dos campos son un dato cerrado y el error dice cuál falla.
- **Impacto.** Spec «Esquema cerrado de la versión 1». Un tramo posterior que añada referencias publica `ai-harness/plan/2` (un plan con otro `format` se rechaza con `unsupported_format`), exige `result_fields` en la lista y solo admite referencias a pasos **anteriores** y a campos declarados.

### D3. Cómo se encuentra el plan en la respuesta

- **Qué.**
  1. El texto se lee con las vallas de `checks.py` (`split_fences`, el mismo `_split` con nombre público), tras normalizar CRLF y CR a LF.
  2. Un bloque es `json` si la primera palabra de su etiqueta, sin distinguir mayúsculas, es `json`.
  3. Hay plan si hay exactamente un bloque `json` y está cerrado.
  4. Si no hay ningún bloque `json`, se busca el nonce: dentro de otro bloque da `wrong_language`; fuera de todo bloque (cita, sangrado o prosa) da `plan_outside_block`; en ningún sitio, `NoPlan`, que es la respuesta final.
  5. Dos o más bloques `json` dan `too_many_blocks`; uno sin cerrar, `block_not_closed`.
  6. La respuesta entera se limita a 200 000 caracteres (`reply_too_large`), el mismo tope de lectura del proveedor (`REPLY_MAX_CHARS`).
  7. **El nonce aparece una sola vez en toda la respuesta** (revisión independiente de `38683ac`, hallazgo 3). Una vez elegido el único bloque `json`, si el nonce aparece más de una vez, la respuesta se rechaza con `nonce_elsewhere`. Da igual dónde esté la segunda aparición: una cita, un comentario HTML, `<details>`, un elemento de lista, la prosa o el propio bloque.
     - **El ataque que cierra:** las vallas dentro de una cita o de un comentario no cuentan como bloque. Una respuesta con `> ```json` (plan B) seguida de un bloque real (plan A) daba el plan A, mientras la respuesta pintada podía mostrar el B.
     - **El falso negativo que acepta:** un modelo que repite el nonce en la prosa ve su plan rechazado. El prompt del tramo 2 dice que no lo repita.

  El nonce va **dentro** del cuerpo, en el campo `nonce`: la línea de apertura solo admite la etiqueta de lenguaje (estudio §3, `REPLY_TEXT_JS`).
- **Por qué.**
  - Un bloque `json` sin nonce es un intento de plan, no una respuesta final: se rechaza con `nonce_missing` y el texto se sigue mostrando a la persona.
  - Un nonce fuera de un bloque válido delata un plan mal colocado. Mejor decirlo que tomarlo por respuesta final: la medición del tramo 3 lo cuenta.
  - El mismo analizador que los Skills hace que «bloque» signifique lo mismo en todo el harness.
- **Alternativas rechazadas.**
  - Buscar JSON en cualquier parte del texto: el énfasis y las listas de la página alteran el texto fuera de un bloque (estudio §3).
  - Tomar el primer bloque `json` e ignorar los demás: con dos bloques no se sabe cuál quiso el modelo, y un resultado citado podría colar el segundo.
  - Aceptar `jsonc` o `json5`: otra gramática; `loads_strict` no la lee.
  - Leer CommonMark completo (listas, citas con vallas dentro): más superficie. Un plan legítimo no necesita ir en una cita.
- **Impacto.** Spec «Un plan por respuesta, en un único bloque json» y «Una respuesta incierta o truncada nunca se analiza». `checks.py` solo gana un nombre público, sin cambio de conducta.

### D4. JSON estricto y límites

- **Qué.** `loads_strict` gana:
  - `StrictJsonError(InvalidInput)` con `kind` ∈ {`too_large`, `too_deep`, `duplicate_key`, `not_finite`, `not_json`}, con los mismos mensajes que antes;
  - un `parse_float` que rechaza como `not_finite` un número fuera del rango de `float`, como `1e400` o `-1e400` (revisión independiente, hallazgo 1). `json.loads` lo convertía en `inf` sin pasar por `parse_constant`, y después `canonical_json(allow_nan=False)` lanzaba `ValueError`: `read_plan` no devolvía una lectura. Un número así nunca fue legítimo en ningún llamador. Para la misma entrada, los mensajes existentes no cambian;
  - además, un sustituto suelto **crudo** en el bloque (no el escape `\ud800`) hacía lanzar `UnicodeEncodeError` al medir el tamaño. El lector lo rechaza antes, con `invisible_character`. Un test de 3 000 mutaciones hostiles con semilla fija comprueba que `read_plan` siempre devuelve una lectura;
  - `max_depth`, que solo puede bajar el tope de 32.

  El plan usa `max_bytes = 16 KiB` y `max_depth = 6`: plan, pasos, paso, argumentos, valor, y un nivel de margen para que `{"$ref": …}` llegue a su propio motivo.

  Límites: 10 pasos, 64 argumentos por paso, 16 KiB de plan. El `args_too_large` de la pasarela (16 KiB) no puede darse dentro de un plan, y una aserción al importar lo fija (`MAX_PLAN_BYTES <= MAX_ARGS_BYTES`).
- **Por qué.**
  - Con un `kind` el motivo se decide sin analizar mensajes, que pueden cambiar.
  - 16 KiB es la mitad del prompt máximo aceptado por Copilot (32 000 caracteres, `copilot-web-provider/tasks.md` 3.2) y el mismo tope que los argumentos de `mcp call`.
  - 10 pasos es el ejemplo del estudio (§8, SEC-15) y cubre la tarea de 5–10 lecturas de §2.2.
- **Alternativas rechazadas.**
  - Un segundo lector JSON propio: duplicaría lo revisado.
  - Distinguir motivos por el texto del mensaje: frágil.
  - Profundidad 32: un plan legítimo no pasa de 5.
  - Más de 10 pasos: sin medida que lo pida; el tramo 3 lo dirá.
- **Impacto.** Spec «JSON estricto y acotado»; `tests/unit/test_strict_json.py` gana 15 casos. Los demás llamadores (`config.py`, `policy.py`, `definition.py`, `checks.py`, `mock.py`) no cambian: siguen capturando `InvalidInput`.

  **Nota sin corregir:** `harness/skills/checks.py:69` serializa con `json.dumps` sin `allow_nan=False`. Con el `parse_float` nuevo, `loads_strict` ya no puede devolver `inf` ni `NaN`, así que hoy no llega ningún valor no finito a esa línea. Se deja como está, fuera del alcance de este change, y se anota para la revisión de `skill-engine`.

### D5. El texto del plan: sin invisibles, en NFC, sin credenciales y sin interpretar

- **Qué.** Antes del esquema se recorre el árbol entero, claves y cadenas, sin recursión. Se rechaza:
  - un carácter que `approvals.is_invisible` declara invisible (`Cc`, `Cf`, `Cs`, `Co`, `Cn` y los ignorables por defecto), lo que incluye los controles bidireccionales, los de anchura cero y un sustituto suelto (`invisible_character`);
  - una cadena que no está en NFC (`not_nfc`);
  - una cadena con una credencial que `redact` reconoce (`credential_in_plan`);
  - una cadena que cualquier camino de visualización cambiaría, también como `invisible_character`. La regla es una sola: **lo que se muestra es lo que se envía**, con el criterio `terminal_safe(s) != s` o `normalise_content(s) != s` (revisión independiente, hallazgo 2). Antes pasaban el salto de línea (que `is_invisible` exceptúa) y los separadores de línea y de párrafo U+2028 y U+2029, que esas funciones borran: la persona habría visto `ab` y el servidor habría recibido `a\u2028b`. Un test recorre todo el BMP y una muestra de los planos astrales (1 de cada 97): todo lo aceptado sale idéntico de `normalise_content`, `terminal_safe` y `safe_foreign_line`.

  Nada se normaliza, se expande ni se interpreta: `~`, `$HOME`, `${X}`, `{{x}}`, `%PATH%` y `$(id)` son literales. El lector no tiene ni `eval`, ni plantillas, ni `os.path.expanduser`, y un test lo comprueba sobre el código fuente.
- **Por qué se rechaza en lugar de normalizar.**
  - Si el harness pasara a NFC, o quitara un invisible, lo enviado al servidor no sería lo que escribió el modelo, y la aprobación mostraría (con `normalise_content`, que aplica NFC y escribe `<U+XXXX>`) un texto distinto del hasheado. Rechazar mantiene una sola forma de bytes de punta a punta.
  - Los nombres de herramienta y de argumento de la lista son ASCII por patrón (`NAME_PATTERN`, `ARGUMENT_NAME_PATTERN`), así que un invisible allí nunca es legítimo.
  - Un valor de lectura (un identificador de proyecto) tampoco lo necesita.
  - Una credencial se rechaza porque la aprobación la enmascararía: la persona aprobaría `[REDACTED:github]` y el servidor recibiría el token.
- **Alternativas rechazadas.**
  - Aplicar NFC: dos textos distintos tendrían el mismo hash, y lo enviado no sería lo escrito.
  - Escapar los invisibles y seguir: la persona vería `<U+200B>` pero el servidor recibiría el carácter real.
  - Enmascarar la credencial y enviar el valor real: se aprobaría algo distinto de lo enviado.
- **Impacto.** Spec «Lo que se lee es lo que se muestra y se envía». Límite: una cadena en NFC con caracteres que se parecen (homóglifos, como una «е» cirílica) pasa este control. Si está en un nombre, no casa con la lista ASCII y se rechaza como `tool_not_allowed`; si está en un valor, la detienen el `pattern` del argumento o la persona al aprobar.

### D6. Política por paso, la misma de `mcp call`, antes de ejecutar nada

- **Qué.** Para cada paso, en orden:
  1. referencias (D2);
  2. `decide_before_start(config, server, tool, parse_arguments(canonical_json(args)))`, exactamente lo que hace `mcp call` antes de arrancar un servidor.

  El primer paso que falla rechaza el plan entero, y el motivo nombra el paso. Los motivos de la política se conservan (`server_not_allowed`, `tool_not_allowed`, `argument_*`), salvo `write_requires_approval`, que en un plan es `write_not_allowed`: en la versión 1 ninguna aprobación habilita una escritura. El detalle viene ya saneado de la política y nunca contiene el valor de un argumento.

  Un paso válido guarda su operación (`read`) y sus argumentos canónicos.
- **Por qué.**
  - Una sola fuente de verdad para lo permitido.
  - Rechazar el plan entero por un paso evita ejecutar media tarea de un plan que el modelo pensó entero.
- **Alternativas rechazadas.**
  - Ejecutar los pasos válidos y saltar los demás: el resultado parcial engaña y la aprobación cubriría otra cosa.
  - Reescribir las comprobaciones en el lector: dos políticas que divergen.
  - Dejar la comprobación para la ejecución: se arrancarían servidores para planes que ya se sabía que no valían (SEC-05, «se rechaza antes de arrancar un servidor»).
- **Impacto.** Spec «Solo lecturas de la lista local» y delta de `tool-policy`. En el tramo 2 la pasarela **vuelve** a decidir al ejecutar: entre la aprobación y la ejecución la persona pudo editar la lista. Una lista más estricta deniega; una más amplia no añade nada, porque el plan está fijado.

### D7. Forma canónica, hash y lo que se aprueba

- **Qué.**
  - **Forma canónica:** `canonical_json` de la política (claves ordenadas, `separators=(",", ":")`, UTF-8 sin escapes ASCII, sin `NaN`) sobre el modelo validado, con todos sus campos.
  - **Hash del plan:** `sha256(b"ai-harness/plan/v1\n" + canónica)`. Incluye el nonce, así que el mismo plan en otra pregunta tiene otro hash. Los enteros se escriben como enteros. Un `1.0` nunca llega aquí: ningún argumento admite números con decimales, y la política lo rechaza.
  - **Lo que se aprueba (tramo 2):** una `Proposal` de `approvals.py` con `scope="code-mode.plan"`, la sesión, la solicitud y como `content` el plan mostrado. El plan mostrado es una línea por paso, generada por el harness: `id`, `servidor.herramienta`, operación, decisión de la política (`allowed`) y los argumentos canónicos. Al final, el hash del plan. El `content` pasa por `normalise_content`. Las cadenas del plan salen de ella sin cambios porque D5 rechaza toda cadena que esa función o `terminal_safe` alterarían. Corregido tras la revisión independiente de `38683ac`: antes esta frase afirmaba lo mismo sin que fuera cierto para U+2028, U+2029 y el salto de línea. El hash que se aprueba es el de la `Proposal` (dominio `ai-harness/approval/v1`): liga el plan, la decisión de cada paso, la sesión y la solicitud.
  - **Al ejecutar:** se comprueba que los bytes canónicos son los del plan aprobado y que la aprobación no ha caducado ni se ha usado.
- **Por qué.**
  - Las claves ordenadas y sin espacios hacen el hash independiente de cómo escribió el modelo el JSON. Lo comprueban 200 variantes aleatorias y 9 mutaciones.
  - El dominio separa este hash del de una aprobación.
  - Mostrar la decisión por paso hace visible a la persona que todo es lectura.
- **Alternativas rechazadas.**
  - Hashear el texto del bloque tal cual: dos escrituras del mismo plan tendrían hashes distintos, y una diferencia de espacios no se ve.
  - Hashear sin el nonce: una aprobación de una pregunta valdría para un plan idéntico de otra; el uso único lo mitiga, pero no cuesta nada ligarlo.
  - Aprobar cada paso por separado: N códigos sin saber más (estudio §5.2, opción C).
- **Impacto.** Spec «Forma canónica y hash del plan» y «Aprobación del plan entero ligada a su hash».

### D8. Cómo se le dice al modelo el formato y el catálogo (tramo 2)

- **Qué.** El prompt de `/plan` lleva:
  1. un aviso del harness;
  2. la gramática en unas 10 reglas, con el ejemplo de D2 y el nonce de esta pregunta;
  3. el catálogo, una línea por herramienta `read` de los servidores elegidos, generada **desde la lista local**, por ejemplo `synthetic.get_project_metadata(project: string, max 64, pattern [a-z0-9][a-z0-9-]*, required)`;
  4. la pregunta de la persona, al final.

  Nunca va la descripción que manda un servidor. Si la decisión abierta 5 se toma como (a), va la `description` que la persona escriba en la lista.

  **Tope.** Gramática y catálogo cuentan en el tope de 32 000 caracteres. Si no caben, `/plan` dice cuánto ocupan y no envía nada. Se miden con el render real en el tramo 2 (estimación del estudio §6: unos 1 000 caracteres con 10 herramientas y 800–1 200 de gramática).
- **Por qué.**
  - La lista es la única verdad de la política.
  - El texto de un servidor sería una vía de inyección hacia el modelo.
- **Alternativas rechazadas.**
  - Descubrimiento progresivo, en el que el modelo pide herramientas: cada búsqueda es un envío de 11 s.
  - Tipos de TypeScript: suponen que el código es TypeScript.
  - El esquema JSON del servidor: no confiable y largo.
- **Impacto.** Tramo 2: `/context` muestra el catálogo exacto que se envía.

### D9. Aprobación: botón en la pantalla completa, código en plano y CLI (tramo 2)

- **Qué.**
  - **Pantalla completa:** `open_approval(header, content, approval_hash, question)`. La cabecera la escribe el harness (plan, pasos, hash, caducidad); el contenido son las líneas de D7, como texto ajeno. Valen las protecciones de `approval-buttons`: «Approve» solo tras mostrar el final, sin foco al abrir y armado tras 0,5 s. El motor acepta solo un `ButtonPress` con el hash preguntado; `Verdict.means` queda en la auditoría.
  - **Modo plano y CLI:** `decide_by_code`, los 8 primeros caracteres del hash.
  - **En los dos:** uso único y caducidad de `approvals.py`.
  - **Lo que la caja tiene que decir** (revisión independiente de `38683ac`, para el tramo 2; sin código ahora):
    - que **solo se ejecuta el plan canónico de la caja**, porque la respuesta pintada en la conversación puede ser distinta: Markdown, HTML o un bloque que se ve y no cuenta;
    - **qué leerá el plan**: servidor, herramienta y argumentos de cada paso, en lenguaje llano. El nonce solo separa preguntas. Una inyección dentro de la misma pregunta (una nota de memoria o un fichero adjunto) puede hacer que el modelo escriba un plan **válido** con el nonce correcto. Contra eso, la única defensa es la persona que aprueba, y la caja tiene que darle lo necesario para decidir.
  - **`read_plan` solo se llama sobre la respuesta a una pregunta `/plan`**, nunca sobre una respuesta normal de la conversación, de `ask` ni de un Skill. Un plan que aparece en una respuesta cualquiera es texto, no una propuesta.
- **Por qué.** Lo decidió el dueño, y el mecanismo existe y está revisado.
- **Alternativas rechazadas.**
  - Un sí o no sin código ni botón: lo propuso el modelo, no la persona (estudio §10, 2).
  - Ninguna confirmación porque «son lecturas»: una lectura que la persona no pidió saca datos de su máquina hacia un servidor.
- **Impacto.** Spec «Aprobación del plan entero ligada a su hash».

### D10. Ejecución por la pasarela, parada en el primer fallo (tramo 2)

- **Qué.**
  - **La llamada:** el cuerpo de `_call` en `harness/mcp/commands.py` se extrae a una función que devuelve el resultado sin imprimir, y `mcp call` y el plan la usan igual: `decide_before_start`, `record_running`, `run_session` con `decide_offered`, `record_finished`.
  - **La auditoría:** cada fila de `tool_calls` gana `plan_id` (uuid7) y la posición del paso, y hay una fila del plan con su hash, su estado y sus límites. Es una migración numerada que no cambia ninguna fila existente; su SQL es literal con `?`.
  - **El orden:** los pasos van en serie. El primero que se deniega, falla o vence detiene el plan (`failed` en el paso k); los siguientes no se llaman.
  - **Los plazos:** cada llamada conserva el `call_timeout_s` de su servidor. El plan entero tiene un plazo total: la suma de los de sus pasos, con un máximo de 300 s. Una lectura vencida no tiene efecto: no es `uncertain` y no se reintenta.
  - **Los resultados:** cada uno conserva su `max_result_bytes`, y lo mostrado del plan entero se corta en 256 KiB con aviso.
  - **Ctrl+C:** deja el plan `interrupted` y la fila del paso en curso como `mcp call`.
  - **Hooks:** cuando exista `mcp.call.before` (hooks, corte 4), se dispara en **cada** paso y solo puede denegar.
- **Por qué.**
  - La misma pasarela da la misma política, la misma auditoría y los mismos límites por llamada (SEC-05, SEC-15).
  - Parar en el primer fallo es lo único que cumple lo aprobado sin improvisar.
- **Alternativas rechazadas.**
  - Llamadas en paralelo: el orden de efectos y de fallos deja de ser obvio. Fuera.
  - Seguir tras un fallo: la persona aprobó un plan, no un subconjunto.
  - Una sesión MCP compartida entre pasos del mismo servidor: optimización sin medida. Cada paso arranca su servidor como `mcp call` (0,52 s por llamada); se revisa con las cifras del tramo 3.
- **Impacto.** Spec «Ejecución paso a paso por la pasarela» y delta de `tool-policy`.

### D11. Resultados como texto ajeno, solo para la persona (tramo 2)

- **Qué.**
  - El resultado de cada paso se pinta con `render_result`, el mismo de `mcp call`: literal, saneado con `safe_foreign_text`, con las credenciales enmascaradas y cada línea con el prefijo ajeno.
  - Va en un bloque plegable por paso (`collapsible-blocks`), con su cabecera escrita por el harness.
  - No se envía al proveedor. El tramo 4 añade `/send`, que manda el resultado como datos entre marcas `<<<RESULTADO nonce … RESULTADO nonce>>>`, con el aviso de datos, cuenta como un envío y está sujeto al presupuesto visible.
- **Por qué.**
  - Decisión del dueño (§10.1, 4).
  - Los resultados intermedios no salen de la máquina (estudio §2.2, privacidad).
- **Alternativas rechazadas.**
  - Devolverlo siempre: un envío más y datos fuera sin que la persona los vea.
  - Mostrarlo sin marca: un resultado podría imitar líneas del harness.
- **Impacto.** Spec «El resultado es para la persona». La fila nueva de la matriz («dato de herramienta enviado al proveedor sin que la persona lo vea», estudio §8) se propone en el tramo 4.

### D12. Nunca reenviar; `uncertain`

- **Qué.** Lo que ya existe, más lo propio del plan:
  - Una pregunta `/plan` que vence o se interrumpe tras el envío queda `uncertain` (`request-recovery`) y su texto no se lee (`read_plan_reply`, tramo 1).
  - Un plan sin aprobar caduca con su aprobación.
  - Un plan interrumpido no se reanuda con la misma aprobación.
  - No hay pregunta de reparación automática: «tu plan falló en el paso 3» solo existe como acción explícita, contada en el presupuesto (tramo 4).
- **Por qué.** Lo exigen `config.yaml` («Tras un timeout posterior a un envío… no se reintenta solo») y SEC-07.
- **Alternativas rechazadas.**
  - Reintentar una lectura que falla: esconde errores y cambia lo aprobado.
  - Pedir al modelo que repare: un envío oculto.
- **Impacto.** Spec «Una respuesta incierta o truncada nunca se analiza» y «Un plan nunca se reenvía ni se repite solo».

### D13. Escrituras: fuera, y lo que pediría el tramo 5

- **Qué.** En la versión 1, una herramienta `write` rechaza el plan (`write_not_allowed`), y la pasarela además deniega toda escritura.

  El tramo 5 necesitaría cuatro cosas:
  1. un change que habilite escrituras MCP con aprobación en la pasarela;
  2. un `Effect` de MCP con `prepare`, `apply` y `reconcile` (`harness/skills/effects.py`);
  3. la regla de escrituras terminales: pueden usar valores de lecturas, pero su resultado no alimenta ningún paso;
  4. una vista previa que ejecute las lecturas y calcule la **lista exacta de efectos** (servidor, herramienta y argumentos canónicos), que es lo que se aprueba por hash (estudio §5.2, opción B; decisión 4 abierta).

  Una escritura que vence tras enviarse deja el plan `uncertain` y lo que falta no se aplica.
- **Por qué.** Aprobar el programa no dice qué hará. Aprobar la lista de efectos sí.
- **Alternativas rechazadas.**
  - Admitir escrituras con el mismo hash del plan: un valor leído decide el destino sin que se vea (TOCTOU, inyección).
- **Impacto.** Tareas del tramo 5, sin fecha. EA sigue en pausa.

### D14. Relación con los hooks y con el futuro `/run`

- **Qué.**
  - **Hooks:** solo observan o bloquean, nunca modifican (decisiones del dueño, hooks §10). `prompt.submit`/`prompt.send` ven la pregunta `/plan` como cualquier otra. `mcp.call.before` ve cada paso y solo puede denegarlo. Ningún hook puede aprobar un plan ni cambiar un paso.
  - **`/run` (`feature/code-run`, propuesta sin commits):** guardaría y ejecutaría con aprobación código escrito por el modelo. Es otra orden y otra superficie (SEC-14), y no comparte intérprete con el plan. Lo que sí comparte es el patrón: bloque único con nonce, hash exacto, botón o código, resultado solo para la persona.
- **Por qué.** Un plan es un dato, no un programa. Mezclarlos borraría la garantía de D1.
- **Alternativas rechazadas.**
  - Un hook que añade pasos: modificar está fuera.
  - Que `/run` acepte un plan como código: dos intérpretes para lo mismo.
- **Impacto.** Ninguno en el tramo 1. En el tramo 2, el orden de `mcp.call.before` queda dentro de la función extraída de D10.

### D15. El nonce

- **Qué.** El mismo formato que la memoria: 16 hexadecimales en minúscula, de `secrets.token_hex`, uno por pregunta `/plan`. Lo genera quien compone el prompt (tramo 2), nunca el lector. El lector exige que el esperado tenga ese formato, y si no, es un error de programación (`ValueError`). Compara con `hmac.compare_digest`. El nonce se comprueba antes que el esquema.
- **Por qué.** Un plan de otra pregunta (una respuesta vieja pegada o un resultado que imita un plan) se identifica como tal antes de cualquier otro motivo.
- **Alternativas rechazadas.**
  - El nonce en la línea de apertura: la página solo conserva la etiqueta de lenguaje.
  - Un nonce por sesión: un plan viejo de la misma sesión pasaría.
- **Impacto.** Spec «El nonce de la pregunta».

## Seguridad (SEC)

| SEC | Amenaza | Tramo 1 (este commit) | Tramos siguientes |
|---|---|---|---|
| SEC-03 | Un resultado o texto ajeno cambia lo que se llama | El plan se fija y valida sin leer ningún resultado; ninguna cadena se interpreta (D5) | Sin referencias (D2), un resultado no puede ser argumento; caso de inyección en el servidor sintético (tramo 2) |
| SEC-05 | Herramienta o argumentos fuera de la lista | `decide_before_start` por paso; escritura y no listada rechazan el plan entero (D6) | La pasarela vuelve a decidir al ejecutar |
| SEC-07 | Timeout tras enviar | Respuesta no `completed` o truncada no se lee (D3, D12) | Plan `interrupted` no se reanuda |
| SEC-12 | Aprobación reutilizada o plan alterado | Forma canónica y hash con dominio y nonce (D7) | `Proposal` con uso único, caducidad, botón ligado al hash |
| SEC-14 | Código arbitrario | No hay código: sin `eval`, sin plantillas, sin expansión (D1, D5) | Igual; `/run` es otra superficie (D14) |
| SEC-15 | Límites | 200 000 caracteres de respuesta, 16 KiB, 6 niveles, 10 pasos, 64 argumentos (D4), fijados con números literales en sus fronteras | Plazo total y 256 KiB de resultado mostrado (D10) |
| SEC-02 | Cruce de sesiones | Nonce por pregunta (D15) | `Proposal` ligada a sesión y solicitud |
| SEC-01 | Credenciales | Un plan con una credencial se rechaza (D5) | Resultados enmascarados (D11) |

La matriz `docs/security/sec-matrix.md` describe `develop`. El tramo 2 añade sus tests y requisitos a las filas SEC-03, 05, 07, 12, 14 y 15 en su propia rama (tarea 4.9) sin cambiar ningún estado, así que `sec-states.json` no cambia; las filas llegan a `develop` con el merge.

## Dependencias del tramo 2 (ramas de interfaz en curso)

El tramo 1 no depende de ninguna. El tramo 2 se construye **encima** de ellas, cuando estén mergeadas en `develop`:
- **Tabla declarativa de órdenes** (`harness/shell/commands.py`), con autocompletado. `/plan` se declara allí: nombre, ayuda, argumentos y si exige una lista MCP. No se añade otro `if` en `conversation.py`.
- **Espaciado de toda la interfaz:** la cabecera del plan y los bloques de resultado usan la escala de `harness/shell/spacing.py`, no márgenes propios.
- **Pintado de respuestas:** la respuesta del modelo que trae el plan se pinta como cualquier otra respuesta, con el bloque `json` como código. El plan canónico va aparte, en la caja de aprobación.
- **`/mode`:** el estilo de respuesta no aplica a `/plan`, cuya gramática manda. Queda por decidir si `/mode` puede pedir un plan sin `/plan`; la recomendación es que no (fuera, estudio §9: «un plan disparado sin que la persona escriba `/plan`»).
- **Ya mergeadas** (`develop` = `79cde60`): `approval-buttons` (`ButtonPress`, `Verdict.means`), `collapsible-blocks` y `prompt-economy`. La guarda de SQL está en `tests/unit/test_sql_literals.py`.

## Decisiones que quedan para el dueño

Cada una tiene una opción de trabajo, que es la que sigue el tramo 1 y que se cambia aquí si el dueño elige otra.

1. **Referencias en la versión 1.**
   - (a) **Ninguna** (tomada, D2);
   - (b) `{"$ref": "paso"}`, el resultado entero;
   - (c) `{"$ref": "paso.campo"}` con `result_fields` en la lista.

   **Recomiendo (a)** hasta que el tramo 3 mida cuántas tareas piden encadenar; después, (c) como `ai-harness/plan/2`.
2. **Unicode en argumentos.**
   - (a) **Rechazar** lo que no está en NFC y todo invisible (tomada, D5);
   - (b) normalizar a NFC y seguir.

   **Recomiendo (a)**: una sola forma de bytes.
3. **Credencial en un plan.**
   - (a) **Rechazar** (tomada);
   - (b) mostrarla enmascarada y enviarla real.

   **Recomiendo (a)**.
4. **Límites.**
   - (a) **10 pasos, 16 KiB, 6 niveles** (tomada);
   - (b) los del estudio con `for_each` (20 iteraciones).

   **Recomiendo (a)** y revisarlos con las cifras del tramo 3.
5. **Plazo total del plan** (tramo 2).
   - (a) **la suma de los plazos de sus pasos, con un máximo de 300 s**;
   - (b) un valor fijo en la configuración.

   **Recomiendo (a)**: no añade otro número que mantener.
6. **Una sesión MCP por paso o una por servidor** (tramo 2).
   - (a) **una por paso**, como `mcp call`;
   - (b) reutilizarla dentro del plan.

   **Recomiendo (a)** hasta medir.
7. Siguen abiertas las del estudio, con su opción de trabajo:
   - 4, escrituras por lista de efectos;
   - 5, `description` y `result_fields` en la lista;
   - 6, esto es la forma del «Experimento de agente».

## Hoja de ruta aprobada por el dueño (2026-11-27): «Fase A»

Esta nota reemplaza, para los tramos posteriores, lo que digan en contra D9, D11 y los tramos 2 a 4 de `proposal.md`. El tramo 1 no cambia. Los tramos siguientes pasan a ser la **Fase A**:

- **A1.** `/plan` de solo lectura con el Mock: el tramo 2 actual.
- **A2.** Lecturas permitidas por regla. Una herramienta puede llevar `auto_read: true` en la lista local, y un plan cuyos pasos son todos `auto_read` se ejecuta sin la caja. Se ve una línea `running plan:` y queda auditado.
- **A3.** El resultado vuelve al modelo como datos marcados y acotados, en un bucle automático:
  - con un tope de vueltas, `HARNESS_LOOP_MAX_TURNS` (5 por defecto);
  - con un contador de envíos visible;
  - con un turno de cierre.
- **A4.** Medición con Copilot real: el tramo 3 actual.

Para los tramos posteriores a A1, esto deja sin efecto dos cosas: «el resultado solo se muestra a la persona» (D11) y, para los planes `auto_read`, «todo plan necesita el botón de aprobación» (D9). Los cambios de spec y de tareas se escribirán en cada tramo, cuando se diseñe.

Las fases siguientes añaden dos cosas:
- herramientas de ficheros del espacio de trabajo, en proceso: `read`, `glob` y `grep` automáticas; `write` y `edit` siempre aprobadas como lista de efectos con el diff exacto;
- órdenes de ejecución con nombre.

**Consecuencia para el esquema.** El catálogo podrá incluir un «servidor» interno, que no es MCP. El esquema `plan/1` ya lo admite: `server` y `tool` son nombres que decide el catálogo, no la sintaxis del plan. El lector solo los comprueba contra la vista de la política que recibe. Cuando exista ese servidor interno, esa vista tendrá que incluirlo con su operación por herramienta, sin cambiar el formato del plan.

## Lo que enseñó el tramo 2 (A1, 2026-11-27)

Decisiones tomadas al construir `/plan`. Completan D8 a D12; donde cambian algo, lo dicen.

### T2-1. El tope del catálogo y una pregunta que no cabe

- **Qué.** El catálogo tiene su propio tope: 64 herramientas y 8 000 caracteres (`MAX_CATALOGUE_TOOLS`, `MAX_CATALOGUE_CHARS`). Si lo pasa, `/plan` no registra ni envía nada y dice cuánto ocupa. Después, el `check` del proveedor mide el texto entero (instrucciones, catálogo, memoria, adjunto y pregunta) antes de registrar nada, como en toda pregunta. Si no cabe, el error dice cuánto ocupa cada parte y nombra «the plan instructions and catalogue». No se recorta nada para que quepa.
- **Por qué.** Recortar la memoria o el catálogo cambiaría lo que el modelo ve sin que la persona lo decida. 8 000 deja sitio a la memoria dentro de los 32 000 de Copilot. Con la lista sintética, las instrucciones y el catálogo ocupan 1 907 caracteres.
- **Alternativas rechazadas.**
  - Recortar el catálogo por orden: el modelo no sabría qué falta.
  - Quitar la memoria en silencio: cambia la respuesta sin avisar.
- **Impacto.** D8 «Tope» queda así. `tests/unit/test_mcp_plan_prompt.py` y `tests/unit/test_shell_plan.py::test_a_prompt_over_the_provider_limit_records_nothing`.

### T2-2. La `description` de la lista: en el catálogo, no en la caja

- **Qué.** Decisión abierta 5 del estudio, opción (a): `ToolEntry.description` es opcional, la escribe la persona, ocupa una línea de 120 caracteres como mucho y se rechaza si la limpieza de la terminal la cambiaría (control, invisibles, bordes en blanco). Va en el catálogo. **No** va en el contenido aprobado: «reads:» se escribe solo con el servidor, la herramienta y los argumentos del plan.
- **Por qué.** La caja tiene que poder escribirse otra vez desde el plan solo. Si incluyera la descripción, editar la lista mientras la caja está abierta parecería una alteración del plan. La lista se vuelve a leer después de consumir la aprobación, y la política se decide otra vez en cada paso (D6).
- **Alternativas rechazadas.**
  - La descripción en la caja: ata el hash a un texto que no es el plan.
  - `result_fields`: sin referencias (D2), nada los usaría todavía.
- **Impacto.** `harness/mcp/config.py` (`DESCRIPTION_MAX`), `harness/mcp/plan_run.py` (`step_lines`).

### T2-3. El plazo del plan

- **Qué.** Decisión 5, opción (a): la suma de `startup_timeout_s + call_timeout_s` de cada paso, con un máximo de 300 s, guardada en la fila del plan y mostrada en la caja. Un temporizador activa la señal de parada (`StopSignal`) al vencer. El paso en curso termina con su árbol de procesos, como con Ctrl+C. El plan queda `timeout` con `error_code = deadline`, y los pasos siguientes no se llaman.
- **Por qué.** Cada paso arranca su servidor (decisión 6, opción (a)), así que su tiempo máximo es el arranque más la llamada.
- **Alternativas rechazadas.**
  - Solo los plazos de llamada: un arranque lento se comería el plazo.
  - Un valor fijo: otro número que mantener.
- **Impacto.** `deadline_s`, `_run_steps`.

### T2-4. Migración 009 y la fila del plan

- **Qué.** `009_plan_runs.sql`, porque la 008 es de `feature/response-mode`.
  - `plan_runs` guarda una fila por plan: hash del plan, hash de la aprobación, pasos, plazo, tope mostrado, estado de la aprobación (`pending`, `granted`, `rejected`, `expired`, `undecided`, `consumed`), medio (`code` o `button`), identidad, estado del plan, paso donde paró, código de error y marcas de tiempo.
  - `tool_calls` gana `plan_id` y `plan_step`.
  - SQL literal con `?`. Ninguna fila existente cambia.
  - Una fila que espera aprobación de un proceso que ya no existe se marca `abandoned` en el siguiente `/plan` de la misma sesión. Una fila en `running` sin su bloqueo vivo se marca `interrupted` al ejecutar el siguiente plan.
- **Por qué.** `approvals` exige un `run_id` de `skill_runs`, y un plan no es un Skill. Una tabla propia evita una clave falsa.
- **Alternativas rechazadas.**
  - Reutilizar `approvals` con un `skill_run` ficticio: mezcla dos máquinas de estados.
- **Impacto.** `tests/unit/test_storage.py` espera la tabla y la versión 9. Al mergear `response-mode` quedan 1–9 sin hueco.

### T2-5. El ejecutor: su hilo, su conexión, su bloqueo

- **Qué.** `execute_plan` corre en un hilo del ejecutor de asyncio, con su propia conexión SQLite y un bloqueo con nombre `plan-<id>`.
  - Compara en este orden:
    - el hash del plan contra sus bytes canónicos;
    - ese hash contra la fila;
    - el hash de la aprobación contra la fila;
    - los pasos que se ejecutarán (leídos de los bytes canónicos) contra los mostrados;
    - la `Proposal`, escrita otra vez desde el plan con la sesión, la solicitud y el plan recibidos, contra el hash aprobado.
  - Si algo difiere, termina `plan_altered` y no arranca nada. Después consume la aprobación con un único `UPDATE … WHERE approval = 'granted' AND approval_hash = ? AND expires_at > ?`.
  - Lo que se audita usa la sesión y la solicitud de la fila, nunca las recibidas. Un `plan_id` sin fila devuelve un informe `not_run`, sin lanzar.
  - Ctrl+C en la conversación cancela la tarea. `run_in_thread` lo convierte en `StopSignal("interrupted")`, quita la cancelación y espera el informe, para que la persona vea qué paso paró.
- **Por qué.** El cliente MCP abre su propio bucle de eventos (`anyio.run`), y una conexión SQLite no se comparte entre hilos.
  - Hallazgo al probar: con otra solicitud, el primer borrador lanzaba `FOREIGN KEY constraint failed` al auditar la denegación. Ahora se deniega y se audita bien.
- **Alternativas rechazadas.**
  - Ejecutar en el hilo de la conversación: bloquearía la pantalla y Ctrl+C.
- **Impacto.** `harness/mcp/plan_run.py`, `harness/mcp/client.py` (`StopSignal`, `SessionRequest.stop`).

### T2-6. La CLI y la terminal no interactiva

- **Qué.** `main.py plan SESSION_ID PREGUNTA` usa el mismo flujo (`plan_flow.run_plan`).
  - Exige stdin y stdout de consola. Sin ella sale con código 2 antes de leer la lista o abrir la base.
  - Las líneas del harness van a stderr; la respuesta y los resultados, saneados, a stdout; la caja, a la terminal.
  - En la conversación, una terminal no interactiva no ofrece caja: el plan queda `undecided`.
  - La CLI no tiene `--project` en este tramo.
- **Por qué.** Un plan que nadie puede aprobar no debe gastar un envío.
- **Alternativas rechazadas.** Leer el código de stdin redirigido: cualquiera que escriba en esa tubería aprobaría.
- **Impacto.** `harness/mcp/plan_cli.py`; dos líneas aditivas en `harness/cli.py`.

### T2-7. `/plan` se escribe entero

- **Qué.** `CommandSpec.full_name_only`. `resolve_name` nunca resuelve un prefijo a una orden así, y el parser dice «`/pla` is not a command; `/plan` is typed in full». La ayuda y el autocompletado la ofrecen igual. `/mode` no existe en esta rama. Cuando llegue será otra orden: no llama a `read_plan`.
- **Por qué.** D9: un plan solo se pide cuando la persona escribe `/plan`.
- **Impacto.** `harness/shell/commands.py`, `harness/shell/parser.py`.

### T2-8. El resultado, preparado para A3

- **Qué.** Cada paso devuelve un `StepResult` con estos campos: texto ya saneado y acotado, credenciales enmascaradas, bytes del resultado, si se cortó, duración y `call_id`. La vista lo pinta como texto ajeno bajo una línea del harness. Nada vuelve al proveedor.
- **Por qué.** A3 tendrá que acotarlo y marcarlo para enviarlo. Ya tiene lo que necesita sin volver a llamar.
- **Impacto.** Ninguno en este tramo.

### Decisiones abiertas del tramo 2

1. **Título de los bloques de resultado en la pantalla completa.**
   - (a) el genérico «text from outside the harness», con la línea del harness encima (tomada, porque `tui.py` estaba fuera de alcance);
   - (b) «result of step k», pasando una etiqueta a `show_rows` cuando se mergee `bugfix/windows-parity-2`.

   **Recomiendo (b).**
2. **`--project` en `main.py plan`.**
   - (a) sin memoria (tomada);
   - (b) como `ask --project`, con su auditoría de denegación.

   **Recomiendo (b)** cuando se pida.
3. **Terminal no interactiva en la conversación.**
   - (a) sin caja (tomada);
   - (b) mostrar la caja con «no se puede aprobar aquí».

   **Recomiendo (b)**: la persona ve qué se habría ejecutado.

## Risks / Trade-offs

- [El modelo no escribe a la primera un JSON con una gramática que no conoce] → El tramo 3 lo mide con 10 tareas antes de construir nada más. Cada motivo de rechazo es estable y se cuenta.
- [El editor de código de la página altera o virtualiza un bloque largo] → La sonda del tramo 3 envía un bloque `json` sintético de 80 líneas antes de las tareas. Un bloque alterado falla el análisis, nunca se ejecuta a medias.
- [Una inyección en la misma pregunta hace que el modelo escriba un plan válido] → El nonce no lo impide (D15). La defensa es la aprobación humana con el plan canónico y lo que leerá a la vista (D9), y que un plan de la versión 1 solo pueda leer herramientas de la lista.
- [Un plan legítimo dentro de una lista o una cita se rechaza] → Es un falso negativo aceptado: el texto se muestra y el motivo `plan_outside_block` lo dice.
- [Sin referencias, una tarea que necesita encadenar cuesta otra pregunta] → Límite aceptado en la versión 1 (D2). Se revisa con las cifras del tramo 3.
- [Homóglifos en un valor de argumento] → Límite que no se arregla aquí (D5): el `pattern` del argumento o la persona al aprobar.
- [La lista local cambia entre aprobar y ejecutar] → La pasarela vuelve a decidir en cada paso (D6). Una lista más amplia no añade nada.
- [La aprobación no prueba que haya una persona delante] → Límite ya documentado en `SECURITY.md` y `approval-buttons` D6. No cambia.

## Migration Plan

- **Tramo 1:** sin migración ni configuración. Revertir es quitar `harness/mcp/plan.py`, `split_fences` y `StrictJsonError`. Ningún llamador depende de ellos todavía.
- **Tramo 2:** una migración numerada que solo añade columnas y una tabla. Revertir el código deja columnas nulas que nadie lee.
