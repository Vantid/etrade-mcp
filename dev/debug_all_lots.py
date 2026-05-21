"""Dump all lots across all equity positions as JSON."""
import json
from datetime import datetime
from etrade_mcp.etrade_client import ETradeClient


def main():
    c = ETradeClient()
    api = c._accounts_api()
    out = []
    for acct in c._list_brokerage_accounts():
        acct_id = acct["accountIdKey"]
        acct_desc = acct.get("accountDesc", acct_id)
        try:
            resp = api.get_account_portfolio(
                account_id_key=acct_id, lots_required=True, resp_format="json"
            )
        except Exception:
            continue
        for portfolio in (resp.get("PortfolioResponse", {}).get("AccountPortfolio") or []):
            for pos in (portfolio.get("Position") or []):
                prod = pos.get("Product", {})
                if prod.get("securityType") != "EQ":
                    continue
                pos_id = pos["positionId"]
                url = f"{api.base_url}/{acct_id}/portfolio/{pos_id}.json"
                try:
                    r = api.session.get(url)
                    r.raise_for_status()
                    data = r.json()
                except Exception as e:
                    print(f"Lot fetch failed for {prod.get('symbol')}: {e}")
                    continue
                lots = data.get("PositionLotsResponse", {}).get("PositionLot") or []
                if isinstance(lots, dict):
                    lots = [lots]
                for lot in lots:
                    ms = lot.get("acquiredDate")
                    dt = (
                        datetime.fromtimestamp(ms / 1000).date().isoformat()
                        if ms else None
                    )
                    out.append({
                        "account": acct_desc,
                        "symbol": prod.get("symbol"),
                        "acquired_date": dt,
                        "price": lot.get("price"),
                        "originalQty": lot.get("originalQty"),
                        "remainingQty": lot.get("remainingQty"),
                        "totalCost": lot.get("totalCost"),
                        "termCode": lot.get("termCode"),  # 1=LT, 2=ST
                        "positionLotId": lot.get("positionLotId"),
                    })
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
