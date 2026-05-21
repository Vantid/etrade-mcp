import getpass
import os
from pathlib import Path

import pyetrade

from etrade_mcp.keychain import get_credentials, set_consumer_credentials, set_oauth_tokens

# Resolve the keepalive script path relative to this file so the post-auth
# instructions print an absolute path the user can drop into cron.
_KEEPALIVE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "keepalive.py"
)


def _print_keepalive_instructions() -> None:
    """Show the user how to keep the token from going idle, plus the
    daily-reauth caveat. Printed after a successful auth flow."""
    sandbox = os.environ.get("ETRADE_MODE", "prod").lower() == "sandbox"
    mode_env = "ETRADE_MODE=sandbox " if sandbox else ""
    keepalive = str(_KEEPALIVE_PATH)

    print("\n" + "─" * 64)
    print("Keeping the token alive")
    print("─" * 64)
    print(
        "E*TRADE access tokens have two expiry tiers:\n"
        "  • 2-hour idle  → recoverable via the `keepalive` script below\n"
        "  • Daily midnight ET → requires re-running `etrade-auth` (full\n"
        "    OAuth dance, no automation possible)"
    )
    print("\nManual keepalive (run any time before the 2-hour idle hits):")
    print(f"  {mode_env}uv run python {keepalive}")
    print("\nAutomated keepalive — Linux cron (every 90 min, market hours):")
    print(
        "  0,30 6-17 * * 1-5  cd "
        + str(_KEEPALIVE_PATH.parent.parent)
        + f" && {mode_env}uv run python scripts/keepalive.py >> ~/.etrade-keepalive.log 2>&1"
    )
    print("\nAutomated keepalive — macOS launchd:")
    print("  See README.md → 'Daily cron sync' section for a plist template.")
    print(
        "\nIf the keepalive starts failing with `token_rejected`, the daily\n"
        "midnight-ET expiry hit — re-run `etrade-auth` to mint a fresh token."
    )
    print("─" * 64)


def main():
    # Check for existing consumer credentials
    consumer_key = None
    consumer_secret = None
    try:
        creds = get_credentials()
        consumer_key = creds["consumer-key"]
        consumer_secret = creds["consumer-secret"]
        print(f"Found existing consumer key: {consumer_key[:8]}...")
        reuse = input("Reuse existing consumer credentials? [Y/n]: ").strip().lower()
        if reuse == "n":
            consumer_key = None
            consumer_secret = None
    except RuntimeError:
        pass

    if consumer_key is None:
        consumer_key = input("Enter consumer key: ").strip()
        # Mask the secret — it's keyboard-paste-friendly (no echo) so
        # shoulder-surfing and terminal scrollback both miss it.
        consumer_secret = getpass.getpass("Enter consumer secret: ").strip()

    set_consumer_credentials(consumer_key, consumer_secret)

    # OAuth flow
    oauth = pyetrade.ETradeOAuth(consumer_key, consumer_secret)
    request_token = oauth.get_request_token()
    print(f"\nAuthorize this app at:\n{request_token}")
    verifier = input("\nEnter verification code: ").strip()
    tokens = oauth.get_access_token(verifier)

    set_oauth_tokens(tokens["oauth_token"], tokens["oauth_token_secret"])
    print("\nCredentials stored in OS keychain (service: etrade-mcp).")

    _print_keepalive_instructions()


if __name__ == "__main__":
    main()
