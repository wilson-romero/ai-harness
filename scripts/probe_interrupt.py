"""Probe of premise P1 (interactive-shell, task 1.2). Not part of the product.

How does Ctrl+C reach a process that runs one `asyncio` loop, (a) while a task is pending and
(b) while a line read is blocked in a helper thread, (c) while the loop thread itself waits for
a line read by a helper thread (the approval prompt)? The handler is installed with
`signal.signal`, the one API that exists on both platforms (`loop.add_signal_handler` does not
exist on Windows).

Run it in a terminal and follow the READY lines (press Ctrl+C when told):

    uv run python scripts/probe_interrupt.py

Every line it prints starts with `probe:` and holds no personal data.
`--drive` (POSIX only: it needs a pseudo-terminal) runs the same probe as a child process and
types Ctrl+C into its terminal, as a person would.
"""

import asyncio
import queue
import signal
import sys
import threading

events: list[str] = []


def say(text: str) -> None:
    print(f"probe: {text}", flush=True)


def handler(signum, frame) -> None:
    where = "main" if threading.current_thread() is threading.main_thread() else "other"
    events.append(f"handler ran in the {where} thread")
    on_interrupt()


def on_interrupt() -> None:  # replaced in each phase
    pass


def read_line(prompt: str, out: queue.SimpleQueue) -> None:
    try:
        out.put(("line", input(prompt)))
    except EOFError:
        out.put(("eof", None))
    except KeyboardInterrupt:
        out.put(("keyboardinterrupt", None))


async def main() -> None:
    global on_interrupt
    loop = asyncio.get_running_loop()

    # (a) a pending task
    task = asyncio.create_task(asyncio.sleep(60))
    on_interrupt = lambda: loop.call_soon_threadsafe(task.cancel)  # noqa: E731
    say("READY task: press Ctrl+C now")
    try:
        await task
        say("task: finished (the interrupt did not reach it)")
    except asyncio.CancelledError:
        say("task: cancelled; the loop is still running")
    say("events: " + "; ".join(events))
    events.clear()

    # (b) a line read in a helper thread, the loop waiting for it
    lines: queue.SimpleQueue = queue.SimpleQueue()
    done = asyncio.Event()
    on_interrupt = lambda: loop.call_soon_threadsafe(done.set)  # noqa: E731
    reader = threading.Thread(target=read_line, args=("probe-line> ", lines), daemon=True)
    reader.start()
    say("READY wait: type a few letters, do not press Enter, then press Ctrl+C")
    await done.wait()
    await asyncio.sleep(0.5)  # let the reader report, if it ends
    if reader.is_alive():
        say("wait: the reader thread is still blocked after the interrupt")
        say("READY line: type   after   and press Enter")
    outcome = await asyncio.to_thread(lines.get)
    say(f"wait: reader outcome {outcome[0]} {outcome[1]!r}")
    say("events: " + "; ".join(events))
    events.clear()

    # (c) the loop thread blocked in a line read done by a helper thread (approval prompt)
    answers: queue.SimpleQueue = queue.SimpleQueue()
    on_interrupt = lambda: answers.put(("interrupt", None))  # noqa: E731
    reader = threading.Thread(target=read_line, args=("probe-code> ", answers), daemon=True)
    reader.start()
    say("READY prompt: press Ctrl+C now (do not type anything)")
    while True:
        try:
            outcome = answers.get(timeout=0.1)
            break
        except queue.Empty:
            continue
    say(f"prompt: first outcome {outcome[0]}")
    say("events: " + "; ".join(events))
    if reader.is_alive():
        say("READY end: type   end   and press Enter")
        outcome = answers.get()
    say(f"prompt: reader outcome {outcome[0]} {outcome[1]!r}")


def drive() -> int:
    """POSIX only: the probe as a child on a pseudo-terminal, Ctrl+C typed into it."""
    import os
    import pty
    import time

    pid, fd = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, __file__])
    buffer = b""
    answers = {b"READY task": b"\x03", b"READY wait": b"half typed\x03", b"READY line": b"after\r",
               b"READY prompt": b"\x03", b"READY end": b"end\r"}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        for marker, keys in list(answers.items()):
            if marker in buffer:
                time.sleep(0.3)  # the probe is blocked in its wait by now
                os.write(fd, keys)
                del answers[marker]
    _, status = os.waitpid(pid, 0)
    sys.stdout.write(buffer.decode(errors="replace").replace("\r\n", "\n"))
    print(f"drive: child exit status {os.waitstatus_to_exitcode(status)}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--drive"]:
        sys.exit(drive())
    signal.signal(signal.SIGINT, handler)  # before asyncio.run: the runner then keeps it
    asyncio.run(main())
    say("exit 0")
