"""Helpers for running external commands (docker compose, git, gh) safely.

Commands are always passed as an argument list and never through a shell, so
there is no shell-injection surface even for the raw passthrough tools.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Settings
from .security import truncate


def run_command(
    args: list[str],
    settings: Settings,
    cwd: str | Path | None = None,
    timeout: int | None = None,
    input_text: str | None = None,
) -> dict:
    """Run ``args`` (no shell) and return a structured, size-bounded result."""
    if not args:
        raise ValueError("Refusing to run an empty command")
    if not all(isinstance(a, str) for a in args):
        raise ValueError("All command arguments must be strings")

    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout or settings.command_timeout,
            input=input_text,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Command not found: {args[0]!r}. Is it installed in the server image?"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Command timed out after {timeout or settings.command_timeout}s: "
            f"{' '.join(args)}"
        ) from exc

    return {
        "command": args,
        "cwd": str(cwd) if cwd is not None else None,
        "exit_code": completed.returncode,
        "stdout": truncate(completed.stdout, settings),
        "stderr": truncate(completed.stderr, settings),
    }
