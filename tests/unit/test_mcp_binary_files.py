"""MCP files written through descriptors: the argument key and the server log (hotfix 0.2.1).

On Windows a descriptor opened without O_BINARY translates b"\\n" into b"\\r\\n". v0.2.0 wrote
the key that way, so a key with a 0x0A byte came out longer than 32 bytes and every later
call in that data dir failed with "the MCP argument key is damaged".

Where the system has text-mode descriptors (it defines `os.O_BINARY`), these tests use the
real thing. Where it has not, they simulate it: a fake O_BINARY bit, and an `os.write` that
translates on every descriptor opened without it. Revised on 2026-11-26: v0.2.1's first cut
always simulated, and on Windows replacing the real O_BINARY with the fake one opened every
descriptor in real text mode underneath the double, so the double and the C runtime both
translated.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from harness.mcp import audit
from harness.mcp.audit import ARGS_KEY, KEY_BYTES, args_key

FAKE_O_BINARY = 1 << 29  # a bit no platform uses for open(2) flags here
NEWLINE_KEY = bytes(range(KEY_BYTES))  # contains 0x0A, like one random key in about eight


@pytest.fixture
def text_mode(monkeypatch):
    """Descriptors behave like Windows ones: text mode unless opened with O_BINARY."""
    monkeypatch.setattr(audit.secrets, "token_bytes", lambda n: NEWLINE_KEY[:n])
    if hasattr(os, "O_BINARY"):
        return "real"  # the system translates by itself: never stack a double on top
    assert not os.O_WRONLY & FAKE_O_BINARY and not os.O_CREAT & FAKE_O_BINARY
    monkeypatch.setattr(os, "O_BINARY", FAKE_O_BINARY, raising=False)
    text_descriptors: set[int] = set()
    real_open, real_write, real_close = os.open, os.write, os.close

    def fake_open(path, flags, mode=0o777, **kwargs):
        descriptor = real_open(path, flags & ~FAKE_O_BINARY, mode, **kwargs)
        if not flags & FAKE_O_BINARY:
            text_descriptors.add(descriptor)
        return descriptor

    def fake_write(descriptor, data):
        if descriptor in text_descriptors:
            real_write(descriptor, bytes(data).replace(b"\n", b"\r\n"))
            return len(data)
        return real_write(descriptor, data)

    def fake_close(descriptor):
        text_descriptors.discard(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "write", fake_write)
    monkeypatch.setattr(os, "close", fake_close)
    return "simulated"


def test_a_key_with_a_newline_byte_is_written_exactly_in_text_mode(tmp_path, text_mode):
    key = args_key(tmp_path)
    assert key == NEWLINE_KEY
    assert (tmp_path / ARGS_KEY).read_bytes() == NEWLINE_KEY
    assert args_key(tmp_path) == NEWLINE_KEY


def test_the_simulation_really_translates_without_the_flag(tmp_path, text_mode):
    """Control: a write made without O_BINARY is damaged, by the system where it has text
    mode, by the double elsewhere."""
    path = tmp_path / "plain"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, b"a\nb")
    finally:
        os.close(descriptor)
    assert path.read_bytes() == b"a\r\nb"


def _damaged(data_dir: Path, content: bytes) -> Path:
    path = data_dir / ARGS_KEY
    path.parent.mkdir(mode=0o700, parents=True)
    path.write_bytes(content)
    return path


def test_a_damaged_key_left_by_v0_2_0_is_set_aside_and_replaced(tmp_path):
    damaged = NEWLINE_KEY.replace(b"\n", b"\r\n")
    path = _damaged(tmp_path, damaged)
    key = args_key(tmp_path)
    assert len(key) == KEY_BYTES and path.read_bytes() == key
    aside = sorted(path.parent.glob("mcp-args.key.damaged-*"))
    assert [p.read_bytes() for p in aside] == [damaged]
    assert args_key(tmp_path) == key  # stable from now on
    assert sorted(path.parent.glob("mcp-args.key.damaged-*")) == aside


@pytest.mark.parametrize("content", [b"", b"short", b"x" * (KEY_BYTES + 1)])
def test_any_wrong_length_key_is_recovered(tmp_path, content):
    path = _damaged(tmp_path, content)
    key = args_key(tmp_path)
    assert len(key) == KEY_BYTES and path.read_bytes() == key


def test_a_good_key_is_never_replaced(tmp_path):
    path = _damaged(tmp_path, b"k" * KEY_BYTES)
    assert args_key(tmp_path) == b"k" * KEY_BYTES
    assert list(path.parent.glob("*.damaged-*")) == []


@pytest.fixture
def share_locks(monkeypatch):
    """Windows's mandatory sharing on any system (revised on 2026-11-26): while a file is open
    for reading, renaming, replacing or deleting it fails with a sharing violation, which
    Python raises as `PermissionError` (WinError 32). Reads are held open a little longer so a
    concurrent rename has a window to meet them."""
    import pathlib

    opened: dict[str, int] = {}
    guard = threading.Lock()
    real_read, real_rename = pathlib.Path.read_bytes, os.rename
    real_replace, real_unlink = os.replace, os.unlink

    def read_bytes(self):
        name = os.path.normcase(os.path.abspath(self))
        with guard:
            opened[name] = opened.get(name, 0) + 1
        try:
            data = real_read(self)
            time.sleep(0.02)
            return data
        finally:
            with guard:
                opened[name] -= 1

    def refuse_if_open(real):
        def call(source, *args, **kwargs):
            with guard:
                if opened.get(os.path.normcase(os.path.abspath(source)), 0):
                    raise PermissionError(13, "The process cannot access the file because it "
                                              "is being used by another process", str(source))
            return real(source, *args, **kwargs)
        return call

    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    monkeypatch.setattr(os, "rename", refuse_if_open(real_rename))
    monkeypatch.setattr(os, "replace", refuse_if_open(real_replace))
    monkeypatch.setattr(os, "unlink", refuse_if_open(real_unlink))


@pytest.mark.parametrize("sharing", ["as_is", "share_locks"])
def test_concurrent_recoveries_agree_on_one_key(tmp_path, request, sharing):
    if sharing == "share_locks":
        request.getfixturevalue("share_locks")
    _damaged(tmp_path, b"x" * (KEY_BYTES + 3))
    keys: list[bytes] = []
    errors: list[BaseException] = []

    def work(index: int):
        # staggered starts: some readers arrive while the first recovery is renaming the key
        time.sleep(0.004 * index)
        try:
            keys.append(args_key(tmp_path))
        except BaseException as error:  # noqa: BLE001 - reported by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=work, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []
    assert len(keys) == 8 and len(set(keys)) == 1
    assert len(list((tmp_path / "keys").glob("mcp-args.key.damaged-*"))) == 1


def test_the_server_log_keeps_exact_bytes_in_text_mode(tmp_path, text_mode):
    from harness.mcp.worker import _open_errlog

    path = tmp_path / "server.log"
    descriptor = _open_errlog(str(path))
    assert descriptor is not None
    try:
        os.write(descriptor, b"line one\nline two\n")
    finally:
        os.close(descriptor)
    assert path.read_bytes() == b"line one\nline two\n"


@pytest.mark.parametrize("held_open", [False, True])
def test_a_log_held_open_by_another_session_is_appended_to_not_discarded(
        tmp_path, monkeypatch, capsys, held_open):
    """Revised on 2026-11-26: where the system refuses to replace a file another handle has
    open (Windows, WinError 32), a log still written by a concurrent session is not rotated
    now: this session appends to it (rotated by the next one), instead of losing its log."""
    from harness.mcp import commands

    directory = tmp_path / "logs" / "mcp"
    directory.mkdir(parents=True)
    path = directory / "synthetic.stderr.log"
    path.write_bytes(b"x" * (commands.LOG_ROTATE_BYTES + 1))
    if held_open:
        def refused(source, target):
            raise PermissionError(13, "The process cannot access the file because it is "
                                      "being used by another process", str(source))

        monkeypatch.setattr(commands.os, "replace", refused)
    assert commands._server_log(tmp_path, "synthetic") == path
    assert capsys.readouterr().err == ""
    rotated = path.with_name(path.name + ".1")
    if held_open:
        assert path.stat().st_size == commands.LOG_ROTATE_BYTES + 1 and not rotated.exists()
    else:
        assert rotated.stat().st_size == commands.LOG_ROTATE_BYTES + 1 and not path.exists()
