"""Static rules for the code that drives Edge.

No recording of any kind (screenshots, traces, HAR, video, storage state) anywhere, and the
browser package only looks at pages: it never types, fills, presses or clicks.
"""

import ast
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


def _scopes(path, line_numbers: set[int]) -> dict[int, str]:
    """For each line, the `Class.method` (or function) whose body holds it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[int, str] = {}

    def visit(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                for number in line_numbers:
                    if child.lineno <= number <= (child.end_lineno or child.lineno):
                        found[number] = name
                visit(child, name + ".")

    visit(tree, "")
    return found


def test_provider_types_only_into_the_editor_and_sends_only_with_the_measured_control():
    """The Copilot provider has exactly three input actions that write or send: fill the
    editor, press Enter in the editor, click the measured send control, each in its own
    method of a question's turn. Revised 2026-11-27 (response-mode D3, independent review):
    two more, and only inside the measured response-mode selector (`_ModeSelector`): one
    click, which refuses any element that is another control, and Escape to close its list.
    The selector runs before anything is typed and, to read the mode again after the answer,
    once the reply has ended; it never types. Nothing else is typed, pressed or clicked."""
    path = REPO_ROOT / "harness" / "providers" / "copilot_web.py"
    found = _offenders(INPUT_ACTIONS, "harness/providers")
    assert all(line.startswith("harness/providers/copilot_web.py:") for line in found), found
    actions = {int(line.split(":")[1]): line.split(": ", 1)[1] for line in found}
    scopes = _scopes(path, set(actions))
    where = sorted((scopes.get(number, "<module>"), text.split("(")[0])
                   for number, text in actions.items())
    assert where == [
        ("_ModeSelector._click", "await element.click"),
        ("_ModeSelector.close", 'await self.page.keyboard.press'),
        ("_Turn.put_prompt", "await composer.fill"),
        ("_Turn.submit", "await composer.press"),
        ("_Turn.submit", "await self.locators.send.resolve"),
    ], found
    assert any(a.startswith("await composer.fill(self.request.prompt") for a in actions.values())
    assert any(a.startswith('await composer.press("Enter"') for a in actions.values())
    assert any(a.startswith('await self.page.keyboard.press("Escape")') for a in actions.values())


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
