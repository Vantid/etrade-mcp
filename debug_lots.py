"""Probe lots endpoint shape."""
import json
from etrade_mcp.etrade_client import ETradeClient


def main():
    c = ETradeClient()
    api = c._accounts_api()
    accts = c._list_brokerage_accounts()
    target = [a for a in accts if True][-1]  # the non-empty one we saw earlier
    print(f"Account: {target.get('accountDesc')} ({target['accountIdKey']})")

    # First: portfolio with lots_required=True
    resp = api.get_account_portfolio(
        account_id_key=target["accountIdKey"],
        lots_required=True,
        resp_format="json",
    )
    ap = resp["PortfolioResponse"]["AccountPortfolio"][0]
    print("AccountPortfolio[0] keys:", list(ap.keys()))
    positions = ap.get("Position") or []
    print(f"Position count: {len(positions)}")
    if positions:
        print("Position[0] keys:", list(positions[0].keys()))
        print("Sample lots-related fields on Position[0]:")
        for k, v in positions[0].items():
            if "lot" in k.lower() or "Lot" in k:
                print(f"  {k}: {str(v)[:200]}")

    # Try per-position lots via direct URL
    pos = next((p for p in positions if p.get("Product", {}).get("symbol") == "AMZN"), None)
    if pos:
        pos_id = pos["positionId"]
        print(f"\nFetching lots URL for AMZN positionId={pos_id}")
        url = f"{api.base_url}/{target['accountIdKey']}/portfolio/{pos_id}.json"
        r = api.session.get(url)
        print("status:", r.status_code)
        try:
            data = r.json()
            print(json.dumps(data, indent=2, default=str)[:3000])
        except Exception as e:
            print("Body:", r.text[:1000])


if __name__ == "__main__":
    main()
