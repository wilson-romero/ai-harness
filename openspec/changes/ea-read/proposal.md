# Proposal

> **EN PAUSA desde el 2026-11-25 por decisión de Wilson:** no tiene Enterprise Architect instalado. Este change no se cancela ni se modifica: sus tareas siguen tal como están y se retoman, empezando por la 1.2 (la sonda), cuando EA esté instalado. Ver «Revisado el 2026-11-25 (Wilson)» en `docs/plan/2026-11-24-ai-harness-cortes.md`.

## Why

El Norte del plan pide que el harness «lea el modelo de Enterprise Architect» antes de pedir una propuesta, y hoy no hay ni una línea que hable con EA: `ls harness/enterprise_architect` no existe y `grep -rn -i -E "win32com|pywin32|EA\.Repository" harness/ scripts/` → 0 (medido el 2026-11-24 sobre `8cb2ec5`). Además, la primera premisa del corte **no está medida**: Wilson solo tiene una edición de demostración de EA en Windows y nadie ha comprobado que permita la Automation Interface (COM). La guía oficial de la edición de prueba (Sparx, «Guide to the Trial Edition», 17.0, PDF de 65 páginas, consultada el 2026-11-24) describe una prueba de 30 días de todas las ediciones y menciona el acceso al modelo «using the automation (Active-X) interface» como capacidad general del producto, **sin decir si la prueba la limita**, ni qué pasa al vencer, ni qué hace la edición gratuita de solo lectura; y el modelo de objetos (`enterprise-architect-object-model.pdf`, 16.1, 10-11-2023, p. 29) dice que `EAEdition` no tiene un valor propio para la prueba: devuelve el de la edición que se está probando. Si COM no funciona con esa edición, los cortes 5, 6 y 7 quedan bloqueados: por eso este change empieza con una sonda que Wilson ejecuta a mano, y nada más avanza hasta tener su resumen.

Corte **5 · EA lectura** de `docs/plan/2026-11-24-ai-harness-cortes.md`, segunda mitad (la primera es `mcp-gateway`, de la que depende). Riesgo **N2**. Cubre **SEC-10** en su parte de COM (si el servidor de EA o EA se cuelgan o mueren, se liberan los recursos propios y nunca los ajenos), **SEC-05** aplicado a las herramientas de EA (argumentos no válidos, GUID fuera del alcance autorizado) y **SEC-09** solo en el sentido de `mcp-gateway` D9 (el servidor de EA no escucha en ningún sitio; habla solo con el proceso que lo arrancó). **Solo Windows** para la integración real con EA; todo lo demás (servidor, normalización, alcance, límites) se desarrolla y se prueba en macOS contra un adaptador falso con la misma interfaz, y design D13 lista qué conducta solo se puede demostrar en Windows.

**El repositorio es público en GitHub.** Ningún modelo de EA entra en el repo (el guard rechaza `.qea`, `.qeax`, `.eap`, `.eapx`, `.feap`), ni nombres, GUID, rutas o cadenas de conexión reales. El modelo de prueba se crea en tiempo de ejecución a través de la Automation Interface; el adaptador falso lee un modelo sintético en JSON.

## What Changes

- **Sonda `scripts/ea_probe.py`** (ya escrita en esta rama): biblioteca estándar más `pywin32`, se ejecuta a mano en PowerShell con `uv run --with pywin32`. Mide si se puede crear el objeto COM con la edición de Wilson, la versión y la edición, si se puede crear, poblar, guardar, reabrir y leer por GUID un modelo nuevo en un directorio temporal, si se permite una segunda instancia y si cerrar la propia deja procesos de EA vivos o toca un EA abierto por la persona. Imprime un resumen sin datos del entorno para pegar y guarda el detalle en `HARNESS_DATA_DIR`.
- **Servidor MCP de EA** en su propio paquete (`harness/enterprise_architect/`) y su propio proceso, incorporado en la lista local de `mcp-gateway` (`"builtin": "ea-read"`): la orden de arranque la fija el código.
- **Un hilo dedicado a COM** dentro de ese proceso, con todas las llamadas en serie y un plazo por llamada; una instancia **propia** de EA que se crea y se cierra sola, sin adjuntarse nunca a la sesión interactiva de la persona.
- **Destinos locales permitidos** por identificador (`EA_READ_TARGET_ID`), solo ficheros locales de modelo en este corte, con las raíces de paquete autorizadas; nunca una cadena de conexión que venga de un modelo, de un argumento o de una herramienta.
- **Herramientas de lectura:** `ea_connection_info`, `ea_list_packages`, `ea_list_diagrams`, `ea_get_diagram`, `ea_get_element`; GUID validados, paginación, límites de profundidad y de tamaño; autorización por alcance de paquete incluso cuando se pide por GUID.
- **Salida normalizada:** elementos, relaciones, estereotipos y geometría, distinguiendo los conectores visibles en un diagrama de las relaciones del modelo; sin notas, valores etiquetados, autores, fechas, rutas ni cadenas de conexión.
- **Adaptador falso** con la misma interfaz que el adaptador COM y **pruebas de contrato** que corren contra los dos (el real, solo en Windows con EA).
- `pywin32` como dependencia con marcador de Windows.

**No entra**, aunque un lector lo asumiría:

- **Ninguna escritura** en ningún modelo desde el código del producto: `ea_preview_diagram` y `ea_create_test_diagram` son del Corte 6 (`ea-test-write`). Solo el constructor de modelos de prueba (en `tests/`) y la sonda escriben, y solo en un modelo nuevo dentro de un directorio temporal.
- **El repositorio corporativo:** repositorios en servidor (SQL Server, Pro Cloud Server, cualquier DBMS) y sus credenciales. El tipo de conexión no está medido y el plan lo marca como dependencia externa; este corte lee un fichero local.
- SQL directo (`SQLQuery`, `GetElementsByQuery` y similares), búsquedas de modelo y scripts de EA.
- Adjuntarse a un EA abierto por la persona (`GetObject`, `EA.App` en ejecución), abrir su modelo o cerrar su ventana.
- Mantener EA abierto entre comandos (un proceso por comando, como en `mcp-gateway` D3).
- Llamar a estas herramientas desde un Skill o a propuesta de un modelo (Corte 7) y enviar sus resultados a Copilot.

## Capabilities

### New Capabilities

- `ea-automation-probe`: la sonda manual de la Automation Interface: qué mide, qué no toca, qué imprime y dónde guarda.
- `ea-connection`: proceso y hilo propios para COM, instancia propia de EA y cierre solo de lo propio, destinos locales permitidos e `ea_connection_info`.
- `ea-model-read`: las cuatro herramientas de lectura, su alcance autorizado por paquete, paginación y límites, la salida normalizada y lo que se retiene.

### Modified Capabilities

Ninguna. Comprobado el 2026-11-24 sobre `8cb2ec5`: `openspec list --specs` devuelve las 8 capacidades de los cortes 1 y 3 y `grep -rn -i -E "enterprise architect|mcp|herramienta" openspec/specs/` no devuelve nada. Las capacidades `mcp-client` y `tool-policy` y el requisito ADDED de `secret-redaction` son de `mcp-gateway`, que no está archivado; este change no escribe deltas contra ellas: el servidor de EA es un servidor más de la lista local, sometido a sus requisitos tal como están.

## Impact

- Código nuevo: `harness/enterprise_architect/` (servidor MCP, hilo COM, adaptador COM, adaptador falso, contratos, destinos). Único paquete exento de `tests/unit/test_portability.py` (ya lo está). El núcleo nunca lo importa.
- `scripts/ea_probe.py`, `tests/unit/test_ea_probe.py` y `docs/runbook/enterprise-architect.md` (ya en esta rama).
- Dependencias: `pywin32>=312; sys_platform == "win32"` (el SDK `mcp` ya la trae con `>=311` en Windows). `uv lock` resuelve en macOS y Windows (lock universal); en la Mac no se instala.
- Configuración: `EA_READ_TARGET_ID` (ya en `.env.example`) y una sección de destinos en la lista local de `mcp-gateway`.
- Fixtures: modelo sintético en JSON (`tests/fixtures/ea/`); ningún fichero de modelo de EA.
- Datos locales (fuera del repo): resumen y detalle de la sonda en `HARNESS_DATA_DIR/ea/`; copia privada del modelo abierto en un directorio temporal.
- Documentación: `README.md` (herramientas de EA), `docs/runbook/enterprise-architect.md`, `SECURITY.md` (qué no se lee de un modelo).
- El Corte 6 añade la escritura en el destino de pruebas sobre este mismo paquete, con aprobación (`mcp-gateway` D6).
