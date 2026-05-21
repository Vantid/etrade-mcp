# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

## [0.2.0] — 2026-05-21

First public release after a correctness + scope refactor.

### Added
- WealthWatcher-shaped composite tools — output is pre-shaped for
  WealthWatcher's `import_brokerage_transactions` MCP tool:
  - `get_holdings_for_import` — current holdings as importable rows.
  - `get_transactions_for_import(start_date, end_date)` — transactions
    split into trade rows + terminal events.
  - `get_daily_changes(since)` — incremental sync.
- `ETRADE_MODE=sandbox` env var to target the E\*TRADE sandbox API.
- `EtradePosition` now surfaces the `Complete` block: `optionMultiplier`,
  `ivPct`, full greeks (delta/gamma/theta/vega/rho), `lastTrade`, `bid`,
  `ask`, `previousClose`. Lets downstream tools seed accurate marks
  without a second API call.
- `EtradeLot` carries `security_type` (no longer EQ-only).
- IRAs now included in account scan (was BROKERAGE-only).
- Per-row error envelope (`{rows: [...], errors: [...]}`) — failures
  surface in-band instead of being silently logged.
- 29 unit tests (OSI keys, model parsing, WealthWatcher mapping).
- Ruff lint + pytest configured in `pyproject.toml`.
- GitHub Actions CI matrix (Python 3.11, 3.12).
- MIT LICENSE, README, CHANGELOG, CONTRIBUTING.

### Changed
- **Breaking — OSI key format**: now two dashes per OCC convention
  (`AAPL--261219C00200000`), was three dashes. Anyone relying on the
  three-dash form must update.
- **Breaking — account identifier**: tools now return both
  `account_id_key` (stable handle) and `account_name` (display label);
  the old `account_id` field is gone. Use `account_id_key` for dedup.
- All Pydantic models are now `frozen=True`; mutation uses
  `model_copy(update=...)`.
- Tools return `{rows, errors}` envelopes instead of bare lists.
- Debug probe scripts moved from repo root to `dev/`.
- Console entry point now uses an explicit `main()` function.

### Fixed
- 2-digit-year handling in OSI key generation (E\*TRADE sometimes
  returns `expiryYear: 26`, sometimes `2026`).
- Empty-response detection covers more pyetrade error shapes (204,
  empty-body JSONDecodeError, "No positions", "No Trans").
- Account-list response normalization for the single-account case
  (E\*TRADE returns a dict, not a list, when there's one).
- Pagination's `marker` token now correctly advances on subsequent
  pages (the old code reset `token = response` and re-traversed each
  iteration, which worked but was less clear).

## [0.1.0] — Initial import

Original upstream snapshot. Five tools (`get_portfolio`, `get_lots`,
`get_balance`, `get_transactions`, `get_quote`), pyetrade-based, OAuth
via macOS Keychain.
