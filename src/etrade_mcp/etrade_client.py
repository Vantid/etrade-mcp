"""Thin wrapper around pyetrade that returns Pydantic-validated rows.

Conventions:
- Every record carries `account_id_key` (stable handle) AND `account_name`
  (display label). Dedup on `account_id_key`.
- Errors are collected per-row in a `ToolResult`, never silently dropped.
- Sandbox vs production controlled by `ETRADE_MODE` env var (default
  `prod`; set to `sandbox` for the dev/CI API).
- Account filter includes investment accounts (BROKERAGE + INVESTMENT
  IRAs); banks excluded.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pyetrade

from etrade_mcp.keychain import get_credentials
from etrade_mcp.models import (
    EtradeBalance,
    EtradeLot,
    EtradePosition,
    EtradeQuote,
    EtradeTransaction,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Tool-output envelope. Rows + per-row errors, never silently dropped."""

    rows: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"rows": self.rows, "errors": self.errors}


# Institution types we include. BANK is excluded — checking/savings, not
# brokerage holdings. INVESTMENT covers IRAs + regular brokerage on
# E*TRADE's account model.
_INCLUDED_INSTITUTION_TYPES = frozenset({"BROKERAGE", "INVESTMENT"})


def _etrade_dev_flag() -> bool:
    """Translate `ETRADE_MODE` env var into pyetrade's `dev` boolean."""
    return os.environ.get("ETRADE_MODE", "prod").lower() == "sandbox"


class ETradeClient:
    def __init__(self) -> None:
        creds = get_credentials()
        self._consumer_key = creds["consumer-key"]
        self._consumer_secret = creds["consumer-secret"]
        self._oauth_token = creds["oauth-token"]
        self._oauth_token_secret = creds["oauth-token-secret"]
        self._dev = _etrade_dev_flag()

    def _accounts_api(self) -> pyetrade.ETradeAccounts:
        return pyetrade.ETradeAccounts(
            self._consumer_key,
            self._consumer_secret,
            self._oauth_token,
            self._oauth_token_secret,
            dev=self._dev,
        )

    def _market_api(self) -> pyetrade.ETradeMarket:
        return pyetrade.ETradeMarket(
            self._consumer_key,
            self._consumer_secret,
            self._oauth_token,
            self._oauth_token_secret,
            dev=self._dev,
        )

    def _list_brokerage_accounts(self) -> list[dict[str, Any]]:
        api = self._accounts_api()
        resp = api.list_accounts(resp_format="json")
        accounts = resp["AccountListResponse"]["Accounts"]["Account"]
        if isinstance(accounts, dict):
            accounts = [accounts]
        return [
            a
            for a in accounts
            if a.get("institutionType") in _INCLUDED_INSTITUTION_TYPES
            and a.get("accountStatus") != "CLOSED"
        ]

    @staticmethod
    def _paginate(
        api_func: Callable[..., dict],
        result_path: list[str],
        next_token_path: list[str],
        token_param_name: str,
        **kwargs: Any,
    ) -> Iterator[Any]:
        token: Any = None
        while True:
            kwargs[token_param_name] = token
            response = api_func(**kwargs)
            data: Any = response
            for key in result_path:
                data = data[key]

            next_token: Any = response
            for key in next_token_path:
                next_token = None if next_token is None else next_token.get(key)

            yield data

            if next_token is None:
                break
            token = next_token

    # ------------------------------------------------------------------
    # Raw read tools
    # ------------------------------------------------------------------

    def get_all_positions(self) -> ToolResult:
        api = self._accounts_api()
        out = ToolResult()
        for acct in self._list_brokerage_accounts():
            acct_key = acct["accountIdKey"]
            acct_name = acct.get("accountDesc", acct_key)
            try:
                page_number: int | None = None
                while True:
                    resp = api.get_account_portfolio(
                        account_id_key=acct_key,
                        page_number=page_number,
                        resp_format="json",
                    )
                    portfolios = (
                        resp.get("PortfolioResponse", {}).get("AccountPortfolio") or []
                    )
                    if isinstance(portfolios, dict):
                        portfolios = [portfolios]
                    next_page: int | None = None
                    for portfolio in portfolios:
                        positions = portfolio.get("Position") or []
                        if isinstance(positions, dict):
                            positions = [positions]
                        for pos_data in positions:
                            try:
                                pos = EtradePosition.model_validate(pos_data)
                                pos = pos.model_copy(update={
                                    "account_id_key": acct_key,
                                    "account_name": acct_name,
                                })
                                out.rows.append(pos.to_flat_dict())
                            except Exception as e:
                                out.errors.append({
                                    "account_id_key": acct_key,
                                    "context": "position",
                                    "error": str(e),
                                })
                        np = portfolio.get("nextPageNo")
                        if np is not None:
                            next_page = int(np)
                    if not next_page:
                        break
                    page_number = next_page
            except Exception as e:
                err = str(e)
                if _is_empty_response(err):
                    continue
                out.errors.append({
                    "account_id_key": acct_key,
                    "context": "portfolio_fetch",
                    "error": err,
                })
        return out

    def get_all_position_lots(self) -> ToolResult:
        api = self._accounts_api()
        out = ToolResult()
        for acct in self._list_brokerage_accounts():
            acct_key = acct["accountIdKey"]
            acct_name = acct.get("accountDesc", acct_key)
            try:
                resp = api.get_account_portfolio(
                    account_id_key=acct_key,
                    lots_required=True,
                    resp_format="json",
                )
            except Exception as e:
                if _is_empty_response(str(e)):
                    continue
                out.errors.append({
                    "account_id_key": acct_key,
                    "context": "portfolio_fetch",
                    "error": str(e),
                })
                continue

            portfolios = resp.get("PortfolioResponse", {}).get("AccountPortfolio") or []
            if isinstance(portfolios, dict):
                portfolios = [portfolios]
            for portfolio in portfolios:
                positions = portfolio.get("Position") or []
                if isinstance(positions, dict):
                    positions = [positions]
                for pos in positions:
                    prod = pos.get("Product", {}) or {}
                    sec_type = prod.get("securityType")
                    pos_id = pos.get("positionId")
                    symbol = prod.get("symbol", "")
                    url = f"{api.base_url}/{acct_key}/portfolio/{pos_id}.json"
                    try:
                        r = api.session.get(url)
                        r.raise_for_status()
                        data = r.json()
                    except Exception as e:
                        out.errors.append({
                            "account_id_key": acct_key,
                            "symbol": symbol,
                            "context": "lot_fetch",
                            "error": str(e),
                        })
                        continue
                    lots = data.get("PositionLotsResponse", {}).get("PositionLot") or []
                    if isinstance(lots, dict):
                        lots = [lots]
                    for lot_data in lots:
                        try:
                            lot = EtradeLot.model_validate(lot_data)
                            lot = lot.model_copy(update={
                                "account_id_key": acct_key,
                                "account_name": acct_name,
                                "symbol": symbol,
                                "security_type": sec_type,
                            })
                            out.rows.append(lot.to_flat_dict())
                        except Exception as e:
                            out.errors.append({
                                "account_id_key": acct_key,
                                "symbol": symbol,
                                "context": "lot",
                                "error": str(e),
                            })
        return out

    def get_all_balances(self) -> ToolResult:
        api = self._accounts_api()
        out = ToolResult()
        for acct in self._list_brokerage_accounts():
            acct_key = acct["accountIdKey"]
            acct_name = acct.get("accountDesc", acct_key)
            try:
                resp = api.get_account_balance(
                    account_id_key=acct_key,
                    account_type=acct.get("accountType", ""),
                    resp_format="json",
                    real_time_nav=True,
                )
                balance_data = resp["BalanceResponse"]
                balance = EtradeBalance.model_validate(balance_data)
                balance = balance.model_copy(update={
                    "account_id_key": acct_key,
                    "account_name": acct_name,
                })
                out.rows.append(balance.to_flat_dict())
            except Exception as e:
                out.errors.append({
                    "account_id_key": acct_key,
                    "context": "balance",
                    "error": str(e),
                })
        return out

    def get_all_transactions(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ToolResult:
        if start_date is None:
            start_date = date(date.today().year, 1, 1)
        if end_date is None:
            end_date = date.today()

        api = self._accounts_api()
        out = ToolResult()
        for acct in self._list_brokerage_accounts():
            acct_key = acct["accountIdKey"]
            acct_name = acct.get("accountDesc", acct_key)
            try:
                pages = self._paginate(
                    api_func=api.list_transactions,
                    result_path=["TransactionListResponse", "Transaction"],
                    next_token_path=["TransactionListResponse", "marker"],
                    token_param_name="marker",
                    account_id_key=acct_key,
                    start_date=start_date,
                    end_date=end_date,
                    resp_format="json",
                )
                for page in pages:
                    if isinstance(page, dict):
                        page = [page]
                    for txn_data in page:
                        try:
                            txn = EtradeTransaction.model_validate(txn_data)
                            txn = txn.model_copy(update={
                                "account_id_key": acct_key,
                                "account_name": acct_name,
                            })
                            out.rows.append(txn.to_flat_dict())
                        except Exception as e:
                            out.errors.append({
                                "account_id_key": acct_key,
                                "context": "transaction",
                                "error": str(e),
                            })
            except Exception as e:
                err = str(e)
                if _is_empty_response(err):
                    continue
                out.errors.append({
                    "account_id_key": acct_key,
                    "context": "transactions_fetch",
                    "error": err,
                })
        return out

    def get_quotes(self, symbols: list[str]) -> ToolResult:
        api = self._market_api()
        out = ToolResult()
        # E*TRADE limits to 25 symbols per request.
        for i in range(0, len(symbols), 25):
            batch = symbols[i : i + 25]
            try:
                resp = api.get_quote(batch, resp_format="json")
                quote_data = resp["QuoteResponse"]["QuoteData"]
                if not isinstance(quote_data, list):
                    quote_data = [quote_data]
                for qd in quote_data:
                    try:
                        quote = EtradeQuote.model_validate(qd)
                        out.rows.append(quote.to_flat_dict())
                    except Exception as e:
                        out.errors.append({
                            "context": "quote",
                            "error": str(e),
                        })
            except Exception as e:
                out.errors.append({
                    "context": "quote_batch",
                    "symbols": batch,
                    "error": str(e),
                })
        return out


def _is_empty_response(err: str) -> bool:
    """E*TRADE returns 204 No Content or empty bodies for accounts with
    no positions/transactions — not an error, just an empty result."""
    return any(
        marker in err
        for marker in ("204", "No positions", "No Trans", "Expecting value")
    )
