"""Dump raw portfolio response to inspect shape."""
import json
from etrade_mcp.etrade_client import ETradeClient


def main():
    client = ETradeClient()
    api = client._accounts_api()
    for acct in client._list_brokerage_accounts():
        acct_id = acct["accountIdKey"]
        print(f"\n=== Account: {acct.get('accountDesc', acct_id)} ===")
        try:
            resp = api.get_account_portfolio(
                account_id_key=acct_id,
                resp_format="json",
            )
            print(json.dumps(resp, indent=2, default=str)[:4000])
            print("---")
            pr = resp.get("PortfolioResponse", {})
            ap = pr.get("AccountPortfolio")
            print("type(AccountPortfolio):", type(ap).__name__)
            if isinstance(ap, list) and ap:
                print("type(AccountPortfolio[0]):", type(ap[0]).__name__)
                print("keys[0]:", list(ap[0].keys()))
                pos = ap[0].get("Position")
                print("type(Position):", type(pos).__name__)
        except Exception as e:
            print("ERROR:", type(e).__name__, e)


if __name__ == "__main__":
    main()
