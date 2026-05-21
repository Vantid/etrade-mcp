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
