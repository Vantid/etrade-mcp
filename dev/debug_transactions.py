"""Dump raw E*TRADE transaction data to inspect the structure."""

import json
from datetime import date
from etrade_mcp.etrade_client import ETradeClient


def main():
    client = ETradeClient()
    api = client._accounts_api()

    for acct in client._list_brokerage_accounts():
        acct_id = acct["accountIdKey"]
        acct_desc = acct.get("accountDesc", acct_id)
        print(f"\n{'='*60}")
        print(f"Account: {acct_desc}")
        print(f"{'='*60}")

        try:
            pages = client._paginate(
                api_func=api.list_transactions,
                result_path=["TransactionListResponse", "Transaction"],
                next_token_path=["TransactionListResponse", "marker"],
                token_param_name="marker",
                account_id_key=acct_id,
                start_date=date(2024, 1, 1),
                end_date=date.today(),
                resp_format="json",
            )
            for page in pages:
                for txn in page:
                    # Look for anything options-related
                    brokerage = txn.get("brokerage", {})
                    product = brokerage.get("product") if brokerage else None
                    desc = txn.get("description", "")
                    txn_type = txn.get("transactionType", "")

                    # Print ALL transactions with their brokerage structure
                    # so we can spot options trades
                    has_options_hint = any(
                        kw in desc.upper()
                        for kw in ["CALL", "PUT", "OPTN", "OPTION", "STRIKE", "CONTRACT"]
                    )

                    if has_options_hint or (product and product.get("securityType") == "OPTN"):
                        print(f"\n--- POSSIBLE OPTIONS TXN ---")
                        print(json.dumps(txn, indent=2, default=str))
                    else:
                        # Print summary for non-options
                        print(f"  {txn_type:20s} | {desc:50s} | product={product}")

        except Exception as e:
            print(f"  Error: {e}")


if __name__ == "__main__":
    main()
