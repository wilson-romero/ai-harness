"""Shared fixtures. Everything runs on temporary data directories with synthetic content."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
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
from tests.copilot_app import SyntheticCopilot

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_VARS = [
    "HARNESS_DATA_DIR",
    "HARNESS_PROVIDER",
    "HARNESS_REQUEST_TIMEOUT_S",
    "HARNESS_DEEP_REQUEST_TIMEOUT_S",
    "HARNESS_MOCK_BEHAVIOR",
    "HARNESS_MOCK_DELAY_MS",
    # Never inherit a real Copilot URL or the real dedicated profile into a test.
    "HARNESS_COPILOT_URL",
    "HARNESS_EDGE_PROFILE",
    "HARNESS_COPILOT_READY_TIMEOUT_S",
    "HARNESS_COPILOT_MAX_PROMPT_CHARS",
    "HARNESS_COPILOT_REUSE_TAB",
    "HARNESS_COPILOT_FAST_END",
    "HARNESS_COPILOT_TIMINGS",
    "HARNESS_COPILOT_HEADLESS",
    "HARNESS_VAULT_ROOT",
    "HARNESS_MEMORY_CONTEXT_MAX_BYTES",
    "HARNESS_MOCK_RESPONSES",
    "HARNESS_CONCISE_ANSWERS",
    "HARNESS_SKILLS_DIR",
    "HARNESS_APPROVAL_TTL_S",
    "HARNESS_MCP_CONFIG",
    "HARNESS_PLAIN",
    # Set in every MCP server the harness starts; a test run inside one would be refused.
    "AI_HARNESS_MCP_CHILD",
    # No longer read by the harness; cleared so a developer's shell cannot change a test.
    "HARNESS_PROFILE",
]
VAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "vault-synthetic"

# Credentials of each known format, assembled at run time so that no versioned file contains
# one. Keys are the redaction kinds.
SECRET_SAMPLES = {
    "anthropic": "sk-" + "ant-" + "api03-" + "Q" * 40,
    "openai": "sk-" + "proj-" + "R" * 40,
    "github": "gh" + "p_" + "A" * 36,
    "gitlab": "gl" + "pat-" + "B" * 20,
    "aws": "AK" + "IA" + "C" * 16,
    "google": "AI" + "za" + "D" * 35,
    "slack": "xo" + "xb-" + "1234567890-abcdefghij",
    "digitalocean": "do" + "p_v1_" + "e" * 64,
    "stripe": "sk" + "_live_" + "F" * 24,
    "jwt": "ey" + "J" + "a" * 20 + ".ey" + "J" + "b" * 20 + "." + "c" * 20,
}
# The other shape of two kinds that have two patterns each.
EXTRA_SECRET_SAMPLES = {
    "openai": "sk-" + "G" * 48,
    "github": "github" + "_pat_" + "H" * 22 + "_" + "J" * 59,
}
PRIVATE_KEY_SAMPLE = "\n".join(
    [
        "-----BEGIN " + "RSA PRIVATE KEY-----",
        "K" * 64,
        "L" * 64,
        "-----END " + "RSA PRIVATE KEY-----",
    ]
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """No test sees a real Copilot URL or profile, and no test ever opens a visible window."""
    for name in HARNESS_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HARNESS_TEST_HEADLESS", "1")
    if request.node.get_closest_marker("edge"):
        request.getfixturevalue("edge_ready")


@pytest.fixture(scope="session")
def edge_ready(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Edge's version, or a visible skip when Edge genuinely cannot be launched here."""
    from playwright.async_api import async_playwright

    async def launch() -> str:
        profile = tmp_path_factory.mktemp("edge-check")
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(profile), channel="msedge", headless=True, timeout=60_000
            )
            version = context.browser.version if context.browser else "unknown"
            await context.close()
            return version

    try:
        return asyncio.run(launch())
    except Exception as exc:  # any reason Edge cannot start is a reason to skip, said aloud
        first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        pytest.skip(f"Microsoft Edge cannot be launched by Playwright here: {first_line}")


@pytest.fixture
def copilot_app() -> Iterator[SyntheticCopilot]:
    app = SyntheticCopilot().start()
    yield app
    app.stop()


@pytest.fixture
def edge_env(
    data_dir: Path, tmp_path: Path, copilot_app: SyntheticCopilot, monkeypatch: pytest.MonkeyPatch
) -> SyntheticCopilot:
    """Environment for a browser test: temporary data and profile, the synthetic app's URL."""
    monkeypatch.setenv("HARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("HARNESS_EDGE_PROFILE", str(tmp_path / "edge-profile"))
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url())
    return copilot_app


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A private copy of the synthetic vault. Tests may add links, secrets and defects to it."""
    root = tmp_path / "vault-copy"
    shutil.copytree(VAULT_FIXTURE, root)
    return root


def write_note(root: Path, relative: str, body: str, **fields: str) -> Path:
    """Write a note with a valid frontmatter block into a vault copy."""
    header = {"type": "nota", "created": "2026-11-01", "updated": "2026-11-01", **fields}
    lines = ["---", *(f"{key}: {value}" for key, value in header.items()), "---", body, ""]
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# A note header in the memory block (prompt-economy D2, revised 2026-11-26): `--- <path>
# (<type>, <updated>)`, the path without `projects/<slug>/` and without `.md`.
NOTE_HEADER_RE = re.compile(r"^--- (\S+) \([^\n]*\)$", re.MULTILINE)


def vault_path(shown: str, slug: str = "demo-alpha") -> str:
    """The vault path a header path stands for: the inverse that the design says is exact."""
    if shown == "_project" or shown.startswith("sessions/"):
        return f"projects/{slug}/{shown}.md"
    return f"{shown}.md"


def note_header(relative: str, slug: str = "demo-alpha") -> str:
    """The start of the header of the note at vault path `relative`, up to the path."""
    prefix = f"projects/{slug}/"
    shown = relative[len(prefix):] if relative.startswith(prefix) else relative
    return f"--- {shown.removesuffix('.md')} "


def header_paths(text: str, slug: str = "demo-alpha") -> list[str]:
    """The vault paths of the note headers of a memory block, in order."""
    return [vault_path(shown, slug) for shown in NOTE_HEADER_RE.findall(text)]


def make_symlink(link: Path, target: Path) -> None:
    """Create a symbolic link, or skip with a visible reason where the OS does not allow it."""
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:  # e.g. Windows without developer mode or the privilege
        pytest.skip(f"cannot create symbolic links here: {exc}")


def fingerprint(root: Path) -> dict[str, tuple]:
    """Relative path -> (kind, size, mtime_ns, sha256 or link target) of every entry under root."""
    prints: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath, name)
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                prints[relative] = ("link", info.st_size, info.st_mtime_ns, os.readlink(path))
            elif path.is_dir():
                prints[relative] = ("dir", 0, info.st_mtime_ns, "")
            else:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                prints[relative] = ("file", info.st_size, info.st_mtime_ns, digest)
    return prints


class RecordingProvider:
    """A synthetic provider that keeps the exact text it was sent, like a wire tap."""

    name = "mock"
    synthetic_content = True

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ask(self, request, on_sent) -> str:
        self.prompts.append(request.prompt)
        on_sent()
        return "respuesta sintética"


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingProvider:
    """Make every provider the CLI builds a RecordingProvider, and return it."""
    provider = RecordingProvider()
    monkeypatch.setattr("harness.cli.provider_factory", lambda settings: lambda name: provider)
    return provider


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
