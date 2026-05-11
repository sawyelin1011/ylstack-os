"""
YL StackOS — Safe shell execution utilities.
All system commands must go through this module.
Never use os.system() or subprocess with shell=True directly.
"""
import subprocess
import pathlib
import logging
import os
from typing import Generator

log = logging.getLogger(__name__)


class ShellError(Exception):
    """Raised when a shell command fails."""
    def __init__(self, cmd: list, returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"Command {cmd[0]!r} failed (rc={returncode}): {stderr[:200]}")


def run(args: list, timeout: int = 30, cwd: str | None = None,
        check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    """
    Run a command safely. No shell interpolation.

    Args:
        args: Command and arguments as a list. Never pass user input as a single string.
        timeout: Seconds before killing the process.
        cwd: Working directory.
        check: Raise ShellError on non-zero exit code.
        env: Environment variables (merged with os.environ if provided).

    Returns:
        CompletedProcess with stdout/stderr as strings.

    Raises:
        ShellError: If check=True and command exits non-zero.
        ValueError: If args is empty or contains None.
    """
    if not args:
        raise ValueError("args must not be empty")
    if any(a is None for a in args):
        raise ValueError("args must not contain None values")

    # Ensure all args are strings
    str_args = [str(a) for a in args]

    merged_env = None
    if env:
        merged_env = {**os.environ, **env}

    log.debug("run: %s", ' '.join(str_args))

    try:
        result = subprocess.run(
            str_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=merged_env,
            shell=False,  # NEVER shell=True
        )
    except subprocess.TimeoutExpired:
        raise ShellError(str_args, -1, f"Command timed out after {timeout}s")
    except FileNotFoundError:
        raise ShellError(str_args, -1, f"Command not found: {str_args[0]!r}")

    if check and result.returncode != 0:
        raise ShellError(str_args, result.returncode, result.stderr)

    return result


def run_output(args: list, timeout: int = 30) -> str:
    """Run a command and return stdout as a stripped string."""
    return run(args, timeout=timeout).stdout.strip()


def run_stream(args: list, timeout: int = 300) -> Generator[str, None, None]:
    """
    Run a command and yield stdout lines as they arrive.
    Used for SSE streaming (container create, system commands).
    """
    if not args:
        raise ValueError("args must not be empty")

    str_args = [str(a) for a in args]
    log.debug("run_stream: %s", ' '.join(str_args))

    proc = subprocess.Popen(
        str_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=False,
    )

    try:
        for line in iter(proc.stdout.readline, ''):
            yield line.rstrip()
        proc.stdout.close()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        yield f"[ERROR] Command timed out after {timeout}s"


def safe_path(user_input: str, allowed_base: str) -> pathlib.Path:
    """
    Resolve a user-supplied path relative to allowed_base.
    Raises ValueError on path traversal attempts.

    Example:
        safe_path("ubuntu-dev", "/container/list")
        → Path("/container/list/ubuntu-dev")

        safe_path("../../etc/passwd", "/container/list")
        → raises ValueError
    """
    base = pathlib.Path(allowed_base).resolve()
    # Strip leading slashes to prevent absolute path injection
    clean_input = user_input.lstrip('/')
    target = (base / clean_input).resolve()

    if not str(target).startswith(str(base) + os.sep) and target != base:
        raise ValueError(
            f"Path traversal attempt blocked: {user_input!r} "
            f"resolves outside {allowed_base!r}"
        )
    return target


def which(cmd: str) -> str | None:
    """Return full path of command if it exists, else None."""
    import shutil
    return shutil.which(cmd)
