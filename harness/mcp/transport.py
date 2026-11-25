"""A stdio transport for the SDK `Client` that bounds every message before it is parsed.

Why not the SDK's own `stdio_client` (measured 2026-11-24, `mcp` 2.3.0, CPython 3.14.8): it
joins stdout chunks as `str` until a newline, without a limit; a server that writes 8 MiB with
no newline took the client to 484 MiB of peak memory and 16 MiB to 1003 MiB. Here stdout is
read as bytes into one buffer, each new chunk is scanned once for the newline, and a message
longer than the current limit is never decoded or parsed: the transport counts its size,
reports a fault and stops reading.

This transport runs inside the session process (`harness.mcp.worker`, design D4 as revised on
2026-11-24). The server is started as a plain child of that process, in the same process group
(POSIX) or Job Object (Windows): the harness kills the whole tree of the session process from
outside, so the server and anything it starts in that group end with it, without a platform
branch here. Inside, the shutdown is: close stdin, wait 2 s, kill the server, wait 2 s.

The server's stderr is read through a pipe and redacted line by line before it reaches its
log (`StderrLog`, revised 2026-11-25): at most `STDERR_KEEP_BYTES` of redacted text go to the
log, the rest is counted and dropped, and past `STDERR_KILL_BYTES` the session is ended with
the fault `stderr_too_large` (independent review of 2026-11-24, finding 2).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio
import anyio.lowlevel
import mcp_types as types
from mcp.client.stdio import _drain_stdout, _get_executable_command
from mcp.shared.message import SessionMessage

from harness.text.redaction import LineRedactor

# The rest of an oversized message is counted (not kept) up to this size or for this long, to
# report its size; past either bound it is reported as "at least" what was seen.
OVERFLOW_COUNT_CAP = 64 * 1024 * 1024
OVERFLOW_COUNT_WINDOW_S = 1.0
WRITER_FLUSH_TIMEOUT_S = 0.5
STOP_GRACE_S = 2.0  # after closing the server's stdin, before killing it
REAP_WAIT_S = 2.0  # after the kill, for the process to be seen ended
EXIT_POLL_S = 0.01
STDERR_KEEP_BYTES = 1024 * 1024  # per session, written to the server's log
STDERR_KILL_BYTES = 64 * 1024 * 1024  # per session: past this the server is stopped


@dataclass
class TransportState:
    """Shared between the transport and the session that owns it (one thread, one loop)."""

    limit: int  # largest message accepted now, in bytes of its UTF-8 line
    phase: str = "startup"
    fault: str | None = None  # protocol_error, result/message_too_large, stderr_too_large
    fault_bytes: int | None = None  # size of the oversized message, if it was measured
    fault_bytes_exact: bool = True
    call_bytes: int = 0  # bytes of the messages received during the call phase
    server_stopped: bool | None = None  # set by the shutdown: did the server process end?
    error_replies: int = 0  # JSON-RPC error responses the server itself sent
    stderr_bytes: int = 0  # everything the server wrote on stderr, kept or not
    on_fault: Callable[[], None] = field(default=lambda: None)

    def report(self, fault: str, size: int | None = None, exact: bool = True) -> None:
        if self.fault is None:
            self.fault, self.fault_bytes, self.fault_bytes_exact = fault, size, exact
            self.on_fault()


@asynccontextmanager
async def bounded_stdio(
    command: list[str],
    env: dict[str, str],
    cwd: str | None,
    errlog: int | None,
    state: TransportState,
) -> AsyncGenerator[tuple[object, object], None]:
    """`errlog` is a file descriptor open for appending, or None to drop the server's stderr."""
    executable = await _get_executable_command(command[0])
    # Not in a new session or job of its own: the server stays in the session process's kill
    # scope, which the harness ends from outside (see the module docstring).
    process = await anyio.open_process([executable, *command[1:]], env=env, cwd=cwd)
    # No awaits until the task group is entered (same rule as the SDK): a cancellation in the
    # gap would leak the live process.
    read_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_reader = anyio.create_memory_object_stream[SessionMessage](0)
    writer_done = anyio.Event()

    def oversized(size: int, exact: bool) -> None:
        state.report(
            "result_too_large" if state.phase == "call" else "message_too_large", size, exact
        )

    async def read_messages() -> int | None:
        """Forward each message; return the bytes seen of an oversized one, or None."""
        assert process.stdout is not None
        buffer = bytearray()
        scanned = 0  # bytes at the start of `buffer` known to hold no newline
        async for chunk in process.stdout:
            buffer += chunk
            start = 0
            while (newline := buffer.find(b"\n", max(scanned, start))) >= 0:
                line = bytes(buffer[start:newline]).rstrip(b"\r")
                start = scanned = newline + 1
                if len(line) > state.limit:
                    oversized(len(line), True)
                    return None
                if not line.strip():
                    continue
                if state.phase == "call":
                    state.call_bytes += len(line)
                message = _parse(line)
                if message is None:
                    state.report("protocol_error")
                    return None
                if isinstance(message.message, types.JSONRPCError):
                    state.error_replies += 1
                await read_writer.send(message)
            del buffer[:start]
            scanned = len(buffer)
            if len(buffer) > state.limit:
                return len(buffer)
        return None

    async def measure_overflow(seen: int) -> None:
        """Count the rest of an oversized message, without keeping it, for a short while."""
        assert process.stdout is not None
        with anyio.move_on_after(OVERFLOW_COUNT_WINDOW_S):
            while seen <= OVERFLOW_COUNT_CAP:
                try:
                    chunk = await process.stdout.receive()
                except anyio.EndOfStream:
                    break
                newline = chunk.find(b"\n")
                if newline >= 0:
                    oversized(seen + newline, True)
                    return
                seen += len(chunk)
        oversized(seen, False)

    async def stdout_reader() -> None:
        try:
            async with read_writer:
                try:
                    overflow = await read_messages()
                    if overflow is not None:
                        await measure_overflow(overflow)
                finally:
                    await _drain_stdout(process)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, ConnectionError):
            pass  # shutdown closed a stream under the read; the session sees the closure

    async def stderr_reader() -> None:
        """Keep the first bytes in the log, redacted; count the rest; stop a server that floods."""
        assert process.stderr is not None
        log = StderrLog(errlog)
        try:
            async for chunk in process.stderr:
                state.stderr_bytes += len(chunk)
                log.feed(chunk)
                if state.stderr_bytes > STDERR_KILL_BYTES:
                    state.report("stderr_too_large", state.stderr_bytes, False)
                    return
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
            pass
        finally:
            log.close(state.stderr_bytes)

    async def stdin_writer() -> None:
        assert process.stdin is not None
        try:
            async with write_reader:
                async for session_message in write_reader:
                    data = session_message.message.model_dump_json(
                        by_alias=True, exclude_unset=True
                    )
                    await process.stdin.send((data + "\n").encode("utf-8"))
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
            await read_writer.aclose()  # the session must see the end, not wait forever
        finally:
            writer_done.set()

    async def shutdown() -> None:
        read_stream.close()
        write_stream.close()
        with anyio.move_on_after(WRITER_FLUSH_TIMEOUT_S):
            await writer_done.wait()
        await _close(process.stdin)
        if not await _exited(process, STOP_GRACE_S):
            try:
                process.kill()  # the server only; its whole tree is the harness's to end
            except OSError:
                pass
            await _exited(process, REAP_WAIT_S)
        state.server_stopped = process.returncode is not None
        await _close(process.stdout)
        await _close(process.stderr)
        for stream in (read_stream, write_stream, read_writer, write_reader):
            await stream.aclose()
        await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as group:
        group.start_soon(stdout_reader)
        group.start_soon(stderr_reader)
        group.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            # Every wait inside is bounded; shielded so that a cancelled caller cannot leave
            # the server process alive.
            with anyio.CancelScope(shield=True):
                await shutdown()
            group.cancel_scope.cancel()
    await anyio.lowlevel.cancel_shielded_checkpoint()


class StderrLog:
    """The server's stderr as its log keeps it: redacted, and at most `STDERR_KEEP_BYTES`.

    Text goes through `LineRedactor` (SEC-01), so a credential split across two reads is
    still masked, and a line is written only once it is complete or once the redactor's bound
    releases it. The cap counts what is written; once it is reached nothing more is fed to the
    redactor, and what it still holds is dropped. The closing line says how many bytes of the
    server's stderr are not in the log. `errlog` None: everything is dropped, nothing written.
    """

    def __init__(self, errlog: int | None) -> None:
        self._errlog = errlog
        self._room = STDERR_KEEP_BYTES
        self._kept = 0  # bytes of the server's stderr whose (redacted) text is in the log
        self._redactor = LineRedactor()

    def feed(self, chunk: bytes) -> None:
        if self._errlog is not None and self._room > 0:
            self._write(self._redactor.feed(chunk))

    def close(self, total: int) -> None:
        """The stream ended (or was abandoned) after `total` bytes."""
        if self._errlog is None:
            return
        if self._room > 0:
            self._write(self._redactor.finish())
        dropped = total - self._kept
        if dropped > 0:
            self._append(f"\n[ai-harness: {dropped} more bytes of stderr were "
                         "dropped]\n".encode("ascii"))

    def _write(self, pieces: list[tuple[int, bytes]]) -> None:
        for raw_bytes, output in pieces:
            if self._room <= 0:
                return
            part = output[: self._room]
            self._room -= len(part)
            # A piece cut by the cap: exact when redaction did not change it (the usual case).
            self._kept += raw_bytes if len(part) == len(output) else min(raw_bytes, len(part))
            self._append(part)

    def _append(self, data: bytes) -> None:
        if not data:
            return
        try:
            os.write(self._errlog, data)  # type: ignore[arg-type]
        except OSError:
            pass


async def _close(stream: object) -> None:
    if stream is None:
        return
    try:
        await stream.aclose()  # type: ignore[attr-defined]
    except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
        pass


async def _exited(process: object, timeout: float) -> bool:
    """Poll the return code (not `wait()`: a grandchild holding a pipe would make it hang)."""
    with anyio.move_on_after(timeout):
        while process.returncode is None:  # type: ignore[attr-defined]
            await anyio.sleep(EXIT_POLL_S)
    return process.returncode is not None  # type: ignore[attr-defined]


def _parse(line: bytes) -> SessionMessage | None:
    """One JSON-RPC message, or None. The line is already within the size limit."""
    try:
        return SessionMessage(types.jsonrpc_message_adapter.validate_json(line, by_name=False))
    except ValueError:  # pydantic's ValidationError is a ValueError; nothing is logged
        return None
