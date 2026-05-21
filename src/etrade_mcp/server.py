from datetime import date

from mcp.server.fastmcp import FastMCP

from etrade_mcp.etrade_client import ETradeClient

mcp = FastMCP("etrade")


@mcp.tool()
def get_portfolio() -> list[dict]:
    """All positions across all brokerage accounts, tagged with account_id."""
    client = ETradeClient()
    return client.get_all_positions()


@mcp.tool()
def get_lots() -> list[dict]:
    """Per-lot cost basis for all equity positions across all brokerage accounts.
    Each lot has acquired_date, price, original_qty, remaining_qty, total_cost,
    term_code (1=long-term, 2=short-term), symbol, account_id."""
    client = ETradeClient()
    return client.get_all_position_lots()


@mcp.tool()
def get_balance() -> list[dict]:
    """Balances for all brokerage accounts, tagged with account_id."""
    client = ETradeClient()
    return client.get_all_balances()


@mcp.tool()
def get_transactions(
    start_date: str | None = None, end_date: str | None = None
) -> list[dict]:
    """All transactions across all brokerage accounts. Dates in YYYY-MM-DD. Defaults to YTD."""
    client = ETradeClient()
    sd = date.fromisoformat(start_date) if start_date else None
    ed = date.fromisoformat(end_date) if end_date else None
    return client.get_all_transactions(start_date=sd, end_date=ed)


@mcp.tool()
def get_quote(symbols: list[str]) -> list[dict]:
    """Market quotes for given symbols. Max 25 per batch (auto-batched)."""
    client = ETradeClient()
    return client.get_quotes(symbols)


if __name__ == "__main__":
    mcp.run()
