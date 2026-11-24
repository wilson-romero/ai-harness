"""The synthetic chat app behaves as the browser tests need, and its server counts prompts."""

from collections.abc import AsyncIterator

import pytest
from playwright.async_api import Page, async_playwright, expect

from tests.copilot_app import wait_until

pytestmark = pytest.mark.edge


@pytest.fixture
async def page(tmp_path) -> AsyncIterator[Page]:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"), channel="msedge", headless=True
        )
        try:
            yield context.pages[0] if context.pages else await context.new_page()
        finally:
            await context.close()


async def send(page: Page, prompt: str) -> None:
    await page.locator("#synthetic-composer").fill(prompt)
    await page.get_by_role("button", name="Send synthetic message", exact=True).click()


async def test_one_prompt_sent_by_hand_is_counted_once(page, copilot_app):
    await page.goto(copilot_app.url())
    await send(page, "synthetic question ZQX-END-1")
    assistant = page.locator("#synthetic-thread .turn.assistant")
    await expect(assistant.locator(".synthetic-copy")).to_have_count(1)
    await expect(assistant).to_contain_text("ZQX-END-1")
    assert copilot_app.prompt_count == 1
    conversation = copilot_app.prompts[0].conversation
    assert page.url.startswith(f"{copilot_app.base}/c/{conversation}")


async def test_nothing_is_counted_without_sending(page, copilot_app):
    await page.goto(copilot_app.url())
    await page.locator("#synthetic-composer").fill("typed but never sent")
    await page.wait_for_timeout(500)
    assert copilot_app.prompt_count == 0


async def test_conversation_reopens_from_its_url(page, copilot_app):
    await page.goto(copilot_app.url())
    await send(page, "first ZQX-END-1")
    await expect(page.locator(".synthetic-copy")).to_have_count(1)
    url = page.url
    await page.goto(copilot_app.url())
    await page.goto(url)
    await expect(page.locator("#synthetic-thread .turn.user")).to_have_count(1)
    assert page.url == url


async def test_forgotten_or_missing_conversation_opens_a_new_one(page, copilot_app):
    await page.goto(copilot_app.url("/c/0123456789abcdef"))
    await expect(page).to_have_url(f"{copilot_app.base}/app")
    await page.goto(copilot_app.url(forget="1"))
    await send(page, "first ZQX-END-1")
    await expect(page.locator(".synthetic-copy")).to_have_count(1)
    await page.goto(page.url)
    await expect(page).to_have_url(f"{copilot_app.base}/app?forget=1")
    await expect(page.locator("#synthetic-thread .turn")).to_have_count(0)


async def test_done_control_can_be_made_to_appear_early(page, copilot_app):
    await page.goto(copilot_app.url(early="done_control", pause_ms="1500"))
    await send(page, "early ZQX-END-2")
    assistant = page.locator("#synthetic-thread .turn.assistant")
    await expect(assistant.locator(".synthetic-copy")).to_have_count(1)
    assert "ZQX-END-2" not in await assistant.inner_text()  # the signal came before the end
    await expect(assistant).to_contain_text("ZQX-END-2")


async def test_reply_that_never_finishes(page, copilot_app):
    await page.goto(copilot_app.url(never_finish="1"))
    await send(page, "endless ZQX-END-3")
    await page.wait_for_timeout(1500)
    stop = page.get_by_role("button", name="Stop synthetic reply", exact=True)
    await expect(stop).to_be_visible()
    assert "ZQX-END-3" not in await page.locator(".turn.assistant").inner_text()


async def test_login_redirects_to_another_host_and_counts_interaction(page, copilot_app):
    copilot_app.require_login = True
    await page.goto(copilot_app.url())
    await expect(page.locator("#synthetic-login-form")).to_be_visible()
    assert page.url.startswith(f"http://localhost:{copilot_app.port}/login")
    assert copilot_app.login_events == []
    await page.locator("#synthetic-user").click()
    await page.keyboard.press("a")
    await wait_until(lambda: len(copilot_app.login_events) > 1, what="login events")


async def test_login_completes_by_itself_after_a_delay(page, copilot_app):
    copilot_app.require_login = True
    copilot_app.login_auto_ms = 300
    await page.goto(copilot_app.url())
    await expect(page.locator("#synthetic-composer")).to_be_visible(timeout=10_000)
    assert page.url.startswith(copilot_app.base)
    assert copilot_app.login_events == []
