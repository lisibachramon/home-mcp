from home_mcp.audit import redact


def test_redacts_sensitive_keys():
    out = redact({"token": "abc", "password": "p", "name": "ok"})
    assert out["token"] == "***redacted***"
    assert out["password"] == "***redacted***"
    assert out["name"] == "ok"


def test_redaction_is_case_and_separator_insensitive():
    out = redact({"GH_TOKEN": "x", "Api-Key": "y", "authorization": "z"})
    assert out["GH_TOKEN"] == "***redacted***"
    assert out["Api-Key"] == "***redacted***"
    assert out["authorization"] == "***redacted***"


def test_does_not_redact_innocuous_lookalikes():
    out = redact({"author": "octocat", "headRefName": "feature"})
    assert out["author"] == "octocat"
    assert out["headRefName"] == "feature"


def test_truncates_long_strings():
    out = redact("a" * 1000)
    assert out.endswith("…(truncated)")
    assert len(out) < 1000


def test_nested_structures():
    out = redact({"outer": {"secret": "s", "ok": [1, 2, {"password": "p"}]}})
    assert out["outer"]["secret"] == "***redacted***"
    assert out["outer"]["ok"][2]["password"] == "***redacted***"
