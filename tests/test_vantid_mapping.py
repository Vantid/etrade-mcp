"""Tests for E*TRADE → Vantid import-row mappings."""
from __future__ import annotations

from etrade_mcp.vantid import (
    map_position_to_import_row,
    map_transaction_to_import_row,
    split_terminal_events,
)

# ---------------------------------------------------------------------------
# map_position_to_import_row
# ---------------------------------------------------------------------------


def test_stock_long_position_maps_to_buy_row():
    row = map_position_to_import_row({
        "securityType": "EQ",
        "symbol": "BR",
        "symbolDescription": "BROADRIDGE FINL SOLUTIONS",
        "quantity": 10,
        "price_paid": 20.70,
        "market_value": 207,
        "currency": "USD",
        "account_name": "Brokerage-1",
        "date_acquired": "2024-05-01T00:00:00",
    })
    assert row is not None
    assert row["type"] == "stock"
    assert row["tradeType"] == "buy"
    assert row["symbol"] == "BR"
    assert row["quantity"] == 10
    assert row["price"] == 20.70
    assert row["snapshotShares"] == 10
    assert row["account"] == "Brokerage-1"


def test_stock_zero_pricePaid_falls_back_to_marketValue_per_share():
    """E*TRADE sandbox returns pricePaid=0 for many positions. Fall back."""
    row = map_position_to_import_row({
        "securityType": "EQ",
        "symbol": "BR",
        "quantity": 10,
        "price_paid": 0,
        "market_value": 207,
        "account_name": "X",
    })
    assert row["price"] == 20.70


def test_short_stock_emits_sell_tradeType():
    row = map_position_to_import_row({
        "securityType": "EQ",
        "symbol": "BR",
        "quantity": -10,
        "price_paid": 20.70,
        "market_value": -207,
        "account_name": "X",
    })
    assert row["tradeType"] == "sell"
    assert row["quantity"] == 10  # absolute


def test_zero_quantity_position_is_skipped():
    row = map_position_to_import_row({
        "securityType": "EQ",
        "symbol": "BR",
        "quantity": 0,
        "price_paid": 20.70,
        "market_value": 0,
    })
    assert row is None


def test_option_long_position_carries_osi_key_iv_multiplier():
    row = map_position_to_import_row({
        "securityType": "OPTN",
        "symbol": "AAPL",
        "symbolDescription": "AAPL Dec 19 '26 $200 Call",
        "quantity": 2,
        "price_paid": 2.50,
        "currency": "USD",
        "account_name": "Brokerage-1",
        "callPut": "CALL",
        "strikePrice": 200,
        "expiry_date": "2026-12-19T00:00:00",
        "osi_key": "AAPL--261219C00200000",
        "optionMultiplier": 100,
        "ivPct": 28.5,
        "date_acquired": "2025-05-01T00:00:00",
    })
    assert row["type"] == "option"
    assert row["tradeType"] == "buy"
    assert row["quantity"] == 2
    assert row["price"] == 2.50
    assert row["optionType"] == "call"
    assert row["strikePrice"] == 200
    assert row["expirationDate"] == "2026-12-19"
    assert row["underlyingTicker"] == "AAPL"
    assert row["osiKey"] == "AAPL--261219C00200000"
    assert row["contractMultiplier"] == 100
    # ivPct comes in as percentage; WW expects decimal (0.285, not 28.5).
    assert row["iv"] == 0.285


def test_short_option_emits_sell_tradeType_with_positive_quantity():
    row = map_position_to_import_row({
        "securityType": "OPTN",
        "symbol": "MSFT",
        "quantity": -1,
        "price_paid": 8.80,
        "callPut": "PUT",
        "strikePrice": 400,
        "expiry_date": "2026-07-17T00:00:00",
        "osi_key": "MSFT--260717P00400000",
        "account_name": "X",
    })
    assert row["tradeType"] == "sell"
    assert row["quantity"] == 1  # absolute, sign in tradeType
    assert row["optionType"] == "put"


def test_unknown_security_type_skipped():
    row = map_position_to_import_row({
        "securityType": "FUT",  # E*TRADE doesn't actually return FUT
        "symbol": "ESM6",
        "quantity": 1,
        "price_paid": 5842,
    })
    assert row is None


def test_mutual_fund_maps_to_mutual_fund_type():
    """MF positions now preserve their type instead of being flattened to 'stock'."""
    row = map_position_to_import_row({
        "securityType": "MF",
        "symbol": "VTSAX",
        "quantity": 100,
        "price_paid": 110.50,
        "market_value": 11000,
        "account_name": "Brokerage-1",
    })
    assert row is not None
    assert row["type"] == "mutual_fund"


def test_bond_maps_to_bond_type():
    row = map_position_to_import_row({
        "securityType": "BOND",
        "symbol": "T-BILL-26",
        "quantity": 10,
        "price_paid": 95.50,
        "market_value": 960,
        "account_name": "X",
    })
    assert row is not None
    assert row["type"] == "bond"


def test_exchange_comes_from_complete_block_not_hardcoded():
    """M2 fix: stock mapper should propagate Complete.exchange instead of
    forcing every row to NYSE. E*TRADE returns the actual listing exchange
    (NASDAQ, ARCA, etc.) in the Complete block."""
    row = map_position_to_import_row({
        "securityType": "EQ",
        "symbol": "AAPL",
        "quantity": 50,
        "price_paid": 200,
        "market_value": 10000,
        "exchange": "NASDAQ",
        "account_name": "Brokerage-1",
    })
    assert row is not None
    assert row["exchange"] == "NASDAQ"


def test_exchange_falls_back_to_NYSE_when_missing():
    row = map_position_to_import_row({
        "securityType": "EQ",
        "symbol": "BR",
        "quantity": 10,
        "price_paid": 20.70,
        "market_value": 207,
        "account_name": "X",
    })
    assert row["exchange"] == "NYSE"


# ---------------------------------------------------------------------------
# map_transaction_to_import_row
# ---------------------------------------------------------------------------


def test_buy_transaction_maps_correctly():
    row = map_transaction_to_import_row({
        "transaction_id": "tx1",
        "transaction_date": "2024-05-01T00:00:00",
        "transaction_type": "Bought",
        "amount": -2070,
        "quantity": 100,
        "price": 20.70,
        "symbol": "BR",
        "securityType": "EQ",
        "account_name": "Brokerage-1",
    })
    assert row is not None
    assert row["tradeType"] == "buy"
    assert row["type"] == "stock"
    assert row["quantity"] == 100
    assert row["price"] == 20.70


def test_sold_to_open_maps_to_sell():
    row = map_transaction_to_import_row({
        "transaction_id": "tx-cc",
        "transaction_date": "2026-03-20T00:00:00",
        "transaction_type": "Sold To Open",
        "amount": 485,
        "quantity": 1,
        "price": 4.85,
        "symbol": "AAPL",
        "securityType": "OPTN",
        "callPut": "CALL",
        "strikePrice": 250,
        "expiry_date": "2026-05-15T00:00:00",
        "osi_key": "AAPL--260515C00250000",
        "account_name": "X",
    })
    assert row["tradeType"] == "sell"
    assert row["type"] == "option"
    assert row["osiKey"] == "AAPL--260515C00250000"
    assert row["contractMultiplier"] == 100


def test_non_tradeable_transaction_returns_none():
    """Transfer, Fee, Bill Payment etc. shouldn't be import rows."""
    assert map_transaction_to_import_row({
        "transaction_type": "Transfer",
        "quantity": 0,
        "price": 0,
    }) is None
    assert map_transaction_to_import_row({
        "transaction_type": "Fee",
        "quantity": 0,
        "price": 0,
    }) is None


def test_zero_quantity_transaction_skipped():
    assert map_transaction_to_import_row({
        "transaction_type": "Bought",
        "quantity": 0,
        "price": 20,
        "symbol": "BR",
        "securityType": "EQ",
    }) is None


# ---------------------------------------------------------------------------
# split_terminal_events
# ---------------------------------------------------------------------------


def test_option_expiration_returns_terminal_event():
    event = split_terminal_events({
        "transaction_type": "Option Expiration",
        "transaction_date": "2026-12-19T00:00:00",
        "symbol": "AAPL",
        "callPut": "CALL",
        "strikePrice": 200,
        "expiry_date": "2026-12-19T00:00:00",
        "osi_key": "AAPL--261219C00200000",
        "description": "Option Expiration AAPL Dec19'26 200 Call",
        "account_name": "X",
    })
    assert event is not None
    assert event["status"] == "expired"
    assert event["osiKey"] == "AAPL--261219C00200000"
    assert event["optionType"] == "call"


def test_option_assignment_maps_to_assigned():
    event = split_terminal_events({
        "transaction_type": "Option Assignment",
        "symbol": "MSFT",
        "callPut": "PUT",
        "strikePrice": 400,
        "osi_key": "MSFT--260717P00400000",
    })
    assert event["status"] == "assigned"


def test_normal_buy_returns_none():
    """A normal buy should NOT be classified as a terminal event."""
    assert split_terminal_events({
        "transaction_type": "Bought",
        "symbol": "BR",
    }) is None
