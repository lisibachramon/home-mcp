import pytest

from home_mcp.config import Settings
from home_mcp.security import find_compose_file, resolve_project, truncate

STRONG = "x" * 40


def _settings(**over):
    env = {"HOME_MCP_TOKEN": STRONG}
    env.update(over)
    return Settings.from_env(env)


def test_resolve_known_project(tmp_path):
    settings = _settings(HOME_MCP_PROJECTS=f'{{"app": "{tmp_path}"}}')
    assert resolve_project("app", settings) == tmp_path.resolve()


def test_unknown_project_rejected_by_default(tmp_path):
    settings = _settings()
    with pytest.raises(ValueError, match="Unknown project"):
        resolve_project(str(tmp_path), settings)


def test_any_path_allows_existing_dir(tmp_path):
    settings = _settings(HOME_MCP_ALLOW_ANY_PATH="true")
    assert resolve_project(str(tmp_path), settings) == tmp_path.resolve()


def test_any_path_rejects_missing_dir():
    settings = _settings(HOME_MCP_ALLOW_ANY_PATH="true")
    with pytest.raises(ValueError, match="does not exist"):
        resolve_project("/nonexistent/path/xyz", settings)


def test_find_compose_file(tmp_path):
    assert find_compose_file(tmp_path) is None
    (tmp_path / "docker-compose.yml").write_text("services: {}")
    assert find_compose_file(tmp_path).name == "docker-compose.yml"


def test_truncate_under_limit():
    settings = _settings(HOME_MCP_MAX_OUTPUT="100")
    assert truncate("hello", settings) == "hello"


def test_truncate_over_limit():
    settings = _settings(HOME_MCP_MAX_OUTPUT="10")
    out = truncate("a" * 50, settings)
    assert out.startswith("a" * 10)
    assert "truncated" in out
