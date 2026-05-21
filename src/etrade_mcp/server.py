"""FastMCP tool surface for the E*TRADE MCP server.

Two layers:
1. Raw E*TRADE reads (positions / lots / transactions / balances / quotes).
2. WealthWatcher-shaped composites (`get_holdings_for_import`,
   `get_transactions_for_import`, `get_daily_changes`).

Every tool returns `{rows: [...], errors: [...]}` so failures are surfaced
in-band rather than silently dropped.
"""
from datetime import date

from mcp.server.fastmcp import FastMCP

from etrade_mcp.etrade_client import ETradeClient
from etrade_mcp.wealthwatcher import (
    map_position_to_import_row,
    map_transaction_to_import_row,
    split_terminal_events,
)

mcp = FastMCP("etrade")


# ---------------------------------------------------------------------------
# Raw read tools — direct E*TRADE shapes
# ---------------------------------------------------------------------------


@mcp.tool()
def get_portfolio() -> dict:
    """All positions across all brokerage / investment accounts.

    Each row carries `account_id_key` (stable handle) and `account_name`
    (display). For options, includes `osi_key`, `optionMultiplier`, `ivPct`,
    and greeks when E*TRADE returns them.

    Returns: {rows: [...], errors: [...]}
    """
    return ETradeClient().get_all_positions().to_dict()


@mcp.tool()
def get_lots() -> dict:
    """Per-lot cost basis for all positions (stocks AND options).

    Each lot has `acquired_date`, `price`, `original_qty`, `remaining_qty`,
    `total_cost`, `term_code` (1=long-term, 2=short-term), `symbol`,
    `security_type`, `account_id_key`.

    Returns: {rows: [...], errors: [...]}
    """
    return ETradeClient().get_all_position_lots().to_dict()


@mcp.tool()
def get_balance() -> dict:
    """Balances for all brokerage / investment accounts.

    Returns: {rows: [...], errors: [...]}
    """
    return ETradeClient().get_all_balances().to_dict()


@mcp.tool()
def get_transactions(
    start_date: str | None = None, end_date: str | None = None
) -> dict:
    """Transactions across all accounts. Dates in YYYY-MM-DD. Defaults to YTD.

    Returns: {rows: [...], errors: [...]}
    """
    sd = date.fromisoformat(start_date) if start_date else None
    ed = date.fromisoformat(end_date) if end_date else None
    return ETradeClient().get_all_transactions(start_date=sd, end_date=ed).to_dict()


@mcp.tool()
def get_quote(symbols: list[str]) -> dict:
    """Market quotes for given symbols. Max 25 per batch (auto-batched).

    For option quotes, pass the OSI-formatted symbol (e.g.
    `AAPL--261219C00200000`).

    Returns: {rows: [...], errors: [...]}
    """
    return ETradeClient().get_quotes(symbols).to_dict()


# ---------------------------------------------------------------------------
# WealthWatcher-shaped composites — output is ready to pipe into
# WealthWatcher's `import_brokerage_transactions` MCP tool.
# ---------------------------------------------------------------------------


def _build_holdings_for_import() -> dict:
    """Implementation of `get_holdings_for_import`. Pulled out so tools
    can compose without going through the FastMCP decorator wrapping."""
    positions = ETradeClient().get_all_positions()
    rows: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = list(positions.errors)
    for pos in positions.rows:
        try:
            row = map_position_to_import_row(pos)
            if row is None:
                quantity = pos.get("quantity")
                if quantity is None or quantity == 0:
                    skipped.append({
                        "account_id_key": pos.get("account_id_key"),
                        "symbol": pos.get("symbol"),
                        "reason": "zero quantity (closed position)",
                    })
                else:
                    skipped.append({
                        "account_id_key": pos.get("account_id_key"),
                        "symbol": pos.get("symbol"),
                        "reason": f"unsupported securityType: {pos.get('securityType')}",
                    })
            else:
                rows.append(row)
        except Exception as e:
            errors.append({
                "account_id_key": pos.get("account_id_key"),
                "symbol": pos.get("symbol"),
                "context": "position_mapping",
                "error": str(e),
            })
    return {"rows": rows, "skipped": skipped, "errors": errors}


def _build_transactions_for_import(
    sd: date | None,
    ed: date | None,
) -> dict:
    """Implementation of `get_transactions_for_import` /
    `get_daily_changes`. Pulled out so tools can compose without going
    through the FastMCP decorator wrapping."""
    txns = ETradeClient().get_all_transactions(start_date=sd, end_date=ed)

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
    return {"rows": rows, "terminal_events": terminal_events, "errors": errors}


@mcp.tool()
def get_holdings_for_import() -> dict:
    """Current holdings shaped as WealthWatcher import rows.

    Returns one row per position (stock / mutual_fund / bond / option) in
    the schema expected by WealthWatcher's `import_brokerage_transactions`
    MCP tool. Use this for initial portfolio import or full-resync. Rows
    include:
      - `type`: "stock" / "mutual_fund" / "bond" / "option"
      - `symbol`, `name`, `quantity`, `price` (per-share / per-contract premium)
      - `tradeType`: "buy" for long positions, "sell" for short (sell-to-open)
      - `snapshotShares`: broker-reported current share count (holdings-as-truth)
      - `exchange`: from E*TRADE's Complete.exchange (NYSE / NASDAQ / ARCA…)
      - For options: `optionType`, `strikePrice`, `expirationDate`,
        `underlyingTicker`, `osiKey`, `contractMultiplier`, `iv` (when available)

    Closed positions (quantity=0) and unsupported security types are
    surfaced in `skipped` so the LLM/user can see what didn't make it.

    Returns: {rows: [...], skipped: [...], errors: [...]}
    """
    return _build_holdings_for_import()


@mcp.tool()
def get_transactions_for_import(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Transactions shaped as WealthWatcher import rows + terminal events.

    Splits the response into two streams:
      - `rows`: buy/sell transactions ready for
        `import_brokerage_transactions` (shape matches WealthWatcher's
        schema; tradeType auto-mapped from E*TRADE's transactionType).
      - `terminal_events`: option expirations / assignments / exercises
        — these should NOT go through `import_brokerage_transactions`;
        route them to `update_asset({details: {status: "expired" | "assigned"
        | "exercised"}})` instead, per WealthWatcher's modeling rule.

    Dates in YYYY-MM-DD. Defaults to YTD.

    Returns: {rows: [...], terminal_events: [...], errors: [...]}
    """
    sd = date.fromisoformat(start_date) if start_date else None
    ed = date.fromisoformat(end_date) if end_date else None
    return _build_transactions_for_import(sd, ed)


@mcp.tool()
def get_daily_changes(since: str) -> dict:
    """Incremental sync: new transactions + terminal events since timestamp.

    `since` is an ISO date (YYYY-MM-DD) — typically the last successful sync.
    Returns the same shape as `get_transactions_for_import` but scoped to
    the date range `[since, today]`. Use this for daily-update workflows
    instead of refetching full YTD every day.

    Returns: {rows: [...], terminal_events: [...], errors: [...]}
    """
    return _build_transactions_for_import(date.fromisoformat(since), None)


def main() -> None:
    """Console-script entry point. Starts the MCP stdio server."""
    mcp.run()


if __name__ == "__main__":
    main()
