"""Check, in a folder you choose, the file primitives the decision writer depends on.

Usage (PowerShell or a POSIX shell):

    uv run python scripts/diag_vault_write.py <carpeta-de-prueba>

It creates one new, empty subfolder inside <carpeta-de-prueba> (never touching any existing
file), runs each check there, removes everything it created and prints a block of booleans,
counts, error categories and timings to paste back. The block holds no path, no file name of
yours, no user or machine name. Standard library only.

What it checks, the same way `harness/memory/decisions.py` uses them:
  - exclusive creation (`O_CREAT | O_EXCL`) of a hidden temporary file, and that a second one
    with the same name is refused;
  - write and `fsync`;
  - a hard link to a new name, and that a hard link onto an existing name is refused (never
    replaces it);
  - the link count (2 after the link, 1 after removing the temporary file);
  - that `fstat` of the open file and `lstat` of the linked name give the same device and inode;
  - whether a name starting with `.` is hidden by the file system (it is not on Windows: the
    memory reader skips it by its name, not by an attribute);
  - removing the temporary file, and how long each step took.
"""

from __future__ import annotations

import errno
import os
import platform
import secrets
import stat
import sys
import time
from pathlib import Path

HIDDEN_ATTRIBUTE = 0x2  # FILE_ATTRIBUTE_HIDDEN, where `st_file_attributes` exists
FLAGS = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
         | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_CLOEXEC", 0))
DATA = b"---\ntype: decision\n---\n# diag\n"


def category(exc: BaseException) -> str:
    """The class and errno name of an error, without its message (which may hold a path)."""
    code = getattr(exc, "errno", None)
    name = errno.errorcode.get(code, str(code)) if code is not None else "-"
    winerror = getattr(exc, "winerror", None)
    extra = f" winerror={winerror}" if winerror is not None else ""
    return f"{type(exc).__name__}/{name}{extra}"


class Report:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []
        self.timings: dict[str, float] = {}

    def add(self, key: str, value: object) -> None:
        self.lines.append((key, str(value).lower() if isinstance(value, bool) else str(value)))

    def timed(self, key: str, action):
        started = time.perf_counter()
        try:
            return action()
        finally:
            self.timings[key] = (time.perf_counter() - started) * 1000

    def render(self) -> str:
        out = ["--- ai-harness diag_vault_write ---",
               f"python: {sys.version.split()[0]}",
               f"system: {platform.system()} {platform.release()}"]
        out += [f"{key}: {value}" for key, value in self.lines]
        out += [f"ms_{key}: {value:.1f}" for key, value in self.timings.items()]
        out.append("--- end ---")
        return "\n".join(out)


def run_checks(work: Path, report: Report) -> None:
    temp = work / ".harness-diag-save.tmp"
    note = work / "2026-01-01-diag-00000000.md"
    other = work / "ocupado.md"

    fd = report.timed("exclusive_create", lambda: os.open(temp, FLAGS, 0o644))
    report.add("exclusive_create_ok", True)
    try:
        view = memoryview(DATA)
        while view:
            view = view[os.write(fd, view):]
        report.timed("fsync", lambda: os.fsync(fd))
        report.add("write_fsync_ok", True)
        opened = os.fstat(fd)
    finally:
        os.close(fd)
    try:
        os.close(os.open(temp, FLAGS, 0o644))
        report.add("exclusive_create_refuses_existing", False)
    except FileExistsError:
        report.add("exclusive_create_refuses_existing", True)
    except OSError as exc:
        report.add("exclusive_create_refuses_existing", f"other:{category(exc)}")

    try:
        report.timed("link", lambda: os.link(temp, note))
        report.add("hard_link_ok", True)
    except OSError as exc:
        report.add("hard_link_ok", False)
        report.add("hard_link_error", category(exc))
        return
    linked = note.lstat()
    report.add("link_count_after_link", linked.st_nlink)
    report.add("fstat_lstat_same_inode",
               (opened.st_dev, opened.st_ino) == (linked.st_dev, linked.st_ino))
    report.add("fstat_inode_nonzero", opened.st_ino != 0)

    with open(other, "xb") as handle:
        handle.write(b"existing\n")
    try:
        os.link(temp, other)
        report.add("link_refuses_existing", False)
    except FileExistsError:
        report.add("link_refuses_existing", True)
    except OSError as exc:
        report.add("link_refuses_existing", f"other:{category(exc)}")
    report.add("existing_kept", other.read_bytes() == b"existing\n")

    attributes = getattr(temp.lstat(), "st_file_attributes", None)
    report.add("dot_name_hidden_attribute",
               "n/a" if attributes is None else bool(attributes & HIDDEN_ATTRIBUTE))
    names = {entry.name for entry in os.scandir(work)}
    report.add("dot_name_listed", temp.name in names)

    try:
        report.timed("unlink_temp", lambda: os.unlink(temp))
        report.add("unlink_temp_ok", True)
    except OSError as exc:
        report.add("unlink_temp_ok", False)
        report.add("unlink_temp_error", category(exc))
    report.add("link_count_after_unlink", note.lstat().st_nlink)
    report.add("note_intact", note.read_bytes() == DATA)


def clean(work: Path, report: Report) -> None:
    left = 0
    for entry in list(os.scandir(work)):
        try:
            if stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                os.unlink(entry.path)
            else:
                left += 1
        except OSError:
            left += 1
    try:
        os.rmdir(work)
    except OSError as exc:
        report.add("cleanup_error", category(exc))
        left += 1
    report.add("cleanup_ok", left == 0)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: uv run python scripts/diag_vault_write.py <carpeta-de-prueba>",
              file=sys.stderr)
        return 2
    base = Path(argv[0])
    if not base.is_dir():
        print("error: the folder does not exist or is not a folder", file=sys.stderr)
        return 2
    report = Report()
    work = base / f"ai-harness-diag-{secrets.token_hex(4)}"
    try:
        os.mkdir(work)  # fails if it exists: nothing of yours is ever reused
    except OSError as exc:
        print(f"error: cannot create a test subfolder ({category(exc)})", file=sys.stderr)
        return 1
    try:
        run_checks(work, report)
    except OSError as exc:
        report.add("unexpected_error", category(exc))
    finally:
        clean(work, report)
    print(report.render())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
