"""Server introspection tools so a connecting session can orient itself."""

from __future__ import annotations

import shutil

from .. import __version__
from ..config import Settings
from ..docker_client import get_client
from ..registry import ToolRegistry


def register(reg: ToolRegistry, settings: Settings) -> None:
    def server_info() -> dict:
        """Report server version, enabled capabilities, deploy projects and connectivity.

        Call this first to discover what this home-mcp instance can do.
        """
        docker_status: dict = {"enabled": settings.enable_docker}
        if settings.enable_docker:
            try:
                version = get_client(settings).version()
                docker_status["connected"] = True
                docker_status["server_version"] = version.get("Version")
            except Exception as exc:  # surface but don't fail the whole call
                docker_status["connected"] = False
                docker_status["error"] = str(exc)

        gh_status = {"enabled": settings.enable_gh}
        if settings.enable_gh:
            gh_status["binary_found"] = shutil.which(settings.gh_bin) is not None

        return {
            "name": "home-mcp",
            "version": __version__,
            "capabilities": settings.capabilities(),
            "docker": docker_status,
            "gh": gh_status,
            "deploy": {
                "projects": sorted(settings.projects),
                "allow_any_path": settings.allow_any_path,
            },
            "guards": {
                "protect_self": settings.protect_self,
                "ip_allowlist_enabled": bool(settings.ip_allowlist),
            },
        }

    reg.add(server_info)
