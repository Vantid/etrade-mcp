import keyring

SERVICE = "etrade-mcp"

_KEYS = ("consumer-key", "consumer-secret", "oauth-token", "oauth-token-secret")


def get_credentials() -> dict[str, str]:
    creds = {}
    missing = []
    for key in _KEYS:
        val = keyring.get_password(SERVICE, key)
        if val is None:
            missing.append(key)
        else:
            creds[key] = val
    if missing:
        raise RuntimeError(
            f"Missing keychain entries for {SERVICE}: {', '.join(missing)}. "
            "Run `etrade-auth` to configure credentials."
        )
    return creds


def set_consumer_credentials(key: str, secret: str) -> None:
    keyring.set_password(SERVICE, "consumer-key", key)
    keyring.set_password(SERVICE, "consumer-secret", secret)


def set_oauth_tokens(token: str, secret: str) -> None:
    keyring.set_password(SERVICE, "oauth-token", token)
    keyring.set_password(SERVICE, "oauth-token-secret", secret)
