"""Static rules for the code that drives Edge.

No recording of any kind (screenshots, traces, HAR, video, storage state) anywhere, and the
browser package only looks at pages: it never types, fills, presses or clicks.
"""

import re

from tests.conftest import REPO_ROOT

RECORDING = re.compile(
    r"record_har|record_video|\.tracing\b|\.screenshot\(|\bstorage_state\s*[=(]|"
    r"\.storage_state\(|\.pdf\(|\.video\b"
)
INPUT_ACTIONS = re.compile(r"\.(fill|type|press|click|check|select_option|set_input_files)\(|keyboard|mouse")


def _files(*roots: str) -> list:
    paths = []
    for root in roots:
        path = REPO_ROOT / root
        paths += [path] if path.is_file() else sorted(path.rglob("*.py"))
    return paths


def _offenders(pattern: re.Pattern[str], *roots: str) -> list[str]:
    found = []
    for path in _files(*roots):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            if pattern.search(code):
                found.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{number}: {line.strip()}")
    return found


def test_no_recording_options_anywhere_near_the_browser():
    roots = [
        "harness",
        "scripts/copilot_probe.py",
        "scripts/copilot_discovery.py",
        "tests/browser",
        "tests/copilot_app.py",
    ]
    assert _offenders(RECORDING, *[r for r in roots if (REPO_ROOT / r).exists()]) == []


def test_browser_package_never_interacts_with_the_page():
    assert _offenders(INPUT_ACTIONS, "harness/browser") == []


def test_provider_types_only_into_the_editor_and_sends_only_with_the_measured_control():
    """The Copilot provider has exactly three input actions that write or send: fill the
    editor, press Enter in the editor, click the measured send control. Revised 2026-11-27
    (response-mode D3): three more, only in the measured response-mode selector, before
    anything is typed: click its opener, click the option of one mode, press Escape to close
    its list. Nothing else is typed, pressed or clicked."""
    found = _offenders(INPUT_ACTIONS, "harness/providers")
    actions = sorted(line.split(": ", 1)[1] for line in found)
    assert len(actions) == 6, found
    assert all(line.startswith("harness/providers/copilot_web.py:") for line in found)
    assert any(a.startswith("await composer.fill(self.request.prompt") for a in actions)
    assert any(a.startswith('await composer.press("Enter"') for a in actions)
    assert any(a.startswith("await self.locators.send.resolve(page).first.click(") for a in actions)
    assert any(a.startswith("await trigger.click(") for a in actions)
    assert any(a.startswith("await option.click(") for a in actions)
    assert any(a.startswith('await self.page.keyboard.press("Escape")') for a in actions)


LAUNCH = re.compile(r"\.launch_persistent_context\(|\bchromium\.launch\(|\.connect_over_cdp\(")


def test_edge_is_launched_in_one_place_only():
    """Every path that opens the dedicated profile (`copilot login`, the probe, a one-shot
    `ask`, a conversation's `open_resources`) goes through `EdgeLauncher._launch`, so all of
    them pass the same arguments (sandbox, dropped defaults, Playwright's `--password-store` and
    `--use-mock-keychain`, which set where the cookie key comes from) and the same profile
    directory. A second launch site could open the profile with another key source and lose
    its cookies (2026-11-26 review of the lost sessions)."""
    found = _offenders(LAUNCH, "harness", "main.py", "scripts")
    assert [f.split(":")[0] for f in found] == ["harness/browser/edge.py"], found


def test_the_launch_rule_sees_another_launch_site(tmp_path):
    """Negative control: the pattern catches a direct launch however it is written."""
    for line in ("ctx = await pw.chromium.launch_persistent_context(str(p))",
                 "browser = await playwright.chromium.launch(channel='msedge')",
                 "b = await pw.chromium.connect_over_cdp('http://127.0.0.1:9222')"):
        assert LAUNCH.search(line), line
    assert not LAUNCH.search("async with launcher.open(wait_s=None) as context:")
