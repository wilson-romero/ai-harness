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
| JSON estricto | `harness/core/strict_json.py`, `loads_strict` | Ya rechazaba lo que el plan necesita: duplicados, `NaN`/`Infinity`, datos tras el valor, BOM, clave no cadena, control crudo en una cadena, entero de más de 4 300 cifras y profundidad. Faltaban dos cosas: decir **qué** rechazó sin leer el mensaje, y un tope de profundidad más estricto que 32. Además **acepta** `"\ud800"` (sustituto suelto), comprobado con `loads_strict('"\\ud800"')`. El plan lo rechaza aparte (D5). |
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

### D5. El texto del plan: sin invisibles, en NFC, sin credenciales y sin interpretar

- **Qué.** Antes del esquema se recorre el árbol entero, claves y cadenas, sin recursión. Se rechaza:
  - un carácter que `approvals.is_invisible` declara invisible (`Cc`, `Cf`, `Cs`, `Co`, `Cn` y los ignorables por defecto), lo que incluye los controles bidireccionales, los de anchura cero y un sustituto suelto (`invisible_character`);
  - una cadena que no está en NFC (`not_nfc`);
  - una cadena con una credencial que `redact` reconoce (`credential_in_plan`).

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
  - **Lo que se aprueba (tramo 2):** una `Proposal` de `approvals.py` con `scope="code-mode.plan"`, la sesión, la solicitud y como `content` el plan mostrado. El plan mostrado es una línea por paso, generada por el harness: `id`, `servidor.herramienta`, operación, decisión de la política (`allowed`) y los argumentos canónicos. Al final, el hash del plan. El `content` pasa por `normalise_content`, que con D5 no cambia nada. El hash que se aprueba es el de la `Proposal` (dominio `ai-harness/approval/v1`): liga el plan, la decisión de cada paso, la sesión y la solicitud.
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
| SEC-15 | Límites | 200 000 caracteres de respuesta, 16 KiB, 6 niveles, 10 pasos, 64 argumentos (D4) | Plazo total y 256 KiB de resultado mostrado (D10) |
| SEC-02 | Cruce de sesiones | Nonce por pregunta (D15) | `Proposal` ligada a sesión y solicitud |
| SEC-01 | Credenciales | Un plan con una credencial se rechaza (D5) | Resultados enmascarados (D11) |

La matriz `docs/security/sec-matrix.md` describe `develop`. Las filas se actualizan cuando el tramo 2 se mergee (tarea 6.x), no antes.

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

## Risks / Trade-offs

- [El modelo no escribe a la primera un JSON con una gramática que no conoce] → El tramo 3 lo mide con 10 tareas antes de construir nada más. Cada motivo de rechazo es estable y se cuenta.
- [El editor de código de la página altera o virtualiza un bloque largo] → La sonda del tramo 3 envía un bloque `json` sintético de 80 líneas antes de las tareas. Un bloque alterado falla el análisis, nunca se ejecuta a medias.
- [Un plan legítimo dentro de una lista o una cita se rechaza] → Es un falso negativo aceptado: el texto se muestra y el motivo `plan_outside_block` lo dice.
- [Sin referencias, una tarea que necesita encadenar cuesta otra pregunta] → Límite aceptado en la versión 1 (D2). Se revisa con las cifras del tramo 3.
- [Homóglifos en un valor de argumento] → Límite que no se arregla aquí (D5): el `pattern` del argumento o la persona al aprobar.
- [La lista local cambia entre aprobar y ejecutar] → La pasarela vuelve a decidir en cada paso (D6). Una lista más amplia no añade nada.
- [La aprobación no prueba que haya una persona delante] → Límite ya documentado en `SECURITY.md` y `approval-buttons` D6. No cambia.

## Migration Plan

- **Tramo 1:** sin migración ni configuración. Revertir es quitar `harness/mcp/plan.py`, `split_fences` y `StrictJsonError`. Ningún llamador depende de ellos todavía.
- **Tramo 2:** una migración numerada que solo añade columnas y una tabla. Revertir el código deja columnas nulas que nadie lee.
