# Edgework

**Trade analytics for pro traders.**

Edgework is a performance intelligence tool for serious traders on SoDEX.
It turns your raw order history into the one thing PNL doesn't show:
**conditional edge** — the slices of time, regime, and behavior where
you actually make money, and the slices where you give it back.

> Most traders discover that 60–80% of their losses come from
> 10–20% of their setups. Edgework finds those setups.

This project is a submission to the
[SoSoValue Buildathon](https://app.akindo.io/wave-hacks/JBEQXgN4Zi2jA3wA).

---

## What it does

Edgework does three things:

1. **Conditional Performance Mapping.** Pulls every order from your SoDEX
   account and slices winrate, expectancy, and time-in-trade across
   dimensions you don't normally see: time of day, market regime,
   consecutive losses, recovery trades, news sentiment at entry, and more.

2. **Leaderboard-Benchmarked Alpha.** Compares your conditional
   performance against the public SoDEX leaderboard. You don't just see
   "I'm losing in this slice" — you see "top traders also fade this
   setup; you're trading their losing setup."

3. **AI Briefing Before the Session.** A pre-session paragraph (not a
   dashboard) generated from SoSoValue's data feeds and your own
   historical edge in similar regimes. You know in 30 seconds whether
   today is a day to size up, size down, or stay flat.

---

## Stack

- **Python 3.11+** for the analytics core
- **Streamlit** for the live demo (deployable to Streamlit Cloud)
- **Pandas + Plotly** for slicing and visualization
- **Anthropic Claude** for the AI Briefing layer
- **SoSoValue API** for news, indexes, ETF flows, sector rotation
- **SoDEX API** for account history and leaderboard data
- **ValueChain** for on-chain proof of trade history (later phase)

---

## Project structure

```
edgework/
├── src/edgework/
│   ├── sodex_client.py      # SoDEX API client (read-only, account history)
│   ├── sosovalue_client.py  # SoSoValue API client (news, indexes, ETF flows)
│   ├── slicer.py            # Conditional Performance Mapping core
│   ├── benchmark.py         # Leaderboard benchmarking
│   ├── briefing.py          # AI Briefing generator (Anthropic Claude)
│   └── config.py            # Settings, API keys via env vars
├── scripts/
│   ├── pull_history.py      # One-shot: pull your SoDEX history → parquet
│   └── pull_leaderboard.py  # One-shot: pull leaderboard snapshot
├── tests/                   # Unit tests for slicer + benchmark
├── data/                    # Local parquet/CSV cache (gitignored)
├── docs/                    # Architecture notes, API usage plan
├── streamlit_app.py         # Live demo entry point
├── pyproject.toml
└── README.md
```

---

## Running locally

```bash
git clone https://github.com/nftradercrypto/edgework.git
cd edgework
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# fill in: SODEX_API_KEY, SODEX_API_SECRET, SOSOVALUE_API_KEY, ANTHROPIC_API_KEY

# pull your trade history (one-time)
python scripts/pull_history.py

# launch the app
streamlit run streamlit_app.py
```

---

## Wave 1 scope (concept / early prototype)

- [x] Repo + architecture documented
- [ ] SoDEX read-only history puller working with real account
- [ ] Slicer module: winrate / expectancy by hour, day, consecutive losses
- [ ] Streamlit demo: upload history → see your slices
- [ ] AI Briefing v0: SoSoValue news + indexes → Claude → paragraph
- [ ] Public demo deployed
- [ ] Wave 1 video (2–3 min)

Leaderboard benchmark and ValueChain integration arrive in Wave 2.

---

## Author

Built solo by [@nftradercrypto](https://x.com/nftradercrypto).
Top-3 weekly volume trader on SoDEX Season 1, creator of
[TokenBar](https://sosovalue.com/profile/index/1883320395045875714)
on SoSoValue.

---

## License

MIT.
