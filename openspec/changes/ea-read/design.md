# Design

## Context

Parte de `develop` en `8cb2ec5` más `mcp-gateway` (planificado en esta misma rama y que se implementa antes): lista local de servidores, servidores incorporados (`"builtin"`), política deny-by-default, plazos duros, auditoría `tool_calls` y saneado común en `harness/text/`. La motivación está en `proposal.md`; los requisitos, en `specs/`.

Restricciones que mandan sobre todo lo que sigue:

- **Repositorio público.** Ningún modelo de EA, nombre, GUID, ruta ni cadena de conexión reales. El guard rechaza `.qea`, `.qeax`, `.eap`, `.eapx`, `.feap`, así que un modelo de prueba **no se puede versionar**: se crea en tiempo de ejecución (D11).
- **Regla de plataforma.** EA es la única excepción: vive en `harness/enterprise_architect/` (ya exento en `tests/unit/test_portability.py`) y en **otro proceso**. El núcleo nunca importa `pywin32` ni ese paquete. Todo lo que no es el adaptador COM se desarrolla y se prueba en macOS contra un adaptador falso con la misma interfaz.
- **Nadie con Windows salvo Wilson.** Los agentes no pueden ejecutar EA. Toda afirmación sobre COM es premisa hasta que la mida la sonda (D1) o una prueba de contrato en su equipo.
- **Lecciones de Windows** (ver `mcp-gateway`, Context): esperas acotadas, entorno copiado de `os.environ`, UTF-8 explícito, OneDrive bloquea directorios.

### Premisas: qué está comprobado en documentación y qué no

Consultado el 2026-11-24. La web de la guía de usuario de Sparx devuelve 403 a un cliente automático; se leyeron los PDF oficiales descargados fuera del repo.

**Comprobado en la documentación** (Sparx, *Enterprise Architect Object Model*, 16.1, 10-11-2023, 352 páginas; y *Guide to the Trial Edition*, 17.0):

- `Repository.OpenFile(Filename) -> Boolean` abre un fichero o una cadena de conexión; `OpenFile2(FilePath, Username, Password)`; `CloseFile()` «cierra cualquier fichero abierto»; `Exit()` «cierra EA inmediatamente»; la guía recomienda `CloseFile()` y `Exit()` al terminar y avisa de que un cliente que termina mal puede dejar `EA.exe` vivo (p. 19).
- `CreateModel(CreateModelType, FilePath, ParentWnd) -> Boolean` crea un modelo nuevo copiando el modelo base (`cmEAPFromBase`); la documentación habla de «.eap» y **no da el valor numérico** del enumerado.
- `GetPackageByGuid`, `GetDiagramByGuid`, `GetElementByGuid`, `GetConnectorByGuid` existen y devuelven el objeto; un paquete tiene un elemento con el mismo GUID.
- `Models` es una colección de paquetes raíz (`ParentID` 0); las colecciones son base 0 (`GetAt`), y todo `AddNew` exige `Update()`.
- `Diagram.DiagramObjects` (instancias de elementos con `ElementID`, `Left`, `Right`, `Top`, `Bottom`; arriba y abajo se guardan **negativos**, p. 50) y `Diagram.DiagramLinks` (información de presentación de un conector en ese diagrama: `ConnectorID`, `IsHidden`, `Geometry`, p. 218). Las relaciones del modelo están en `Element.Connectors` (`ClientID`, `SupplierID`, `ConnectorGUID`, `Stereotype`, `StereotypeEx`).
- `ConnectionString` es de solo lectura y contiene el fichero o la cadena de conexión del repositorio abierto.
- `EA.App` representa una instancia en ejecución; se puede crear, y `GetObject(, "EA.App")` **se adjunta a una instancia en ejecución** (p. 20). `CreateObject("EA.Repository")` + `OpenFile` + `Exit` es el ejemplo oficial de cliente externo (p. 331).
- `EAEdition`/`EAEditionEx` devuelven `piLite`, `piProfessional`, `piCorporate`, `piBusiness`, `piSystemEng` o `piUltimate`, y **no hay valor para la prueba**: devuelve la edición que se está probando (p. 29). Los valores numéricos no están documentados.
- `SQLQuery`, `GetElementsByQuery` y `Execute` existen: este diseño los prohíbe (D9).
- La guía de la prueba describe 30 días con todas las ediciones y menciona la automatización como capacidad del producto, sin decir si la prueba la limita.

**pywin32** (PyPI JSON, 2026-11-24): versión 312, ruedas `cp314` para `win32`, `win_amd64` y `win_arm64`, clasificador 3.14; sin ruedas para macOS. `uv run --with pywin32` en la Mac falla al resolver sin tocar `uv.lock` (medido). El SDK `mcp` 2.3.0 ya declara `pywin32>=311; sys_platform == "win32"`.

**No comprobado (premisas que mide la sonda, tarea 1.2):**

- P1 · Que la edición de Wilson permita crear `EA.Repository` o `EA.App` por COM, y si un diálogo de la prueba bloquea la automatización.
- P2 · Que `DispatchEx("EA.Repository")` dé **una instancia nueva** y no un objeto de un EA que la persona tenga abierto (depende de cómo EA registra su clase COM; no está documentado).
- P3 · Qué extensión crea `CreateModel` con `cmEAPFromBase` = 0 en EA 16/17 (`.qea`, `.eapx`) y si un fichero así se abre y se lee después.
- P4 · Si `DiagramLinks` tiene una fila por conector visible o solo para los que tienen estilo propio (decide la regla de D8).
- P5 · Si `Exit()` deja procesos `EA.exe` vivos y cuánto tardan en irse; si se permite una segunda instancia simultánea.
- P6 · Cuánto tarda cada paso (decide los plazos por defecto de D3).
- P7 · Que `EA.exe` lanzado por COM **no** es hijo del servidor (lo arranca el lanzador de COM), así que el Job Object de `mcp-gateway` D4 no lo cubre. No lo mide la sonda directamente; lo mide la tarea 7.4.

## Goals / Non-Goals

**Goals:**

- Saber pronto, con un solo comando de Wilson, si el corte es viable.
- Que todo salvo el adaptador COM se escriba y se pruebe en la Mac, y que la parte que solo se puede probar en Windows esté escrita con nombre y apellidos (D13).
- Leer sin poder escribir: ni una llamada de escritura ni de SQL en el código del producto, comprobado estructuralmente.

**Non-Goals:**

- Escribir en un modelo (Corte 6), repositorios de servidor, credenciales, búsquedas.
- Fidelidad completa del adaptador falso con EA: solo para las operaciones y campos de las cinco herramientas.

## Decisions

### D1 · La sonda primero, y todo lo demás bloqueado hasta su resumen

- **Qué:** `scripts/ea_probe.py`, ya escrita en esta rama, y su runbook `docs/runbook/enterprise-architect.md`. Biblioteca estándar más `pywin32`; se ejecuta con `uv run --with pywin32 python scripts/ea_probe.py`. Sin una sola comprobación de plataforma: intenta importar `pywin32` y crear el objeto. Mide P1–P6 con un paso por línea (sí/no/valor y tiempo), cada uno con su control de errores y su plazo; todas las llamadas COM van en un hilo propio con `CoInitialize`, y una llamada que vence su plazo deja ese hilo fuera de uso (la sonda sigue con lo que no es COM y termina con salida dura para no esperar a un hilo atascado). Resumen sin datos del entorno entre dos líneas marcadoras; detalle en `HARNESS_DATA_DIR/ea/probe-<fecha>.json`, negándose a escribir donde Git podría versionarlo (misma comprobación que la sonda de Copilot). Los mensajes de error **no se guardan** ni en el resumen ni en el JSON: solo categoría, `hresult`, `scode` y tipo, porque una descripción de EA puede llevar una ruta.
- **Qué está probado y qué no:** `tests/unit/test_ea_probe.py` (17 tests, en la Mac) prueba el camino sin `pywin32` ejecutando el script real, y todo el flujo contra un COM falso: cada tipo de fallo, un paso colgado, el objeto ajeno que se suelta sin cerrarlo, el recuento de procesos, que el resumen no lleva rutas, usuario, GUID ni mensajes, y la negativa a escribir en un directorio versionable. **El camino COM real no se ha ejecutado nunca.** **Revisada el 2026-11-25 (hotfix 0.2.1):** en la primera batería en Windows (v0.2.0) ese test sí tomó el camino COM real, porque `pywin32` llega instalado con `mcp` y el script se lanzaba con el intérprete normal. Ahora ningún test puede crear un objeto COM: `main` no tiene backend por defecto y el backend real solo se construye bajo `if __name__ == "__main__":`; los tests lanzan el script solo con `python -I -S` (sin `site-packages` ni `PYTHONPATH`), comprobando antes que `pythoncom`, `pywintypes` y `win32com` no se pueden importar así. No hay interruptor de prueba en el script: no sabe que lo prueban. Un test de guarda lo comprueba sobre el código (`ast`).
- **Por qué:** si la edición de prueba no permite COM, todo lo demás del corte es trabajo perdido. La sonda además crea el modelo sintético por la misma vía que usarán las pruebas de contrato (D11), así que si pasa, esa vía está probada.
- **Alternativas rechazadas:**
  - Empezar por el servidor y el adaptador falso y medir COM después: es construir sobre P1 sin medirla.
  - Una sonda que importe `harness` (como la de Copilot): exigiría `uv sync` con las dependencias del proyecto en Windows antes de saber nada; la sonda de EA tiene que funcionar con lo mínimo.
  - `GetObject` para medir con el EA abierto: es adjuntarse a la sesión de la persona, justo lo prohibido.
- **Impacto:** spec `ea-automation-probe`; tareas 1.1 (hecha) y 1.2; todas las demás tareas quedan **BLOCKED** hasta 1.2.

### D2 · Servidor incorporado, paquete propio y proceso propio

- **Qué:** `harness/enterprise_architect/` con `server.py` (un `MCPServer` del SDK por stdio), `worker.py` (D3), `adapter.py` (la interfaz `EaAdapter` y los modelos Pydantic de salida), `com_adapter.py` (el único fichero que toca `win32com`, importado dentro de su método de apertura), `fake_adapter.py` (D11), `targets.py` (D5) y `scope.py` (D7). En la lista local de `mcp-gateway`: `"ea": {"builtin": "ea-read"}`. La orden de arranque la fija `harness/mcp/` para ese nombre: `[sys.executable, "-m", "harness.enterprise_architect.server"]`, sin `uv` en medio (un `uv run` sería un proceso intermedio más que matar). La entrada no admite `command`, `env` ni herramientas: las cinco herramientas, sus argumentos declarados y su operación `read` las fija el código, con el mismo formato de política de `mcp-gateway` D2. El entorno del servidor lleva además `HARNESS_MCP_CONFIG` y `EA_READ_TARGET_ID`, copiados del harness. El servidor se niega a arrancar sin `AI_HARNESS_MCP_CHILD=1` (prevención de errores al lanzarlo a mano, **no** autenticación). El adaptador lo elige el destino (`"adapter": "com"` o `"fake"`), nunca la plataforma.
- **Por qué:** el plan pide EA en un servidor MCP separado; separarlo en proceso hace que un cuelgue o una caída de COM no afecten al harness y que el harness nunca cargue `pywin32`. Fijar la orden en el código elimina la posibilidad de que una entrada mal escrita lance otra cosa con el nombre `ea`.
- **Alternativas rechazadas:**
  - EA como módulo del harness en un hilo: un cuelgue de COM se lleva el proceso del harness, y el núcleo importaría `pywin32`.
  - Orden de arranque en la lista local como un servidor externo: más flexible, pero cualquier error de configuración cambia qué se ejecuta con acceso a EA.
  - Elegir el adaptador por `sys.platform`: rama por plataforma innecesaria; en Windows también se quiere poder usar el falso.
- **Impacto:** spec `ea-connection` (Servidor de EA incorporado y en su propio proceso); `harness/mcp/config.py` (entrada `builtin`); tareas 2.1–2.3.

### D3 · Un hilo dedicado a COM, llamadas en serie y plazo por llamada

- **Qué:** el servidor arranca un hilo `ea-com` que hace `CoInitialize`, crea la instancia, abre el destino y luego atiende una cola: cada herramienta pone una tarea y espera su respuesta con un plazo (`call_timeout_s` del servidor, 30 s por defecto hasta que la sonda dé cifras; P6). El bucle MCP (asyncio) nunca toca un objeto COM. Si una tarea vence su plazo, el hilo queda **envenenado**: la herramienta devuelve `timeout`, el servidor deja de aceptar llamadas y termina su proceso con salida dura (no se puede pedir `CloseFile` a un hilo que sigue dentro de EA). El harness ve el cierre del canal y lo audita (`mcp-gateway` D4). La instancia de EA que quede viva en ese caso es el límite de D12.
- **Por qué:** los objetos COM de un apartamento de un hilo solo se usan en ese hilo; serializar todo en uno hace imposible el acceso concurrente y es lo que pide el plan («worker dedicado inicializado con COM»). La sonda usa el mismo diseño, así que la tarea 1.2 lo prueba en Windows antes de escribir el servidor.
- **Alternativas rechazadas:**
  - Un proceso trabajador por llamada: arrancar EA en cada llamada (P6 dirá cuánto cuesta) y otro proceso que matar.
  - Reintentar la llamada en un hilo nuevo tras un plazo vencido: el EA anterior sigue ocupado y el nuevo hilo no puede usar sus objetos.
- **Impacto:** spec `ea-connection` (Todas las llamadas COM en un solo hilo y en serie); tareas 3.1 y 3.2.

### D4 · Instancia propia, copia privada del modelo y cierre solo de lo propio

- **Qué:**
  - `win32com.client.DispatchEx("EA.Repository")`; nunca `GetObject`, `GetActiveObject` ni `EA.App` en ejecución.
  - **Antes de abrir nada**, `ConnectionString` tiene que estar vacío. Si no lo está, el objeto es un EA ya abierto (P2): se suelta la referencia sin llamar a `CloseFile` ni a `Exit` y el servidor responde `foreign_instance`. *Revisada el 2026-11-24, tras una revisión independiente de la sonda:* un `ConnectionString` vacío no basta. Un EA de la persona **sin** modelo abierto también lo tiene vacío, y `Exit()` lo cerraría. La instancia solo es propia si además apareció un proceso de EA nuevo al crearla; si no apareció, o si no se puede contar, se trata como ajena. La sonda ya aplica esta regla (`own_instance_unproven`), y el servidor de EA la heredará con la cifra que mida la sonda.
  - El fichero del destino se copia a un directorio privado creado con `tempfile.mkdtemp(prefix="ea-read-")` y se abre la copia. Al cerrar: `CloseFile()`, `Exit()`, soltar referencias y `gc.collect()` en el hilo COM, `CoUninitialize()`, y borrar la copia con hasta 5 intentos a 1 s (EA o un antivirus pueden retenerla).
  - El cierre se hace al cerrarse stdin del servidor (señal de cierre del SDK), tras un error de herramienta y al terminar normalmente, con un plazo de 10 s; dentro del margen de cierre de `mcp-gateway`.
- **Por qué:** la copia garantiza que el fichero de la persona queda idéntico aunque EA escriba algo al abrir (no está documentado si lo hace) y evita bloquear un fichero que la persona tenga abierto. Comprobar `ConnectionString` es la única señal documentada de que el objeto ya tenía un modelo; la sonda mide si alguna vez ocurre.
- **Alternativas rechazadas:**
  - Abrir el fichero original «en solo lectura»: `OpenFile` no tiene esa opción documentada.
  - Copiar a `HARNESS_DATA_DIR`: puede estar en OneDrive (decisión de Wilson en el Corte 3) y una copia de un modelo real no debe sincronizarse.
  - Cerrar con `ShutdownEA`: cierra todas las vistas de EA; no es «solo lo propio».
- **Impacto:** spec `ea-connection` (Instancia propia y nunca la de la persona, El modelo de la persona no se modifica, Cierre de lo propio); tareas 3.3 y 3.4.

### D5 · Destinos locales permitidos

- **Qué:** en la misma lista local de `mcp-gateway`, una sección `ea_targets`:

  ```json
  "ea_targets": {
    "demo-model": {
      "adapter": "com",
      "file": "C:\\ruta\\local\\al\\modelo.qea",
      "read_roots": ["{00000000-0000-4000-8000-000000000001}"]
    }
  }
  ```

  `EA_READ_TARGET_ID` elige uno. Identificador `[a-z][a-z0-9-]{0,63}`; `file` absoluto, fichero regular existente con extensión `.qea`, `.qeax`, `.eapx`, `.eap` o `.feap`; se rechaza todo texto con `DBType=`, `Connect=`, `;` o `://` (forma de cadena de conexión); `read_roots` no vacío, GUID con llaves. Un destino `"adapter": "fake"` lleva `"fixture"` (ruta a un modelo sintético JSON) en lugar de `file`. Ninguna herramienta tiene argumentos de destino: la política de `mcp-gateway` los deniega como no declarados. `ea_connection_info` nunca devuelve `file`.
- **Por qué:** es lo que pide F06.1 («targets por identificador local allowlisted, no aceptar cadenas de conexión del LLM»). Solo ficheros porque el tipo de conexión del repositorio corporativo no está medido y es una dependencia externa del plan; abrir un servidor exigiría credenciales y una decisión de seguridad propia.
- **Alternativas rechazadas:**
  - Aceptar cadenas de conexión en la lista local: credenciales en un fichero JSON y un camino de red sin medir.
  - Alcance por nombre de paquete: los nombres se repiten y cambian; el GUID es estable.
- **Impacto:** spec `ea-connection` (Destinos locales permitidos, Información de la conexión sin datos sensibles); `README.md`; tarea 2.2.

### D6 · Las cinco herramientas y sus argumentos

- **Qué** (todos `read`; GUID con el patrón `\{[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}`):
  - `ea_connection_info()` → identificador del destino, adaptador, `own_instance`, `LibraryVersion`, edición (número y nombre supuesto), número de raíces.
  - `ea_list_packages(parent_guid?, offset=0, limit=50)` → sin padre, las raíces autorizadas; con padre, sus hijos.
  - `ea_list_diagrams(package_guid, offset=0, limit=50)` → diagramas directos del paquete.
  - `ea_get_diagram(diagram_guid)` → diagrama, objetos, `visible_connectors`, `model_relationships_not_shown`, `truncated`.
  - `ea_get_element(element_guid)` → elemento y relaciones en los dos sentidos, `truncated`.
  - `offset` 0–100 000, `limit` 1–200. Orden por nombre (`casefold`) y GUID. `max_result_bytes` 256 KiB.
- **Por qué:** las cuatro herramientas del corte más `ea_connection_info` de F06.2, con los argumentos mínimos. GUID y no ID numérico porque el ID es local a la base y cambia entre copias.
- **Alternativas rechazadas:** profundidad configurable en `ea_list_packages` (árbol entero de una vez): un modelo grande devolvería megas; se pagina nivel a nivel.
- **Impacto:** spec `ea-model-read` (Identificadores GUID validados, Listar paquetes, Listar diagramas de un paquete, Paginación y límites); tareas 4.1–4.4.

### D7 · Autorización por alcance de paquete, también por GUID

- **Qué:** todo objeto que sale (paquete, diagrama, elemento, extremo de una relación, objeto de un diagrama) tiene que estar bajo alguna raíz autorizada. Se comprueba subiendo por `ParentID`/`PackageID` con `GetPackageByID` hasta una raíz o hasta 64 niveles, con caché por llamada. Fuera del alcance, inexistente o más profundo de 64 niveles → la misma respuesta `not_found`, sin nombre ni tipo (sin oráculo de existencia). Un extremo de relación u objeto de diagrama fuera del alcance sale como `{"out_of_scope": true}` con el tipo de la relación y el sentido, sin GUID ni nombre. La comprobación la hace `scope.py` sobre la interfaz del adaptador, así que es la misma con el falso y con COM.
- **Por qué:** F06.2 pide «validar pertenencia al paquete autorizado incluso cuando se consulta por GUID»; un GUID se puede adivinar o copiar de otro sitio. Responder igual a «no existe» y «no autorizado» evita confirmar que un GUID existe.
- **Alternativas rechazadas:** confiar en que la persona solo pase GUID autorizados; filtrar solo las listas y no las lecturas por GUID.
- **Impacto:** spec `ea-model-read` (Alcance autorizado por paquete, Jerarquía demasiado profunda); tarea 4.2.

### D8 · Salida normalizada: visibles frente a relaciones del modelo

- **Qué:** modelos Pydantic `extra="forbid"`. Elemento: `guid`, `name`, `type`, `stereotypes` (de `StereotypeEx`, separado por comas, sin vacíos), `package_guid`. Relación: `guid`, `type`, `stereotypes`, `direction` (`outgoing` si el elemento es `ClientID`, `incoming` si es `SupplierID`), `other` (elemento o `out_of_scope`). Diagrama: `guid`, `name`, `type`, `stereotypes`, `package_guid`, `objects` (elemento + `x = Left`, `y = -Top`, `width = Right - Left`, `height = Top - Bottom`, según la convención documentada de valores negativos), `visible_connectors`, `model_relationships_not_shown`. **Regla de visibilidad (premisa P4):** una relación entre dos elementos que están en el diagrama es visible salvo que el diagrama tenga para ella un `DiagramLink` con `IsHidden`; si no hay `DiagramLink`, se considera visible (lo que hace EA al dibujar, según la descripción de `DiagramLinks` como «información de presentación»). Si la sonda o la prueba de contrato miden otra cosa, se cambia esta regla y se releen las specs.
- **Por qué:** el Corte 7 necesita distinguir «lo que el diagrama muestra» de «lo que el modelo sabe» para no inventar ni omitir relaciones al proponer un cambio. Geometría positiva y con `y` hacia abajo es lo que cualquier consumidor espera.
- **Alternativas rechazadas:** devolver los objetos COM tal cual (campos de EA, ID numéricos, valores negativos): ata el contrato a EA y filtra campos que D9 retiene.
- **Impacto:** spec `ea-model-read` (Leer un diagrama, Leer un elemento); tareas 4.3 y 4.4.

### D9 · Lo que no se lee ni se devuelve, y la prohibición de escribir y de SQL

- **Qué:** no salen notas, documentos enlazados, valores etiquetados, autor, fechas, alias, rutas, `ConnectionString`, `ProjectGUID`, `InstanceGUID`, usuario ni ID numéricos. Nombres recortados a 256 caracteres. El harness sanea y redacta todo al imprimir (`mcp-gateway` D7), y el servidor no registra contenido del modelo en su stderr (solo códigos). **Lista blanca estructural** (`ast`) sobre `com_adapter.py`: solo puede leer los atributos y llamar a los métodos de una lista (`OpenFile`, `CloseFile`, `Exit`, `ConnectionString`, `LibraryVersion`, `EAEdition`, `EAEditionEx`, `Models`, `Packages`, `Diagrams`, `Elements`, `Connectors`, `DiagramObjects`, `DiagramLinks`, `GetAt`, `Count`, `Get*ByGuid`, `GetPackageByID`, `GetElementByID`, `GetConnectorByID` y los campos de D8); cualquier otro nombre (`AddNew`, `Update`, `Delete`, `DeleteAt`, `SQLQuery`, `GetElementsByQuery`, `Execute`, `RunModelSearch`, `ShutdownEA`, `SaveDiagram`, `CreateModel`…) es un hallazgo. El adaptador falso registra cada operación para que las pruebas comprueben que no hubo escrituras.
- **Por qué:** el plan pide «no usar SQL directo» y «no confiar solo en el nombre de una herramienta»; una lista blanca sobre el código es una comprobación que dice NO a lo que no conoce, igual que la de `harness/memory/` en el Corte 3. Las notas son el campo con más texto libre (y más probabilidad de contenido sensible o de instrucciones) y no hacen falta para el Corte 7.
- **Alternativas rechazadas:** lista negra de métodos prohibidos (no ve un método nuevo); devolver notas recortadas (se puede añadir con un change cuando un Skill lo necesite).
- **Límite:** la lista blanca prueba lo que dice el código del adaptador, no lo que EA hace por dentro al leer (por ejemplo, actualizar una marca de acceso); por eso se abre una copia (D4).
- **Impacto:** spec `ea-model-read` (Campos que no salen del modelo, Solo lectura y sin SQL, El texto del modelo es un dato no confiable); tarea 4.5.

### D10 · Límites

- **Qué:** página por defecto 50, máximo 200; 500 objetos por diagrama y 200 relaciones por elemento, con `truncated`; 64 niveles de subida para el alcance; 256 KiB por resultado; plazo por llamada COM 30 s y de arranque del servidor 120 s hasta tener P6 (se ajustan con las cifras de la sonda, sin cambiar specs).
- **Por qué:** acota memoria, tiempo y tamaño de salida sin depender del tamaño del modelo real, que no está medido.
- **Alternativas rechazadas:** sin límites y confiar en el plazo: un diagrama grande consumiría el plazo entero y no devolvería nada.
- **Impacto:** spec `ea-model-read` (Paginación y límites); tarea 4.6.

### D11 · Adaptador falso y fidelidad comprobada con pruebas de contrato

- **Qué:**
  - `EaAdapter` es la interfaz mínima que usan las herramientas: `open(target)`, `info()`, `package(guid)`, `package_by_id(id)`, `child_packages(guid)`, `diagrams(package_guid)`, `diagram(guid)`, `element(guid)`, `element_by_id(id)`, `connectors(element_guid)`, `close()`. Devuelve registros planos (no objetos COM).
  - `FakeAdapter` carga un modelo sintético en JSON (`tests/fixtures/ea/synthetic-model.json`: paquetes con raíz autorizada y hermanos no autorizados, un paquete con 120 diagramas, un diagrama de 600 objetos, una relación oculta, una cadena de 70 niveles, un elemento con notas, valor etiquetado y autor canarios, un nombre con órdenes y una secuencia de escape; GUID con forma `{0000000N-0000-4000-8000-…}`, evidentemente sintéticos). Guarda los valores como EA (arriba y abajo negativos) para que la normalización se pruebe de verdad. Registra cada operación.
  - **Pruebas de contrato** (`tests/contract/test_ea_adapter_contract.py`): la misma batería parametrizada sobre los dos adaptadores, comparando la salida normalizada por nombres (los GUID difieren). El lado falso corre siempre; el lado COM solo con los marcadores `windows` y `ea` y si se puede crear `EA.Repository` (se omite con motivo visible si no). El modelo real lo construye `tests/contract/ea_model_builder.py` en un directorio temporal a partir del **mismo JSON**, por la Automation Interface (la vía que la sonda prueba primero). Es el único código del repo que escribe en un modelo, vive en `tests/` y escribe solo en un modelo nuevo.
- **Por qué:** sin un falso fiel, «pasa en la Mac» no dice nada de Windows; con el mismo JSON en los dos lados, una divergencia aparece como un test rojo en el equipo de Wilson.
- **Alternativas rechazadas:** versionar un `.qea` sintético (el guard lo prohíbe, con razón: un `.qea` no se revisa en un diff); grabar respuestas COM reales (serían contenido de un modelo).
- **Impacto:** fixtures; tareas 5.1–5.4.

### D12 · SEC-10 en EA: qué se libera y qué puede quedar

- **Qué:** con un cierre normal o tras un error, el servidor cierra su modelo y su instancia (D4). Si el servidor muere o se envenena (D3), el harness lo mata con el árbol (`mcp-gateway` D4), pero **`EA.exe` no es hijo del servidor**: lo arranca el lanzador de COM (P7, no medida), así que puede quedar vivo hasta que COM detecte que su cliente desapareció. El harness no busca ni mata procesos `EA.exe`: no puede distinguir con certeza el suyo del de la persona. Lo que sí hace: auditar la llamada como `abandoned`/`failed` y decir por stderr que puede quedar un `EA.exe` de la sesión anterior.
- **Por qué:** matar por nombre de imagen cerraría el EA de la persona; la regla es «cerrar solo recursos propios».
- **Alternativas rechazadas:** guardar el PID de `EA.exe` al crearlo (no hay forma documentada de obtenerlo desde la Automation Interface); `taskkill /IM EA.exe` (mata lo ajeno).
- **Límite que no se arregla en este corte:** tras un cuelgue o una caída del servidor puede quedar un `EA.exe` propio vivo durante un tiempo no medido. Se escribe en el runbook con cómo cerrarlo a mano.
- **Impacto:** spec `ea-connection` (Cierre de lo propio); tareas 3.4 y 7.4.

### D13 · Qué se prueba en la Mac y qué solo en Windows

- **En la Mac, contra el falso o sin COM** (mismo código que en Windows): servidor MCP, configuración y destinos, política y argumentos, hilo trabajador y plazos (con un adaptador falso que se cuelga), alcance, paginación, límites, normalización, retención de campos, saneado, auditoría, ciclo de vida del proceso del servidor, ausencia de escucha, lista blanca estructural, que el harness no importa `pywin32`, la sonda sin `pywin32`.
- **Solo en Windows con EA (Wilson):** P1–P7; que `com_adapter.py` traduce bien la Automation Interface a la interfaz (lado COM de las pruebas de contrato); la creación de la instancia propia y la detección de una ajena; la apertura de la copia y el borrado tras el cierre con EA reteniendo el fichero; los códigos de error COM reales; los tiempos; que `pywin32` se instala desde `uv.lock`; y la demo del corte.
- **Por qué:** es la regla del plan («un corte con integración real no se cierra si solo pasó con mocks»), con la frontera escrita para que nadie la confunda.
- **Impacto:** tareas 5.4, 7.1–7.5.

### D14 · Dependencia `pywin32`

- **Qué:** `pywin32>=312; sys_platform == "win32"` en `pyproject.toml` (marcador de dependencia, no código). `uv lock` resuelve el lock universal en la Mac sin instalarlo (medido con el proyecto desechable de `mcp-gateway`). Hasta esta tarea el probe usa `--with`, que no toca el lock.
- **Por qué:** declarar la dependencia que el código usa, aunque el SDK ya la traiga, para que no desaparezca si el SDK la quita.
- **Alternativas rechazadas:** depender solo de la que trae `mcp`: dependencia implícita.
- **Impacto:** tarea 2.1.

## Risks / Trade-offs

- [La edición de prueba no permite COM, o la prueba vence] → la sonda lo dice el primer día (P1); los cortes 5–7 se replantean con Wilson (licencia con Automation, que el plan ya lista como dependencia externa). Los cortes 3–4 no dependen de este.
- [Un diálogo de la prueba bloquea cada arranque por COM] → la sonda lo detecta como `TIMEOUT` y el runbook pide anotar el diálogo; si pasa, una ejecución desatendida no es viable con esa edición.
- [`DispatchEx` entrega el EA de la persona (P2)] → comprobación de `ConnectionString` vacío antes de abrir y respuesta `foreign_instance` sin cerrar nada; la sonda lo mide en el paso 3 opcional del runbook.
- [La regla de visibilidad de D8 no es la de EA (P4)] → la sonda cuenta `DiagramLinks`; la prueba de contrato con la relación oculta lo confirma; si difiere se cambia D8 y se releen las specs.
- [Un `EA.exe` propio queda vivo tras un cuelgue (D12)] → límite escrito; runbook.
- [El modelo real es mucho mayor que el sintético] → límites de D10 y paginación; P6 y la tarea 7.3 dan las cifras.
- [El adaptador falso diverge de EA] → pruebas de contrato con el mismo JSON en los dos lados (D11).
- [Copia de un modelo real grande en `%TEMP%`] → tiempo y disco no medidos; la tarea 7.3 lo mide. Un modelo corporativo real no se abre en este corte (solo ficheros locales).
- [Conflicto con el Corte 6 por el paquete compartido] → el Corte 6 añade un servidor de escritura con su propio destino y su propio proceso; `com_adapter.py` de lectura no gana métodos de escritura (la lista blanca de D9 lo impide).

## Migration Plan

Aditivo: un paquete nuevo, una sección nueva opcional en la lista local, una dependencia con marcador. Sin entrada `ea` en la lista, el harness se comporta como con `mcp-gateway`. Vuelta atrás: revertir el change.

## Open Questions

- Los plazos por defecto (D3, D10) se fijan con las cifras de P6; no cambian specs ni tareas.
