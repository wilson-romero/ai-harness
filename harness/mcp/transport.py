"""A stdio transport for the SDK `Client` that bounds every message before it is parsed.

Why not the SDK's own `stdio_client` (measured 2026-11-24, `mcp` 2.3.0, CPython 3.14.8): it
joins stdout chunks as `str` until a newline, without a limit; a server that writes 8 MiB with
no newline took the client to 484 MiB of peak memory and 16 MiB to 1003 MiB. Here stdout is
read as bytes into one buffer, each new chunk is scanned once for the newline, and a message
longer than the current limit is never decoded or parsed: the transport counts its size,
reports a fault and stops reading.

What is reused from the SDK, unchanged: starting the process in its own kill scope (process
group on POSIX, Job Object on Windows) and the shutdown sequence (close stdin, wait, kill the
whole tree). Those are the SDK's private helpers of the pinned version (`mcp==2.3.0`); the
platform branches stay inside the SDK, none is added here.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TextIO

import anyio
import anyio.lowlevel
import mcp_types as types
from mcp.client.stdio import (
    _create_platform_compatible_process,
    _drain_stdout,
    _get_executable_command,
    _stop_server_process,
)
from mcp.shared.message import SessionMessage

# The rest of an oversized message is counted (not kept) up to this size or for this long, to
# report its size; past either bound it is reported as "at least" what was seen.
OVERFLOW_COUNT_CAP = 64 * 1024 * 1024
OVERFLOW_COUNT_WINDOW_S = 1.0
WRITER_FLUSH_TIMEOUT_S = 0.5


@dataclass
class TransportState:
    """Shared between the transport and the session that owns it (one thread, one loop)."""

    limit: int  # largest message accepted now, in bytes of its UTF-8 line
    phase: str = "startup"
    fault: str | None = None  # protocol_error, result_too_large, message_too_large
    fault_bytes: int | None = None  # size of the oversized message, if it was measured
    fault_bytes_exact: bool = True
    call_bytes: int = 0  # bytes of the messages received during the call phase
    server_stopped: bool | None = None  # set by the shutdown: did the process end?
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
    errlog: TextIO,
    state: TransportState,
) -> AsyncGenerator[tuple[object, object], None]:
    executable = await _get_executable_command(command[0])
    process = await _create_platform_compatible_process(
        command=executable, args=command[1:], env=env, errlog=errlog, cwd=cwd
    )
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
        await _stop_server_process(process)
        state.server_stopped = process.returncode is not None
        for stream in (read_stream, write_stream, read_writer, write_reader):
            await stream.aclose()
        await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as group:
        group.start_soon(stdout_reader)
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


def _parse(line: bytes) -> SessionMessage | None:
    """One JSON-RPC message, or None. The line is already within the size limit."""
    try:
        return SessionMessage(types.jsonrpc_message_adapter.validate_json(line, by_name=False))
    except ValueError:  # pydantic's ValidationError is a ValueError; nothing is logged
        return None
