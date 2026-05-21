from pydantic import BaseModel, Field, computed_field
from pydantic.aliases import AliasPath
from pydantic.functional_validators import BeforeValidator
from datetime import datetime
from typing import Optional, Annotated, TYPE_CHECKING


class Product(BaseModel, frozen=True):
    callPut: Optional[str] = Field(default=None)
    expiryDay: Optional[int] = Field(default=None, exclude=True)
    expiryMonth: Optional[int] = Field(default=None, exclude=True)
    expiryYear: Optional[int] = Field(default=None, exclude=True)
    securityType: Optional[str] = Field(default=None)
    strikePrice: Optional[float] = Field(default=None)
    symbol: Optional[str] = Field(default=None)


class ProductMixin:
    if TYPE_CHECKING:
        product: Optional[Product]

    @computed_field
    @property
    def expiry_date(self) -> Annotated[Optional[datetime], computed_field(...)]:
        if self.product is None or self.product.securityType != "OPTN":
            return None

        assert (
            self.product.expiryYear is not None
            and self.product.expiryMonth is not None
            and self.product.expiryDay is not None
        )

        expiry_year = self.product.expiryYear % 2000 + 2000

        return datetime(
            expiry_year,
            self.product.expiryMonth,
            self.product.expiryDay,
        )

    @computed_field
    @property
    def osi_key(self) -> Optional[str]:
        """Computes the Options Symbology Initiative (OSI) key."""
        product = self.product

        if product is None or product.securityType != "OPTN":
            return None

        expiry_date = self.expiry_date

        assert (
            product.expiryDay is not None
            and product.strikePrice is not None
            and product.symbol is not None
            and product.callPut is not None
            and expiry_date is not None
        )

        strike_value = int(product.strikePrice * 1000)
        strike_formatted = f"{strike_value:08d}"

        date_str = expiry_date.strftime("%y%m%d")
        return f"{product.symbol.upper()}---{date_str}{product.callPut[0].upper()}{strike_formatted}"


def _convert_ms_to_datetime(v):
    return datetime.fromtimestamp(int(v) / 1000)


TimestampType = Annotated[datetime, BeforeValidator(_convert_ms_to_datetime)]


def _coerce_str(v):
    return str(v) if v is not None else v


CoercedStr = Annotated[str, BeforeValidator(_coerce_str)]


class EtradeTransaction(BaseModel, ProductMixin, frozen=True):
    account_id: str = ""
    product: Optional[Product] = Field(
        validation_alias=AliasPath("brokerage", "product"), default=None
    )
    transaction_id: str = Field(validation_alias="transactionId")
    transaction_date: TimestampType = Field(validation_alias="transactionDate")
    amount: float
    description: str
    transaction_type: str = Field(validation_alias="transactionType")
    quantity: Optional[float] = Field(default=None, validation_alias=AliasPath("brokerage", "quantity"))
    price: Optional[float] = Field(default=None, validation_alias=AliasPath("brokerage", "price"))
    fee: Optional[float] = Field(default=None, validation_alias=AliasPath("brokerage", "fee"))

    def to_flat_dict(self) -> dict:
        data = self.model_dump(mode="json")
        product = data.pop("product", {}) or {}
        return {**data, **product}


class EtradePosition(BaseModel, ProductMixin):
    account_id: str = ""
    product: Optional[Product] = Field(
        validation_alias="Product", default=None
    )
    position_id: CoercedStr = Field(validation_alias="positionId")
    quantity: float
    market_value: float = Field(validation_alias="marketValue")
    total_cost: float = Field(validation_alias="totalCost")
    total_gain: float = Field(validation_alias="totalGain")

    def to_flat_dict(self) -> dict:
        data = self.model_dump(mode="json")
        product = data.pop("product", {}) or {}
        return {**data, **product}


class EtradeLot(BaseModel):
    account_id: str = ""
    symbol: str = ""
    position_id: CoercedStr = Field(validation_alias="positionId")
    position_lot_id: CoercedStr = Field(validation_alias="positionLotId")
    acquired_date: TimestampType = Field(validation_alias="acquiredDate")
    price: float
    original_qty: float = Field(validation_alias="originalQty")
    remaining_qty: float = Field(validation_alias="remainingQty")
    total_cost: float = Field(validation_alias="totalCost")
    term_code: int = Field(validation_alias="termCode")  # 1=long-term, 2=short-term

    def to_flat_dict(self) -> dict:
        return self.model_dump(mode="json")


class EtradeBalance(BaseModel):
    account_id: str = ""
    account_description: str = Field(
        validation_alias=AliasPath("accountDescription")
    )
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


class EtradeQuote(BaseModel):
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
