#!/usr/bin/env python
"""Keep the E*TRADE OAuth access token from going idle.

E*TRADE access tokens become "inactive" after 2 hours of no activity.
A simple keepalive — call `renew_access_token` every ~90 minutes during
market hours — keeps the token usable without the full OAuth dance.

Important: this does NOT extend the daily midnight-ET hard expiry.
Tokens still need a full re-auth (`etrade-auth`) once a day.

Usage from cron (every 90 minutes, 06:00–17:00 PT):

    0,30 6-17 * * 1-5  /path/to/venv/bin/python /path/to/scripts/keepalive.py

Exit codes:
    0  — token renewed (or was already active)
    1  — renewal failed (probably means full re-auth is needed)
"""
from __future__ import annotations

import os
import sys

from pyetrade import ETradeAccessManager

from etrade_mcp.keychain import get_credentials


def main() -> int:
    try:
        creds = get_credentials()
    except RuntimeError as e:
        print(f"[keepalive] credentials error: {e}", file=sys.stderr)
        return 1

    dev = os.environ.get("ETRADE_MODE", "prod").lower() == "sandbox"
    manager = ETradeAccessManager(
        creds["consumer-key"],
        creds["consumer-secret"],
        creds["oauth-token"],
        creds["oauth-token-secret"],
        dev=dev,
    )

    try:
        manager.renew_access_token()
    except Exception as e:
        print(
            f"[keepalive] renew failed: {e}\n"
            "  This usually means the daily midnight-ET expiry has hit.\n"
            "  Run `uv run etrade-auth` to re-authenticate.",
            file=sys.stderr,
        )
        return 1

    print("[keepalive] token renewed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
