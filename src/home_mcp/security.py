"""Path scoping and output-size helpers shared by the tool modules."""

from __future__ import annotations

from pathlib import Path

from .config import Settings

_COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)


def resolve_project(name_or_path: str, settings: Settings) -> Path:
    """Resolve a deploy target to an existing directory, honoring the allowlist.

    A configured project name always wins. A raw filesystem path is only accepted
    when ``HOME_MCP_ALLOW_ANY_PATH`` is enabled, which keeps a leaked token from
    being able to run compose against arbitrary directories.
    """
    if name_or_path in settings.projects:
        base = Path(settings.projects[name_or_path])
    elif settings.allow_any_path:
        base = Path(name_or_path).expanduser()
    else:
        known = ", ".join(sorted(settings.projects)) or "(none configured)"
        raise ValueError(
            f"Unknown project {name_or_path!r}. Configured projects: {known}. "
            "Set HOME_MCP_ALLOW_ANY_PATH=true to allow arbitrary directory paths."
        )

    resolved = base.resolve()
    if not resolved.is_dir():
        raise ValueError(f"Project directory does not exist: {resolved}")
    return resolved


def find_compose_file(project_dir: Path) -> Path | None:
    for name in _COMPOSE_FILENAMES:
        candidate = project_dir / name
        if candidate.is_file():
            return candidate
    return None


def truncate(text: str | None, settings: Settings) -> str:
    if not text:
        return ""
    limit = settings.max_output_chars
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f"\n…[truncated {omitted} chars]"
