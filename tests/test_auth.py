import ipaddress

from home_mcp.auth import _ip_allowed, is_authorized

TOKENS = ("supersecrettoken-aaaaaaaaaaaaaaaaaaaa", "second-token-bbbbbbbbbbbbbbbbbbbb")


def test_valid_bearer_token():
    assert is_authorized(f"Bearer {TOKENS[0]}", TOKENS) is True


def test_second_token_also_valid():
    assert is_authorized(f"Bearer {TOKENS[1]}", TOKENS) is True


def test_bearer_is_case_insensitive_scheme():
    assert is_authorized(f"bearer {TOKENS[0]}", TOKENS) is True


def test_wrong_token_rejected():
    assert is_authorized("Bearer nope", TOKENS) is False


def test_missing_header_rejected():
    assert is_authorized(None, TOKENS) is False
    assert is_authorized("", TOKENS) is False


def test_non_bearer_scheme_rejected():
    assert is_authorized(f"Basic {TOKENS[0]}", TOKENS) is False
    assert is_authorized(TOKENS[0], TOKENS) is False  # raw token, no scheme


def test_empty_token_after_bearer_rejected():
    assert is_authorized("Bearer ", TOKENS) is False


def test_ip_allowlist_empty_allows_all():
    assert _ip_allowed("203.0.113.5", []) is True


def test_ip_allowlist_matches_cidr():
    nets = [ipaddress.ip_network("100.64.0.0/10")]  # tailscale range
    assert _ip_allowed("100.100.1.2", nets) is True
    assert _ip_allowed("203.0.113.5", nets) is False


def test_ip_allowlist_blocks_unknown_when_set():
    nets = [ipaddress.ip_network("10.0.0.0/8")]
    assert _ip_allowed(None, nets) is False
    assert _ip_allowed("not-an-ip", nets) is False
