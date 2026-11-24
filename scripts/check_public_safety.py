#!/usr/bin/env python3
"""Refuse content that must never reach this public repository.

Usage:
    python scripts/check_public_safety.py            # every tracked file
    python scripts/check_public_safety.py --staged   # what is about to be committed
    python scripts/check_public_safety.py PATH ...   # specific files

Standard library only, so it runs before the project environment exists.

A line that is a deliberate, reviewed exception carries the marker `public-safety: allow`.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARKER = "public-safety: allow"
DENYLIST_ENV = "HARNESS_PUBLIC_DENYLIST"
# Relative to the home directory, which is resolved only when the variable is not set.
DEFAULT_DENYLIST = Path(".config") / "ai-harness" / "public-denylist.txt"
NO_HOME = "the home directory could not be determined"

# Files that carry runtime data, credentials, browser state or real models.
FORBIDDEN_PATHS = [
    ".env", ".env.*", "*.sqlite", "*.sqlite3", "*.db", "*.db-wal", "*.db-shm",
    "*.sqlite-wal", "*.sqlite-shm", "*.sqlite3-wal", "*.sqlite3-shm", "*.log",
    "*.pem", "*.key", "*.pfx", "*.p12", "*.jks", "*.kdbx", "id_rsa*", "id_ed25519*",
    "*.har", "*.zip", "*.webm", "*.mp4", "storage_state*.json", "*cookies*",
    "*.qea", "*.qeax", "*.eap", "*.eapx", "*.feap",
    "data/*", "logs/*", "vault/*", "edge-profile/*",
]
ALLOWED_PATHS = [".env.example"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
IMAGE_ROOTS = ("docs/",)

SECRET_PATTERNS = {
    "AWS access key": r"\b(AKIA|ASIA)[0-9A-Z]{16}\b",
    "GitHub token": r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})",
    "API key (sk-)": r"\bsk-[A-Za-z0-9_-]{20,}",
    "Slack token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY",
    "JWT": r"\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}",
    "bearer token": r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}",
    "credentials in URL": r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]+@",
    "connection string": r"(?i)\b(password|pwd)\s*=\s*[^;\s\"']{4,}\s*;",
    "assigned secret": (
        r"(?i)\b(password|passwd|secret|token|api[_-]?key|client[_-]?secret)\b"
        r"[\"']?\s*[:=]\s*[\"'][^\"'\s$<{]{8,}[\"']"
    ),
}
PRIVACY_PATTERNS = {
    "personal path": r"(/Users/|/home/)[A-Za-z0-9._-]+/|\b[A-Za-z]:\\+Users\\+[A-Za-z0-9._-]+",
    "email address": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b",
    "IP address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}
SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com")
SAFE_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}
# Lock files hold hashes and registry URLs that look like secrets and are not.
SKIP_CONTENT = {"uv.lock"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.rule}"


def check_path(path: str) -> list[Finding]:
    posix = path.replace("\\", "/")
    name = posix.rsplit("/", 1)[-1]
    if posix in ALLOWED_PATHS or name in ALLOWED_PATHS:
        return []
    for pattern in FORBIDDEN_PATHS:
        if fnmatch.fnmatch(posix, pattern) or fnmatch.fnmatch(name, pattern):
            return [Finding(path, 0, f"forbidden file ({pattern})")]
    if Path(name).suffix.lower() in IMAGE_SUFFIXES and not posix.startswith(IMAGE_ROOTS):
        return [Finding(path, 0, "image outside docs/ (screenshots can show real content)")]
    return []


def check_text(path: str, text: str, denylist: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    if path.replace("\\", "/").rsplit("/", 1)[-1] in SKIP_CONTENT:
        return findings
    denylist_patterns = compile_denylist(denylist)
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for rule, pattern in SECRET_PATTERNS.items():
            if re.search(pattern, line):
                findings.append(Finding(path, number, rule))
        for rule, pattern in PRIVACY_PATTERNS.items():
            for match in re.finditer(pattern, line):
                value = match.group(0)
                if rule == "email address" and value.lower().endswith(SAFE_EMAIL_DOMAINS):
                    continue
                if rule == "IP address" and (
                    value in SAFE_IPS or any(int(part) > 255 for part in value.split("."))
                ):
                    continue
                findings.append(Finding(path, number, rule))
        for index, pattern in enumerate(denylist_patterns, start=1):
            if pattern.search(line):
                # The term itself is not printed: this output may be pasted elsewhere.
                findings.append(Finding(path, number, f"local denylist term #{index}"))
    return findings


CASE_SENSITIVE_PREFIX = "cs:"
_WORD = "0-9A-Za-z\u00c0-\u024f_"


def compile_denylist(terms: list[str]) -> list[re.Pattern[str]]:
    """Whole-word patterns. A term written as `cs:Name` also has to match the exact case,
    which lets a name that is also an ordinary word be listed without flagging the word."""
    patterns = []
    for term in terms:
        exact_case = term.startswith(CASE_SENSITIVE_PREFIX)
        text = term[len(CASE_SENSITIVE_PREFIX):].strip() if exact_case else term
        flags = 0 if exact_case else re.IGNORECASE
        patterns.append(re.compile(f"(?<![{_WORD}]){re.escape(text)}(?![{_WORD}])", flags))
    return patterns


def load_denylist(env: dict[str, str]) -> tuple[list[str], Path | None, bool]:
    """Terms, the file they came from (None when there is no home directory), configured."""
    if env.get(DENYLIST_ENV):
        path = Path(env[DENYLIST_ENV])
    else:
        try:
            path = Path.home() / DEFAULT_DENYLIST
        except RuntimeError:
            return [], None, False
    if not path.is_file():
        return [], path, False
    terms = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return terms, path, True


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def _files(args: argparse.Namespace) -> list[tuple[str, bytes | None]]:
    """Pairs of (path, content). Content is None when the file is gone or unreadable."""
    if args.paths:
        return [(p, Path(p).read_bytes() if Path(p).is_file() else None) for p in args.paths]
    if args.staged:
        names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
        paths = [p for p in names.decode().split("\0") if p]
        return [(p, _git("show", f":{p}")) for p in paths]
    paths = [p for p in _git("ls-files", "-z").decode().split("\0") if p]
    return [(p, Path(p).read_bytes() if Path(p).is_file() else None) for p in paths]


def scan(files: list[tuple[str, bytes | None]], denylist: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path, content in files:
        findings.extend(check_path(path))
        if content is None or b"\0" in content[:8192]:
            continue  # missing or binary
        findings.extend(check_text(path, content.decode("utf-8", errors="replace"), denylist))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staged", action="store_true", help="check the staged content")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    denylist, denylist_path, configured = load_denylist(dict(os.environ))
    files = _files(args)
    findings = scan(files, denylist)
    for finding in findings:
        print(f"public-safety: {finding}", file=sys.stderr)
    if not configured:
        where = f"at {denylist_path}" if denylist_path else f"({NO_HOME})"
        print(
            f"public-safety: WARNING no local denylist {where}; "
            "company, client and system names are NOT being checked",
            file=sys.stderr,
        )
    if findings:
        print(f"public-safety: FAIL ({len(findings)} finding(s) in {len(files)} file(s))",
              file=sys.stderr)
        return 1
    print(f"public-safety: PASS ({len(files)} file(s), {len(denylist)} denylist term(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
