# ai-harness

Copiloto de arquitectura que se ejecuta en local. Mantiene varias conversaciones persistentes con un proveedor de lenguaje y, en cortes posteriores, usará Microsoft Copilot Web, herramientas MCP, Skills, una segunda memoria en Markdown y Enterprise Architect.

Estado: **Corte 1 · Esqueleto**. Sesiones, historial y recuperación funcionan con un proveedor Mock. El plan de entregas está en [`docs/plan/2026-11-24-ai-harness-cortes.md`](docs/plan/2026-11-24-ai-harness-cortes.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/). Python 3.14 lo instala uv.
- macOS o Windows. Enterprise Architect (cortes 5 a 7) solo funcionará en Windows.

## Instalación

```sh
uv sync
uv run pytest
```

## Uso

```sh
uv run python main.py session create "Arquitectura WhatsApp"
uv run python main.py session list
uv run python main.py ask SESSION_ID "Analiza este requerimiento"
uv run python main.py history SESSION_ID
```

`session create` imprime el identificador de la sesión. Los comandos aceptan solo el UUID completo, no un prefijo. Los resultados salen por stdout; los avisos y los errores, por stderr. Código de salida: 0 hecho, 1 error controlado, 2 uso incorrecto, 130 interrumpido con Ctrl+C.

## Configuración

Por variables de entorno (ver `.env.example`). Este corte usa:

| Variable | Por defecto | Para qué |
|---|---|---|
| `HARNESS_DATA_DIR` | `./data` | Dónde viven SQLite y los bloqueos. Debe ser un **disco local**: en una unidad de red los bloqueos de fichero no son fiables. |
| `HARNESS_PROVIDER` | `mock` | Proveedor de las sesiones nuevas. Hoy solo existe `mock`. |
| `HARNESS_REQUEST_TIMEOUT_S` | `120` | Plazo de cada pregunta. |
| `HARNESS_MOCK_BEHAVIOR` | `ok` | `ok`, `fail`, `timeout_before_send` o `timeout_after_send`. Solo para pruebas y demos. |
| `HARNESS_MOCK_DELAY_MS` | `0` | Espera del Mock después de enviar. Sirve para interrumpir una pregunta a mitad. |

## Estados de una solicitud

| Estado | Qué significa |
|---|---|
| `completed` | El proveedor respondió. |
| `failed` | El proveedor informó de un error. |
| `timeout` | Venció el plazo **antes** de que el prompt saliera. No llegó a ningún sitio. |
| `uncertain` | Venció el plazo o murió el proceso **después** de que el prompt saliera. Pudo haber llegado. |

El harness nunca reenvía una solicitud por su cuenta. Una solicitud `uncertain` se queda así en el historial; si repites la pregunta, es una solicitud nueva. La sesión aparece como `uncertain` hasta que la siguiente pregunta se completa.

Solo una pregunta a la vez por sesión: una segunda pregunta mientras la primera sigue en curso se rechaza. Sesiones distintas sí pueden preguntar a la vez.

## Qué se guarda

- SQLite en `HARNESS_DATA_DIR/harness.sqlite3`, sin cifrar.
- El texto de prompts y respuestas se guarda solo si el proveedor declara que su contenido es sintético (el Mock). Con cualquier otro proveedor se guardan la solicitud, su estado y sus fechas, sin el texto.
- La auditoría registra qué pasó y cuándo, nunca el texto.

## Desarrollo

- Flujo OpenSpec personalizado: `openspec/config.yaml` lleva el contexto y las reglas por artefacto.
- Git flow: ramas `feature/<change>` desde `develop`.
- El repositorio es público: lee [`SECURITY.md`](SECURITY.md) y activa el hook una vez por clon con `git config core.hooksPath .githooks`.
- Sin código condicionado por plataforma fuera de Enterprise Architect: lo que pasa en macOS es lo que corre en Windows.
- Puerta local antes de un merge: `scripts/verify.sh` sobre el árbol limpio.
- Demo del Corte 1: `scripts/demo-session-core.sh`.
