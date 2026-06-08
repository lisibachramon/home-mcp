#!/usr/bin/env python3
"""Print a strong random bearer token for HOME_MCP_TOKEN."""

import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(48))
