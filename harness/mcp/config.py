"""The local allowlist of MCP servers (mcp-gateway D2).

Only the person edits it; the harness only reads it. It names the servers that may be started,
the exact command of each (an argument list, never a shell string), the names of the
environment variables each one receives, its deadlines, and the tools and arguments that may be
used, each tool with its operation (`read` or `write`). Whatever a server says about itself
can only restrict this, never extend it (D5).
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from harness.core.errors import HarnessError
from harness.core.git_guard import VersionableFile, ensure_not_versionable
from harness.core.strict_json import loads_strict
from harness.text.safe_text import safe_foreign_line

if TYPE_CHECKING:
    import sqlite3

    from harness.mcp.audit import PlanLink
    from harness.mcp.gateway import CallReport
    from harness.mcp.policy import ParsedArguments

CONFIG_ENV = "HARNESS_MCP_CONFIG"
FORMAT = "ai-harness/mcp/1"
MAX_CONFIG_BYTES = 256 * 1024
NAME_PATTERN = r"[a-z][a-z0-9_-]{0,63}"
ARGUMENT_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]{0,63}"
ENV_NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_]{0,127}"
MAX_TIMEOUT_S = 300
DEFAULT_STARTUP_TIMEOUT_S = 20
DEFAULT_CALL_TIMEOUT_S = 30
DEFAULT_MAX_RESULT_BYTES = 64 * 1024
MIN_RESULT_BYTES = 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_STRING_LENGTH = 4096
MAX_PATTERN_LENGTH = 256
DESCRIPTION_MAX = 120
# Names of the servers the harness itself is (workspace-tools D6, D7): a local list that
# declares one is refused when it is read (`reserved_server_name`), so the name in a plan
# always means the harness's own table, never a program of the list.
RESERVED_SERVER_NAMES = frozenset({"workspace"})
RESERVED_SERVER_NAME = "reserved_server_name"


class ConfigError(HarnessError):
    """The allowlist is missing, unreadable, versionable or invalid. Nothing is started."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StringArgument(_Strict):
    type: Literal["string"]
    max_length: int = Field(ge=1, le=MAX_STRING_LENGTH)
    pattern: str | None = Field(default=None, max_length=MAX_PATTERN_LENGTH)
    required: bool = False

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error:
                raise ValueError("is not a valid regular expression") from None
        return value


class IntegerArgument(_Strict):
    type: Literal["integer"]
    minimum: int
    maximum: int
    required: bool = False


class BooleanArgument(_Strict):
    type: Literal["boolean"]
    required: bool = False


class EnumArgument(_Strict):
    type: Literal["enum"]
    values: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(
        min_length=1, max_length=64
    )
    required: bool = False


Argument = Annotated[
    StringArgument | IntegerArgument | BooleanArgument | EnumArgument,
    Field(discriminator="type"),
]


class ToolEntry(_Strict):
    operation: Literal["read", "write"]
    max_result_bytes: int = Field(
        default=DEFAULT_MAX_RESULT_BYTES, ge=MIN_RESULT_BYTES, le=MAX_RESULT_BYTES
    )
    arguments: dict[Annotated[str, Field(pattern=f"^{ARGUMENT_NAME_PATTERN}$")], Argument] = Field(
        default_factory=dict, max_length=64
    )
    # What the tool reads, in the person's words, for the catalogue of `/plan` (code-mode D8,
    # study decision 5 (a)). Never the server's description, which is untrusted.
    description: str | None = Field(default=None, min_length=1, max_length=DESCRIPTION_MAX)
    # A read the person allows by rule (code-mode A2): a plan whose steps are all `auto_read`
    # runs without the approval box, audited as approved by `rule`. Valid only for a read.
    auto_read: bool = False

    @model_validator(mode="after")
    def _auto_read_is_a_read(self) -> "ToolEntry":
        if self.auto_read and self.operation != "read":
            raise ValueError("auto_read is valid only for a tool whose operation is read")
        return self

    @field_validator("description")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        if value is not None and (safe_foreign_line(value).text != value or value != value.strip()):
            raise ValueError("must be one line of plain text, with no control, format or "
                             "invisible character, no credential and no surrounding blanks")
        return value


# A string argument counts as bounded (owner decision of 2026-11-28, code-mode A3-12) when it
# declares a pattern and at most this many characters. The policy matches the pattern against
# the whole value (`re.fullmatch`), so it is anchored whatever it is written as; the length
# limit caps what one value the model chooses can carry. What the pattern lets through is the
# person's choice: the harness does not judge a pattern (`.*` is as free as none).
BOUNDED_STRING_MAX_LENGTH = 64


def free_argument(entry: ToolEntry) -> str | None:
    """The first declared argument (in name order) that can carry free text, or None when
    every one is bounded: an `enum`, an `integer`, a `boolean`, or a `string` with a `pattern`
    and `max_length` at most BOUNDED_STRING_MAX_LENGTH. An argument the list does not declare
    is never sent (the gateway refuses it, `argument_not_allowed`), whatever the server's
    schema accepts."""
    for name in sorted(entry.arguments):
        spec = entry.arguments[name]
        if isinstance(spec, StringArgument) and (
                spec.pattern is None or spec.max_length > BOUNDED_STRING_MAX_LENGTH):
            return name
    return None


class ServerEntry(_Strict):
    command: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(
        min_length=1, max_length=64
    )
    cwd: str | None = None
    env: list[Annotated[str, Field(pattern=f"^{ENV_NAME_PATTERN}$")]] = Field(
        default_factory=list, max_length=64
    )
    startup_timeout_s: int = Field(default=DEFAULT_STARTUP_TIMEOUT_S, ge=1, le=MAX_TIMEOUT_S)
    call_timeout_s: int = Field(default=DEFAULT_CALL_TIMEOUT_S, ge=1, le=MAX_TIMEOUT_S)
    tools: dict[Annotated[str, Field(pattern=f"^{NAME_PATTERN}$")], ToolEntry] = Field(
        default_factory=dict, max_length=256
    )

    @field_validator("command")
    @classmethod
    def _absolute_program(cls, value: list[str]) -> list[str]:
        if any("\x00" in part for part in value):
            raise ValueError("must not contain NUL characters")
        if not Path(value[0]).is_absolute():
            raise ValueError("the program (first element) must be an absolute path")
        return value

    @field_validator("cwd")
    @classmethod
    def _absolute_cwd(cls, value: str | None) -> str | None:
        if value is not None and ("\x00" in value or not Path(value).is_absolute()):
            raise ValueError("must be an absolute path")
        return value


class McpConfig(_Strict):
    format: Literal["ai-harness/mcp/1"]
    servers: dict[Annotated[str, Field(pattern=f"^{NAME_PATTERN}$")], ServerEntry] = Field(
        max_length=64
    )

    @field_validator("servers")
    @classmethod
    def _no_reserved_name(cls, value: dict[str, ServerEntry]) -> dict[str, ServerEntry]:
        for name in sorted(value):
            if name in RESERVED_SERVER_NAMES:
                raise ValueError(f"{RESERVED_SERVER_NAME}: the server name {name} is the "
                                 "harness's own work folder and cannot be declared here")
        return value


class InternalServer:
    """A server the harness itself is (workspace-tools D6, D7): a literal table of tools in
    code, decided by the same policy (`decide_before_start`), bound by the same entry hash and
    audited in the same `tool_calls` table as an MCP server, but never started as a process.
    It is not a `ServerEntry`: it has no command. A subclass gives `tools`, `bound` and `call`.
    """

    startup_timeout_s: int = 0
    call_timeout_s: int = 10
    tools: Mapping[str, ToolEntry] = {}

    def bound(self) -> dict[str, Any]:
        """What the plan's entry hash binds of this server besides its tools (`policy.
        entry_sha256`): never a path in clear, so that a hash cannot be guessed back."""
        raise NotImplementedError

    def model_dump(self, mode: str = "json", exclude: set[str] | None = None) -> dict[str, Any]:
        return self.bound()  # the shape `entry_sha256` reads from a `ServerEntry`

    def call(self, conn: sqlite3.Connection, key: bytes, tool: str, parsed: ParsedArguments,
             plan: PlanLink | None) -> CallReport:
        """Run one call the policy allowed and audit it; never raises for what the tool
        finds (a refusal is a failed call with the harness's reason)."""
        raise NotImplementedError


@dataclass(frozen=True)
class LoadedConfig:
    config: McpConfig | None  # None: no HARNESS_MCP_CONFIG, so no servers at all
    # The harness's own servers in force now (the work folder, when the person set one for
    # the session); never read from the local list (workspace-tools D6).
    internal: Mapping[str, InternalServer] = field(default_factory=dict)

    @property
    def servers(self) -> Mapping[str, ServerEntry | InternalServer]:
        listed = self.config.servers if self.config is not None else {}
        if not self.internal:
            return listed
        return {**listed, **self.internal}


def load_config(env: Mapping[str, str]) -> LoadedConfig:
    """Read and validate the allowlist named by `HARNESS_MCP_CONFIG`; nothing is started."""
    raw = (env.get(CONFIG_ENV) or "").strip()
    if not raw:
        return LoadedConfig(None)
    path = Path(raw)
    if not path.is_absolute():
        raise ConfigError(f"{CONFIG_ENV} must be an absolute path")
    _check_writers(path)
    text = _read_checked(path.resolve())
    try:
        data = loads_strict(text, max_bytes=MAX_CONFIG_BYTES, what="the MCP configuration")
    except HarnessError as exc:
        raise ConfigError(str(exc)) from None
    try:
        return LoadedConfig(McpConfig.model_validate(data))
    except ValidationError as exc:
        raise ConfigError(f"invalid MCP configuration: {_first_error(exc)}") from None


def _check_writers(path: Path) -> None:
    """Refuse an allowlist that someone else could change (independent review, 2026-11-24).

    The allowlist decides which programs run, so the file, the link that names it (if any)
    and the directories that hold them must belong to the person (or to the system) and not be
    writable by the group or by others. Checked where the system has owners and mode bits
    (`os.getuid` exists); on Windows the ACL is not checked, as the README says.
    """
    if not hasattr(os, "getuid"):
        return
    owners = {os.getuid(), 0}
    try:
        checked = [(os.lstat(path), "file"), (os.stat(path.parent), "directory")]
        target = path.resolve()
        if target != path:
            checked += [(os.stat(target), "file"), (os.stat(target.parent), "directory")]
    except OSError:
        raise ConfigError("the MCP configuration file cannot be read") from None
    for info, kind in checked:
        if stat.S_ISLNK(info.st_mode):
            if info.st_uid not in owners:
                raise ConfigError("the MCP configuration is a link owned by another user")
            continue
        if info.st_uid not in owners:
            raise ConfigError(f"the MCP configuration {kind} belongs to another user")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ConfigError(
                f"the MCP configuration {kind} is writable by other users; "
                "make it writable only by you (chmod go-w)"
            )


def _read_checked(path: Path) -> str:
    """Open first, then ask Git, then make sure the open file is still the file at that path.

    The file read is the one that was checked: a file swapped in between the check and the
    read is refused, not read.
    """
    try:
        handle = path.open("rb")
    except OSError:
        raise ConfigError("the MCP configuration file cannot be read") from None
    with handle:
        opened = os.fstat(handle.fileno())
        try:
            ensure_not_versionable(path)
        except VersionableFile as exc:
            raise ConfigError(
                f"the MCP configuration file is refused: {exc}; keep it outside any repository "
                "or make Git ignore it"
            ) from None
        try:
            current = os.stat(path)
        except OSError:
            raise ConfigError("the MCP configuration file changed while it was read") from None
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ConfigError("the MCP configuration file changed while it was read")
        raw = handle.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigError(f"the MCP configuration is larger than {MAX_CONFIG_BYTES} bytes")
    try:
        return raw.decode("utf-8").removeprefix("﻿")
    except UnicodeDecodeError:
        raise ConfigError("the MCP configuration is not valid UTF-8") from None


def _first_error(exc: ValidationError) -> str:
    """The field path and message of the first error, never the offending value."""
    error = exc.errors(include_url=False, include_input=False, include_context=False)[0]
    location = ".".join(str(part) for part in error["loc"]) or "(top level)"
    return safe_foreign_line(f"{location}: {error["msg"]}").text[:300]
