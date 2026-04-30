# Changelog

All notable changes to Edgework will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- SoDEX client rewritten for the official read-only API model: read endpoints are public (no auth, no signing), require only `userAddress` in the URL path. Previous HMAC-based auth model removed entirely.
- `slicer.normalize_orders` now reads `positionSide` ("LONG"/"SHORT") and `cumClosedSize` from the official SoDEX `Position` schema. Closed positions correctly identified as long/short and sized by traded volume rather than current open exposure.
- Configuration: `SODEX_USER_ADDRESS` replaces `SODEX_API_KEY` + `SODEX_API_SECRET`. Base URL now includes `/api/v1` prefix.

### Added
- Validated against live SoDEX mainnet: 277 closed positions normalized end-to-end.
- New unit test for the official SoDEX `Position` schema using realistic payload shapes.
- New SoDEX client methods: `get_position_history`, `get_open_positions`, `get_user_trades`, `get_balances`, `get_fee_rate`, `get_account_state`, `get_perps_tickers`, `get_perps_mark_prices`, `get_perps_orderbook`.

### Removed
- HMAC auth path (`SodexAuth` class) - replaced by no-auth read model. EIP-712 signing for write actions is planned for Wave 2+.

## [0.1.0] - 2026-04-29 - Wave 1 kickoff

### Added
- Initial repository structure with src layout (`src/edgework/`).
- `slicer` module: Conditional Performance Mapping core, with seven dimensions (hour of day, day of week, side, symbol, consecutive losses, size quartile, hold duration).
- `sodex_client`: read-only SoDEX API client (account, fills, order history, leaderboard, klines).
- `sosovalue_client`: read-only SoSoValue API client (news, ETF flows, SSI indexes, sectors).
- `briefing` module: AI Briefing layer powered by Anthropic Claude; combines `TraderEdge` from slicer output with live `MarketContext` from SoSoValue into a single 90-140 word pre-session paragraph.
- `streamlit_app.py`: live demo UI with three data sources (file upload, paste JSON, synthetic demo data), conditional performance tabs, and on-demand briefing generation.
- `scripts/pull_history.py`: one-shot CLI to pull and cache the trader's SoDEX history to local parquet.
- Unit tests for the slicer (5 passing).
- `pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE`.
- Architecture document (`docs/architecture.md`) with workflow diagram and per-API usage plan.