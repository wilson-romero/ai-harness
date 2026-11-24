"""`copilot login`: a person signs in, the harness only looks, and the profile is protected."""

import asyncio
import shutil
import time
from contextlib import asynccontextmanager

import pytest
from playwright.async_api import async_playwright

import harness.browser.login as login_module
from harness.browser.edge import EdgeLauncher
from harness.browser.profile import PROFILE_MARKER
from harness.providers.copilot_ui import measurement_path
from harness.storage.locks import NamedLock
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.edge

SYNTHETIC_UI = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "ui.json"


@pytest.fixture
def login_env(data_dir, tmp_path, copilot_app) -> dict[str, str]:
    path = measurement_path(data_dir)
    path.parent.mkdir(parents=True)
    shutil.copy(SYNTHETIC_UI, path)
    copilot_app.require_login = True
    return {
        "HARNESS_COPILOT_URL": copilot_app.url(),
        "HARNESS_EDGE_PROFILE": str(tmp_path / "edge-profile"),
    }


@pytest.fixture
def launches(monkeypatch) -> list:
    calls = []
    original = EdgeLauncher._launch

    async def spy(self, playwright, profile):
        calls.append(profile)
        return await original(self, playwright, profile)

    monkeypatch.setattr(EdgeLauncher, "_launch", spy)
    return calls


class PersonClosesTheWindow(EdgeLauncher):
    """Stands in for a person who looks at the sign-in page and closes the window."""

    @asynccontextmanager
    async def open(self, **kwargs):
        async with super().open(**kwargs) as context:

            async def close_when_login_shows() -> None:
                page = context.pages[0]
                await page.locator("#synthetic-login-form").wait_for(state="visible")
                await asyncio.sleep(1.0)
                await page.close()

            closer = asyncio.create_task(close_when_login_shows())
            try:
                yield context
            finally:
                closer.cancel()


async def profile_is_free(profile) -> bool:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile), channel="msedge", headless=True
        )
        await context.close()
    return True


def test_login_completed_by_hand_on_a_new_profile(cli, login_env, copilot_app, tmp_path, launches):
    copilot_app.login_auto_ms = 800  # the "person" signs in after a while
    profile = tmp_path / "edge-profile"
    assert not profile.exists()
    code, out, err = cli("copilot", "login", **login_env)
    assert code == 0, err
    assert "ready" in out
    assert (profile / PROFILE_MARKER).is_file()
    assert launches == [profile]
    assert copilot_app.login_events == []
    assert asyncio.run(profile_is_free(profile))  # the browser was closed


def test_window_closed_without_signing_in(cli, login_env, copilot_app, monkeypatch):
    monkeypatch.setattr(login_module, "EdgeLauncher", PersonClosesTheWindow)
    code, _, err = cli("copilot", "login", **login_env)
    assert code == 1
    assert "not signed in" in err
    assert "Traceback" not in err


def test_no_field_touched_during_login(cli, login_env, copilot_app, monkeypatch):
    monkeypatch.setattr(login_module, "EdgeLauncher", PersonClosesTheWindow)
    code, _, _ = cli("copilot", "login", **login_env)
    assert code == 1
    assert copilot_app.page_hits >= 1  # it did open the page
    time.sleep(0.5)  # let any late report from the page arrive
    assert copilot_app.login_events == []


def test_login_with_the_browser_busy(cli, login_env, data_dir, copilot_app, launches):
    holder = NamedLock(data_dir, "browser")
    assert holder.acquire()
    try:
        started = time.monotonic()
        code, _, err = cli("copilot", "login", **login_env)
        assert time.monotonic() - started < 5
    finally:
        holder.release()
    assert code == 1
    assert "in use" in err
    assert launches == []
    assert copilot_app.page_hits == 0


def test_foreign_profile_directory_is_refused(cli, login_env, tmp_path, copilot_app, launches):
    profile = tmp_path / "edge-profile"
    profile.mkdir()
    (profile / "Bookmarks").write_text("{}", encoding="utf-8")
    code, _, err = cli("copilot", "login", **login_env)
    assert code == 1
    assert "not an ai-harness Edge profile" in err
    assert launches == []
    assert copilot_app.page_hits == 0
    assert not (profile / PROFILE_MARKER).exists()


# `copilot login` in a child process, so that output printed while Python shuts down is seen.
LOGIN_EXIT_DRIVER = r"""
import asyncio, gc, sys
import playwright._impl.transport as transport
import harness.browser.login as login
from harness.cli import main

mode = sys.argv[1]
drivers = []
real_init = transport.PipeTransport.__init__
def tracking_init(self, *args, **kwargs):
    real_init(self, *args, **kwargs)
    drivers.append(self)
transport.PipeTransport.__init__ = tracking_init

real_classify = login.classify
async def classify(page, measurement, host):
    state = await real_classify(page, measurement, host)
    if mode in ("driver-dies", "driver-dies-then-ctrl-c") and drivers[0]._proc.returncode is None:
        drivers[0]._proc.kill()
        await drivers[0]._proc.wait()
        await asyncio.sleep(0.5)
    if mode in ("ctrl-c", "driver-dies-then-ctrl-c"):
        raise KeyboardInterrupt
    return state
login.classify = classify

code = main(["copilot", "login"])
drivers.clear()
gc.collect()
print("exit", code, flush=True)
sys.exit(code)
"""


@pytest.mark.parametrize(
    "mode, code", [("ctrl-c", 130), ("driver-dies", 1), ("driver-dies-then-ctrl-c", 130)]
)
def test_login_ends_cleanly_however_it_is_interrupted(mode, code, login_env, data_dir):
    import os
    import subprocess
    import sys

    from tests.conftest import HARNESS_VARS

    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    env |= login_env | {
        "HARNESS_DATA_DIR": str(data_dir),
        "HARNESS_TEST_HEADLESS": "1",
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONUTF8": "1",
    }
    run = subprocess.run(
        [sys.executable, "-c", LOGIN_EXIT_DRIVER, mode],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    lines = run.stdout.strip().splitlines()
    assert run.returncode == code, run.stdout
    assert lines[-1] == f"exit {code}"  # nothing printed after the command's own last line
    assert "never retrieved" not in run.stdout and "Traceback" not in run.stdout, run.stdout
    assert NamedLock(data_dir, "browser").acquire()


def test_login_needs_the_probe_measurement(cli, login_env, data_dir, copilot_app, launches):
    measurement_path(data_dir).unlink()
    code, _, err = cli("copilot", "login", **login_env)
    assert code == 1
    assert "run the probe" in err
    assert launches == []
    assert copilot_app.page_hits == 0
