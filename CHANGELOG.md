# Changelog

All notable changes to Edgework will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- SoDEX base URL updated to `https://mainnet-gw.sodex.dev` (confirmed via Buildathon API channel).
- `get_klines` now uses the perps-specific path `/api/v1/perps/markets/{symbol}/klines`.

### Added
- `get_perps_symbols()` — list available perps markets dynamically.
- `get_spot_klines()` and `get_spot_symbols()` — spot market support (uses `v` / `w` prefixed virtual/wrapped naming).



### Changed
- SoDEX base URL updated to `https://mainnet-gw.sodex.dev` (confirmed
  via Buildathon API channel).
- `get_klines` now uses the perps-specific path
  `/api/v1/perps/markets/{symbol}/klines`.

### Added
- `get_perps_symbols()` â€” list available perps markets dynamically.
- `get_spot_klines()` and `get_spot_symbols()` â€” spot market support
  (uses `v` / `w` prefixed virtual/wrapped naming).
## [0.1.0] â€” 2026-04-29 â€” Wave 1 kickoff

### Added
- Initial repository structure with src layout (`src/edgework/`).
- `slicer` module: Conditional Performance Mapping core, with seven
  dimensions (hour of day, day of week, side, symbol, consecutive
  losses, size quartile, hold duration).
- `sodex_client`: read-only SoDEX API client (account, fills, order
  history, leaderboard, klines).
- `sosovalue_client`: read-only SoSoValue API client (news, ETF flows,
  SSI indexes, sectors).
- `briefing` module: AI Briefing layer powered by Anthropic Claude;
  combines `TraderEdge` from slicer output with live `MarketContext`
  from SoSoValue into a single 90â€“140 word pre-session paragraph.
- `streamlit_app.py`: live demo UI with three data sources
  (file upload, paste JSON, synthetic demo data), conditional
  performance tabs, and on-demand briefing generation.
- `scripts/pull_history.py`: one-shot CLI to pull and cache the
  trader's SoDEX history to local parquet.
- Unit tests for the slicer (5 passing).
- `pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE`.
- Architecture document (`docs/architecture.md`) with workflow diagram
  and per-API usage plan.
