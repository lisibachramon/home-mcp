"""Lazy Docker client.

The client is created on first use so the server still starts (and can serve
``server_info`` / gh tools) even when the Docker socket is temporarily
unavailable. Connection problems surface as clear tool errors instead.
"""

from __future__ import annotations

import threading

import docker
from docker import DockerClient

from .config import Settings

_lock = threading.Lock()
_client: DockerClient | None = None


def get_client(settings: Settings) -> DockerClient:
    global _client
    with _lock:
        if _client is None:
            try:
                if settings.docker_host:
                    _client = docker.DockerClient(base_url=settings.docker_host)
                else:
                    _client = docker.from_env()
            except docker.errors.DockerException as exc:
                raise RuntimeError(
                    "Could not connect to Docker. Make sure the Docker socket is "
                    "mounted (e.g. -v /var/run/docker.sock:/var/run/docker.sock) and "
                    f"reachable. Underlying error: {exc}"
                ) from exc
        return _client


def reset_client() -> None:
    """Drop the cached client (used by tests)."""
    global _client
    with _lock:
        _client = None
