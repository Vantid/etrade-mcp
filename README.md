# etrade-mcp

An [MCP server](https://modelcontextprotocol.io/) for E\*TRADE. Lets any
MCP-capable agent (Claude Desktop, Claude Code, Cursor, etc.) read your
brokerage data — positions, lots, transactions, balances, quotes — and
optionally feed it into [WealthWatcher](https://vantid.money) via that
project's `import_brokerage_transactions` MCP tool.

> **Read-only.** This server has no trading endpoints. It reads positions,
> lots, transactions, balances, and quotes. Nothing else.

## What it does

Two layers of tools:

**Raw E\*TRADE reads** — useful for any client:
- `get_portfolio` — all positions across all accounts
- `get_lots` — per-lot cost basis (stocks + options)
- `get_balance` — account balances (cash, margin, total value)
- `get_transactions(start_date, end_date)` — transactions in a date range
- `get_quote(symbols)` — real-time quotes (stocks + options via OSI key)

**WealthWatcher-shaped composites** — output is pre-shaped for WealthWatcher's
`import_brokerage_transactions` schema, so the LLM can pipe one tool's
output directly into the next without translation:
- `get_holdings_for_import` — current holdings as importable rows (one per
  position, including options with OSI key + broker IV)
- `get_transactions_for_import(start_date, end_date)` — transactions as
  importable rows, with terminal events (Expiration/Assignment/Exercise)
  split out for separate handling
- `get_daily_changes(since)` — delta since a timestamp, for incremental
  daily sync

## Install

Requires Python 3.11+. Recommended setup with [`uv`](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Vantid/etrade-mcp
cd etrade-mcp
uv sync
```

Get an E\*TRADE consumer key:

1. Sign in to [developer.etrade.com](https://developer.etrade.com).
2. Apply for production API access (sandbox keys also work — see [Sandbox mode](#sandbox-mode)).
3. Copy your consumer key + consumer secret.

Run the one-time auth flow:

```bash
uv run etrade-auth
```

It will prompt for your consumer key/secret, open your browser to E\*TRADE's
authorization page, ask for the verification code, and store everything in
your OS keychain (Keychain on macOS, libsecret on Linux, Credential Manager
on Windows). Credentials never touch disk.

## Use with Claude Desktop / Claude Code

Add to your MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS, or `.mcp.json` for Claude Code):

```json
{
  "mcpServers": {
    "etrade": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/etrade-mcp", "run", "etrade-mcp"]
    }
  }
}
```

Restart Claude. Ask: *"What are my E\*TRADE holdings?"*

## Use with WealthWatcher

If you also run the WealthWatcher MCP, point both at the same Claude
session. The composite tools return rows pre-shaped for WealthWatcher's
`import_brokerage_transactions`:

```
You:    Import my latest E*TRADE transactions into WealthWatcher.
LLM:    [calls etrade.get_transactions_for_import]
        [pipes 47 rows + 2 terminal events directly into
         wealthwatcher.import_brokerage_transactions]
        Done — created 5 new assets, recorded 47 transactions.
        Routed 2 terminal events (1 expiration, 1 exercise) to
        update_asset with status="expired"/"exercised".
```

## Ad-hoc resync after a gap

If you've been away for a while and want the LLM to "import everything I'm
missing," the right pattern is:

1. **Ask WealthWatcher for the watermark.** WealthWatcher exposes a
   `get_latest_transaction_date` MCP tool that returns the most recent
   transaction date for a given account / asset type / source. That's
   the only trustworthy "what's already synced" signal — etrade-mcp is
   intentionally stateless.
2. **Fetch from etrade-mcp starting at that date** (or one day earlier,
   for safety overlap).
3. **Pipe into `import_brokerage_transactions`.** WealthWatcher's
   importer dedups by `(symbol, date, amount)` and `osiKey` for options,
   so any overlap from the safety window is skipped cleanly.

Example conversation:

```
You:    Import any missing E*TRADE transactions into WealthWatcher.
LLM:    [calls wealthwatcher.get_latest_transaction_date(
         account="E*TRADE", source="import")]
        → { latestDate: "2026-05-18", count: 47, ... }
        [calls etrade.get_transactions_for_import(
         start_date="2026-05-17")]  # 1-day overlap for safety
        → { rows: [9 new], terminal_events: [1], errors: [] }
        [calls wealthwatcher.import_brokerage_transactions(...)]
        → 9 new transactions imported (3 skipped as duplicates).
        Routed 1 option expiration via update_asset.
```

Why this works without per-account state on the E\*TRADE side:
- WealthWatcher's DB is the only place that knows what's been imported.
- The importer's dedup is the safety net — over-fetching is cheap and
  correct.
- No risk of "I told etrade-mcp I synced through Tuesday but the
  WealthWatcher import actually failed" state drift.

## Daily cron sync

You can run a daily sync from cron, but there's one constraint to know:
**E\*TRADE access tokens expire at midnight US Eastern every day**, and
re-authentication requires a browser PIN dance that cron can't do
unattended. You'll need to run `uv run etrade-auth` once per day
manually (typically in the morning) — then cron can drive the actual
sync for the rest of the day.

A second, lower-tier limit: tokens go *idle* after 2 hours of no calls.
That's fully automatable — see the keepalive script below.

### `scripts/daily_sync.py` — sync transactions

Fetches transactions for a date range and prints a JSON envelope
(`{rows, terminal_events, errors}`) ready to feed into WealthWatcher's
`import_brokerage_transactions` MCP tool.

```bash
# Default — yesterday's transactions to stdout
python scripts/daily_sync.py

# Custom window, write to a file
python scripts/daily_sync.py --since 2026-05-15 --until 2026-05-21 \
    --output /tmp/etrade-sync.json

# Hand off to Claude Code for the WealthWatcher import:
python scripts/daily_sync.py | \
    claude --print "Import this E*TRADE data into WealthWatcher."
```

Bypasses the MCP protocol entirely — no LLM in the hot path. Returns
exit code 2 if any row failed to parse (you can wire that into cron
mail for monitoring).

### `scripts/keepalive.py` — keep the token active

Calls `renew_access_token` to bump the 2-hour idle timer. Doesn't
extend the daily hard expiry; just stops the token from going dormant
between cron runs.

```bash
python scripts/keepalive.py
```

### Example cron schedule (Linux)

```cron
# Keepalive every 90 min during market hours (Mon-Fri, 06:00–17:00 PT)
0,30 6-17 * * 1-5  /path/to/.venv/bin/python /path/to/etrade-mcp/scripts/keepalive.py >> /var/log/etrade-keepalive.log 2>&1

# Daily sync at 18:30 PT (after market close)
30 18 * * 1-5      /path/to/.venv/bin/python /path/to/etrade-mcp/scripts/daily_sync.py --output /var/log/etrade-sync-$(date +\%F).json
```

### Example launchd plist (macOS)

Save as `~/Library/LaunchAgents/com.vantid.etrade-sync.plist` and
load with `launchctl load`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key><string>com.vantid.etrade-sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/.venv/bin/python</string>
        <string>/path/to/etrade-mcp/scripts/daily_sync.py</string>
        <string>--output</string>
        <string>/Users/you/Library/Logs/etrade-sync.json</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>18</integer>
        <key>Minute</key><integer>30</integer>
    </dict>
    <key>StandardErrorPath</key><string>/Users/you/Library/Logs/etrade-sync.err</string>
</dict>
</plist>
```

### When the daily re-auth bites

If your cron starts failing with `oauth_problem=token_rejected`, your
overnight token expired — open a terminal, run `uv run etrade-auth`,
complete the browser flow, and cron will pick up again on its next
scheduled run.

## Sandbox mode

To point at E\*TRADE's sandbox API (`apisb.etrade.com`) instead of
production:

```bash
ETRADE_MODE=sandbox uv run etrade-mcp
```

Note that sandbox returns synthetic data; cost bases are often nonsensical.

## Privacy & security

- OAuth tokens stored in OS keychain, never on disk.
- No analytics, no telemetry, no calls outside `api.etrade.com` (or
  `apisb.etrade.com` in sandbox mode).
- All data flows local: E\*TRADE → this MCP server → your LLM client.

## Status

Beta. Tested against E\*TRADE production API with equities + options.
Futures are not supported by E\*TRADE itself.

## License

[MIT](LICENSE).
