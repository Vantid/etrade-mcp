"""Unit tests for Pydantic model parsing + OSI key generation."""
from __future__ import annotations

from datetime import datetime

import pytest

from etrade_mcp.models import (
    EtradeBalance,
    EtradeLot,
    EtradePosition,
    EtradeQuote,
    EtradeTransaction,
)


# ---------------------------------------------------------------------------
# OSI key — the bug fix that motivated this rewrite (was three dashes,
# should be two per OCC convention)
# ---------------------------------------------------------------------------

class TestOSIKey:
    def test_call_uses_two_dashes_and_pads_strike_to_8_digits(self):
        # AAPL Dec 19 2026 $200 Call
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": 2,
            "marketValue": 22000,
            "totalCost": 500,
            "totalGain": 21500,
            "Product": {
                "symbol": "AAPL",
                "securityType": "OPTN",
                "callPut": "CALL",
                "strikePrice": 200,
                "expiryYear": 2026,
                "expiryMonth": 12,
                "expiryDay": 19,
            },
        })
        assert pos.osi_key == "AAPL--261219C00200000"

    def test_put_uses_P_suffix(self):
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": -1,
            "marketValue": -320,
            "totalCost": -880,
            "totalGain": 560,
            "Product": {
                "symbol": "MSFT",
                "securityType": "OPTN",
                "callPut": "PUT",
                "strikePrice": 400,
                "expiryYear": 2026,
                "expiryMonth": 7,
                "expiryDay": 17,
            },
        })
        assert pos.osi_key == "MSFT--260717P00400000"

    def test_non_integer_strike_preserves_3_decimals_padding(self):
        # 12.50 strike — strike × 1000 = 12500 → 8 digits = 00012500.
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": 1,
            "marketValue": 50,
            "totalCost": 30,
            "totalGain": 20,
            "Product": {
                "symbol": "SOFI",
                "securityType": "OPTN",
                "callPut": "CALL",
                "strikePrice": 12.5,
                "expiryYear": 2026,
                "expiryMonth": 1,
                "expiryDay": 16,
            },
        })
        assert pos.osi_key == "SOFI--260116C00012500"

    def test_no_osi_key_for_stock(self):
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": 10,
            "marketValue": 207,
            "totalCost": 0,
            "totalGain": 207,
            "Product": {"symbol": "BR", "securityType": "EQ"},
        })
        assert pos.osi_key is None

    def test_no_osi_key_when_strike_missing(self):
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": 1,
            "marketValue": 0,
            "totalCost": 0,
            "totalGain": 0,
            "Product": {
                "symbol": "AAPL",
                "securityType": "OPTN",
                "callPut": "CALL",
                "expiryYear": 2026,
                "expiryMonth": 12,
                "expiryDay": 19,
            },
        })
        assert pos.osi_key is None

    def test_handles_2_digit_year(self):
        """E*TRADE sometimes sends `expiryYear` as the 2-digit form (26
        instead of 2026). Make sure we handle both."""
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": 1,
            "marketValue": 1000,
            "totalCost": 500,
            "totalGain": 500,
            "Product": {
                "symbol": "AAPL",
                "securityType": "OPTN",
                "callPut": "CALL",
                "strikePrice": 200,
                "expiryYear": 26,  # 2-digit
                "expiryMonth": 12,
                "expiryDay": 19,
            },
        })
        assert pos.osi_key == "AAPL--261219C00200000"


# ---------------------------------------------------------------------------
# Expiry date computation
# ---------------------------------------------------------------------------

class TestExpiryDate:
    def test_expiry_date_constructed_correctly(self):
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": 1,
            "marketValue": 0,
            "totalCost": 0,
            "totalGain": 0,
            "Product": {
                "symbol": "AAPL",
                "securityType": "OPTN",
                "callPut": "CALL",
                "strikePrice": 200,
                "expiryYear": 2026,
                "expiryMonth": 12,
                "expiryDay": 19,
            },
        })
        assert pos.expiry_date == datetime(2026, 12, 19)

    def test_expiry_date_none_for_stock(self):
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": 10,
            "marketValue": 100,
            "totalCost": 0,
            "totalGain": 100,
            "Product": {"symbol": "BR", "securityType": "EQ"},
        })
        assert pos.expiry_date is None


# ---------------------------------------------------------------------------
# Position model — Complete block surfaces optionMultiplier + IV + greeks
# ---------------------------------------------------------------------------

class TestPositionComplete:
    def test_option_position_surfaces_iv_and_greeks(self):
        pos = EtradePosition.model_validate({
            "positionId": 12345,
            "quantity": 2,
            "marketValue": 21000,
            "totalCost": 500,
            "totalGain": 20500,
            "positionType": "LONG",
            "pricePaid": 2.5,
            "dateAcquired": 1714521600000,  # 2024-05-01
            "Product": {
                "symbol": "AAPL",
                "securityType": "OPTN",
                "callPut": "CALL",
                "strikePrice": 200,
                "expiryYear": 2026,
                "expiryMonth": 12,
                "expiryDay": 19,
            },
            "Complete": {
                "optionMultiplier": 100,
                "ivPct": 28.5,
                "delta": 0.85,
                "theta": -0.08,
                "lastTrade": 110.5,
                "currency": "USD",
            },
        })
        flat = pos.to_flat_dict()
        assert flat["optionMultiplier"] == 100
        assert flat["ivPct"] == 28.5
        assert flat["delta"] == 0.85
        assert flat["theta"] == -0.08
        assert flat["lastTrade"] == 110.5
        assert flat["osi_key"] == "AAPL--261219C00200000"
        assert flat["position_type"] == "LONG"

    def test_short_position_negative_quantity(self):
        pos = EtradePosition.model_validate({
            "positionId": 1,
            "quantity": -1,
            "marketValue": -220,
            "totalCost": -485,
            "totalGain": 265,
            "positionType": "SHORT",
            "Product": {
                "symbol": "AAPL",
                "securityType": "OPTN",
                "callPut": "CALL",
                "strikePrice": 250,
                "expiryYear": 2026,
                "expiryMonth": 5,
                "expiryDay": 15,
            },
        })
        assert pos.quantity == -1
        assert pos.position_type == "SHORT"


# ---------------------------------------------------------------------------
# Transaction model — basic shape + product nesting
# ---------------------------------------------------------------------------

class TestTransaction:
    def test_basic_buy(self):
        txn = EtradeTransaction.model_validate({
            "transactionId": "13153200000361",
            "transactionDate": 1714521600000,
            "amount": -2070.0,
            "description": "Bought 100 BR @ $20.70",
            "transactionType": "Bought",
            "brokerage": {
                "quantity": 100,
                "price": 20.70,
                "fee": 0,
                "product": {"symbol": "BR", "securityType": "EQ"},
            },
        })
        assert txn.transaction_type == "Bought"
        assert txn.quantity == 100
        assert txn.price == 20.70
        assert txn.amount == -2070

    def test_option_transaction_includes_osi(self):
        txn = EtradeTransaction.model_validate({
            "transactionId": "tx-opt-1",
            "transactionDate": 1714521600000,
            "amount": 500,
            "description": "Sold To Open AAPL Dec19'26 200 Call @ 2.50",
            "transactionType": "Sold To Open",
            "brokerage": {
                "quantity": 2,
                "price": 2.50,
                "fee": 1.30,
                "product": {
                    "symbol": "AAPL",
                    "securityType": "OPTN",
                    "callPut": "CALL",
                    "strikePrice": 200,
                    "expiryYear": 2026,
                    "expiryMonth": 12,
                    "expiryDay": 19,
                },
            },
        })
        assert txn.osi_key == "AAPL--261219C00200000"


# ---------------------------------------------------------------------------
# Other models
# ---------------------------------------------------------------------------

class TestLot:
    def test_lot_parses_and_records_term_code(self):
        lot = EtradeLot.model_validate({
            "positionId": 12345,
            "positionLotId": 67890,
            "acquiredDate": 1714521600000,
            "price": 20.70,
            "originalQty": 100,
            "remainingQty": 100,
            "totalCost": 2070,
            "termCode": 1,  # long-term
        })
        assert lot.term_code == 1
        assert lot.original_qty == 100
        assert lot.remaining_qty == 100


class TestBalance:
    def test_balance_parses_real_time_values(self):
        bal = EtradeBalance.model_validate({
            "accountDescription": "INDIVIDUAL",
            "Computed": {
                "RealTimeValues": {
                    "totalAccountValue": 125000.50,
                    "netCash": 5000,
                },
                "marginBuyingPower": 100000,
                "cashBuyingPower": 5000,
            },
        })
        assert bal.total_account_value == 125000.50
        assert bal.net_cash == 5000


class TestQuote:
    def test_quote_parses_nested_product_and_all_blocks(self):
        q = EtradeQuote.model_validate({
            "Product": {"symbol": "AAPL", "securityType": "EQ"},
            "All": {
                "lastTrade": 301.86,
                "bid": 301.80,
                "ask": 301.90,
                "previousClose": 300.00,
                "changeClose": 1.86,
                "high": 302.50,
                "low": 299.50,
                "totalVolume": 50000000,
                "high52": 320.0,
                "low52": 150.0,
            },
        })
        assert q.symbol == "AAPL"
        assert q.last_trade == 301.86
        assert q.previous_close == 300.00
