"""WealthWatcher import-row schema mappings.

Source-of-truth for the shape WealthWatcher's MCP `import_brokerage_transactions`
tool accepts (see https://github.com/aravindbharathy/wealthWatcher). Two
mappings:

- `map_position_to_import_row` — E*TRADE Position dict → WW row (current
  holdings). Sets `snapshotShares` so WealthWatcher's importer treats the
  broker as source-of-truth.
- `map_transaction_to_import_row` — E*TRADE Transaction dict → WW row
  (buy/sell only).
- `split_terminal_events` — Option Expiration / Assignment / Exercise are
  NOT transactions in WealthWatcher's model. Returns a terminal-event dict
  for the LLM to route to `update_asset` instead.

WealthWatcher conventions honored here:
- Top-level `ticker` is blank for options; identity in details JSON.
- `osiKey` is the preferred dedup key for options.
- Short positions: positive `quantity`, with `tradeType: "sell"` (sell-to-open).
- `contractMultiplier` defaults to 100; pass the broker's value when available.
- `iv` is a decimal (0.28 = 28%); E*TRADE's `ivPct` is the percentage form
  (28.5), so we divide by 100.
"""
from __future__ import annotations

# E*TRADE transactionType strings → WealthWatcher tradeType.
# Anything not in this map (and not in the terminal set) is dropped as
# "not a tradeable event" (Transfer, Fee, Bill Payment, etc.).
_TRADE_TYPE_MAP = {
    "Bought": "buy",
    "Bought To Open": "buy",
    "Bought To Close": "buy",
    "Buy": "buy",
    "Sold": "sell",
    "Sold To Open": "sell",
    "Sold To Close": "sell",
    "Sell": "sell",
}

# E*TRADE terminal-event transactionType strings → WealthWatcher status.
_TERMINAL_STATUS_MAP = {
    "Option Expiration": "expired",
    "Option Assignment": "assigned",
    "Option Exercise": "exercised",
    "Option Expired": "expired",
    "Option Assigned": "assigned",
    "Option Exercised": "exercised",
}


def map_position_to_import_row(pos: dict) -> dict | None:
    """Convert a flattened E*TRADE Position dict to a WW import row.

    Returns None if the position should be skipped (zero quantity, missing
    security type, etc.).
    """
    sec_type = pos.get("securityType")
    quantity = pos.get("quantity")
    if quantity is None or quantity == 0:
        return None

    symbol = pos.get("symbol", "")
    account_name = pos.get("account_name") or pos.get("account_id_key") or ""
    date_acquired = _iso_date(pos.get("date_acquired"))

    asset_type = _SECURITY_TYPE_TO_ASSET_TYPE.get(sec_type or "")
    if asset_type == "option":
        return _map_option_position(pos, symbol, account_name, quantity, date_acquired)
    if asset_type is not None:
        return _map_stock_position(
            pos, symbol, account_name, quantity, date_acquired, asset_type=asset_type,
        )
    return None


# E*TRADE securityType → WealthWatcher asset type.
# Money-market funds (MMF) and indices (INDX) map to "stock" because WW's
# share-based importer handles them identically; MF maps to mutual_fund;
# BOND maps to bond.
_SECURITY_TYPE_TO_ASSET_TYPE: dict[str, str] = {
    "EQ": "stock",
    "OPTN": "option",
    "MF": "mutual_fund",
    "MMF": "stock",
    "BOND": "bond",
    "INDX": "stock",
}


def _map_stock_position(
    pos: dict,
    symbol: str,
    account_name: str,
    quantity: float,
    date_acquired: str,
    asset_type: str = "stock",
) -> dict:
    """Stock/ETF/MF — direct mapping."""
    abs_qty = abs(quantity)
    is_short = quantity < 0
    # E*TRADE sandbox often returns pricePaid=0. Fall back to market value /
    # quantity. WealthWatcher will accept it and the user can correct it.
    price = pos.get("price_paid") or 0
    if price <= 0:
        mv = pos.get("market_value") or 0
        if mv and abs_qty:
            price = mv / abs_qty
    return {
        "symbol": symbol,
        "name": pos.get("symbolDescription") or symbol,
        "type": asset_type,
        "date": date_acquired,
        "tradeType": "sell" if is_short else "buy",
        "quantity": abs_qty,
        "price": price,
        "exchange": pos.get("exchange") or "NYSE",
        "currency": pos.get("currency") or "USD",
        "snapshotShares": abs_qty,
        "account": account_name,
    }


def _map_option_position(
    pos: dict,
    symbol: str,
    account_name: str,
    quantity: float,
    date_acquired: str,
) -> dict:
    """Option position — needs the OSI key + derivative-specific fields."""
    abs_qty = abs(quantity)
    is_short = quantity < 0
    # premiumPerShare — E*TRADE's pricePaid for options is per-share already
    # (e.g. $2.50, not $250 per contract).
    price = pos.get("price_paid") or 0
    iv_pct = pos.get("ivPct")
    return {
        "symbol": pos.get("symbolDescription") or pos.get("osi_key") or symbol,
        "name": pos.get("symbolDescription") or pos.get("osi_key"),
        "type": "option",
        "date": date_acquired,
        "tradeType": "sell" if is_short else "buy",
        "quantity": abs_qty,
        "price": price,
        "currency": pos.get("currency") or "USD",
        "optionType": (pos.get("callPut") or "").lower() or None,
        "strikePrice": pos.get("strikePrice"),
        "expirationDate": _iso_date(pos.get("expiry_date")),
        "underlyingTicker": symbol,
        "osiKey": pos.get("osi_key"),
        "contractMultiplier": pos.get("optionMultiplier") or 100,
        "iv": (iv_pct / 100.0) if iv_pct else None,
        "account": account_name,
    }


def map_transaction_to_import_row(txn: dict) -> dict | None:
    """Convert a flattened E*TRADE Transaction dict to a WW import row.

    Returns None when the transaction isn't a tradeable buy/sell — caller
    should have already routed terminal events via `split_terminal_events`.
    """
    trade_type = _TRADE_TYPE_MAP.get(txn.get("transaction_type", ""))
    if trade_type is None:
        return None

    quantity = txn.get("quantity")
    if quantity is None or quantity == 0:
        return None
    abs_qty = abs(quantity)

    price = txn.get("price")
    if price is None or price <= 0:
        return None

    sec_type = txn.get("securityType")
    symbol = txn.get("symbol", "") or ""
    account_name = txn.get("account_name") or txn.get("account_id_key") or ""
    iso_date = _iso_date(txn.get("transaction_date"))

    base = {
        "symbol": symbol,
        "date": iso_date,
        "tradeType": trade_type,
        "quantity": abs_qty,
        "price": price,
        "currency": "USD",
        "account": account_name,
    }

    if sec_type == "OPTN":
        base.update({
            "type": "option",
            "optionType": (txn.get("callPut") or "").lower() or None,
            "strikePrice": txn.get("strikePrice"),
            "expirationDate": _iso_date(txn.get("expiry_date")),
            "underlyingTicker": symbol,
            "osiKey": txn.get("osi_key"),
            "contractMultiplier": 100,
        })
    else:
        # Transactions don't carry an exchange field — fall back to NYSE
        # (E*TRADE-listed symbols are almost always NYSE/NASDAQ; the
        # importer normalizes either way).
        base["type"] = _SECURITY_TYPE_TO_ASSET_TYPE.get(sec_type or "", "stock")
        base["exchange"] = "NYSE"

    return base


def split_terminal_events(txn: dict) -> dict | None:
    """If `txn` is an Option Expiration/Assignment/Exercise, return a
    terminal-event dict for the LLM to route to `update_asset`. Otherwise
    return None and let the caller treat it as a normal buy/sell."""
    status = _TERMINAL_STATUS_MAP.get(txn.get("transaction_type", ""))
    if status is None:
        return None
    return {
        "status": status,
        "underlyingTicker": txn.get("symbol"),
        "osiKey": txn.get("osi_key"),
        "optionType": (txn.get("callPut") or "").lower() or None,
        "strikePrice": txn.get("strikePrice"),
        "expirationDate": _iso_date(txn.get("expiry_date")),
        "transaction_date": _iso_date(txn.get("transaction_date")),
        "description": txn.get("description"),
        "account": txn.get("account_name") or txn.get("account_id_key"),
        "note": (
            "Route to update_asset({assetId, details:{status: '"
            + status
            + "'}}) on the matching contract series. For exercises and "
            + "assignments, record the underlying-stock leg separately via "
            + "record_transaction."
        ),
    }


def _iso_date(v: object) -> str:
    """Coerce datetime / ISO-string / None to YYYY-MM-DD (today's date if None)."""
    if v is None:
        from datetime import date as _date
        return _date.today().isoformat()
    if isinstance(v, str):
        return v[:10]
    # datetime instance
    try:
        return v.strftime("%Y-%m-%d")  # type: ignore[attr-defined]
    except Exception:
        return str(v)[:10]
