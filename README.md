# Edgework

**Trade analytics for pro traders.**

> 🏆 **Wave 1 winner (1st place).** Wave 1 submission preserved at tag
> [`wave-1-final`](https://github.com/nftradercrypto/edgework/releases/tag/wave-1-final)
> and branch `wave-1`. The current `main` is the **Wave 2 submission**.

Edgework is a performance intelligence tool for serious traders on SoDEX.
It turns your raw order history into the one thing PNL doesn't show:
**conditional edge** — the slices of time, regime, and behavior where you
actually make money, and the slices where you give it back.

> Most traders discover that 60–80% of their losses come from
> 10–20% of their setups. Edgework finds those setups, benchmarks
> them against the SoDEX leaderboard, and warns you when you're
> about to trade against the smart-money book.

Live app: **[edgework.streamlit.app](https://edgework.streamlit.app)**
Submission: [SoSoValue Buildathon](https://app.akindo.io/wave-hacks/JBEQXgN4Zi2jA3wA)

---

## What's in Wave 2

Everything from Wave 1, plus six new value props that turn Edgework from
a *diagnostic dashboard* into a *decision tool you use every session*:

### 1 · Counterfactual Equity Curve
A dashed overlay on your equity chart showing **what your PNL would have
been if you'd skipped the trades flagged by the risk filters**. Quantifies
the dollar value of your worst patterns directly on the chart — not buried
in a table somewhere.

### 2 · Smart Money Watch (live)
A real-time snapshot of where the **top 20 active+profitable SoDEX traders**
are positioned right now. We pull the top 50 by 30-day volume, filter to
those with positive PNL (so you don't see the lucky one-shot whales), then
aggregate their open positions per symbol into LONG / SHORT / NET exposure.
Refreshes every 15 min.

### 3 · Your Positions vs Smart Money
Compares each of your open positions to the smart-money consensus on the
same symbol. Flags **✓ aligned**, **⚠ contrarian** (≥3 traders or 2× notional
dominance opposite to you), or **~ mixed**. The first step toward the
Discord alert bot — once it's wired up, you get notified the moment you
open a contrarian trade.

### 4 · Volume-Ranked Wallet Banner
Replaces the old PNL rank (skewed by 118k dormant wallets) with **30-day
volume rank** — a real signal of activity, not noise. Tells you where you
stand among traders who *actually trade*.

### 5 · Full Diagnostic (single-call AI)
Replaces the old briefing + Q&A buttons with one **"Generate diagnostic"**
CTA. A deterministic tool-use loop powered by Claude Sonnet 4.6 that always
calls `get_full_breakdown` first (one cheap call covers ~all data), then
produces a structured autopsy: **the 5 biggest problems destroying your
account** + **3-5 specific rules to implement**. Every cited number is
backed by a tool call against your data — no hallucinations.

### 6 · PT/EN i18n
Full UI translation — toggle at the top right. Topbar, slicers, equity
curve, verdict, confrontation, waterfall, performance tabs, peer benchmark,
smart money watch, your-positions-vs-smart-money, risk filters, diagnostic
prompt, bottombar — every label and every dynamic insight string.

### Bonus polish (already in Wave 1 but expanded)
- Bookmarkable URL state — slicer filters + wallet survive a refresh / share
- BTC regime tagging (uptrend / downtrend / chop) as a slicer dimension
- 2D risk filter (cross-dimensional anti-pattern detector)
- Heatmap day-of-week × hour-of-day
- Peer benchmark vs top-5 traders with PT/EN dynamic insights

---

## What it does (the core, from Wave 1)

1. **Conditional Performance Mapping.** Pulls every order from your SoDEX
   account and slices winrate, expectancy, and time-in-trade across
   dimensions you don't normally see: time of day, day of week, BTC regime,
   consecutive losses, position size quartile, hold duration, side bias,
   and per-symbol performance.

2. **Leaderboard-Benchmarked Alpha.** Compares your conditional performance
   against the public SoDEX leaderboard top traders. You don't just see
   *"I'm losing in this slice"* — you see *"top traders also fade this
   setup; you're trading their losing setup."*

3. **AI-Powered Diagnostic.** A single-call Claude diagnostic that runs a
   full autopsy of your history and produces ranked, dollar-quantified
   problems + specific rules. Prompt-cached for repeat-session efficiency.

---

## Stack

- **Python 3.13+** for the analytics core
- **Streamlit ≥ 1.39** for the live demo (deployable to Streamlit Cloud)
- **Pandas 3.x + Plotly** for slicing and visualization
- **Anthropic Claude Sonnet 4.6** for the diagnostic engine (with prompt
  caching + tool use)
- **SoSoValue API** for news, indexes, ETF flows, sector rotation
- **SoDEX Public API** for account history, leaderboard, live positions
- **ValueChain** for on-chain proof of trade history (later phase)

---

## Project structure

```
edgework/
├── src/edgework/
│   ├── sodex_client.py      # SoDEX API client (read-only, account + leaderboard)
│   ├── sosovalue_client.py  # SoSoValue API client (news, indexes, ETF flows)
│   ├── slicer.py            # Conditional Performance Mapping core
│   ├── benchmark.py         # Leaderboard benchmarking
│   ├── briefing.py          # Legacy briefing (kept for back-compat)
│   ├── qna.py               # Wave 2: Full diagnostic engine (Claude tool use)
│   └── config.py            # Settings, API keys via env vars
├── tests/                   # Unit tests for slicer + benchmark
├── data/                    # Local parquet/CSV cache (gitignored)
├── docs/                    # Architecture notes, API usage plan
├── streamlit_app.py         # Live app entry point
├── pyproject.toml
└── README.md
```

---

## Running locally

```bash
git clone https://github.com/nftradercrypto/edgework.git
cd edgework
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in:
#   SODEX_USER_ADDRESS     — your EVM wallet (read-only, no auth needed)
#   SOSOVALUE_API_KEY      — for news / indexes / ETF flows
#   ANTHROPIC_API_KEY      — for the AI diagnostic

streamlit run streamlit_app.py
```

The app loads a wallet's full SoDEX history via the public read API
(`mainnet-gw.sodex.dev`), so no upload step is required — paste any
SoDEX wallet address and you see the analytics immediately.

---

## Author

Built solo by [@nftradercrypto](https://x.com/nftradercrypto).
Wave 1 winner (1st place) of the SoSoValue Buildathon.
Top-3 weekly volume trader on SoDEX Season 1, creator of
[TokenBar](https://sosovalue.com/profile/index/1883320395045875714)
on SoSoValue.

---

## License

MIT.
