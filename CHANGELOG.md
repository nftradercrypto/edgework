# Changelog

All notable changes to Edgework will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — Wave 3 (final): from analytics to action

### Added — Execution layer (`src/edgework/exchange/`)
- EIP-712 signing pipeline for SoDEX (`signing.py`), ported bit-for-bit from a
  production trading client and pinned against a known-good signature vector.
- `order_builder.py`: turns a position + reason into a **reduce-only** close
  order. `simulate()` signs with an ephemeral throwaway key and sends nothing —
  what the hosted app uses, zero custody risk.
- `execution_client.py`: LOCAL-ONLY live submission to SoDEX `/exchange`.
- In-app "Close · SIM" buttons render the full signed order (digest, signature,
  exact POST body) per open position.
- `scripts/edgework_exec.py`: local companion CLI for real reduce-only closes
  (dry-run by default; `--live` requires a typed `YES`). Keys never leave the
  user's machine; the hosted app is simulation-only.

### Added — Smart Money Divergence alerts (Discord)
- `smart_money.py`: pure, importable consensus + open-positions fetch shared by
  the app and the poller.
- `alerts.py`: divergence detection, Discord embed formatting, webhook send, and
  a dedupe state so the same open position never double-pings.
- `scripts/alert_bot.py`: local read-only poller (`--test` / `--once` / loop).
- In-app webhook wizard: test the webhook + copy the command to run the watcher.

### Added — Contrarian track record (the evidence behind the alert)
- Reconstructs the smart-money book at each past entry from top traders'
  position history and classifies the trader's trades aligned / contrarian /
  no-signal, with winrate + expectancy per bucket.

### Changed — Statistical rigor
- Verdict confidence is now a real **bootstrap probability** (2,000 resamples)
  with a small-sample honesty cap, replacing a decorative sample-size heuristic.
- `sodex_client._get` retries 429/5xx so a rate-limited wallet no longer
  silently skews the smart-money consensus.
- Smart-money and peer-benchmark fetches parallelized (cold load ~8-15s → ~1.5s).
- AI tool filters fold dash/case variants ("5-30m" now matches the en-dash
  bucket label) so the diagnostic never reasons over silently-empty filters.

### Added — UX & clarity
- TL;DR card: deterministic 10-second read (biggest leak / best edge / fees).
- Numbered anchor navigation across the long page.
- One-click "try a top trader's wallet" demo.
- Tooltips on every technical term, including how the bootstrap confidence works.
- Progressive disclosure (waterfall + risk filters collapsed by default).
- Fees decomposition (gross vs fees vs net), profit factor, max drawdown.
- Tilt detector: live loss-streak banner citing the trader's own historical
  expectancy for that streak bucket.
- Low-sample (n<15) badges on conditional-performance cards.
- Mobile pass; fixed a cold-load bug where bookmarked `?w=` links rendered empty.

### Dependencies
- Added `eth-keys`, `eth-utils`, `eth-hash[pycryptodome]` (no `web3`).

### Tests
- `test_exchange.py`, `test_qna_filters.py`, `test_alerts.py` added. 33 passing.

## [0.2.0] - Wave 2 (1st place) — Leaderboard-benchmarked alpha

### Added
- **Smart Money Watch**: live aggregation of the open positions of the top 20
  active+profitable SoDEX traders (top 50 by 30d volume → PNL>0), with per-symbol
  LONG/SHORT/NET exposure. 15-minute cache.
- **Your Positions vs Smart Money**: live aligned/contrarian/mixed classification
  of each of your open positions against the qualified book.
- **Counterfactual equity curve**: dashed overlay showing PNL if the risk-filter
  anti-patterns had been skipped.
- **Peer benchmark** vs the top-5 traders, per conditional slice.
- **Full Diagnostic**: single deterministic Claude Sonnet 4.6 tool-use call
  ("5 biggest problems + 3-5 rules"), every number backed by a tool call.
- **BTC regime tagging** (uptrend/downtrend/chop) as an 8th slicer dimension.
- **2D risk filter**: cross-dimensional anti-pattern detector.
- **Volume-ranked wallet banner**, day-of-week × hour-of-day heatmap,
  bookmarkable URL state, and full PT/EN i18n.
- Live SoDEX history pull by wallet address (no upload needed).

## [0.1.x] - Wave 1 → Wave 2 transition

### Changed
- SoDEX client rewritten for the official read-only API model: read endpoints are
  public (no auth, no signing), require only `userAddress` in the URL path.
- `slicer.normalize_orders` reads `positionSide` ("LONG"/"SHORT") and
  `cumClosedSize` from the official SoDEX `Position` schema.
- Configuration: `SODEX_USER_ADDRESS` replaces `SODEX_API_KEY` + `SODEX_API_SECRET`.

### Added
- Validated against live SoDEX mainnet (closed positions normalized end-to-end).
- SoDEX client methods: `get_position_history`, `get_open_positions`,
  `get_user_trades`, `get_balances`, `get_fee_rate`, `get_account_state`,
  `get_perps_tickers`, `get_perps_mark_prices`, `get_perps_orderbook`.

## [0.1.0] - 2026-04-29 - Wave 1 (1st place) kickoff

### Added
- Initial repository structure with src layout (`src/edgework/`).
- `slicer` module: Conditional Performance Mapping core, seven dimensions
  (hour of day, day of week, side, symbol, consecutive losses, size quartile,
  hold duration).
- `sodex_client`: read-only SoDEX API client (account, fills, order history,
  leaderboard, klines).
- `sosovalue_client`: read-only SoSoValue API client (news, ETF flows, SSI
  indexes, sectors).
- `briefing` module: AI Briefing layer powered by Anthropic Claude.
- `streamlit_app.py`: live demo UI with conditional performance tabs and
  on-demand briefing generation.
- `scripts/pull_history.py`: one-shot CLI to cache SoDEX history to parquet.
- Unit tests for the slicer; `pyproject.toml`, `.env.example`, `.gitignore`,
  `LICENSE`; architecture document (`docs/architecture.md`).
