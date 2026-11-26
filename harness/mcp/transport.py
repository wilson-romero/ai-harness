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

from harness.text.redaction import LineRedactor, Piece

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
# Per session, besides the cap: a line that is dropped (too long, in a key block) or that
# redacts to a short marker uses little or none of the cap, so the work is bounded apart:
# lines handed to the log (a fixed cost each) and bytes handed to `redact` (about 100 ns
# each). Reviews of 2026-11-25.
STDERR_LOG_LINES = 64 * 1024
STDERR_REDACT_BYTES = 4 * 1024 * 1024


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
    stderr_dropped: int = 0  # of those, the bytes that are in no form in its log
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
            state.stderr_dropped = log.close(state.stderr_bytes)

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
    """The server's stderr as its log keeps it: redacted, and within the session's budgets.

    Text goes through `LineRedactor` (SEC-01): a line is written only once it is complete and
    redacted; a line too long to redact, or inside a private key block, is dropped with a
    marker. One rule ends the writing, line by line: the first line that would pass
    `STDERR_LOG_LINES` lines, `STDERR_REDACT_BYTES` bytes handed to `redact`, or what is left
    of `STDERR_KEEP_BYTES` is not written, nor is anything after it (what the redactor holds
    is dropped, never written). A failure inside the logging stops the writing the same way,
    with a marker if the log can still be written, and never ends the session. The closing
    line counts the bytes of the server's stderr that are in no form in the log (a redacted
    credential is in it, as its marker) and says why. It is written when the stream ends or
    the session is stopped; a process killed outright writes neither it nor the unfinished
    line. `errlog` None: nothing is written, and everything counts as dropped.
    """

    def __init__(self, errlog: int | None) -> None:
        self._errlog = errlog
        self._room = STDERR_KEEP_BYTES
        self._kept = 0  # bytes of the server's stderr whose (redacted) text is in the log
        self._lines = 0
        self._redacted = 0
        self._stopped: str | None = None if errlog is not None else "no log"
        self._redactor = LineRedactor()

    def feed(self, chunk: bytes) -> None:
        if self._stopped is not None:
            return
        try:
            self._write(self._redactor.feed(chunk))
        except Exception as exc:  # noqa: BLE001 - the log must never end the session
            self._fail(exc)

    def close(self, total: int) -> int:
        """The stream ended (or was abandoned) after `total` bytes. Returns the bytes that are
        in no form in the log."""
        try:
            self._write(self._redactor.finish())  # writes nothing once the writing has stopped
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
        dropped = total - self._kept
        if dropped > 0 and self._errlog is not None:
            why = self._stopped or "lines too long to redact or private key blocks, marked above"
            self._append(f"\n[ai-harness: {dropped} more bytes of stderr were dropped; "
                         f"{why}]\n".encode("ascii"))
        self._stopped = self._stopped or "closed"
        return dropped

    def _write(self, pieces: list[Piece]) -> None:
        for piece in pieces:
            if self._stopped is not None:
                return
            self._lines += 1
            self._redacted += piece.raw if piece.kept else 0
            if self._lines > STDERR_LOG_LINES:
                self._stopped = f"the log passed its budget of {STDERR_LOG_LINES} lines"
            elif self._redacted > STDERR_REDACT_BYTES:
                self._stopped = (f"the log passed its budget of {STDERR_REDACT_BYTES} bytes "
                                 "to redact")
            elif len(piece.output) > self._room:
                self._stopped = f"the log reached its cap of {STDERR_KEEP_BYTES} bytes"
            elif self._append(piece.output):
                self._room -= len(piece.output)
                self._kept += piece.raw if piece.kept else 0

    def _fail(self, exc: Exception) -> None:
        # the exception's text is never written: it may quote the input
        self._stopped = f"the stderr log failed ({type(exc).__name__})"
        self._append(f"\n[ai-harness: the stderr log stopped here ({type(exc).__name__}); "
                     "the rest is counted, not kept]\n".encode("ascii"))

    def _append(self, data: bytes) -> bool:
        """Write all of `data`, looping over short writes; a failure stops the writing (with
        no marker: the log cannot take one) and is not raised."""
        view = memoryview(data)
        try:
            while view:
                written = os.write(self._errlog, view)  # type: ignore[arg-type]
                if written <= 0:
                    raise OSError("the log took no bytes")
                view = view[written:]
        except Exception:  # noqa: BLE001 - a log that cannot be written ends only the log
            self._stopped = self._stopped or "writing the log failed"
            return False
        return True


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
