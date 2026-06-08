"""Runtime configuration, loaded entirely from environment variables.

The server fails closed: it refuses to start without at least one sufficiently
strong bearer token, so it can never accidentally come up wide open.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_PORT = 8848
DEFAULT_PATH = "/mcp"
DEFAULT_MIN_TOKEN_LEN = 24
DEFAULT_CMD_TIMEOUT = 300
DEFAULT_MAX_OUTPUT = 100_000

_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n", ""}


class ConfigError(RuntimeError):
    """Raised when the environment is missing or has invalid configuration."""


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    raise ConfigError(f"{name} must be a boolean (got {raw!r})")


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer (got {raw!r})") from exc


def _split_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _parse_projects(raw: str | None) -> dict[str, str]:
    """Parse HOME_MCP_PROJECTS as either JSON ``{name: path}`` or ``name=path,...``."""
    if not raw or not raw.strip():
        return {}
    raw = raw.strip()
    projects: dict[str, str] = {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"HOME_MCP_PROJECTS is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("HOME_MCP_PROJECTS JSON must be an object {name: path}")
        items = data.items()
    else:
        items = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                raise ConfigError(
                    f"HOME_MCP_PROJECTS entry {part!r} must be 'name=path'"
                )
            name, path = part.split("=", 1)
            items.append((name, path))
    for name, path in items:
        name = str(name).strip()
        path = str(path).strip()
        if not name or not path:
            raise ConfigError("HOME_MCP_PROJECTS entries need a non-empty name and path")
        projects[name] = str(Path(path).expanduser())
    return projects


@dataclass
class Settings:
    tokens: tuple[str, ...]
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    streamable_path: str = DEFAULT_PATH
    log_level: str = "info"
    audit_log_file: str | None = None

    docker_host: str | None = None
    projects: dict[str, str] = field(default_factory=dict)
    allow_any_path: bool = False
    protect_self: bool = True
    self_container: str | None = None

    ip_allowlist: tuple[str, ...] = ()
    trust_proxy: bool = True
    # JSON responses (vs SSE) play nicest behind a buffering proxy like nginx-proxy.
    json_response: bool = True

    enable_docker: bool = True
    enable_compose: bool = True
    enable_gh: bool = True

    gh_bin: str = "gh"
    command_timeout: int = DEFAULT_CMD_TIMEOUT
    max_output_chars: int = DEFAULT_MAX_OUTPUT

    allow_weak_token: bool = False
    min_token_length: int = DEFAULT_MIN_TOKEN_LEN

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env

        tokens: list[str] = []
        single = env.get("HOME_MCP_TOKEN")
        if single and single.strip():
            tokens.append(single.strip())
        for tok in _split_csv(env.get("HOME_MCP_TOKENS")):
            tokens.append(tok)
        # de-duplicate while preserving order
        seen: set[str] = set()
        unique_tokens = tuple(t for t in tokens if not (t in seen or seen.add(t)))

        return cls(
            tokens=unique_tokens,
            host=env.get("HOME_MCP_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_get_int(env, "HOME_MCP_PORT", DEFAULT_PORT),
            streamable_path=env.get("HOME_MCP_PATH", DEFAULT_PATH).strip() or DEFAULT_PATH,
            log_level=env.get("HOME_MCP_LOG_LEVEL", "info").strip().lower() or "info",
            audit_log_file=(env.get("HOME_MCP_AUDIT_LOG") or "").strip() or None,
            docker_host=(env.get("DOCKER_HOST") or "").strip() or None,
            projects=_parse_projects(env.get("HOME_MCP_PROJECTS")),
            allow_any_path=_get_bool(env, "HOME_MCP_ALLOW_ANY_PATH", False),
            protect_self=_get_bool(env, "HOME_MCP_PROTECT_SELF", True),
            self_container=(env.get("HOME_MCP_SELF_CONTAINER") or "").strip() or None,
            ip_allowlist=_split_csv(env.get("HOME_MCP_IP_ALLOWLIST")),
            trust_proxy=_get_bool(env, "HOME_MCP_TRUST_PROXY", True),
            json_response=_get_bool(env, "HOME_MCP_JSON_RESPONSE", True),
            enable_docker=_get_bool(env, "HOME_MCP_ENABLE_DOCKER", True),
            enable_compose=_get_bool(env, "HOME_MCP_ENABLE_COMPOSE", True),
            enable_gh=_get_bool(env, "HOME_MCP_ENABLE_GH", True),
            gh_bin=env.get("HOME_MCP_GH_BIN", "gh").strip() or "gh",
            command_timeout=_get_int(env, "HOME_MCP_CMD_TIMEOUT", DEFAULT_CMD_TIMEOUT),
            max_output_chars=_get_int(env, "HOME_MCP_MAX_OUTPUT", DEFAULT_MAX_OUTPUT),
            allow_weak_token=_get_bool(env, "HOME_MCP_ALLOW_WEAK_TOKEN", False),
            min_token_length=_get_int(env, "HOME_MCP_MIN_TOKEN_LEN", DEFAULT_MIN_TOKEN_LEN),
        )

    def validate(self) -> None:
        """Raise ConfigError unless the server is safe to start."""
        if not self.tokens:
            raise ConfigError(
                "No bearer token configured. Set HOME_MCP_TOKEN (or HOME_MCP_TOKENS) "
                "to a long random secret. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if not self.allow_weak_token:
            weak = [t for t in self.tokens if len(t) < self.min_token_length]
            if weak:
                raise ConfigError(
                    f"Bearer token is too short (minimum {self.min_token_length} chars). "
                    "Use a longer secret, or set HOME_MCP_ALLOW_WEAK_TOKEN=true to override "
                    "(not recommended)."
                )
        if not self.streamable_path.startswith("/"):
            raise ConfigError("HOME_MCP_PATH must start with '/'")

    def capabilities(self) -> dict[str, bool]:
        return {
            "docker": self.enable_docker,
            "compose": self.enable_compose,
            "gh": self.enable_gh,
        }
