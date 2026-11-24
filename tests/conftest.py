"""Shared fixtures. Everything runs on temporary data directories with synthetic content."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from harness.cli import main
from harness.core.errors import UnknownProvider
from harness.core.service import SessionService
from harness.providers.base import LLMProvider
from harness.providers.mock import MockProvider
from harness.storage.database import DATABASE_NAME, open_database

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_VARS = [
    "HARNESS_DATA_DIR",
    "HARNESS_PROVIDER",
    "HARNESS_REQUEST_TIMEOUT_S",
    "HARNESS_MOCK_BEHAVIOR",
    "HARNESS_MOCK_DELAY_MS",
]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def conn(data_dir: Path) -> Iterator[sqlite3.Connection]:
    connection = open_database(data_dir)
    yield connection
    connection.close()


@pytest.fixture
def make_service(conn: sqlite3.Connection, data_dir: Path) -> Callable[..., SessionService]:
    def build(
        providers: dict[str, LLMProvider] | None = None,
        default: str = "mock",
        timeout_s: float = 5.0,
    ) -> SessionService:
        available = providers if providers is not None else {"mock": MockProvider()}

        def factory(name: str) -> LLMProvider:
            if name not in available:
                raise UnknownProvider(f"unknown provider {name!r}")
            return available[name]

        return SessionService(conn, data_dir, factory, default, timeout_s)

    return build


@pytest.fixture
def cli(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[..., tuple[int, str, str]]:
    """Run the CLI in-process and return (exit code, stdout, stderr)."""
    for name in HARNESS_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HARNESS_DATA_DIR", str(data_dir))

    def run(*args: str, **env: str) -> tuple[int, str, str]:
        with monkeypatch.context() as patch:
            for key, value in env.items():
                patch.setenv(key, value)
            code = main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


def subprocess_env(data_dir: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    env["HARNESS_DATA_DIR"] = str(data_dir)
    env.update(extra)
    return env


def run_main(data_dir: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run `main.py` as a real, separate process."""
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=REPO_ROOT,
        env=subprocess_env(data_dir, **env),
        capture_output=True,
        text=True,
        timeout=60,
    )


def spawn_main(data_dir: Path, *args: str, **env: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "main.py", *args],
        cwd=REPO_ROOT,
        env=subprocess_env(data_dir, **env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def query(data_dir: Path, sql: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(data_dir / DATABASE_NAME, timeout=5.0)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def wait_for_running(data_dir: Path, session_id: str, timeout_s: float = 20.0) -> str:
    """Block until the session has a request in `running` and return its id."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if (data_dir / DATABASE_NAME).exists():
            rows = query(
                data_dir,
                "SELECT request_id FROM requests WHERE session_id = ? AND status = 'running'",
                (session_id,),
            )
            if rows:
                return rows[0][0]
        time.sleep(0.05)
    raise AssertionError("no request reached the running state in time")
