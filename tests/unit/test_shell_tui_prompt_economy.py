"""prompt-economy on the full screen: the concise-answer notice and the short note headers in
`/context` and in what is sent, and the side panel's note list (D2, D3)."""

from __future__ import annotations

import re

from harness.core.answer_style import CONCISE_NOTICE
from harness.core.service import SessionService
from harness.storage.database import open_database
from tests.shell_support import CountingProvider
from tests.tui_support import SIZE, Tui

NONCE = re.compile(r"\b[0-9a-f]{16}\b")


def _project_session(data_dir) -> str:
    conn = open_database(data_dir)
    try:
        service = SessionService(conn, data_dir, lambda name: CountingProvider(), "mock", 5.0)
        return str(service.create_session("S", "demo-alpha").session_id)
    finally:
        conn.close()


async def test_context_and_a_question_on_the_full_screen(tmp_path, vault):
    session = _project_session(tmp_path)
    tui = Tui(tmp_path, session=session, vault=vault, answer_notice=CONCISE_NOTICE)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        await tui.send(pilot, "/context")
        await tui.until(pilot, lambda: tui.blocks("foreign"))
        await tui.ready(pilot)
        (shown,) = tui.blocks("foreign")
        assert shown.startswith(CONCISE_NOTICE + "\n\nLo que sigue es memoria local")
        assert "\n--- _project (project, 2026-11-21)\n" in shown
        assert "\n--- sessions/2026-11-21-121500 (session, 2026-11-21)\n" in shown
        assert "--- nota:" not in shown
        await tui.send(pilot, "pregunta")
        await tui.until(pilot, lambda: len(tui.blocks("foreign")) == 2)
        await tui.ready(pilot)
        (sent,) = tui.provider.prompts
        assert NONCE.sub("N", sent) == NONCE.sub("N", shown) + "\n\npregunta"  # seen == sent
        # The panel lists the notes by the vault paths the context reports, not by header.
        await tui.until(pilot, lambda: "7 note(s) in the last question" in tui.side())
        assert "projects/demo-alpha/_project.md" in tui.side()
        assert "Decisiones/alpha-mensajeria.md" in tui.side()
        assert CONCISE_NOTICE not in tui.side()
        await tui.send(pilot, "/exit")
    assert tui.app.return_value == 0


async def test_without_the_notice_the_full_screen_shows_and_sends_none(tmp_path, vault):
    session = _project_session(tmp_path)
    tui = Tui(tmp_path, session=session, vault=vault, answer_notice=None)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        await tui.send(pilot, "pregunta")
        await tui.until(pilot, lambda: tui.blocks("foreign"))
        await tui.ready(pilot)
        (sent,) = tui.provider.prompts
        assert sent.startswith("Lo que sigue es memoria local") and CONCISE_NOTICE not in sent
        await tui.send(pilot, "/exit")
    assert tui.app.return_value == 0
