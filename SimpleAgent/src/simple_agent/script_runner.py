"""Run Python scripts belonging to discovered skills.

This confines the script path, not the script's actions: it runs with the
current user's permissions and environment.
"""

from __future__ import annotations

import asyncio
import locale
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any


def resolve_skill_script(skill: Any, relative_path: str) -> Path:
    """Resolve a Python file inside the selected skill, following symlinks."""
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("Script path must be a non-empty relative path")
    path = Path(relative_path)
    if path.is_absolute() or path.drive:
        raise ValueError("Script path must be relative to the skill directory")
    root = skill.path.parent.resolve(strict=True)
    try:
        resolved = (root / path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot resolve skill script: {exc}") from exc
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Script must be inside the skill directory")
    if resolved.suffix != ".py" or not resolved.is_file():
        raise ValueError("Script must be a Python (.py) file")
    return resolved


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    """Stop the script and, where possible, its subprocesses.

    Windows cannot identify a process tree using taskkill once the root has
    already exited. Descendants in that case may continue independently.
    """
    if os.name == "nt":
        # taskkill's tree operation is needed because Python's terminate only
        # stops the immediate child on Windows. It fails harmlessly if the root
        # process already exited.
        if process.returncode is None:
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(process.pid), "/T", "/F",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.wait()
            except OSError:
                pass
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    # A descendant may outlive its parent while retaining the output handles.
    # Close the read transports before waiting so that a cancelled drain task
    # cannot keep this session open indefinitely. asyncio has no public Process
    # API to close the pipe transports; the process transport owns them.
    for fd in (1, 2):
        pipe = process._transport.get_pipe_transport(fd)
        if pipe is not None:
            pipe.close()
    await process.wait()


async def run_skill_script(
    skill: Any,
    relative_path: str,
    args: list[str],
    *,
    timeout: float = 60,
    output_limit: int = 32768,
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    """Execute a skill script with bounded output and return its result.

    ``output_limit`` is a shared byte limit for stdout and stderr. Both pipes
    continue to be drained after the limit is reached to avoid deadlocks.
    """
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("Script arguments must be a list of strings")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout < float("inf"):
        raise ValueError("Script timeout must be a positive finite number")
    if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit < 1:
        raise ValueError("Script output limit must be a positive integer")

    script = resolve_skill_script(skill, relative_path)
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    env = os.environ.copy()
    # Use a portable default for redirected Python output, preserving any
    # explicit choice already made by the user.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(script), *args,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **options,
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    retained = 0
    truncated = False

    async def drain(stream: asyncio.StreamReader, name: str) -> None:
        nonlocal retained, truncated
        while chunk := await stream.read(8192):
            keep = min(len(chunk), max(0, output_limit - retained))
            buffers[name].extend(chunk[:keep])
            retained += keep
            if keep < len(chunk):
                truncated = True

    assert process.stdout is not None and process.stderr is not None
    waiters = [asyncio.create_task(process.wait()),
               asyncio.create_task(drain(process.stdout, "stdout")),
               asyncio.create_task(drain(process.stderr, "stderr"))]
    timed_out = False
    try:
        await asyncio.wait_for(asyncio.gather(*waiters), timeout)
    except TimeoutError:
        timed_out = True
        await _stop_process(process)
    except BaseException:
        await _stop_process(process)
        raise
    finally:
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)

    encoding = env["PYTHONIOENCODING"].partition(":")[0] or locale.getpreferredencoding(False)
    try:
        stdout = buffers["stdout"].decode(encoding, errors="replace")
        stderr = buffers["stderr"].decode(encoding, errors="replace")
    except LookupError:
        stdout = buffers["stdout"].decode("utf-8", errors="replace")
        stderr = buffers["stderr"].decode("utf-8", errors="replace")
    return {
        "exit_code": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "truncated": truncated,
    }
