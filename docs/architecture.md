# Edgework — Architecture & API Usage Plan

## Workflow

```
┌──────────────────┐       ┌──────────────────┐
│   SoDEX API      │       │   SoSoValue API  │
│  (read-only)     │       │  (read-only)     │
│                  │       │                  │
│ • account orders │       │ • news + sent.   │
│ • fills          │       │ • SSI indexes    │
│ • leaderboard    │       │ • ETF flows      │
│ • klines         │       │ • sectors        │
└────────┬─────────┘       └────────┬─────────┘
         │                          │
         ▼                          ▼
┌──────────────────┐       ┌──────────────────┐
│  sodex_client    │       │ sosovalue_client │
└────────┬─────────┘       └────────┬─────────┘
         │                          │
         ▼                          │
┌──────────────────┐                │
│     slicer       │                │
│                  │                │
│  Conditional     │                │
│  Performance     │                │
│  Mapping         │                │
└────────┬─────────┘                │
         │                          │
         │     ┌────────────────────┘
         │     │
         ▼     ▼
┌──────────────────────┐
│      briefing        │
│                      │
│  TraderEdge          │
│  + MarketContext     │
│  → Anthropic Claude  │
│  → 1 paragraph       │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   streamlit_app      │
│   (live demo)        │
└──────────────────────┘
```

## API usage plan

### SoSoValue API (required by Buildathon rules)
- `news/list` — used for sentiment context input to the briefing prompt
- `etf/btc/currentEtfDataMetrics` — institutional flow signal
- `etf/eth/currentEtfDataMetrics` — same for ETH
- `sectors/list` — sector rotation regime variable
- `indices/list` + `indices/{symbol}` — SSI index regime context
  (planned for Wave 2: per-trade regime tagging)

### SoDEX API (required for the trader-edge half of the product)
- `perps/account` — verify auth, account tier
- `perps/trade/fills` — primary source for trade history
- `perps/trade/orders/history` — fallback if fills endpoint shape differs
- `leaderboard` — Wave 2: benchmark trader's slices vs top-50 (planned)
- `market/klines` — Wave 2: regime classification per trade entry (planned)

### Anthropic Claude
- `messages.create` with `claude-sonnet-4-20250514`
- System prompt enforces tight, trader-to-trader voice
- User prompt is a structured digest of TraderEdge + MarketContext —
  small, deterministic, low-cost (~400 tokens out)

## Why this shape

1. **Read-only first.** Wave 1 needs no order signing. The product is
   useful as pure analytics before any execution path is added. Removes
   EIP-712 signing as a blocker for the prototype.

2. **Slicer is the moat.** Anyone can pipe an LLM at SoSoValue news.
   The competitive defense is the personal conditional-performance
   engine — its outputs are what make the briefing specific instead of
   generic. The slicer runs on the trader's own data, so a generic
   competitor can't replicate without each user's history.

3. **One paragraph, not a dashboard.** Existing tools in the
   buildathon submissions are dashboards. Edgework's primary output is
   a single paragraph of decision-grade prose. Trading attention is
   the scarce resource; we optimize for that constraint.

## Wave plan

### Wave 1 (May 1–12) — this submission
- [x] Repo structure, README, architecture
- [x] Slicer module + 5 passing tests
- [x] SoDEX read-only client
- [x] SoSoValue client
- [x] Briefing module (Anthropic Claude)
- [x] Streamlit app (demo data + upload paths)
- [ ] Live demo deployed to Streamlit Cloud
- [ ] Pull author's real SoDEX history; validate end-to-end
- [ ] 2–3 minute demo video

### Wave 2 (May 18–29)
- Leaderboard benchmarking: compare user's slices to top-50 traders
- Per-trade regime tagging using SSI index history at entry time
- Persistent caching layer (avoid recomputing slices on every reload)
- Trade-journal export

### Wave 3 (Jun 4–15)
- Optional execution layer (resolves EIP-712 signing for limit orders)
- Risk-control hooks: cooldowns triggered by Edgework's own anti-pattern
  detector (only acts when the trader explicitly opts in)
- Session-replay: visualize a single trading day's decisions vs edge map
