"""The Enterprise Architect probe, everywhere except the real COM path.

The real path (pywin32 and Enterprise Architect on Windows) has never run in these tests: the
COM layer is replaced by a fake with the same small interface. What is proven here is the
control flow around it: what happens without pywin32, with each kind of failure, with a step
that hangs, what the summary may contain, and where the detail may be written.

No test may reach real COM (hotfix 0.2.1): the real script is started only without
site-packages, so pywin32 cannot be imported even where it is installed.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ea_probe.py"
GUID_SHAPE = re.compile(r"\{?[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}?")
PLATFORM_CONDITIONAL = re.compile(
    r"\bsys\.platform\b|\bos\.name\b|\bplatform\.system\b|\bimport (msvcrt|fcntl|winreg)\b"
)


def load_probe() -> Any:
    spec = importlib.util.spec_from_file_location("ea_probe_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up while building classes
    spec.loader.exec_module(module)
    return module


probe = load_probe()


# -- a fake of the few Automation Interface objects the probe uses -------------------------------


class FakeComError(Exception):
    """Shaped like pywintypes.com_error: (hresult, message, excepinfo, argerror)."""

    def __init__(self, hresult: int, message: str, excepinfo: tuple | None = None) -> None:
        super().__init__(hresult, message, excepinfo, None)
        self.hresult = hresult


def signed(value: int) -> int:
    """pywin32 reports HRESULTs as signed 32-bit integers."""
    return value - (1 << 32) if value & 0x80000000 else value


class Collection:
    def __init__(self, repo: FakeRepository, make: Any) -> None:
        self._repo, self._make, self._items = repo, make, []

    def AddNew(self, name: str, kind: str) -> Any:  # noqa: N802 - COM name
        item = self._make(name, kind)
        self._items.append(item)
        return item

    def Refresh(self) -> None:  # noqa: N802
        pass

    def GetAt(self, index: int) -> Any:  # noqa: N802
        return self._items[index]

    @property
    def Count(self) -> int:  # noqa: N802
        return len(self._items)


class Thing:
    def Update(self) -> bool:  # noqa: N802
        return True


class FakeRepository(Thing):
    def __init__(self, backend: FakeBackend, connection: str = "") -> None:
        self.backend = backend
        self.ConnectionString = connection
        self.LibraryVersion = 1700
        self.EAEdition = 2
        self.EAEditionEx = 2
        self.closed_files = 0
        self.exited = 0
        self._next_id = 1
        self._by_guid: dict[str, Any] = {}
        self.Models = Collection(self, self._package)

    def _guid(self, obj: Any) -> str:
        number = self._next_id
        self._next_id += 1
        guid = "{%08X-0000-4000-8000-%012X}" % (number, number)
        self._by_guid[guid] = obj
        return guid

    def _package(self, name: str, _kind: str) -> Any:
        pkg = Thing()
        pkg.Name = name
        pkg.PackageGUID = self._guid(pkg)
        pkg.Packages = Collection(self, self._package)
        pkg.Elements = Collection(self, self._element)
        pkg.Diagrams = Collection(self, self._diagram)
        return pkg

    def _element(self, name: str, kind: str) -> Any:
        element = Thing()
        element.Name, element.Type = name, kind
        element.ElementGUID = self._guid(element)
        element.ElementID = self._next_id
        element.Connectors = Collection(self, lambda n, k: self._connector(element, n, k))
        return element

    def _connector(self, owner: Any, name: str, kind: str) -> Any:
        connector = Thing()
        connector.Name, connector.Type = name, kind
        connector.ClientID, connector.SupplierID = owner.ElementID, 0
        connector.ConnectorGUID = self._guid(connector)
        return connector

    def _diagram(self, name: str, kind: str) -> Any:
        diagram = Thing()
        diagram.Name, diagram.Type = name, kind
        diagram.DiagramGUID = self._guid(diagram)
        diagram.DiagramObjects = Collection(self, self._node)
        diagram.DiagramLinks = Collection(self, lambda n, k: Thing())
        return diagram

    def _node(self, style: str, _kind: str) -> Any:
        values = dict(part.split("=") for part in style.strip(";").split(";"))
        node = Thing()
        node.Left, node.Right = int(values["l"]), int(values["r"])
        node.Top, node.Bottom = -int(values["t"]), -int(values["b"])  # as EA stores them
        node.ElementID = 0
        return node

    # Repository methods

    def CreateModel(self, kind: int, path: str, parent: int) -> bool:  # noqa: N802
        self.backend.calls.append("CreateModel" + Path(path).suffix)
        hook = self.backend.on_create_model
        if hook is not None:
            return hook(path)
        Path(path).write_bytes(b"synthetic")
        return True

    def OpenFile(self, path: str) -> bool:  # noqa: N802
        self.backend.calls.append("OpenFile")
        if self.backend.open_delay_s:
            time.sleep(self.backend.open_delay_s)
        self.ConnectionString = path
        return True

    def CloseFile(self) -> None:  # noqa: N802
        self.closed_files += 1
        self.ConnectionString = ""

    def Exit(self) -> None:  # noqa: N802
        self.exited += 1
        self.backend.live -= 1

    def GetPackageByGuid(self, guid: str) -> Any:  # noqa: N802
        return self._by_guid.get(guid)

    GetDiagramByGuid = GetElementByGuid = GetConnectorByGuid = GetPackageByGuid  # noqa: N815


class FakeBackend:
    def __init__(self, *, load_error: BaseException | None = None,
                 create_errors: dict[str, BaseException] | None = None,
                 foreign: bool = False, attach: bool = False) -> None:
        self.load_error = load_error
        # attach: the object comes from an EA that was already running (no new process) with
        # no model open, so its ConnectionString is empty like a fresh instance's.
        self.attach = attach
        self.create_errors = create_errors or {}
        self.foreign = foreign
        self.repos: list[FakeRepository] = []
        self.calls: list[str] = []
        self.live = 0
        self.threads: set[str] = set()
        self.on_create_model: Any = None
        self.open_delay_s = 0.0

    def load(self) -> str:
        if self.load_error is not None:
            raise self.load_error
        return "312"

    def init_thread(self) -> None:
        self.threads.add(threading.current_thread().name)

    def uninit_thread(self) -> None:
        self.calls.append("uninit")

    def create(self, progid: str) -> Any:
        self.threads.add(threading.current_thread().name)
        if progid in self.create_errors:
            raise self.create_errors[progid]
        repo = FakeRepository(self, "C:\\canary-root\\canary-user\\model.qea" if self.foreign else "")
        if progid == "EA.App":
            app = Thing()
            app.Repository = repo
            self.repos.append(repo)
            self.live += 0 if self.attach else 1
            return app
        self.repos.append(repo)
        self.live += 0 if self.attach else 1
        return repo


def run_main(backend: FakeBackend, data_dir: Path, monkeypatch: pytest.MonkeyPatch,
             preexisting: int = 0, argv: list[str] | None = None,
             counter: Any = None) -> tuple[int, str, list[int]]:
    monkeypatch.setenv("HARNESS_DATA_DIR", str(data_dir))
    exits: list[int] = []
    lines: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(map(str, a))))
    code = probe.main(
        argv or ["--step-timeout", "2", "--create-timeout", "2", "--settle-timeout", "1"],
        backend=backend,
        counter=counter or (lambda: preexisting + backend.live),
        hard_exit=exits.append,
    )
    monkeypatch.undo()
    return code, "\n".join(lines), exits


def summary_of(output: str) -> str:
    start = output.index(probe.SUMMARY_START)
    end = output.index(probe.SUMMARY_END) + len(probe.SUMMARY_END)
    return output[start:end]


def leaks(summary: str, forbidden: list[str]) -> list[str]:
    found = [text for text in forbidden if text and text in summary]
    found += GUID_SHAPE.findall(summary)
    return found


def line(summary: str, name: str) -> str:
    for text in summary.splitlines():
        if text.strip().startswith(name + ":"):
            return text.strip()
    raise AssertionError(f"no line {name!r} in:\n{summary}")


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A data directory outside any Git work tree (pytest's temporary root is not in one)."""
    return tmp_path / "data"


# -- without pywin32 ------------------------------------------------------------------------------


# Revised on 2026-11-25 (hotfix 0.2.1). On Windows pywin32 comes installed with `mcp`, so the
# real script, started with the plain interpreter, took its COM path inside the test. The
# script is now started without site-packages (`-S`) and isolated from the environment and
# the user site (`-I`): no installed package can be imported, pywin32 included, wherever it
# is installed. No switch in the script is involved; the script cannot tell it is under test.
ISOLATED = ("-I", "-S")
FIND = "import importlib.util as u, sys; print(sorted(n for n in sys.argv[1:] if u.find_spec(n)))"
COM_MODULES = ["pythoncom", "pywintypes", "win32com"]


def importable(names: list[str], *flags: str) -> list[str]:
    done = subprocess.run([sys.executable, *flags, "-c", FIND, *names], capture_output=True,
                          text=True, encoding="utf-8", timeout=60, check=True)
    return ast.literal_eval(done.stdout.strip())


def run_script_isolated(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """The only way these tests start the real probe: never with pywin32 importable."""
    assert importable(COM_MODULES, *ISOLATED) == []
    return subprocess.run([sys.executable, *ISOLATED, str(SCRIPT), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env, timeout=120, check=False)


def test_the_isolated_interpreter_cannot_import_installed_packages() -> None:
    """Control: `mcp` and `pydantic` sit in the same site-packages as pywin32 on Windows. The
    plain interpreter finds them; the isolated one finds none of them."""
    installed = ["mcp", "pydantic"]
    assert importable(installed) == installed
    assert importable(installed + COM_MODULES, *ISOLATED) == []


def test_without_pywin32_the_real_script_runs_to_the_end(outside: Path) -> None:
    import os

    env = dict(os.environ, HARNESS_DATA_DIR=str(outside))
    done = run_script_isolated(env=env)
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stderr + done.stdout
    summary = summary_of(done.stdout)
    assert "pywin32: no import_error" in summary
    assert "create_repository: not run (pywin32 not available)" in summary
    assert len(list((outside / "ea").glob("probe-*.json"))) == 1


def test_broken_pywin32_install_is_reported_not_raised(outside: Path, monkeypatch) -> None:
    code, out, _ = run_main(FakeBackend(load_error=OSError("DLL load failed")), outside, monkeypatch)
    assert code == 0
    assert line(summary_of(out), "pywin32") == "pywin32: no python_error"


# -- a full run against the fake ---------------------------------------------------------------------


def test_full_run_against_the_fake(outside: Path, monkeypatch) -> None:
    backend = FakeBackend()
    code, out, exits = run_main(backend, outside, monkeypatch)
    summary = summary_of(out)
    assert code == 0 and exits == []
    for name, expected in [
        ("create_repository", "create_repository: yes"),
        ("create_app", "create_app: not run (EA.Repository was created)"),
        ("own_instance", "own_instance: yes"),
        ("create_model", "create_model: yes .qea"),
        ("open_model", "open_model: yes"),
        ("populate", "populate: yes"),
        ("reopen_model", "reopen_model: yes"),
        ("elements_by_guid", "elements_by_guid: 2"),
        ("connector_by_guid", "connector_by_guid: yes"),
        ("diagram_objects", "diagram_objects: 2"),
        ("diagram_objects_match", "diagram_objects_match: yes"),
        ("diagram_links", "diagram_links: 0"),
        ("geometry_top_stored_negative", "geometry_top_stored_negative: yes"),
        ("second_instance", "second_instance: yes"),
        ("close_own_instance", "close_own_instance: yes"),
        ("ea_processes_left_behind", "ea_processes_left_behind: 0"),
        ("temp_dir_removed", "temp_dir_removed: yes"),
    ]:
        assert line(summary, name).startswith(expected), line(summary, name)
    assert "ea_edition: 2 (assumed piCorporate)" in summary
    own, second = backend.repos
    assert (own.closed_files, own.exited) == (2, 1)  # the model is closed once to reopen it
    assert (second.closed_files, second.exited) == (0, 1)
    assert backend.threads == {"ea-probe-com"}  # every COM call on the one COM thread
    assert backend.calls[-1] == "uninit"


def test_detail_is_json_without_guids_or_paths(outside: Path, monkeypatch) -> None:
    run_main(FakeBackend(), outside, monkeypatch)
    [detail] = (outside / "ea").glob("probe-*.json")
    text = detail.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["steps"]["read_back"]["value"]["elements_by_guid"] == 2
    assert GUID_SHAPE.findall(text) == []
    assert tempfile.gettempdir() not in text


# -- the summary says nothing about the environment ----------------------------------------------


def test_summary_carries_no_path_user_guid_or_message(tmp_path: Path, monkeypatch) -> None:
    user_tmp = tmp_path / "Users" / "canary-user" / "AppData" / "Local" / "Temp"
    user_tmp.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(user_tmp))
    data_dir = tmp_path / "Users" / "canary-user" / "data"
    backend = FakeBackend(create_errors={
        "EA.App": FakeComError(signed(0x80040154), "Class not registered at C:\\canary-root\\canary-user"),
    })

    def second_fails(path: str) -> bool:
        raise FakeComError(signed(0x80020009), "cannot write C:\\canary-root\\canary-user\\x.qea",
                           (0, "EA", "denied for canary-user", None, 0, signed(0x80004005)))

    backend.on_create_model = second_fails
    code, out, _ = run_main(backend, data_dir, monkeypatch)
    summary = summary_of(out)
    assert code == 0
    assert leaks(summary, ["canary-user", str(user_tmp), str(data_dir), "denied", "cannot write"]) == []
    assert line(summary, "create_model_qea").startswith(
        "create_model_qea: FAIL exception_occurred hresult=0x80020009 scode=0x80004005 "
    )


def test_the_leak_check_says_no() -> None:
    """Negative control: the check used above does find each kind of leak."""
    guid = "{0A1B2C3D-0000-4000-8000-00000000ABCD}"
    assert leaks(f"x: {guid}", []) == [guid]
    assert leaks("x: canary-user", ["canary-user"]) == ["canary-user"]


# -- each kind of failure ------------------------------------------------------------------------


def test_class_not_registered_falls_back_to_app_and_reports_codes(outside, monkeypatch) -> None:
    error = FakeComError(signed(0x80040154), "Class not registered")
    backend = FakeBackend(create_errors={"EA.Repository": error, "EA.App": error})
    code, out, _ = run_main(backend, outside, monkeypatch)
    summary = summary_of(out)
    assert code == 0
    assert line(summary, "create_repository").startswith("create_repository: FAIL class_not_registered hresult=0x80040154")
    assert line(summary, "create_app").startswith("create_app: FAIL class_not_registered")
    assert "own_instance: not run (no object was created)" in summary
    assert "open_model" not in summary


def test_app_is_used_when_repository_cannot_be_created(outside, monkeypatch) -> None:
    backend = FakeBackend(create_errors={"EA.Repository": FakeComError(signed(0x800401F3), "x")})
    code, out, _ = run_main(backend, outside, monkeypatch)
    summary = summary_of(out)
    assert line(summary, "create_app").startswith("create_app: yes")
    assert line(summary, "read_back").startswith("read_back: yes")


def test_a_failing_step_does_not_stop_the_probe(outside, monkeypatch) -> None:
    backend = FakeBackend()

    def qea_fails(path: str) -> bool:
        if path.endswith(".qea"):
            raise FakeComError(signed(0x80004005), "no")
        Path(path).write_bytes(b"synthetic")
        return True

    backend.on_create_model = qea_fails
    code, out, _ = run_main(backend, outside, monkeypatch)
    summary = summary_of(out)
    assert code == 0
    assert line(summary, "create_model_qea").startswith("create_model_qea: FAIL unspecified_failure")
    assert line(summary, "create_model").startswith("create_model: yes .eapx")
    assert line(summary, "read_back").startswith("read_back: yes")
    assert line(summary, "create_model_attempts") == "create_model_attempts: .qea fail, .eapx yes"


def test_a_hung_step_times_out_and_the_probe_still_ends(outside, monkeypatch) -> None:
    backend = FakeBackend()
    backend.open_delay_s = 5.0
    started = time.monotonic()
    code, out, exits = run_main(backend, outside, monkeypatch,
                                argv=["--step-timeout", "0.5", "--create-timeout", "2", "--settle-timeout", "1"])
    elapsed = time.monotonic() - started
    summary = summary_of(out)
    assert code == 0 and exits == [0]  # the stuck COM thread is left behind with a hard exit
    assert line(summary, "open_model").startswith("open_model: TIMEOUT")
    assert "populate: not run" in summary
    assert "close_own_instance: not run (the COM thread is stuck" in summary
    assert line(summary, "ea_processes_after_close").startswith("ea_processes_after_close:")
    assert line(summary, "temp_dir_removed").startswith("temp_dir_removed:")
    assert "ea_processes_left_behind: 1" in summary  # its own instance was never closed
    assert elapsed < 4.5, elapsed  # well before the 5 s the fake would have taken


# -- it only touches what it created ---------------------------------------------------------------


def test_an_object_with_a_model_open_is_released_not_closed(outside, monkeypatch) -> None:
    backend = FakeBackend(foreign=True)
    code, out, _ = run_main(backend, outside, monkeypatch, preexisting=1)
    summary = summary_of(out)
    [repo] = backend.repos
    assert code == 0
    assert (repo.closed_files, repo.exited) == (0, 0)
    assert "own_instance: no" in summary and "attached_to_existing: yes" in summary
    assert not any(call.startswith(("CreateModel", "OpenFile")) for call in backend.calls)
    assert "canary-user" not in summary


def test_an_empty_object_without_a_new_process_is_foreign(outside, monkeypatch) -> None:
    """EA was already running with no model open: COM may hand back that instance, whose
    ConnectionString is empty too. No new EA process appeared, so it is not the probe's."""
    backend = FakeBackend(attach=True)
    code, out, _ = run_main(backend, outside, monkeypatch, preexisting=1)
    summary = summary_of(out)
    [repo] = backend.repos
    assert code == 0
    assert (repo.closed_files, repo.exited) == (0, 0)
    assert "own_instance: no" in summary and "attached_to_existing: yes" in summary
    assert "own_instance_unproven: no_new_process" in summary
    assert not any(call.startswith(("CreateModel", "OpenFile")) for call in backend.calls)


def test_without_a_process_count_the_object_is_treated_as_foreign(outside, monkeypatch) -> None:
    backend = FakeBackend()
    code, out, _ = run_main(backend, outside, monkeypatch, counter=lambda: None)
    summary = summary_of(out)
    [repo] = backend.repos
    assert code == 0
    assert (repo.closed_files, repo.exited) == (0, 0)
    assert "own_instance: no" in summary
    assert "own_instance_unproven: count_unavailable" in summary
    assert not any(call.startswith(("CreateModel", "OpenFile")) for call in backend.calls)


def test_a_second_object_without_a_new_process_is_not_exited(outside, monkeypatch) -> None:
    backend = FakeBackend()
    original = backend.create

    def create(progid: str) -> Any:
        backend.attach = bool(backend.repos)  # the second one attaches
        return original(progid)

    backend.create = create
    code, out, _ = run_main(backend, outside, monkeypatch)
    summary = summary_of(out)
    first, second = backend.repos
    assert code == 0
    assert first.exited == 1 and second.exited == 0
    assert "second_attached_to_existing: yes" in summary


def test_preexisting_ea_processes_are_counted_and_left_alone(outside, monkeypatch) -> None:
    backend = FakeBackend()
    code, out, _ = run_main(backend, outside, monkeypatch, preexisting=2)
    summary = summary_of(out)
    assert line(summary, "ea_processes_before") == "ea_processes_before: 2"
    assert "preexisting_ea_processes: 2" in summary
    assert "preexisting_still_running: yes" in summary
    assert "ea_processes_left_behind: 0" in summary


# -- where the detail may go -------------------------------------------------------------------------


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def test_a_versionable_data_dir_is_refused(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    backend = FakeBackend()
    code, out, _ = run_main(backend, repo / "datos", monkeypatch)
    assert code == 1
    assert probe.SUMMARY_START not in out
    assert not (repo / "datos").exists()
    assert backend.repos == [] and backend.calls == []


def test_an_ignored_data_dir_is_accepted(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / ".gitignore").write_text("datos/\n", encoding="utf-8")
    code, _, _ = run_main(FakeBackend(), repo / "datos", monkeypatch)
    assert code == 0
    assert len(list((repo / "datos" / "ea").glob("probe-*.json"))) == 1


# -- the script itself -----------------------------------------------------------------------------


def test_no_platform_conditionals_in_the_probe() -> None:
    offenders = [
        f"{number}: {text.strip()}"
        for number, text in enumerate(SCRIPT.read_text(encoding="utf-8").splitlines(), start=1)
        if PLATFORM_CONDITIONAL.search(text)
    ]
    assert offenders == []


def test_the_platform_check_says_no() -> None:
    assert PLATFORM_CONDITIONAL.search("if sys.platform == 'win32':")
    assert PLATFORM_CONDITIONAL.search("WINDOWS = os.name == 'nt'")


def test_the_com_backend_is_built_only_when_run_as_a_script() -> None:
    """No test can create a COM object (hotfix 0.2.1). `main` has no default backend, the
    real one is built only under `if __name__ == "__main__":`, and the tests start the script
    only through `run_script_isolated`, where pywin32 cannot be imported."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main_guard = next(
        node for node in tree.body
        if isinstance(node, ast.If) and ast.unparse(node.test) == "__name__ == '__main__'"
    )
    inside = {id(node) for node in ast.walk(main_guard)}
    built = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "Pywin32Backend"
    ]
    assert built and all(id(node) in inside for node in built), [n.lineno for n in built]
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    backend = next(a for a in main.args.kwonlyargs if a.arg == "backend")
    assert main.args.kw_defaults[main.args.kwonlyargs.index(backend)] is None
    with pytest.raises(TypeError):
        probe.main([])  # nothing to fall back on

    here = Path(__file__).resolve()
    others = [
        path.relative_to(REPO_ROOT).as_posix() for path in sorted((REPO_ROOT / "tests").rglob("*.py"))
        if path.resolve() != here and "ea_probe" in path.read_text(encoding="utf-8")
    ]
    assert others == []
    tree = ast.parse(here.read_text(encoding="utf-8"))
    assert script_starts(tree) == ["run_script_isolated"]
    helper = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "run_script_isolated")
    started = [ast.unparse(n) for n in ast.walk(helper)
               if isinstance(n, ast.List) and "SCRIPT" in ast.unparse(n)]
    assert started == ["[sys.executable, *ISOLATED, str(SCRIPT), *args]"]
    assert ISOLATED == ("-I", "-S")


def script_starts(tree: ast.Module) -> list[str]:
    """The function around every process start whose arguments name SCRIPT."""
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"subprocess", "os"}
                and any(isinstance(n, ast.Name) and n.id == "SCRIPT"
                        for arg in node.args for n in ast.walk(arg))
            ):
                found.append(function.name)
    return found


def test_probe_imports_only_the_standard_library_and_pywin32() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    outside_stdlib = names - set(sys.stdlib_module_names) - {"__future__"}
    assert outside_stdlib == {"pythoncom", "win32com"}
