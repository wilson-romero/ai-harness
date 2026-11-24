#!/usr/bin/env python3
"""Enterprise Architect probe: can this EA edition be driven through its Automation Interface?

Usage (see docs/runbook/enterprise-architect.md), from the repository root, in PowerShell:

    uv run --with pywin32 python scripts/ea_probe.py

Standard library plus pywin32 only, and pywin32 is optional: without it, or without EA, the
probe still runs to the end and says what it could not do. It never decides anything from the
platform name; it tries the import and tries to create the COM object.

What it touches: it creates its OWN Enterprise Architect instance, creates a brand-new model
file in a fresh temporary directory, adds one package, two elements, one connector and one
diagram to it, closes it, reopens it, reads everything back by GUID, and closes its own
instance. It never opens an existing model, never attaches to a running EA, and never closes
or kills a process it did not start. If the object it gets already has a model open (that is,
it is somebody else's EA), it lets go of it without closing anything.

What it prints: a summary block between the two marker lines with booleans, counts, timings,
the EA version and edition numbers, and COM error categories and codes. No paths, user names,
GUIDs, model content or error message text. The same steps go to a JSON file under
`HARNESS_DATA_DIR/ea/` (default `./data/ea/`), which must not be a place Git could version.

Exit code: 0 when the probe ran to the end, even if steps failed; 1 when it refused to start
(output directory); 130 when interrupted.
"""

from __future__ import annotations

import argparse
import gc
import importlib.metadata
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

PROBE_VERSION = 1
SUMMARY_START = "---- ea probe summary (paste only this) ----"
SUMMARY_END = "---- end of summary ----"
EXIT_OK, EXIT_REFUSED, EXIT_INTERRUPTED = 0, 1, 130

DEFAULT_CREATE_TIMEOUT_S = 180.0  # starting EA can be slow, and a dialog may block it
DEFAULT_STEP_TIMEOUT_S = 60.0
SETTLE_TIMEOUT_S = 20.0
REMOVE_ATTEMPTS = 5

# Documented order of the EAEditionTypes enumeration (object model guide, 16.1, page 29). The
# numeric values are not documented: the names printed next to a number are an assumption.
EDITION_NAMES = ("piLite", "piProfessional", "piCorporate", "piBusiness", "piSystemEng", "piUltimate")
# CreateModelType.cmEAPFromBase. Its numeric value is not documented either: assumed 0.
CM_EAP_FROM_BASE = 0
MODEL_SUFFIXES = (".qea", ".eapx")

# HRESULT categories that say something about EA and COM. Anything else is "other".
HRESULT_CATEGORIES = {
    0x80040154: "class_not_registered",
    0x800401F3: "invalid_class_string",
    0x80080005: "server_exec_failure",
    0x800706BA: "rpc_server_unavailable",
    0x800706BE: "rpc_call_failed",
    0x80010001: "call_rejected",
    0x8001010A: "server_busy",
    0x80020009: "exception_occurred",
    0x80020006: "unknown_name",
    0x80070005: "access_denied",
    0x80004005: "unspecified_failure",
}


# -- the COM layer, behind a small interface so that tests can use a fake ----------------------


class ComBackend(Protocol):
    def load(self) -> str:
        """Import the COM bindings and return their version. Raises when they are missing."""

    def init_thread(self) -> None: ...

    def uninit_thread(self) -> None: ...

    def create(self, progid: str) -> Any:
        """A new instance of a COM class (never an existing, running one)."""


class Pywin32Backend:
    def __init__(self) -> None:
        self._pythoncom: Any = None
        self._client: Any = None

    def load(self) -> str:
        import pythoncom  # noqa: PLC0415 - optional: the probe must run without it
        import win32com.client  # noqa: PLC0415

        self._pythoncom = pythoncom
        self._client = win32com.client
        try:
            return importlib.metadata.version("pywin32")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    def init_thread(self) -> None:
        self._pythoncom.CoInitialize()

    def uninit_thread(self) -> None:
        self._pythoncom.CoUninitialize()

    def create(self, progid: str) -> Any:
        # DispatchEx asks COM for a new object of the class. Whether EA then starts a new
        # process or hands out an object of a running one is what the probe measures.
        return self._client.DispatchEx(progid)


ProcessCounter = Callable[[], "int | None"]


def count_ea_processes() -> int | None:
    """How many EA.exe processes are running, or None when that cannot be measured here.

    Capability, not platform: if `tasklist` does not exist or fails, the count is unknown.
    """
    try:
        done = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq EA.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=15,
            env=dict(os.environ),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    lines = done.stdout.decode("latin-1", errors="replace").splitlines()
    return sum(1 for line in lines if line.strip().lower().startswith('"ea.exe"'))


# -- error classification -----------------------------------------------------------------------


def _as_hresult(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value & 0xFFFFFFFF
    return None


def classify(exc: BaseException) -> dict[str, Any]:
    """Category and codes of an exception. Never its message: it may hold a path or a name."""
    hresult = _as_hresult(getattr(exc, "hresult", None))
    if hresult is None and exc.args:
        hresult = _as_hresult(exc.args[0])
    scode = None
    excepinfo = getattr(exc, "excepinfo", None)
    if excepinfo is None and len(exc.args) >= 3:
        excepinfo = exc.args[2]
    if isinstance(excepinfo, tuple) and len(excepinfo) >= 6:
        scode = _as_hresult(excepinfo[5])
    if hresult is not None:
        category = HRESULT_CATEGORIES.get(hresult, "other_com_error")
    elif isinstance(exc, ImportError):
        category = "import_error"
    else:
        category = "python_error"
    return {
        "category": category,
        "hresult": f"0x{hresult:08X}" if hresult is not None else None,
        "scode": f"0x{scode:08X}" if scode is not None else None,
        "type": type(exc).__name__,
    }


# -- one thread owns COM; every call has a deadline ----------------------------------------------


class ComWorker:
    """Runs callables one at a time on a single thread that initialised COM.

    COM objects created on this thread are used only on this thread. A call that does not
    return within its deadline poisons the worker: nothing else is sent to it, because the
    thread is still inside that call.
    """

    def __init__(self, backend: ComBackend) -> None:
        self._backend = backend
        self._jobs: queue.Queue[tuple[Callable[[], Any], queue.Queue[tuple[str, Any]]] | None] = (
            queue.Queue()
        )
        self.poisoned = False
        self.init_error: dict[str, Any] | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="ea-probe-com", daemon=True)
        self._thread.start()
        if not self._ready.wait(30):
            self.poisoned = True
            self.init_error = {"category": "timeout", "hresult": None, "scode": None, "type": None}

    def _loop(self) -> None:
        try:
            self._backend.init_thread()
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            self.init_error = classify(exc)
        self._ready.set()
        while True:
            job = self._jobs.get()
            if job is None:
                break
            fn, reply = job
            try:
                reply.put(("ok", fn()))
            except Exception as exc:  # noqa: BLE001 - recorded, never raised
                reply.put(("fail", exc))
        gc.collect()  # drop COM references on the thread that owns them
        try:
            self._backend.uninit_thread()
        except Exception:  # noqa: BLE001, S110 - nothing useful to do on the way out
            pass

    def run(self, fn: Callable[[], Any], timeout_s: float) -> tuple[str, Any, float]:
        """Returns (status, value or exception or None, seconds). Status: ok, fail, timeout,
        skipped."""
        if self.poisoned:
            return "skipped", "worker_hung", 0.0
        reply: queue.Queue[tuple[str, Any]] = queue.Queue()
        started = time.monotonic()
        self._jobs.put((fn, reply))
        try:
            status, value = reply.get(timeout=timeout_s)
        except queue.Empty:
            self.poisoned = True
            return "timeout", None, time.monotonic() - started
        return status, value, time.monotonic() - started

    def stop(self, timeout_s: float = 10.0) -> bool:
        """Ask the thread to finish. Returns whether it did within the timeout."""
        if not self.poisoned:
            self._jobs.put(None)
            self._thread.join(timeout_s)
        return not self._thread.is_alive()


# -- results ------------------------------------------------------------------------------------


@dataclass
class Step:
    status: str  # ok, fail, timeout, skipped, not_run
    seconds: float | None = None
    value: Any = None
    error: dict[str, Any] | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.seconds is not None:
            out["seconds"] = round(self.seconds, 3)
        for key in ("value", "error", "reason"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        return out


@dataclass
class Probe:
    steps: dict[str, Step] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)

    def record(self, name: str, step: Step) -> Step:
        self.steps[name] = step
        return step

    def ok(self, name: str) -> bool:
        step = self.steps.get(name)
        return step is not None and step.status == "ok"


def _from_run(result: tuple[str, Any, float]) -> Step:
    status, value, seconds = result
    if status == "ok":
        return Step("ok", seconds, value=value)
    if status == "fail":
        return Step("fail", seconds, error=classify(value))
    if status == "timeout":
        return Step("timeout", seconds, reason="no answer within the step deadline")
    return Step("skipped", seconds, reason=str(value))


# -- the probe ----------------------------------------------------------------------------------


@dataclass
class Settings:
    data_dir: Path
    create_timeout_s: float = DEFAULT_CREATE_TIMEOUT_S
    step_timeout_s: float = DEFAULT_STEP_TIMEOUT_S
    settle_timeout_s: float = SETTLE_TIMEOUT_S
    keep_model: bool = False


class ProbeRun:
    """The ordered steps. Each one is guarded; a failure is recorded and the run goes on."""

    def __init__(self, backend: ComBackend, counter: ProcessCounter, settings: Settings) -> None:
        self.backend = backend
        self.counter = counter
        self.settings = settings
        self.probe = Probe()
        self.worker: ComWorker | None = None
        self.repo: Any = None
        self.second: Any = None
        self.own = False
        self.com_stuck = False
        self.tmp_dir: Path | None = None
        self.model_path: Path | None = None
        self.ids: dict[str, Any] = {}  # GUIDs and IDs of the synthetic model: never printed

    # helpers

    def com(self, name: str, fn: Callable[[], Any], timeout_s: float | None = None) -> Step:
        if self.worker is None:
            return self.probe.record(name, Step("not_run", reason="no COM"))
        timeout = self.settings.step_timeout_s if timeout_s is None else timeout_s
        return self.probe.record(name, _from_run(self.worker.run(fn, timeout)))

    def not_run(self, name: str, reason: str) -> Step:
        return self.probe.record(name, Step("not_run", reason=reason))

    def count(self, name: str) -> int | None:
        started = time.monotonic()
        try:
            value = self.counter()
        except Exception as exc:  # noqa: BLE001
            self.probe.record(name, Step("fail", time.monotonic() - started, error=classify(exc)))
            return None
        if value is None:
            self.probe.record(name, Step("not_run", reason="process count not measurable here"))
            return None
        self.probe.record(name, Step("ok", time.monotonic() - started, value=value))
        return value

    # the run

    def run(self) -> Probe:
        started = time.monotonic()
        try:
            self._run()
        except KeyboardInterrupt:
            self.probe.facts["interrupted"] = True
            self._close_own()
            raise
        finally:
            self.probe.facts["total_seconds"] = round(time.monotonic() - started, 3)
        return self.probe

    def _run(self) -> None:
        p = self.probe
        p.facts["python"] = platform.python_version()
        p.facts["os"] = platform.platform(terse=True)
        try:
            version = self.backend.load()
        except Exception as exc:  # noqa: BLE001 - ImportError, or a broken install
            p.record("pywin32", Step("fail", error=classify(exc)))
        else:
            p.record("pywin32", Step("ok", value=version))
        before = self.count("ea_processes_before")

        if p.ok("pywin32"):
            self.worker = ComWorker(self.backend)
            if self.worker.init_error is not None:
                p.record("com_init", Step("fail", error=self.worker.init_error))
                if self.worker.poisoned:
                    self.com_stuck = True
                else:
                    self.worker.stop()
                self.worker = None
            else:
                p.record("com_init", Step("ok"))
        reason = "pywin32 not available" if not p.ok("pywin32") else "COM not initialised"

        if self.worker is None:
            for name in ("create_repository", "create_app"):
                self.not_run(name, reason)
        else:
            self._create()
        after_create = self.count("ea_processes_after_create") if self.repo is not None else None
        if before is not None and after_create is not None:
            p.facts["ea_processes_started_by_create"] = after_create - before

        if self.repo is not None and self.own:
            self._version()
            self._build_and_read()
            self._second_instance()
        elif self.repo is not None:
            for name in ("version", "create_model", "open_model", "populate", "close_model",
                         "reopen_model", "read_back", "second_instance"):
                self.not_run(name, "the created object was not a fresh instance")

        self._close_own()
        self._settle(before)
        self._cleanup()

    def _create(self) -> None:
        timeout = self.settings.create_timeout_s
        step = self.com("create_repository", lambda: self.backend.create("EA.Repository"), timeout)
        if step.status == "ok":
            self.repo = step.value
            step.value = None
            self.not_run("create_app", "EA.Repository was created")
        elif self.worker is not None and not self.worker.poisoned:
            app = self.com("create_app", lambda: self.backend.create("EA.App").Repository, timeout)
            if app.status == "ok":
                self.repo = app.value
                app.value = None
        else:
            self.not_run("create_app", "the COM thread is stuck")
        if self.repo is None:
            self.not_run("own_instance", "no object was created")
            return
        fresh = self.com("own_instance", lambda: str(self.repo.ConnectionString or "") == "")
        self.own = fresh.status == "ok" and bool(fresh.value)
        self.probe.facts["attached_to_existing"] = fresh.status == "ok" and not fresh.value
        if not self.own and fresh.status == "ok":
            # Somebody else's EA: let go of it, close nothing.
            self.worker.run(self._drop_repo, 10)

    def _drop_repo(self) -> None:
        self.repo = None
        gc.collect()

    def _version(self) -> None:
        def read() -> dict[str, Any]:
            out: dict[str, Any] = {}
            for attr in ("LibraryVersion", "EAEdition", "EAEditionEx"):
                try:
                    value = getattr(self.repo, attr)
                    out[attr] = int(value) if value is not None else None
                except Exception as exc:  # noqa: BLE001
                    out[attr] = classify(exc)["category"]
            return out

        self.com("version", read)

    def _build_and_read(self) -> None:
        try:
            self.tmp_dir = Path(tempfile.mkdtemp(prefix="ea-probe-"))
        except OSError as exc:
            self.probe.record("create_model", Step("fail", error=classify(exc)))
            for name in ("open_model", "populate", "close_model", "reopen_model", "read_back"):
                self.not_run(name, "no temporary directory")
            return
        attempts: dict[str, str] = {}
        for suffix in MODEL_SUFFIXES:
            path = self.tmp_dir / f"probe-model{suffix}"
            step = self.com(
                f"create_model{suffix.replace('.', '_')}",
                lambda path=path: bool(self.repo.CreateModel(CM_EAP_FROM_BASE, str(path), 0)),
            )
            attempts[suffix] = step.status if step.status != "ok" else ("yes" if step.value else "no")
            if step.status == "ok" and step.value and path.is_file():
                self.model_path = path
                break
            if self.worker is None or self.worker.poisoned:
                break
        self.probe.record(
            "create_model",
            Step("ok" if self.model_path else "fail", value=self.model_path.suffix if self.model_path else None,
                 reason=None if self.model_path else "no model file was created"),
        )
        self.probe.facts["create_model_attempts"] = attempts
        if self.model_path is None:
            for name in ("open_model", "populate", "close_model", "reopen_model", "read_back"):
                self.not_run(name, "no model file")
            return
        path = str(self.model_path)
        opened = self.com("open_model", lambda: bool(self.repo.OpenFile(path)))
        if not (opened.status == "ok" and opened.value):
            for name in ("populate", "close_model", "reopen_model", "read_back"):
                self.not_run(name, "the model did not open")
            return
        self.com("populate", self._populate)
        self.com("close_model", lambda: self.repo.CloseFile())
        reopened = self.com("reopen_model", lambda: bool(self.repo.OpenFile(path)))
        if reopened.status == "ok" and reopened.value and self.probe.ok("populate"):
            self.com("read_back", self._read_back)
        else:
            self.not_run("read_back", "the populated model could not be reopened")

    def _populate(self) -> dict[str, Any]:
        repo = self.repo
        model = repo.Models.AddNew("Probe Model", "")
        model.Update()
        repo.Models.Refresh()
        package = model.Packages.AddNew("Probe Package", "")
        package.Update()
        alpha = package.Elements.AddNew("Probe Alpha", "Component")
        alpha.Update()
        beta = package.Elements.AddNew("Probe Beta", "Component")
        beta.Update()
        package.Elements.Refresh()
        connector = alpha.Connectors.AddNew("", "Dependency")
        connector.SupplierID = beta.ElementID
        connector.Update()
        alpha.Connectors.Refresh()
        diagram = package.Diagrams.AddNew("Probe Diagram", "Component")
        diagram.Update()
        for element, style in ((alpha, "l=100;r=220;t=40;b=100;"), (beta, "l=300;r=420;t=40;b=100;")):
            node = diagram.DiagramObjects.AddNew(style, "")
            node.ElementID = element.ElementID
            node.Update()
        diagram.DiagramObjects.Refresh()
        diagram.Update()
        self.ids = {
            "package": str(package.PackageGUID),
            "diagram": str(diagram.DiagramGUID),
            "alpha": str(alpha.ElementGUID),
            "beta": str(beta.ElementGUID),
            "connector": str(connector.ConnectorGUID),
            "alpha_id": int(alpha.ElementID),
            "beta_id": int(beta.ElementID),
        }
        return {"elements": 2, "connectors": 1, "diagram_objects": 2}

    def _read_back(self) -> dict[str, Any]:
        repo, ids = self.repo, self.ids
        out: dict[str, Any] = {}
        package = repo.GetPackageByGuid(ids["package"])
        out["package_by_guid"] = package is not None and str(package.Name) == "Probe Package"
        diagram = repo.GetDiagramByGuid(ids["diagram"])
        out["diagram_by_guid"] = diagram is not None and str(diagram.Name) == "Probe Diagram"
        found = 0
        for key, name in (("alpha", "Probe Alpha"), ("beta", "Probe Beta")):
            element = repo.GetElementByGuid(ids[key])
            found += int(element is not None and str(element.Name) == name)
        out["elements_by_guid"] = found
        connector = repo.GetConnectorByGuid(ids["connector"])
        out["connector_by_guid"] = connector is not None and (
            int(connector.ClientID) == ids["alpha_id"] and int(connector.SupplierID) == ids["beta_id"]
        )
        if diagram is not None:
            objects = diagram.DiagramObjects
            out["diagram_objects"] = int(objects.Count)
            out["diagram_links"] = int(diagram.DiagramLinks.Count)
            on_diagram = set()
            tops: list[int] = []
            for index in range(int(objects.Count)):
                node = objects.GetAt(index)
                on_diagram.add(int(node.ElementID))
                tops.append(int(node.Top))
            out["diagram_objects_match"] = on_diagram == {ids["alpha_id"], ids["beta_id"]}
            out["geometry_top_stored_negative"] = bool(tops) and all(top < 0 for top in tops)
        alpha = repo.GetElementByGuid(ids["alpha"])
        if alpha is not None:
            out["element_connectors"] = int(alpha.Connectors.Count)
        return out

    def _second_instance(self) -> None:
        if self.worker is None or self.worker.poisoned:
            self.not_run("second_instance", "the COM thread is stuck")
            return

        def create_second() -> bool:
            self.second = self.backend.create("EA.Repository")
            return str(self.second.ConnectionString or "") == ""

        step = self.com("second_instance", create_second, self.settings.create_timeout_s)
        count = self.count("ea_processes_with_second")
        before = self.probe.steps.get("ea_processes_after_create")
        if count is not None and before is not None and before.status == "ok":
            self.probe.facts["ea_processes_started_by_second"] = count - before.value
        if self.second is None:
            return
        if step.status == "ok" and step.value:
            self.com("close_second", self._exit_second)
        else:
            self.probe.facts["second_attached_to_existing"] = True
            self.worker.run(self._drop_second, 10)

    def _exit_second(self) -> None:
        second, self.second = self.second, None
        second.Exit()
        del second
        gc.collect()

    def _drop_second(self) -> None:
        self.second = None
        gc.collect()

    def _close_own(self) -> None:
        if self.worker is None:
            return
        if self.worker.poisoned:
            self.not_run("close_own_instance", "the COM thread is stuck; the own instance may still run")
            return
        if self.repo is None or not self.own:
            self.worker.stop()
            return

        def close() -> None:
            repo, self.repo = self.repo, None
            try:
                repo.CloseFile()
            finally:
                repo.Exit()
                del repo
                gc.collect()

        self.com("close_own_instance", close)
        self.probe.facts["com_thread_finished"] = self.worker.stop() if not self.worker.poisoned else False

    def _settle(self, before: int | None) -> None:
        """Wait, bounded, for EA processes to go back to the count before the probe."""
        if before is None:
            self.not_run("ea_processes_after_close", "process count not measurable here")
            return
        deadline = time.monotonic() + self.settings.settle_timeout_s
        started = time.monotonic()
        while True:
            try:
                count = self.counter()
            except Exception:  # noqa: BLE001 - same as "not measurable"
                count = None
            if count is None:
                self.not_run("ea_processes_after_close", "process count not measurable here")
                return
            if count <= before or time.monotonic() >= deadline:
                break
            time.sleep(1.0)
        self.probe.record("ea_processes_after_close", Step("ok", time.monotonic() - started, value=count))
        self.probe.facts["ea_processes_left_behind"] = max(0, count - before)
        if before > 0:
            self.probe.facts["preexisting_ea_processes"] = before
            self.probe.facts["preexisting_still_running"] = count >= before

    def _cleanup(self) -> None:
        if self.tmp_dir is None:
            return
        if self.settings.keep_model and self.model_path is not None and self.model_path.is_file():
            try:
                target = self.settings.data_dir / "ea" / f"probe-model{self.model_path.suffix}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.model_path, target)
                self.probe.facts["model_kept"] = True
            except OSError as exc:
                self.probe.facts["model_kept"] = classify(exc)["category"]
        for attempt in range(REMOVE_ATTEMPTS):
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            if not self.tmp_dir.exists():
                break
            time.sleep(1.0)  # EA, an antivirus or a sync client may still hold the file
        self.probe.record(
            "temp_dir_removed",
            Step("ok" if not self.tmp_dir.exists() else "fail", value=not self.tmp_dir.exists(),
                 reason=None if not self.tmp_dir.exists() else f"still present after {attempt + 1} attempts"),
        )


# -- summary ------------------------------------------------------------------------------------

SUMMARY_ORDER = (
    "pywin32", "com_init", "ea_processes_before", "create_repository", "create_app",
    "own_instance", "ea_processes_after_create", "version", "create_model_qea",
    "create_model_eapx", "create_model", "open_model", "populate", "close_model",
    "reopen_model", "read_back", "second_instance", "ea_processes_with_second", "close_second",
    "close_own_instance", "ea_processes_after_close", "temp_dir_removed",
)
FACT_ORDER = (
    "attached_to_existing", "ea_processes_started_by_create", "ea_processes_started_by_second",
    "second_attached_to_existing", "ea_processes_left_behind", "preexisting_ea_processes",
    "preexisting_still_running", "com_thread_finished", "model_kept", "interrupted",
    "total_seconds",
)
# Values that may appear in the summary: only these keys of a step value, all scalars.
READ_BACK_KEYS = (
    "package_by_guid", "diagram_by_guid", "elements_by_guid", "connector_by_guid",
    "diagram_objects", "diagram_links", "diagram_objects_match", "element_connectors",
    "geometry_top_stored_negative",
)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.replace(".", "").replace("_", "").isalnum() and len(value) <= 24:
        return value
    return "?"


def _edition(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        name = EDITION_NAMES[value] if 0 <= value < len(EDITION_NAMES) else "unknown"
        return f"{value} (assumed {name})"
    return _scalar(value)


def _head(name: str, step: Step) -> str:
    if step.status == "ok":
        if isinstance(step.value, bool):
            return _scalar(step.value)
        if name.startswith("ea_processes"):
            return _scalar(step.value)
        if step.value is None or isinstance(step.value, dict):
            return "yes"
        return f"yes {_scalar(step.value)}"
    if step.status == "fail":
        return "no" if name == "pywin32" else "FAIL"
    return {"timeout": "TIMEOUT", "skipped": "skipped", "not_run": "not run"}.get(step.status, "?")


def _step_line(name: str, step: Step) -> list[str]:
    parts = [_head(name, step)]
    if step.error:
        parts.append(step.error["category"])
        for key in ("hresult", "scode"):
            if step.error.get(key):
                parts.append(f"{key}={step.error[key]}")
    if step.seconds is not None and step.status != "not_run" and not name.startswith("ea_processes"):
        parts.append(f"{step.seconds:.2f}s")
    lines = []
    if name == "version" and isinstance(step.value, dict):
        lines.append(f"{name}: {' '.join(parts)}")
        lines.append(f"  ea_library_version: {_scalar(step.value.get('LibraryVersion'))}")
        lines.append(f"  ea_edition: {_edition(step.value.get('EAEdition'))}")
        lines.append(f"  ea_edition_ex: {_edition(step.value.get('EAEditionEx'))}")
        return lines
    if name == "read_back" and isinstance(step.value, dict):
        lines.append(f"{name}: {' '.join(parts)}")
        lines.extend(f"  {key}: {_scalar(step.value[key])}" for key in READ_BACK_KEYS if key in step.value)
        return lines
    if step.status in ("not_run", "skipped") and step.reason:
        parts.append(f"({step.reason})")
    return [f"{name}: {' '.join(parts)}"]


def format_summary(probe: Probe, detail_name: str | None) -> str:
    lines = [SUMMARY_START, f"probe_version: {PROBE_VERSION}", f"python: {_scalar(probe.facts.get('python'))}"]
    for name in SUMMARY_ORDER:
        if name in probe.steps:
            lines.extend(_step_line(name, probe.steps[name]))
    for name in FACT_ORDER:
        if name in probe.facts:
            lines.append(f"{name}: {_scalar(probe.facts[name])}")
    if "create_model_attempts" in probe.facts:
        attempts = probe.facts["create_model_attempts"]
        lines.append("create_model_attempts: " + ", ".join(f"{k} {_scalar(v)}" for k, v in attempts.items()))
    lines.append(f"detail_saved: {'yes (' + detail_name + ')' if detail_name else 'no'}")
    lines.append(SUMMARY_END)
    return "\n".join(lines)


# -- where the detail may go --------------------------------------------------------------------


class Refused(Exception):
    pass


def ensure_unversionable(directory: Path) -> None:
    """Refuse a destination inside a Git work tree that is not ignored by it."""
    anchor = directory.resolve()
    while not anchor.exists():
        anchor = anchor.parent
    try:
        inside = subprocess.run(
            ["git", "-C", str(anchor), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=30, env=dict(os.environ), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return  # no Git here: nothing can version the file
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return
    relative = directory.resolve().relative_to(anchor) / "probe-check.json"
    ignored = subprocess.run(
        ["git", "-C", str(anchor), "check-ignore", "-q", relative.as_posix()],
        capture_output=True, timeout=30, env=dict(os.environ), check=False,
    )
    if ignored.returncode != 0:
        raise Refused(
            "HARNESS_DATA_DIR is inside a Git work tree and not ignored by it: the probe detail "
            "could be committed. Use the default ./data, or a folder outside any repository."
        )


def write_detail(directory: Path, probe: Probe) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    name = f"probe-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    data = {
        "probe_version": PROBE_VERSION,
        "facts": probe.facts,
        "steps": {key: step.as_dict() for key, step in probe.steps.items()},
    }
    tmp = directory / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    tmp.replace(directory / name)
    return name


# -- entry point --------------------------------------------------------------------------------


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(
    argv: list[str] | None = None,
    backend: ComBackend | None = None,
    counter: ProcessCounter = count_ea_processes,
    hard_exit: Callable[[int], Any] = os._exit,
) -> int:
    _utf8_output()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep-model", action="store_true",
                        help="copy the synthetic model it creates to HARNESS_DATA_DIR/ea/")
    parser.add_argument("--create-timeout", type=float, default=DEFAULT_CREATE_TIMEOUT_S,
                        help="seconds to wait for EA to start (default %(default)s)")
    parser.add_argument("--step-timeout", type=float, default=DEFAULT_STEP_TIMEOUT_S,
                        help="seconds to wait for any other COM step (default %(default)s)")
    parser.add_argument("--settle-timeout", type=float, default=SETTLE_TIMEOUT_S,
                        help="seconds to wait for EA processes to go away (default %(default)s)")
    args = parser.parse_args(argv)

    data_dir = Path(os.environ.get("HARNESS_DATA_DIR") or "./data")
    detail_dir = data_dir / "ea"
    try:
        ensure_unversionable(detail_dir)
    except Refused as exc:
        print(f"ea probe: refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    settings = Settings(data_dir, args.create_timeout, args.step_timeout, args.settle_timeout,
                        keep_model=args.keep_model)
    run = ProbeRun(backend or Pywin32Backend(), counter, settings)
    print("ea probe: running; it can take a few minutes. Do not use the EA windows it opens.",
          file=sys.stderr, flush=True)
    code = EXIT_OK
    try:
        probe = run.run()
    except KeyboardInterrupt:
        probe = run.probe
        code = EXIT_INTERRUPTED
    try:
        detail_name: str | None = write_detail(detail_dir, probe)
    except OSError as exc:
        print(f"ea probe: could not save the detail ({classify(exc)['category']})", file=sys.stderr)
        detail_name = None
    print(format_summary(probe, f"HARNESS_DATA_DIR/ea/{detail_name}" if detail_name else None), flush=True)
    sys.stderr.flush()
    if run.com_stuck or (run.worker is not None and run.worker.poisoned):
        # The COM thread is stuck inside EA. Interpreter shutdown could wait on it forever.
        hard_exit(code)
    return code


if __name__ == "__main__":
    sys.exit(main())
