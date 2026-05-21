#!/usr/bin/env python
"""Daily E*TRADE → WealthWatcher sync (cron-friendly).

Fetches transactions since a given date and prints them as a JSON
object — `{rows, terminal_events, errors}` — ready to feed into
WealthWatcher's `import_brokerage_transactions` MCP tool.

Designed to run unattended from cron / launchd / systemd. Bypasses the
MCP protocol entirely (talks straight to the E*TRADE client) so there's
no LLM in the hot path.

Usage:

    # Default: print yesterday's transactions to stdout.
    python scripts/daily_sync.py

    # Custom window:
    python scripts/daily_sync.py --since 2026-05-15 --until 2026-05-21

    # Write to a file instead of stdout:
    python scripts/daily_sync.py --output /tmp/etrade-2026-05-21.json

    # Hand off to a Claude Code headless run (sample consumer):
    python scripts/daily_sync.py | \\
        claude --print "Import this E*TRADE data into WealthWatcher."

Exit codes:
    0  — success (rows may still be empty)
    1  — runtime failure (missing creds, network, etc.)
    2  — partial success: rows produced but at least one row error

OAuth caveat: E*TRADE tokens expire daily at midnight US Eastern. This
script CANNOT recover from that automatically — re-run `etrade-auth`
once per day manually before kicking off your cron schedule. See the
"Daily cron sync" section of the README.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from etrade_mcp.etrade_client import ETradeClient
from etrade_mcp.wealthwatcher import (
    map_transaction_to_import_row,
    split_terminal_events,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--since",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=1),
        help="Start date (YYYY-MM-DD). Default: yesterday.",
    )
    p.add_argument(
        "--until",
        type=date.fromisoformat,
        default=date.today(),
        help="End date (YYYY-MM-DD). Default: today.",
    )
    p.add_argument(
        "--output",
        type=Path,
        help="Write JSON to this path instead of stdout.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.since > args.until:
        print(
            f"[daily_sync] --since ({args.since}) must be <= --until ({args.until})",
            file=sys.stderr,
        )
        return 1

    try:
        client = ETradeClient()
    except RuntimeError as e:
        print(f"[daily_sync] credentials error: {e}", file=sys.stderr)
        return 1

    print(
        f"[daily_sync] fetching transactions {args.since} → {args.until}",
        file=sys.stderr,
    )
    try:
        txns = client.get_all_transactions(start_date=args.since, end_date=args.until)
    except Exception as e:
        print(f"[daily_sync] fetch failed: {e}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    terminal_events: list[dict] = []
    errors: list[dict] = list(txns.errors)

    for txn in txns.rows:
        try:
            terminal = split_terminal_events(txn)
            if terminal is not None:
                terminal_events.append(terminal)
                continue
            row = map_transaction_to_import_row(txn)
            if row is not None:
                rows.append(row)
        except Exception as e:
            errors.append({
                "account_id_key": txn.get("account_id_key"),
                "transaction_id": txn.get("transaction_id"),
                "context": "transaction_mapping",
                "error": str(e),
            })

    payload = {
        "since": args.since.isoformat(),
        "until": args.until.isoformat(),
        "rows": rows,
        "terminal_events": terminal_events,
        "errors": errors,
    }
    output = json.dumps(payload, indent=2, default=str)

    if args.output:
        # Output contains real transaction history — restrict to owner only.
        args.output.touch(mode=0o600, exist_ok=True)
        args.output.write_text(output + "\n")
        args.output.chmod(0o600)
        print(
            f"[daily_sync] wrote {len(rows)} rows + "
            f"{len(terminal_events)} terminal events to {args.output}",
            file=sys.stderr,
        )
    else:
        print(output)

    if errors:
        print(
            f"[daily_sync] {len(errors)} per-row error(s); see `errors` in output.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
