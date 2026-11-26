"""The reply is rebuilt as Markdown from the page's structure (design D8, task 8.14).

The fixtures in `tests/fixtures/copilot_ui/rich/` use the structure the real page gave on
2026-11-26 (measured without its text); their text is invented. Each test also reads the same
page as `innerText` would, the reader before this change: that is the negative control, and it
must fail where the rebuilt reply passes."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator

import pytest
from playwright.async_api import async_playwright

from harness.providers.copilot_web import REPLY_TEXT_JS
from harness.skills.checks import check
from harness.skills.definition import ValidateStep
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.edge

RICH = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "rich"


def skill_check(skill: str) -> ValidateStep:
    """The validate step of one of the repository's real Skills, as it is shipped."""
    workflow = json.loads((REPO_ROOT / "skills" / skill / "workflow.json").read_text("utf-8"))
    step = next(s for s in workflow["steps"] if s["kind"] == "validate")
    return ValidateStep.model_validate(step)


class Reader:
    """One headless Edge page; `read` renders HTML inside a turn and reads it both ways."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.playwright = self.loop.run_until_complete(async_playwright().start())
        self.browser = self.loop.run_until_complete(
            self.playwright.chromium.launch(channel="msedge", headless=True))
        self.page = self.loop.run_until_complete(self.browser.new_page())

    def read(self, html: str, max_chars: int = 200_000) -> tuple[int, str, str]:
        async def go() -> tuple[int, str, str]:
            await self.page.set_content(f'<div id="turn">{html}</div>')
            turn = self.page.locator("#turn")
            length, text = await turn.evaluate(REPLY_TEXT_JS, max_chars)
            return length, text, await turn.evaluate("(e) => e.innerText")
        return self.loop.run_until_complete(go())

    def close(self) -> None:
        self.loop.run_until_complete(self.browser.close())
        self.loop.run_until_complete(self.playwright.stop())
        self.loop.close()


@pytest.fixture(scope="module")
def reader(edge_ready) -> Iterator[Reader]:
    r = Reader()
    yield r
    r.close()


def fixture(name: str) -> str:
    return (RICH / f"{name}.html").read_text("utf-8")


def test_each_markdown_element_comes_back_as_markdown(reader):
    _, text, plain = reader.read(fixture("elements"))
    assert text == (
        "## Uno\n\n"
        "Texto con **negrita**, *cursiva* y `codigo`.\n\n"
        "- primero\n- segundo\n  - dentro\n\n"
        "1. paso uno\n2. paso dos\n\n"
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        '```json\n{\n  "clave": "valor",\n  "n": 1\n}\n```'
    )
    # Negative control: read as before, the marks are gone and a button's text is in.
    assert "## " not in plain and "```" not in plain and "ZZ-MORE-BUTTON" in plain


def test_the_code_blocks_buttons_and_label_chrome_stay_out(reader):
    _, text, plain = reader.read(fixture("decision"))
    assert "ZZ-MORE-BUTTON" not in text and "ZZ-COPY-LABEL" not in text
    assert text.count("```") == 2 and text.split("\n").count("```json") == 1
    assert "ZZ-MORE-BUTTON" in plain  # negative control


def test_the_real_review_skill_accepts_a_rendered_review(reader):
    step = skill_check("hls-review")
    _, text, plain = reader.read(fixture("review"))
    assert check(step, text).ok, check(step, text).error_code
    # Negative control: the same page read as plain text fails the heading check.
    assert "required_headings" in check(step, plain).error_code


def test_the_real_decision_skill_accepts_a_rendered_json_block(reader):
    step = skill_check("architecture-memory")
    _, text, plain = reader.read(fixture("decision"))
    result = check(step, text)
    assert result.ok, result.error_code
    assert result.fields["title"] == "Usar una cola sintética para pedidos"
    assert result.fields["alternatives"] == ["Alternativa A", "Alternativa B"]
    # Negative control: as plain text the label and the button text break the JSON.
    assert not check(step, plain).ok


def test_prose_around_a_lone_code_block_is_kept(reader):
    """An element holding a single code block is the block only if its other text is a
    language label; a sentence next to it is walked, not swallowed."""
    html = ('<div><p>Una frase sintética antes del bloque.</p>'
            '<div><span>python</span><div role="textbox" style="white-space: pre">x = 1</div></div></div>')
    _, text, _ = reader.read(html)
    assert text == "Una frase sintética antes del bloque.\n\n```python\nx = 1\n```"
    # Control: with no label at all the block still fences, with no language.
    _, bare, _ = reader.read('<div><div role="textbox" style="white-space: pre">y = 2</div></div>')
    assert bare == "```\ny = 2\n```"


def test_a_pre_block_and_unmapped_elements(reader):
    html = ('<pre><code class="language-sql">SELECT 1;</code></pre>'
            '<details open><summary>Resumen sintético</summary><span>texto suelto</span></details>'
            '<blockquote><p>cita sintética</p></blockquote><hr><p>a<br>b</p>')
    _, text, _ = reader.read(html)
    assert text == ("```sql\nSELECT 1;\n```\n\nResumen sintético\n\ntexto suelto\n\n"
                    "> cita sintética\n\n---\n\na\nb")


def test_hidden_text_and_controls_stay_out(reader):
    html = ('<h6 style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">'
            'ZZ-SR-LABEL</h6><p>visible</p><p style="display:none">ZZ-NONE</p>'
            '<div role="toolbar"><button>ZZ-CHIP</button></div><div role="menu">ZZ-MENU</div>')
    _, text, plain = reader.read(html)
    assert text == "visible"
    assert "ZZ-CHIP" in plain  # negative control


def test_the_walk_is_bounded_in_depth_and_size(reader):
    """A hostile page cannot make the reader walk without end: past 64 levels or 20 000
    elements the rest is left out, and the result is still capped at `max`."""
    deep = "<div>" * 200 + "ZZ-TOO-DEEP" + "</div>" * 200
    _, text, _ = reader.read("<p>arriba</p>" + deep)
    assert text == "arriba"
    wide = "".join(f"<p>p{n}</p>" for n in range(30_000))
    started = time.monotonic()
    length, text, _ = reader.read(wide, max_chars=1_000)
    assert time.monotonic() - started < 30
    assert len(text) == 1_000 and "p29999" not in text
    assert length < 30_000 * 4  # stopped before the end, not only cut at `max`
    # Control: a shallow page of the same kind is read whole.
    _, small, _ = reader.read("".join(f"<p>p{n}</p>" for n in range(10)))
    assert small.split("\n\n") == [f"p{n}" for n in range(10)]


# -- emphasis wraps inline text only (seen on the real page on 2026-11-26) ---------------------


def test_emphasis_around_blocks_gives_no_markers(reader):
    html = "<strong><h2>Resumen</h2><ul><li>alfa</li><li>beta</li></ul></strong>"
    _, text, _ = reader.read(html)
    assert text == "## Resumen\n\n- alfa\n- beta"


def test_empty_emphasis_gives_nothing(reader):
    """An empty `i` (an icon) before and after the reply printed a line of `**` each."""
    html = '<i class="icon"></i><h2>Resumen</h2><ul><li>alfa</li></ul><em> </em><b></b><code></code>'
    _, text, _ = reader.read(html)
    assert text == "## Resumen\n\n- alfa"
    assert "*" not in text and "`" not in text


def test_nested_emphasis_and_spaces_around_it(reader):
    _, text, _ = reader.read("<p>uno<strong> dos <em>tres</em></strong> cuatro</p>")
    assert text == "uno **dos *tres*** cuatro"


def test_emphasis_across_a_line_break_marks_each_line(reader):
    _, text, _ = reader.read("<p><strong>primera<br>segunda</strong></p>")
    assert text == "**primera**\n**segunda**"


def test_the_skill_checks_still_pass_with_emphasis_and_icons_around(reader):
    review = '<i></i><strong>' + fixture("review") + '</strong><i></i>'
    _, text, _ = reader.read(review)
    assert check(skill_check("hls-review"), text).ok
    decision = '<i></i>' + fixture("decision") + '<em></em>'
    _, text, _ = reader.read(decision)
    assert check(skill_check("architecture-memory"), text).ok
