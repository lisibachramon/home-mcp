"""Bearer-token authentication and optional IP allowlisting.

Implemented as a small ASGI middleware that inspects request headers without
touching the request/response body, so it never interferes with the streamed
(SSE) MCP responses.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
from typing import Iterable

from .audit import audit_log
from .config import Settings

_HEALTH_PATH = "/healthz"


def is_authorized(auth_header: str | None, tokens: Iterable[str]) -> bool:
    """Constant-time check of an ``Authorization: Bearer <token>`` header.

    Every configured token is compared even after a match is found, so the work
    done does not depend on which token matched.
    """
    if not auth_header:
        return False
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    presented = parts[1].strip()
    if not presented:
        return False
    matched = False
    for token in tokens:
        if hmac.compare_digest(presented, token):
            matched = True
    return matched


def _client_ip(scope: dict, headers: dict[bytes, bytes], trust_proxy: bool) -> str | None:
    if trust_proxy:
        xff = headers.get(b"x-forwarded-for")
        if xff:
            return xff.decode("latin-1").split(",")[0].strip()
        real = headers.get(b"x-real-ip")
        if real:
            return real.decode("latin-1").strip()
    client = scope.get("client")
    if client:
        return client[0]
    return None


def _ip_allowed(client_ip: str | None, networks: list) -> bool:
    if not networks:
        return True
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


class AuthMiddleware:
    """ASGI middleware enforcing bearer auth (and optional IP allowlist)."""

    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self.networks = []
        for entry in settings.ip_allowlist:
            try:
                self.networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError as exc:
                raise ValueError(f"Invalid HOME_MCP_IP_ALLOWLIST entry {entry!r}: {exc}")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if path == _HEALTH_PATH and method in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        client_ip = _client_ip(scope, headers, self.settings.trust_proxy)

        if not _ip_allowed(client_ip, self.networks):
            audit_log("auth_denied", reason="ip_not_allowed", client_ip=client_ip, path=path)
            await self._reject(send, 403, "Forbidden")
            return

        auth_header = headers.get(b"authorization")
        auth_str = auth_header.decode("latin-1") if auth_header else None
        if not is_authorized(auth_str, self.settings.tokens):
            audit_log("auth_denied", reason="bad_token", client_ip=client_ip, path=path)
            await self._reject(send, 401, "Unauthorized")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if status == 401:
            headers.append((b"www-authenticate", b'Bearer realm="home-mcp"'))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Adds conservative security/cache headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"referrer-policy", b"no-referrer"))
                headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_wrapper)
