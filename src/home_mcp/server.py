"""Assemble the FastMCP app, wrap it with auth, and run it under uvicorn."""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse

from mcp.server.fastmcp import FastMCP

from . import SERVER_NAME, __version__
from .audit import audit_log, configure_audit
from .auth import AuthMiddleware, SecurityHeadersMiddleware
from .config import ConfigError, Settings
from .registry import ToolRegistry
from .tools import compose_tools, docker_tools, gh_tools, system_tools

INSTRUCTIONS = """\
home-mcp gives you control of a home server. Call `server_info` first to see
which capabilities (docker, compose/deploy, gh) are enabled and which deploy
projects exist.

- Docker tools (docker_*) inspect and control all containers, images, networks
  and volumes, including exec, run, remove and prune.
- Deploy tools (compose_*, deploy, git_*) manage docker compose stacks in
  configured project directories.
- GitHub tools (gh_*) read and control GitHub via the gh CLI, including
  gh_api and gh_command for anything not covered by a dedicated tool.

Destructive actions are permitted. The server refuses to stop or remove its own
container unless protect_self is disabled. Every call is audit-logged.
"""


def build_mcp(settings: Settings) -> FastMCP:
    mcp = FastMCP(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=False,
    )
    mcp.settings.streamable_http_path = settings.streamable_path

    reg = ToolRegistry(mcp)
    system_tools.register(reg, settings)
    if settings.enable_docker:
        docker_tools.register(reg, settings)
    if settings.enable_compose:
        compose_tools.register(reg, settings)
    if settings.enable_gh:
        gh_tools.register(reg, settings)
    return mcp


async def _health(_request):
    return JSONResponse({"status": "ok", "server": SERVER_NAME, "version": __version__})


def build_app(settings: Settings):
    """Return the fully wrapped ASGI app (auth + security headers + MCP)."""
    mcp = build_mcp(settings)
    app = mcp.streamable_http_app()
    app.add_route("/healthz", _health, methods=["GET"])
    # Outermost first: auth runs before anything else; /healthz is exempt.
    return AuthMiddleware(SecurityHeadersMiddleware(app), settings)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass


def main() -> None:
    import uvicorn

    _load_dotenv()
    try:
        settings = Settings.from_env()
        settings.validate()
    except ConfigError as exc:
        raise SystemExit(f"home-mcp configuration error: {exc}")

    configure_audit(settings.audit_log_file, settings.log_level)
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    app = build_app(settings)

    audit_log(
        "server_start",
        version=__version__,
        host=settings.host,
        port=settings.port,
        path=settings.streamable_path,
        capabilities=settings.capabilities(),
        token_count=len(settings.tokens),
        ip_allowlist=list(settings.ip_allowlist),
        protect_self=settings.protect_self,
    )

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        proxy_headers=settings.trust_proxy,
        forwarded_allow_ips="*" if settings.trust_proxy else None,
    )


if __name__ == "__main__":
    main()
