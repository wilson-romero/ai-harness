# Proposal

## Why

En la pantalla completa (`shell-tui`), aprobar una propuesta pide copiar del hash los 8 primeros caracteres y escribirlos en la caja. Wilson probó la caja con Copilot Web real y pidió: «hazlo más sencillo con un botón aprobar». El 2026-11-27 eligió, conociendo el coste, **botones con protecciones**, y aprobó esta maqueta:

```
+------------------ Aprobación ------------------+
| target: Decisiones/2026-11-27-cola-...-3fa81c2e.md |
| hash:   3fa81c2e9b7d...                          |
| caduca: 15 min                                   |
|                                                  |
| | # Cola gestionada para avisar de pedidos       |
| | ## Decisión                                    |
| | Usar una cola gestionada...                    |
|                                                  |
|   has visto toda la propuesta                    |
|                                                  |
|        [ Aprobar ]        [ Rechazar ]           |
+--------------------------------------------------+
```

Las protecciones que pidió:
- «Aprobar» solo se habilita cuando la propuesta entera se ha mostrado.
- No tiene el foco al abrirse la caja: un Enter no aprueba por accidente.
- Se ignora lo que llegue en los primeros 0,5 s.
- Se pulsa con el ratón, o con Tab y Enter.

Hoy aprobar en la caja son 8 caracteres copiados de una línea de 64 (`harness/skills/approvals.py`, `CODE_LENGTH = 8`). Con los botones es un Tab y un Enter, o un clic.

Pertenece al **Corte 9 · Interfaz conversacional**, cuarta entrega tras `interactive-shell`, `shell-appearance` y `shell-tui`. Riesgo **N1**: no cambia lo que se firma ni lo que se escribe, pero sí cómo concede una persona en la pantalla completa. SEC que cubre:
- **SEC-12:** la aprobación sigue ligada al hash, caduca y se usa una vez; el botón responde a la misma pregunta del motor para el mismo hash.
- **SEC-15:** el texto ajeno sigue inerte y no puede pulsar ni imitar los botones.

Se demuestra en **macOS**. Windows queda como ejecución opcional pedida a Wilson.

## What Changes

- **Botones en la caja de aprobación de la pantalla completa:** «Approve» y «Reject». El resto de la interfaz está en inglés; la caja también, para no mezclar idiomas en una pantalla (D5). Dentro de la caja ya no hay entrada para escribir el código (D4).
- **El motor acepta una pulsación** (`ButtonPress`). Es un objeto, no un texto, y solo lo devuelve el método `ask_buttons` de una terminal que lo tiene: hoy solo la pantalla completa. Además tiene que venir con el hash de la pregunta que se hizo (D1). La auditoría de `approval.granted` y `approval.rejected` dice cómo se decidió: `means=button` o `means=code`.
- **Las protecciones de la caja** (D2):
  - el foco empieza en la propuesta;
  - los dos botones están deshabilitados durante 0,5 s;
  - «Approve» sigue deshabilitado hasta que se ha mostrado el final;
  - una pulsación por caja;
  - los botones están fijos abajo, fuera del área ajena;
  - Escape no decide.
- **«Reject» pide confirmación dentro de la caja** («Reject this proposal? …», con [Back] y [Yes, reject]). El foco va a Back, y un segundo clic demasiado pronto no confirma (D3).
- **Texto plano y CLI sin cambios:** `chat --plain`, `skill run` y `skill resume` siguen pidiendo el código. Ahí no existe la vía del botón (D1).

**No entra:**
- un canal que pruebe que hay una persona delante: sigue el límite aceptado el 2026-11-24 (D6);
- botones en el texto plano o en la CLI;
- cambiar el hash, la caducidad, el uso único, el destino o los efectos;
- una migración: la columna `approvals.channel` sigue siendo `tty`, y el modo va en la auditoría.

## Capabilities

### New Capabilities

(ninguna)

### Modified Capabilities

Ninguna de estas capacidades está en `openspec/specs/` (comprobado el 2026-11-27: allí solo están `llm-provider`, `memory-*`, `project-context`, `request-recovery`, `secret-redaction` y `session-management`). Por eso el delta va como requisitos añadidos, como hizo `shell-tui`. Al archivar se convierte en MODIFIED (tarea 5.1).

- `interactive-shell` (de `shell-tui`, sin archivar). Los requisitos «Caja de aprobación en la pantalla completa», «Entrada de la aprobación» y «La propuesta entera antes del código» pasan de la entrada del código a los botones.
- `human-approval` (de `skill-engine`, sin archivar). «Solo una persona en una terminal interactiva aprueba» y «Auditoría de aprobaciones sin contenido» admiten la pulsación de la pantalla completa como segunda forma de conceder, ligada al mismo hash, y registran cuál se usó.

## Impact

- Código:
  - `harness/skills/approvals.py`: `Verdict`, `ButtonPress`, `ButtonApprovalTerminal` y `decide`, que antes devolvía la decisión y ahora devuelve también el modo;
  - `harness/skills/engine.py`: el modo en la auditoría;
  - `harness/shell/tui.py`: la caja con botones, `TuiTerminal.ask_buttons` y `press`; se quitan `CodeInput` y `answer`.
- Tests: `tests/unit/test_shell_tui_buttons.py` y `tests/unit/test_skill_approval_buttons.py`, nuevos. En `tests/unit/test_shell_tui.py` y `tests/unit/test_shell_tui_review.py` salen las pruebas de la entrada del código, que estas sustituyen.
- Documentos: `README.md` y `SECURITY.md`.
- No toca `harness/shell/terminal.py`, `conversation.py`, `app.py`, los proveedores, las migraciones ni el camino plano.
