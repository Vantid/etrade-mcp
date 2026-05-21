# Contributing

Thanks for considering a contribution.

## Setup

```bash
git clone https://github.com/Vantid/etrade-mcp
cd etrade-mcp
uv sync --extra dev
```

## Run tests + lint

```bash
uv run pytest
uv run ruff check src tests
```

CI runs both on every push/PR against `main` (see `.github/workflows/ci.yml`).

## Running against the sandbox

E\*TRADE provides a sandbox API at `apisb.etrade.com`. Apply for a
sandbox consumer key at [developer.etrade.com](https://developer.etrade.com),
then:

```bash
ETRADE_MODE=sandbox uv run etrade-auth   # one-time OAuth setup
ETRADE_MODE=sandbox uv run etrade-mcp    # run the server
```

Sandbox cost-basis values are often synthetic ($0 or $1/share for
positions worth much more). The mapper in `vantid.py` falls back
to `marketValue / quantity` when `pricePaid` is 0 — be aware when
testing against sandbox data.

## Code style

- Python 3.11+, type hints encouraged but not strictly enforced.
- Ruff (line length 100, default rules + B + UP).
- Pydantic models are `frozen=True`; use `model_copy(update=...)`.
- Tools always return `{rows: [...], errors: [...]}` envelopes —
  never raise; collect per-row errors and surface them.

## Adding a tool

1. Add a method to `ETradeClient` in `etrade_client.py` returning a
   `ToolResult`.
2. Register it in `server.py` as a `@mcp.tool()`-decorated function.
3. If the tool produces Vantid-shaped rows, factor the mapping
   into `vantid.py` and add a test in
   `tests/test_vantid_mapping.py`.

## What to flag in PRs

- Schema changes to tool outputs — these are breaking for downstream
  agents and need a CHANGELOG entry.
- New dependencies — keep the install footprint small.
- E\*TRADE response shapes you discovered that differ from what the
  models assume — they vary across account types.

## License

By contributing, you agree your contributions are licensed under
[MIT](LICENSE).
