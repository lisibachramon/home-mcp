"""Tool registration helper.

Each blocking implementation function is registered as an *async* MCP tool whose
body runs in a worker thread. This keeps slow Docker / git / gh operations from
blocking the event loop (and the streamed responses), and records a redacted
audit entry for every call.
"""

from __future__ import annotations

import functools
import time
from typing import Callable

import anyio

from mcp.server.fastmcp import FastMCP

from .audit import audit_log


class ToolRegistry:
    def __init__(self, mcp: FastMCP):
        self.mcp = mcp

    def add(self, fn: Callable, name: str | None = None) -> Callable:
        tool_name = name or fn.__name__

        @functools.wraps(fn)
        async def wrapper(**kwargs):
            started = time.perf_counter()
            try:
                result = await anyio.to_thread.run_sync(
                    functools.partial(fn, **kwargs)
                )
            except Exception as exc:
                audit_log(
                    "tool_call",
                    tool=tool_name,
                    args=kwargs,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                raise
            audit_log(
                "tool_call",
                tool=tool_name,
                args=kwargs,
                status="ok",
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return result

        self.mcp.tool(name=tool_name)(wrapper)
        return fn
