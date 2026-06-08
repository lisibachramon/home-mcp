import pytest

from home_mcp.tools.gh_tools import _kv_flags, _repo_args, _validate_repo


def test_valid_repo_accepted():
    _validate_repo("owner/name")
    _validate_repo("my-org/my.repo_1")
    _validate_repo(None)  # None means "current repo", allowed


@pytest.mark.parametrize("bad", ["noslash", "a/b/c", "owner/", "/name", "bad repo/x", "a/b;rm -rf"])
def test_invalid_repo_rejected(bad):
    with pytest.raises(ValueError):
        _validate_repo(bad)


def test_repo_args():
    assert _repo_args("owner/name") == ["-R", "owner/name"]
    assert _repo_args(None) == []


def test_kv_flags():
    assert _kv_flags("-f", {"a": "1", "b": "2"}) == ["-f", "a=1", "-f", "b=2"]
    assert _kv_flags("-f", None) == []
