"""Pydantic models for E*TRADE API payloads.

Frozen by default — mutation pattern is `model_copy(update=...)` so callers
can attach computed fields (account_id_key, account_name) after parsing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field, computed_field
from pydantic.aliases import AliasPath
from pydantic.functional_validators import BeforeValidator


# ---------------------------------------------------------------------------
# Shared coercers
# ---------------------------------------------------------------------------

def _convert_ms_to_datetime(v: int | str) -> datetime:
    return datetime.fromtimestamp(int(v) / 1000)


def _coerce_str(v: object) -> Optional[str]:
    return str(v) if v is not None else None


TimestampType = Annotated[datetime, BeforeValidator(_convert_ms_to_datetime)]
CoercedStr = Annotated[str, BeforeValidator(_coerce_str)]


# ---------------------------------------------------------------------------
# Product + OSI key helper (shared between Position and Transaction)
# ---------------------------------------------------------------------------


class Product(BaseModel, frozen=True):
    """Subset of E*TRADE's Product block. Same shape for positions and txns."""

    callPut: Optional[str] = None
    expiryDay: Optional[int] = Field(default=None, exclude=True)
    expiryMonth: Optional[int] = Field(default=None, exclude=True)
    expiryYear: Optional[int] = Field(default=None, exclude=True)
    securityType: Optional[str] = None
    strikePrice: Optional[float] = None
    symbol: Optional[str] = None


class ProductMixin:
    """Adds `expiry_date` and `osi_key` computed fields. Requires `product` attr."""

    if TYPE_CHECKING:
        product: Optional[Product]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def expiry_date(self) -> Optional[datetime]:
        p = self.product
        if p is None or p.securityType != "OPTN":
            return None
        if p.expiryYear is None or p.expiryMonth is None or p.expiryDay is None:
            return None
        # E*TRADE sometimes returns 2-digit, sometimes 4-digit years.
        year = p.expiryYear if p.expiryYear >= 1900 else p.expiryYear % 100 + 2000
        return datetime(year, p.expiryMonth, p.expiryDay)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def osi_key(self) -> Optional[str]:
        """Industry-standard OSI contract identifier.

        Format: `{ROOT}--{YYMMDD}{C|P}{strike×1000, 8 digits zero-padded}`.
        Two dashes after the root (per OCC convention).
        Example: AAPL Dec 19 2026 $200 Call → `AAPL--261219C00200000`.
        """
        p = self.product
        if p is None or p.securityType != "OPTN":
            return None
        exp = self.expiry_date
        if (
            exp is None
            or p.strikePrice is None
            or p.symbol is None
            or p.callPut is None
        ):
            return None
        strike_padded = f"{int(round(p.strikePrice * 1000)):08d}"
        date_str = exp.strftime("%y%m%d")
        return f"{p.symbol.upper()}--{date_str}{p.callPut[0].upper()}{strike_padded}"


# ---------------------------------------------------------------------------
# Account-aware base — every record carries its source account
# ---------------------------------------------------------------------------


class AccountTagged(BaseModel, frozen=True):
    """Mixed into records that need account provenance."""

    account_id_key: str = ""
    """E*TRADE's stable account handle (`accountIdKey`). Use this for dedup."""
    account_name: str = ""
    """User-facing label (`accountDesc`). May change if the user renames."""


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class EtradeTransaction(AccountTagged, ProductMixin, frozen=True):
    product: Optional[Product] = Field(
        default=None,
        validation_alias=AliasPath("brokerage", "product"),
    )
    transaction_id: str = Field(validation_alias="transactionId")
    transaction_date: TimestampType = Field(validation_alias="transactionDate")
    amount: float
    description: str
    transaction_type: str = Field(validation_alias="transactionType")
    quantity: Optional[float] = Field(
        default=None, validation_alias=AliasPath("brokerage", "quantity")
    )
    price: Optional[float] = Field(
        default=None, validation_alias=AliasPath("brokerage", "price")
    )
    fee: Optional[float] = Field(
        default=None, validation_alias=AliasPath("brokerage", "fee")
    )

    def to_flat_dict(self) -> dict:
        data = self.model_dump(mode="json")
        product = data.pop("product", None) or {}
        return {**data, **product}


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class CompleteBlock(BaseModel, frozen=True):
    """The `Complete` sub-block from E*TRADE Position payloads.

    Carries option-specific extras (multiplier, IV, greeks) and stock-level
    market data (current price, prev close). Surfaced so downstream tooling
    (e.g. a Black-Scholes engine on the import side) can seed accurate
    values without a second API call.
    """

    optionMultiplier: Optional[int] = None
    ivPct: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    intrinsicValue: Optional[float] = None
    daysToExpiration: Optional[int] = None
    lastTrade: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    previousClose: Optional[float] = None
    currency: Optional[str] = None


class EtradePosition(AccountTagged, ProductMixin, frozen=True):
    product: Optional[Product] = Field(default=None, validation_alias="Product")
    complete: Optional[CompleteBlock] = Field(default=None, validation_alias="Complete")
    position_id: CoercedStr = Field(validation_alias="positionId")
    position_type: Optional[str] = Field(default=None, validation_alias="positionType")
    """LONG or SHORT (E*TRADE's casing)."""
    date_acquired: Optional[TimestampType] = Field(
        default=None, validation_alias="dateAcquired"
    )
    quantity: float
    """Signed quantity — negative for short positions."""
    price_paid: Optional[float] = Field(default=None, validation_alias="pricePaid")
    """Per-share cost basis from E*TRADE. May be 0 in sandbox; trust holdings instead."""
    cost_per_share: Optional[float] = Field(
        default=None, validation_alias="costPerShare"
    )
    market_value: float = Field(validation_alias="marketValue")
    total_cost: float = Field(validation_alias="totalCost")
    total_gain: float = Field(validation_alias="totalGain")

    def to_flat_dict(self) -> dict:
        data = self.model_dump(mode="json")
        product = data.pop("product", None) or {}
        complete = data.pop("complete", None) or {}
        return {**data, **product, **complete}


# ---------------------------------------------------------------------------
# Lots
# ---------------------------------------------------------------------------


class EtradeLot(AccountTagged, frozen=True):
    symbol: str = ""
    security_type: Optional[str] = None
    """EQ, OPTN, MF — preserved so callers can filter as they need."""
    position_id: CoercedStr = Field(validation_alias="positionId")
    position_lot_id: CoercedStr = Field(validation_alias="positionLotId")
    acquired_date: TimestampType = Field(validation_alias="acquiredDate")
    price: float
    original_qty: float = Field(validation_alias="originalQty")
    remaining_qty: float = Field(validation_alias="remainingQty")
    total_cost: float = Field(validation_alias="totalCost")
    term_code: int = Field(validation_alias="termCode")
    """1 = long-term (>1 year), 2 = short-term."""

    def to_flat_dict(self) -> dict:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


class EtradeBalance(AccountTagged, frozen=True):
    account_description: str = Field(validation_alias="accountDescription")
    total_account_value: float = Field(
        validation_alias=AliasPath("Computed", "RealTimeValues", "totalAccountValue")
    )
    margin_buying_power: Optional[float] = Field(
        default=None,
        validation_alias=AliasPath("Computed", "marginBuyingPower"),
    )
    cash_buying_power: Optional[float] = Field(
        default=None,
        validation_alias=AliasPath("Computed", "cashBuyingPower"),
    )
    net_cash: Optional[float] = Field(
        default=None,
        validation_alias=AliasPath("Computed", "RealTimeValues", "netCash"),
    )

    def to_flat_dict(self) -> dict:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


class EtradeQuote(BaseModel, frozen=True):
    symbol: str = Field(validation_alias=AliasPath("Product", "symbol"))
    security_type: Optional[str] = Field(
        default=None,
        validation_alias=AliasPath("Product", "securityType"),
    )
    last_trade: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "lastTrade")
    )
    bid: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "bid")
    )
    ask: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "ask")
    )
    change_close: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "changeClose")
    )
    previous_close: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "previousClose")
    )
    high: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "high")
    )
    low: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "low")
    )
    total_volume: Optional[int] = Field(
        default=None, validation_alias=AliasPath("All", "totalVolume")
    )
    high_52: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "high52")
    )
    low_52: Optional[float] = Field(
        default=None, validation_alias=AliasPath("All", "low52")
    )

    def to_flat_dict(self) -> dict:
        return self.model_dump(mode="json")
