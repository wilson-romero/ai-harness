"""The structure dump never carries page text (rules of the real-page inspection)."""

import re

import pytest
from playwright.async_api import async_playwright

from harness.browser.structure import UnsafeStructure, check_sanitised, structure_dump

pytestmark = pytest.mark.edge

CANARY = re.compile(r"ZZ-CANARY-[A-Z]+-\d{4}|ZZ CANARY|quarterlyplan|tenant\.invalid", re.I)


async def dump_of(copilot_app, tmp_path) -> list[str]:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            tmp_path / "profile", channel="msedge", headless=True
        )
        try:
            page = context.pages[0]
            await page.goto(copilot_app.url("/structure"))
            return await structure_dump(page)
        finally:
            await context.close()


async def test_no_canary_reaches_the_dump(copilot_app, tmp_path):
    lines = await dump_of(copilot_app, tmp_path)
    dump = "\n".join(lines)
    assert not CANARY.search(dump), CANARY.search(dump)
    # ...while the structure is still there to study
    assert 'data-testid=composer-box' in dump
    assert "role=textbox" in dump and "contenteditable=true" in dump
    assert "data-chat-id=<hex>" in dump  # a uuid is masked, not kept
    assert "class=item.ZZ-CANARY-CLASS-#.r<hex>" in dump  # digit runs masked, words kept
    assert "#shadow-root" in dump and "class=shadow-turn" in dump
    assert "data-testid=<len:13,in-text>" in dump  # a value that is also page text
    assert "href=<len:" in dump and "aria-label=<len:" in dump and "title=<len:" in dump


def test_the_checker_refuses_what_the_rules_should_have_removed():
    check_sanitised(["div data-testid=composer-box text:12 @0,0,10,10"])
    for bad in (
        "div aria-label=Quarterly",
        "div data-testid=plan2025",
        'div title="two words"',
        "div id=ZZ-CANARY-ID-4415",
        "Some text line",
    ):
        with pytest.raises(UnsafeStructure):
            check_sanitised([bad])
