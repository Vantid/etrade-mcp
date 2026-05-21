import pyetrade

from etrade_mcp.keychain import get_credentials, set_consumer_credentials, set_oauth_tokens


def main():
    # Check for existing consumer credentials
    consumer_key = None
    consumer_secret = None
    try:
        creds = get_credentials()
        consumer_key = creds["consumer-key"]
        consumer_secret = creds["consumer-secret"]
        print(f"Found existing consumer key: {consumer_key[:8]}...")
        reuse = input("Reuse existing consumer credentials? [Y/n]: ").strip().lower()
        if reuse == "n":
            consumer_key = None
            consumer_secret = None
    except RuntimeError:
        pass

    if consumer_key is None:
        consumer_key = input("Enter consumer key: ").strip()
        consumer_secret = input("Enter consumer secret: ").strip()

    set_consumer_credentials(consumer_key, consumer_secret)

    # OAuth flow
    oauth = pyetrade.ETradeOAuth(consumer_key, consumer_secret)
    request_token = oauth.get_request_token()
    print(f"\nAuthorize this app at:\n{request_token}")
    verifier = input("\nEnter verification code: ").strip()
    tokens = oauth.get_access_token(verifier)

    set_oauth_tokens(tokens["oauth_token"], tokens["oauth_token_secret"])
    print("\nCredentials stored in macOS Keychain (service: etrade-mcp).")


if __name__ == "__main__":
    main()
