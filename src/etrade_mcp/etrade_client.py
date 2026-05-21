from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Iterator

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


class ETradeClient:
    def __init__(self) -> None:
        creds = get_credentials()
        self._consumer_key = creds["consumer-key"]
        self._consumer_secret = creds["consumer-secret"]
        self._oauth_token = creds["oauth-token"]
        self._oauth_token_secret = creds["oauth-token-secret"]

    def _accounts_api(self) -> pyetrade.ETradeAccounts:
        return pyetrade.ETradeAccounts(
            self._consumer_key,
            self._consumer_secret,
            self._oauth_token,
            self._oauth_token_secret,
            dev=False,
        )

    def _market_api(self) -> pyetrade.ETradeMarket:
        return pyetrade.ETradeMarket(
            self._consumer_key,
            self._consumer_secret,
            self._oauth_token,
            self._oauth_token_secret,
            dev=False,
        )

    def _list_brokerage_accounts(self) -> list[dict[str, Any]]:
        api = self._accounts_api()
        resp = api.list_accounts(resp_format="json")
        accounts = resp["AccountListResponse"]["Accounts"]["Account"]
        return [
            a
            for a in accounts
            if a.get("institutionType") == "BROKERAGE"
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
        token = None
        while True:
            kwargs[token_param_name] = token
            response = api_func(**kwargs)

            data = response
            for key in result_path:
                data = data[key]

            token = response
            for key in next_token_path:
                token = None if token is None else token.get(key)

            yield data

            if token is None:
                break

    def get_all_positions(self) -> list[dict]:
        api = self._accounts_api()
        results: list[dict] = []
        for acct in self._list_brokerage_accounts():
            acct_id = acct["accountIdKey"]
            acct_desc = acct.get("accountDesc", acct_id)
            try:
                page_number: int | None = None
                while True:
                    resp = api.get_account_portfolio(
                        account_id_key=acct_id,
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
                                pos.account_id = acct_desc
                                results.append(pos.to_flat_dict())
                            except Exception as e:
                                logger.warning("Skipping position: %s", e)
                        np = portfolio.get("nextPageNo")
                        if np is not None:
                            next_page = int(np)
                    if not next_page:
                        break
                    page_number = next_page
            except Exception as e:
                err = str(e)
                if (
                    "204" in err
                    or "No positions" in err
                    or "Expecting value" in err  # pyetrade JSONDecodeError on empty body
                ):
                    logger.debug("No positions for account %s", acct_desc)
                else:
                    logger.warning("Error fetching positions for %s: %s", acct_desc, e)
        return results

    def get_all_position_lots(self) -> list[dict]:
        api = self._accounts_api()
        results: list[dict] = []
        for acct in self._list_brokerage_accounts():
            acct_id = acct["accountIdKey"]
            acct_desc = acct.get("accountDesc", acct_id)
            try:
                resp = api.get_account_portfolio(
                    account_id_key=acct_id,
                    lots_required=True,
                    resp_format="json",
                )
            except Exception as e:
                err = str(e)
                if "204" in err or "No positions" in err or "Expecting value" in err:
                    continue
                logger.warning("Error fetching portfolio for %s: %s", acct_desc, e)
                continue
            portfolios = (
                resp.get("PortfolioResponse", {}).get("AccountPortfolio") or []
            )
            if isinstance(portfolios, dict):
                portfolios = [portfolios]
            for portfolio in portfolios:
                positions = portfolio.get("Position") or []
                if isinstance(positions, dict):
                    positions = [positions]
                for pos in positions:
                    prod = pos.get("Product", {}) or {}
                    if prod.get("securityType") != "EQ":
                        continue
                    pos_id = pos.get("positionId")
                    symbol = prod.get("symbol")
                    url = f"{api.base_url}/{acct_id}/portfolio/{pos_id}.json"
                    try:
                        r = api.session.get(url)
                        r.raise_for_status()
                        data = r.json()
                    except Exception as e:
                        logger.warning("Lot fetch failed for %s: %s", symbol, e)
                        continue
                    lots = (
                        data.get("PositionLotsResponse", {}).get("PositionLot") or []
                    )
                    if isinstance(lots, dict):
                        lots = [lots]
                    for lot_data in lots:
                        try:
                            lot = EtradeLot.model_validate(lot_data)
                            lot = lot.model_copy(
                                update={"account_id": acct_desc, "symbol": symbol or ""}
                            )
                            results.append(lot.to_flat_dict())
                        except Exception as e:
                            logger.warning("Skipping lot: %s", e)
        return results

    def get_all_balances(self) -> list[dict]:
        api = self._accounts_api()
        results: list[dict] = []
        for acct in self._list_brokerage_accounts():
            acct_id = acct["accountIdKey"]
            acct_desc = acct.get("accountDesc", acct_id)
            try:
                resp = api.get_account_balance(
                    account_id_key=acct_id,
                    account_type=acct.get("accountType", ""),
                    resp_format="json",
                    real_time_nav=True,
                )
                balance_data = resp["BalanceResponse"]
                balance = EtradeBalance.model_validate(balance_data)
                balance.account_id = acct_desc
                results.append(balance.to_flat_dict())
            except Exception as e:
                logger.warning("Error fetching balance for %s: %s", acct_desc, e)
        return results

    def get_all_transactions(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        if start_date is None:
            start_date = date(date.today().year, 1, 1)
        if end_date is None:
            end_date = date.today()

        api = self._accounts_api()
        results: list[dict] = []
        for acct in self._list_brokerage_accounts():
            acct_id = acct["accountIdKey"]
            acct_desc = acct.get("accountDesc", acct_id)
            try:
                pages = self._paginate(
                    api_func=api.list_transactions,
                    result_path=["TransactionListResponse", "Transaction"],
                    next_token_path=["TransactionListResponse", "marker"],
                    token_param_name="marker",
                    account_id_key=acct_id,
                    start_date=start_date,
                    end_date=end_date,
                    resp_format="json",
                )
                for page in pages:
                    for txn_data in page:
                        try:
                            txn = EtradeTransaction.model_validate(txn_data)
                            txn = txn.model_copy(update={"account_id": acct_desc})
                            results.append(txn.to_flat_dict())
                        except Exception as e:
                            logger.warning("Skipping transaction: %s", e)
            except Exception as e:
                if "204" in str(e) or "No Trans" in str(e):
                    logger.debug("No transactions for account %s", acct_desc)
                else:
                    logger.warning("Error fetching transactions for %s: %s", acct_desc, e)
        return results

    def get_quotes(self, symbols: list[str]) -> list[dict]:
        api = self._market_api()
        results: list[dict] = []
        # E*TRADE limits to 25 symbols per request
        for i in range(0, len(symbols), 25):
            batch = symbols[i : i + 25]
            try:
                resp = api.get_quote(batch, resp_format="json")
                quote_data = resp["QuoteResponse"]["QuoteData"]
                if not isinstance(quote_data, list):
                    quote_data = [quote_data]
                for qd in quote_data:
                    quote = EtradeQuote.model_validate(qd)
                    results.append(quote.to_flat_dict())
            except Exception as e:
                logger.warning("Error fetching quotes for %s: %s", batch, e)
        return results
