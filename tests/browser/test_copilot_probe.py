"""The Copilot probe, run against the synthetic chat pages (spec `copilot-ui-probe`)."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from harness.core.contracts import Session, SessionStatus
from harness.providers.copilot_ui import MeasurementError, load_measurement, measurement_path
from harness.storage import repositories as repo
from harness.storage.database import open_database, transaction
from harness.storage.locks import NamedLock
from tests.conftest import HARNESS_VARS, REPO_ROOT
from tests.copilot_app import CANARIES, SyntheticCopilot

pytestmark = pytest.mark.edge

PROBE_PATH = REPO_ROOT / "scripts" / "copilot_probe.py"
SYNTHETIC_UI = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "ui.json"
TENANT_CANARY = "ZZ-CANARY-TENANT-5150"
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".zip", ".har", ".webm", ".mp4", ".trace"}


def load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("copilot_probe_under_test", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while it loads
    spec.loader.exec_module(module)
    return module


def make_fast(patch: pytest.MonkeyPatch, probe: ModuleType, **overrides) -> None:
    """Shorter windows and fewer sizes so a synthetic run takes seconds, same logic."""
    settings = {
        "STABLE_WINDOWS_MS": (300, 600, 1200),
        "SETTLE_MS": 500,
        "SEND_DEADLINE_S": 20.0,
        "TURNS_SETTLE_S": 2.0,
        "LOGIN_HOST_SETTLE_S": 0.5,
        "SIZES": (2000, 8000),
    } | overrides
    for name, value in settings.items():
        patch.setattr(probe, name, value)


def write_candidates(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    locators = json.loads(SYNTHETIC_UI.read_text(encoding="utf-8"))["locators"]
    (out_dir / "candidates.json").write_text(json.dumps(locators), encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


async def person_signs_in(context) -> bool:
    """Stands in for Wilson: waits until the chat is ready, then 'presses Enter'."""
    await context.pages[0].locator("#synthetic-composer").wait_for(state="visible", timeout=15_000)
    return True


def clean_env(patch: pytest.MonkeyPatch, **values: str) -> None:
    for name in HARNESS_VARS:
        patch.delenv(name, raising=False)
    patch.setenv("HARNESS_TEST_HEADLESS", "1")
    patch.setenv("HARNESS_COPILOT_READY_TIMEOUT_S", "15")
    for key, value in values.items():
        patch.setenv(key, value)


@dataclass
class Run:
    app: SyntheticCopilot
    probe: ModuleType
    codes: dict[str, int]
    stdout: str
    repo: Path
    data: Path
    url: str
    repo_status_before: str
    repo_status_after: str
    real_status_before: str
    real_status_after: str

    def result(self, step: str) -> dict:
        # the stamp starts with a digit: "login" must not pick probe-login-state-*
        files = sorted((self.data / "copilot").glob(f"probe-{step}-[0-9]*.json"))
        return json.loads(files[-1].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def full_run(edge_ready, tmp_path_factory) -> Run:
    """login -> measure -> login-state, with the default data directory of a Git work tree."""
    root = tmp_path_factory.mktemp("probe-full")
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    shutil.copy(REPO_ROOT / ".gitignore", repo / ".gitignore")
    app = SyntheticCopilot(require_login=True, login_auto_ms=500).start()
    url = app.url(tenant=TENANT_CANARY)
    probe = load_probe()
    real_before = git(REPO_ROOT, "status", "--porcelain")
    repo_before = git(repo, "status", "--porcelain")
    codes, out = {}, io.StringIO()
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.chdir(repo)  # HARNESS_DATA_DIR unset: the default ./data, ignored by Git
            clean_env(patch, HARNESS_COPILOT_URL=url)
            make_fast(patch, probe)
            patch.setattr(probe, "wait_for_person", person_signs_in)
            write_candidates(repo / "data" / "copilot")
            with redirect_stdout(out):
                codes["login"] = probe.main(["login"])
                codes["measure"] = probe.main(["measure"])
                app.login_auto_ms = None  # nobody signs in on the empty profile
                codes["login-state"] = probe.main(["login-state"])
    finally:
        app.stop()
    return Run(
        app, probe, codes, out.getvalue(), repo, repo / "data", url,
        repo_before, git(repo, "status", "--porcelain"),
        real_before, git(REPO_ROOT, "status", "--porcelain"),
    )


def test_full_probe_run_succeeds(full_run):
    assert full_run.codes == {"login": 0, "measure": 0, "login-state": 0}, full_run.stdout
    assert "copilot probe summary" in full_run.stdout


def test_login_describes_where_copilot_was_ready(full_run):
    assert ("ready page: on configured host yes  path segments 1  ready path /app  "
            "signed-out hints 0") in full_run.stdout
    assert full_run.result("login")["ready_path"] == "/app"
    assert full_run.result("login")["ready_host"] == "127.0.0.1"  # data directory only


def test_prompts_sent_belong_to_the_fixed_list(full_run):
    fixed = set(full_run.probe.all_prompts())
    received = [r.prompt for r in full_run.app.prompts]
    assert received and all(prompt in fixed for prompt in received)
    assert len(received) == 3 * 4 + 2  # 12 timed sends and 2 prompt sizes


def test_result_in_the_data_directory_and_nothing_new_for_git(full_run):
    files = sorted(p.name for p in (full_run.data / "copilot").glob("probe-*.json"))
    assert [f.split("-20")[0] for f in files] == ["probe-login", "probe-login-state", "probe-measure"]
    assert (full_run.data / "copilot" / "ui.json").is_file()
    assert full_run.repo_status_after == full_run.repo_status_before
    assert full_run.real_status_after == full_run.real_status_before


def test_canaries_are_absent_from_the_measurement(full_run):
    texts = [p.read_text(encoding="utf-8") for p in (full_run.data / "copilot").glob("*.json")]
    texts.append(full_run.stdout)
    forbidden = [*CANARIES, TENANT_CANARY, full_run.url, f":{full_run.app.port}"]
    for text in texts:
        for canary in forbidden:
            assert canary not in text


def test_no_binary_artifacts(full_run):
    created = [
        p
        for p in full_run.repo.rglob("*")
        if p.is_file()
        and ".git" not in p.relative_to(full_run.repo).parts
        and (p.suffix.lower() in BINARY_SUFFIXES or p.name.startswith("storage_state"))
        # Edge keeps its own default avatar image inside the profile: browser data, not a
        # capture. Any other binary there (trace, HAR, video, state) still fails.
        and not (
            "edge-profile" in p.relative_to(full_run.repo).parts
            and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
        )
    ]
    assert created == []
    written = [p.name for p in (full_run.data / "copilot").rglob("*") if p.is_file()]
    assert all(name.endswith(".json") for name in written), written


def test_reliable_signal_chosen(full_run):
    measure = full_run.result("measure")
    assert measure["complete"], measure["missing"]
    for name in ("stop_hidden", "send_ready", "done_control", "aria_busy", "text_stable_300"):
        assert measure["signals"][name]["valid"], name
        assert measure["signals"][name]["early"] == 0
    assert measure["end_signal"]["name"] in ("stop_hidden", "send_ready", "done_control", "aria_busy")
    assert measure["stability_window_ms"] == 300
    assert measure["max_prompt_chars"] == 8000
    ui = load_measurement(full_run.data)  # what the provider will accept
    assert ui.complete and ui.login.hosts == ("localhost",)


def test_conversation_reopened(full_run):
    measure = full_run.result("measure")
    assert measure["conversation_ref"] == {"kind": "path_segment", "index": 1, "prefix": ["c"]}
    assert measure["identity_recoverable"] is True
    # reopened from the identifier alone: the full URL (with the tenant canary in its query)
    # was never needed, and the query is in no file
    assert measure["reopened_from_identifier"] == 3
    assert measure["turns_visible_after_reopen"] == [4, 4, 4]
    assert len(measure["startup_ms"]) == 7


def test_expired_login_shape(full_run):
    state = full_run.result("login-state")
    assert state["state"] == "login_indicator"
    assert state["login_hosts"] == ["localhost"]
    assert full_run.app.login_events == []


@pytest.fixture
def quick(tmp_path, monkeypatch, copilot_app):
    """A probe on a temporary data directory, one conversation, one size."""
    probe = load_probe()
    data = tmp_path / "data"
    clean_env(monkeypatch, HARNESS_DATA_DIR=str(data))
    make_fast(monkeypatch, probe, CONVERSATIONS=1, SIZES=(2000,))
    write_candidates(data / "copilot")
    return probe, data


def test_premature_signal_is_discarded(quick, copilot_app, monkeypatch):
    probe, data = quick
    # The page pauses 1.2 s: well above the shortest window (0.3 s) and well below the
    # longest (3 s), so load on the machine cannot move the pause across either.
    monkeypatch.setattr(probe, "STABLE_WINDOWS_MS", (300, 600, 3000))
    url = copilot_app.url(early="done_control", pause_ms="1200", forget="1")
    monkeypatch.setenv("HARNESS_COPILOT_URL", url)
    probe.main(["measure"])
    measure = json.loads(sorted((data / "copilot").glob("probe-measure-*.json"))[-1].read_text())
    signals = measure["signals"]
    assert signals["done_control"]["valid"] is False
    assert signals["done_control"]["early"] == 4  # every send, counted
    assert signals["text_stable_300"]["valid"] is False and signals["text_stable_300"]["early"] > 0
    assert signals["text_stable_3000"]["valid"] is True
    assert signals["stop_hidden"]["valid"] is True
    assert measure["end_signal"]["name"] != "done_control"


def test_conversation_not_recoverable(quick, copilot_app, monkeypatch):
    probe, data = quick
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(forget="1"))
    probe.main(["measure"])
    measure = json.loads(sorted((data / "copilot").glob("probe-measure-*.json"))[-1].read_text())
    assert measure["identity_recoverable"] is False
    assert measure["turns_visible_after_reopen"] == [0]


def test_interrupted_probe_is_marked_incomplete(quick, copilot_app, monkeypatch):
    probe, data = quick
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url())
    real_send, calls = probe.sample_send, []

    async def interrupted(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt  # Wilson presses Ctrl+C before the signal is measured
        return await real_send(*args, **kwargs)

    monkeypatch.setattr(probe, "sample_send", interrupted)
    assert probe.main(["measure"]) == 130
    measure = json.loads(sorted((data / "copilot").glob("probe-measure-*.json"))[-1].read_text())
    assert measure["complete"] is False and measure["interrupted"] is True
    assert "end_signal" in measure["missing"]
    assert not measurement_path(data).exists()  # no ui.json from a partial run
    draft, status = probe.assemble(data / "copilot")
    assert status.startswith("not written") and "end_signal" in status
    measurement_path(data).write_text(draft.model_dump_json(), encoding="utf-8")
    with pytest.raises(MeasurementError, match="incomplete; missing: .*end_signal"):
        load_measurement(data)  # the provider's gate names the missing part


def run_probe_process(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS} | env
    return subprocess.run(
        [sys.executable, str(PROBE_PATH), *args],
        cwd=REPO_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


@pytest.mark.parametrize("args", [("measure", "my own prompt"), ("measure", "--prompt", "x")])
def test_probe_refuses_a_prompt_of_its_own(args, tmp_path, copilot_app):
    result = run_probe_process(
        *args, HARNESS_DATA_DIR=str(tmp_path / "data"), HARNESS_COPILOT_URL=copilot_app.url()
    )
    assert result.returncode == 2
    assert copilot_app.page_hits == 0
    assert not (tmp_path / "data").exists()


def test_versionable_data_directory_is_refused(tmp_path, copilot_app):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    data = repo / "measurements"
    write_candidates(data / "copilot")
    before = sorted(p.name for p in (data / "copilot").iterdir())
    result = run_probe_process(
        "measure", HARNESS_DATA_DIR=str(data), HARNESS_COPILOT_URL=copilot_app.url()
    )
    assert result.returncode == 1
    assert "could be committed" in result.stderr
    assert copilot_app.page_hits == 0
    assert sorted(p.name for p in (data / "copilot").iterdir()) == before


# The probe run in a child process, so that whatever asyncio or Playwright print while the
# interpreter shuts down is captured too. `mode` says how the run ends:
#   driver-dies-then-ctrl-c: the Playwright driver dies and Ctrl+C arrives while the page loads
#       (what a console Ctrl+C does on Windows: it reaches the driver as well as Python);
#   ctrl-c-while-loading: only Ctrl+C, while the page loads;
#   browser-closed: the browser goes away while the probe waits for the person;
#   driver-dies-while-waiting: the driver dies while the probe waits for the person.
EXIT_DRIVER = r"""
import asyncio, gc, importlib.util, sys
import playwright._impl.transport as transport

probe_path, mode, step = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("probe_exit", probe_path)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)

drivers = []
real_init = transport.PipeTransport.__init__
def tracking_init(self, *args, **kwargs):
    real_init(self, *args, **kwargs)
    drivers.append(self)
transport.PipeTransport.__init__ = tracking_init

class Interrupted:
    def __init__(self, page):
        self._page = page
    def __getattr__(self, name):
        return getattr(self._page, name)
    async def goto(self, *args, **kwargs):
        if mode == "driver-dies-then-ctrl-c":
            for driver in drivers:
                driver._proc.kill()
                await driver._proc.wait()
            await asyncio.sleep(0.5)  # the reader sees the pipe close
        raise KeyboardInterrupt

real_first_page = probe.first_page
def first_page(context):
    page = real_first_page(context)
    return Interrupted(page) if "ctrl-c" in mode else page
probe.first_page = first_page

async def browser_goes_away(context):
    session = await context.new_cdp_session(context.pages[0])
    try:
        await session.send("Browser.close")
    except Exception:
        pass
    await asyncio.sleep(1.0)
    return False
if mode == "browser-closed":
    probe.wait_for_person = browser_goes_away

real_wait = probe.wait_for_person
async def driver_dies_while_waiting(context):
    drivers[0]._proc.kill()
    await drivers[0]._proc.wait()
    return await real_wait(context)  # the real wait must notice, not hang
if mode == "driver-dies-while-waiting":
    probe.wait_for_person = driver_dies_while_waiting

code = probe.main([step])
drivers.clear()  # the test's own reference must not keep the driver's futures alive
gc.collect()
sys.exit(code)
"""


def run_exit_driver(mode: str, step: str, data: Path, url: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    env |= {
        "HARNESS_DATA_DIR": str(data),
        "HARNESS_COPILOT_URL": url,
        "HARNESS_TEST_HEADLESS": "1",
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONUTF8": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", EXIT_DRIVER, str(PROBE_PATH), mode, step],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # one stream, so "after the summary" is well defined
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def after_summary(output: str) -> str:
    return output.rpartition("---- end of summary ----")[2].strip()


@pytest.mark.parametrize(
    "mode, code, p1",
    [
        ("driver-dies-then-ctrl-c", 130, "P1 controllable: not measured"),
        ("ctrl-c-while-loading", 130, "P1 controllable: not measured"),
        ("browser-closed", 1, "P1 controllable: yes"),
        ("driver-dies-while-waiting", 1, "P1 controllable: yes"),
    ],
)
def test_login_step_ends_cleanly_however_it_is_interrupted(mode, code, p1, tmp_path, copilot_app):
    data = tmp_path / "data"
    run = run_exit_driver(mode, "login", data, copilot_app.url())
    assert run.returncode == code, run.stdout
    assert "---- end of summary ----" in run.stdout
    assert after_summary(run.stdout) == ""  # nothing at all after the summary
    assert "never retrieved" not in run.stdout and "Traceback" not in run.stdout
    assert p1 in run.stdout
    login = json.loads(sorted((data / "copilot").glob("probe-login-*.json"))[-1].read_text())
    assert login["complete"] is False
    assert isinstance(login["launch_ms"], int)  # the launch did happen
    assert NamedLock(data, "browser").acquire()  # and the browser was given back


def test_structure_step_writes_a_text_free_dump(quick, copilot_app, monkeypatch):
    probe, data = quick
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(tenant=TENANT_CANARY))
    out = io.StringIO()
    with redirect_stdout(out):
        assert probe.main(["structure"]) == 0
    dumps = list((data / "copilot").glob("structure-*.txt"))
    assert len(dumps) == 1
    for text in (dumps[0].read_text(encoding="utf-8"), out.getvalue()):
        for canary in (*CANARIES, TENANT_CANARY):
            assert canary not in text
    assert "on Copilot host: yes" in out.getvalue()
    assert copilot_app.prompt_count == 0  # it sends nothing


def test_structure_step_stops_on_a_sign_in_page(quick, copilot_app, monkeypatch):
    probe, data = quick
    copilot_app.require_login = True  # nobody signs in
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url())
    monkeypatch.setenv("HARNESS_COPILOT_READY_TIMEOUT_S", "3")
    out = io.StringIO()
    with redirect_stdout(out):
        assert probe.main(["structure"]) == 1
    assert "on Copilot host: no" in out.getvalue()
    assert not list((data / "copilot").glob("structure-*.txt"))
    assert copilot_app.login_events == []


def test_a_signal_read_while_the_page_finishes_is_not_early(quick, copilot_app, monkeypatch):
    """Reads in one sample follow one another while the page keeps writing. Here the probe
    is made slow between reading the text and judging it (0.3 s), far longer than the 40 ms
    between the reply's last words and its end signals: a signal read after the page finished
    must not be judged against text read before it. Seen once in a loaded full run, where
    `send_ready` was marked early on the synthetic page that never fires it early."""
    probe, data = quick
    original = probe.content_up_to

    def slow(text, marker):
        time.sleep(0.3)  # the browser keeps going; only the probe waits
        return original(text, marker)

    monkeypatch.setattr(probe, "content_up_to", slow)
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(forget="1"))
    assert probe.main(["measure"]) == 0
    measure = json.loads(sorted((data / "copilot").glob("probe-measure-*.json"))[-1].read_text())
    for name in ("stop_hidden", "send_ready", "done_control", "aria_busy"):
        assert measure["signals"][name]["early"] == 0, name
        assert measure["signals"][name]["valid"] is True, name


# -- code-language: the label element of a code block, measured without sending ------------------


RICH = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "rich"


def bound_session(app: SyntheticCopilot, data: Path, html: str) -> str:
    """A session bound to a synthetic conversation whose one answer renders `html`."""
    from datetime import UTC, datetime
    from uuid import uuid7

    conversation = f"code{uuid7().hex[:12]}"
    app.conversations[conversation] = [
        {"role": "user", "text": "ZQX-RICH-elements"},
        {"role": "assistant", "text": "", "html": html},
    ]
    now = datetime.now(UTC)
    session = Session(session_id=uuid7(), name="Bloque", provider="copilot_web",
                      status=SessionStatus.ACTIVE, created_at=now, updated_at=now)
    conn = open_database(data)
    with transaction(conn):
        repo.insert_session(conn, session)
        repo.bind_remote_ref(conn, session.session_id, conversation)
    conn.close()
    return str(session.session_id)


def measurement_without_code_language(data: Path) -> bytes:
    ui = json.loads(SYNTHETIC_UI.read_text(encoding="utf-8"))
    del ui["locators"]["code_language"]
    target = measurement_path(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(ui), encoding="utf-8")
    return target.read_bytes()


def test_code_language_step_measures_the_label_element_without_sending(quick, copilot_app, monkeypatch):
    """Review 2026-11-26: the language of a code block comes only from a measured element.
    The step finds it by structure on a conversation that shows a code block, checks it with
    the reader (a language with it, none without), and adds it to ui.json, keeping the old."""
    probe, data = quick
    measurement_without_code_language(data)
    session = bound_session(copilot_app, data, (RICH / "elements.html").read_text("utf-8"))
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url())
    out = io.StringIO()
    with redirect_stdout(out):
        assert probe.main(["code-language", "--session", session]) == 0
    code_language = load_measurement(data).locators.code_language
    assert code_language is not None and code_language.test_id == "synthetic-code-identity"
    assert "checked: yes" in out.getvalue() and "fences with a language: 1 (without the locator: 0)" in out.getvalue()
    assert len(list((data / "copilot").glob("ui-*.json"))) == 1  # the old measurement, kept
    assert copilot_app.prompt_count == 0  # it sends nothing
    result = next((data / "copilot").glob("probe-code-language-*.json")).read_text("utf-8")
    for text in (out.getvalue(), result):
        for canary in ("ZZ-COPY-LABEL", "ZZ-MORE-BUTTON", "clave", "valor", *CANARIES):
            assert canary not in text


def test_control_a_conversation_without_code_leaves_the_measurement_alone(quick, copilot_app, monkeypatch):
    probe, data = quick
    before = measurement_without_code_language(data)
    session = bound_session(copilot_app, data, "<p>Respuesta sintética sin código.</p>")
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url())
    with redirect_stdout(io.StringIO()):
        assert probe.main(["code-language", "--session", session]) == 1
    assert measurement_path(data).read_bytes() == before
    assert not list((data / "copilot").glob("ui-*.json"))


def test_a_prose_word_beside_a_code_box_is_not_measured_as_a_label(quick, copilot_app, monkeypatch):
    """Negative control: a plain span next to the code box has no data-testid, so nothing is
    chosen and nothing is written."""
    probe, data = quick
    before = measurement_without_code_language(data)
    html = ('<div><span>Respuesta</span>'
            '<div role="textbox" style="white-space: pre">x = 1</div></div>')
    session = bound_session(copilot_app, data, html)
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url())
    with redirect_stdout(io.StringIO()):
        assert probe.main(["code-language", "--session", session]) == 1
    assert measurement_path(data).read_bytes() == before


def test_measure_keeps_the_measured_code_language(full_run, tmp_path):
    """`assemble` (run by measure, login-state and sizes) keeps the latest code-language
    locator; without one, ui.json has none."""
    out = tmp_path / "copilot"
    shutil.copytree(full_run.data / "copilot", out)
    measured = sorted(out.glob("probe-measure-[0-9]*.json"))[-1]
    result = json.loads(measured.read_text("utf-8"))
    result["locators"].pop("code_language", None)  # a measure made before the locator existed
    measured.write_text(json.dumps(result), "utf-8")
    _, status = full_run.probe.assemble(out)
    assert status == "written", status
    assert json.loads((out / "ui.json").read_text("utf-8"))["locators"].get("code_language") is None
    (out / "probe-code-language-29991231T000000000000Z.json").write_text(json.dumps(
        {"complete": True, "code_language": {"test_id": "synthetic-code-identity"}}), "utf-8")
    full_run.probe.assemble(out)
    locators = json.loads((out / "ui.json").read_text("utf-8"))["locators"]
    assert locators["code_language"]["test_id"] == "synthetic-code-identity"


def test_a_header_whose_text_is_not_a_language_is_not_measured(quick, copilot_app, monkeypatch):
    """Negative control: an element with a data-testid next to the code, holding two words,
    is not a language label; nothing is chosen and nothing is written."""
    probe, data = quick
    before = measurement_without_code_language(data)
    html = ('<div><div data-testid="synthetic-code-identity"><span>dos palabras</span></div>'
            '<div role="textbox" style="white-space: pre">x = 1</div></div>')
    session = bound_session(copilot_app, data, html)
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url())
    with redirect_stdout(io.StringIO()):
        assert probe.main(["code-language", "--session", session]) == 1
    assert measurement_path(data).read_bytes() == before
