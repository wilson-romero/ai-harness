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
