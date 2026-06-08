import pytest

from home_mcp.config import ConfigError, Settings

STRONG = "x" * 40


def test_requires_token():
    settings = Settings.from_env({})
    with pytest.raises(ConfigError, match="No bearer token"):
        settings.validate()


def test_rejects_weak_token():
    settings = Settings.from_env({"HOME_MCP_TOKEN": "short"})
    with pytest.raises(ConfigError, match="too short"):
        settings.validate()


def test_weak_token_override():
    settings = Settings.from_env(
        {"HOME_MCP_TOKEN": "short", "HOME_MCP_ALLOW_WEAK_TOKEN": "true"}
    )
    settings.validate()  # should not raise


def test_strong_token_validates():
    settings = Settings.from_env({"HOME_MCP_TOKEN": STRONG})
    settings.validate()
    assert settings.tokens == (STRONG,)


def test_multiple_tokens_merged_and_deduped():
    settings = Settings.from_env(
        {"HOME_MCP_TOKEN": STRONG, "HOME_MCP_TOKENS": f"{STRONG}, {'y' * 40}"}
    )
    assert settings.tokens == (STRONG, "y" * 40)


def test_projects_json():
    settings = Settings.from_env(
        {"HOME_MCP_TOKEN": STRONG, "HOME_MCP_PROJECTS": '{"blog": "/srv/blog"}'}
    )
    assert settings.projects == {"blog": "/srv/blog"}


def test_projects_csv():
    settings = Settings.from_env(
        {"HOME_MCP_TOKEN": STRONG, "HOME_MCP_PROJECTS": "blog=/srv/blog, api=/srv/api"}
    )
    assert settings.projects == {"blog": "/srv/blog", "api": "/srv/api"}


def test_projects_invalid_csv():
    with pytest.raises(ConfigError):
        Settings.from_env({"HOME_MCP_TOKEN": STRONG, "HOME_MCP_PROJECTS": "noequals"})


def test_bool_and_int_parsing():
    settings = Settings.from_env(
        {
            "HOME_MCP_TOKEN": STRONG,
            "HOME_MCP_ALLOW_ANY_PATH": "yes",
            "HOME_MCP_PROTECT_SELF": "off",
            "HOME_MCP_PORT": "9000",
        }
    )
    assert settings.allow_any_path is True
    assert settings.protect_self is False
    assert settings.port == 9000


def test_bad_bool_raises():
    with pytest.raises(ConfigError):
        Settings.from_env({"HOME_MCP_TOKEN": STRONG, "HOME_MCP_PROTECT_SELF": "maybe"})


def test_ip_allowlist_parsing():
    settings = Settings.from_env(
        {"HOME_MCP_TOKEN": STRONG, "HOME_MCP_IP_ALLOWLIST": "10.0.0.0/8, 100.64.0.0/10"}
    )
    assert settings.ip_allowlist == ("10.0.0.0/8", "100.64.0.0/10")
