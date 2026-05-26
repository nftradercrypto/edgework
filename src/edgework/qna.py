"""AI Q&A — natural-language queries over the trader's own data.

The trader types a question in the dashboard. Claude calls a small set of
read-only tools that execute against the in-memory trades DataFrame +
slicer output, then composes a grounded answer.

Design goals:
- Every numeric claim must come from a tool call (no hallucination).
- Tools return small JSON summaries — never dump raw DataFrames.
- The system prompt + tool definitions are aggressively cached
  (prompt caching) so repeat questions cost ~10% of a fresh call.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pandas as pd
from anthropic import Anthropic

from .config import get_settings
from .slicer import overall as slicer_overall, slice_all as slicer_slice_all


# --------------------------------------------------------------------------- #
# Tool definitions (the shape Claude sees)
# --------------------------------------------------------------------------- #

_DIMENSIONS = [
    "hour_of_day",
    "day_of_week",
    "side",
    "symbol",
    "consecutive_losses",
    "size_quartile",
    "hold_duration",
    "regime",
]

_FILTER_SCHEMA = {
    "type": "object",
    "description": (
        "Optional filters to narrow the dataset before computing stats. "
        "Each key restricts to a single value. Omit any filter you don't "
        "need. Hours are 0-23, day_of_week is 0=Monday … 6=Sunday."
    ),
    "properties": {
        "hour":           {"type": "integer", "description": "Hour of day, 0-23 UTC"},
        "day_of_week":    {"type": "integer", "description": "0=Mon … 6=Sun"},
        "side":           {"type": "string",  "enum": ["long", "short"]},
        "symbol":         {"type": "string",  "description": "e.g. BTC-USD"},
        "streak_bucket":  {"type": "string",  "enum": ["fresh", "1L", "2L", "3L", "4L+"]},
        "size_quartile":  {"type": "string",  "enum": ["Q1", "Q2", "Q3", "Q4"]},
        "hold_bucket":    {"type": "string",  "description": "<5m | 5–30m | 30m–2h | 2–8h | 8–24h | >24h"},
        "regime":         {"type": "string",  "enum": ["uptrend", "chop", "downtrend"]},
    },
}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_full_breakdown",
        "description": (
            "ONE-SHOT tool. Returns the entire dashboard: overall stats + "
            "per-bucket breakdown for ALL 8 dimensions (hour, day, side, "
            "symbol, streak, size, hold, regime). Call this FIRST for any "
            "broad diagnostic question — it gives you everything you need "
            "in a single call instead of 8. Only fall back to other tools "
            "if the user asks for specific trades or a comparison the "
            "breakdown doesn't already cover."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"filters": _FILTER_SCHEMA},
        },
    },
    {
        "name": "get_filtered_summary",
        "description": (
            "Aggregate stats (winrate, expectancy, total PNL, n_trades, "
            "avg hold minutes) for trades matching filters. Use this only "
            "when you've already called get_full_breakdown and need a "
            "specific filtered slice it didn't cover."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"filters": _FILTER_SCHEMA},
        },
    },
    {
        "name": "get_slice_breakdown",
        "description": (
            "Get per-bucket stats for one dimension — like the dashboard's "
            "conditional performance tabs. Useful when the user asks 'how "
            "do I do by hour' or 'what's my best symbol'. Returns a list of "
            "{bucket, n_trades, winrate, expectancy, total_pnl, avg_hold_minutes}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dimension": {
                    "type": "string",
                    "enum": _DIMENSIONS,
                    "description": "Which dimension to slice by.",
                },
                "filters": _FILTER_SCHEMA,
            },
            "required": ["dimension"],
        },
    },
    {
        "name": "list_top_trades",
        "description": (
            "List up to 10 individual trades matching the filters. Use ONLY "
            "when the user asks about specific trades ('show me my worst 5 "
            "trades on Saturday', 'what was my biggest BTC win?'). Do not "
            "use this for aggregate questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": _FILTER_SCHEMA,
                "sort_by": {
                    "type": "string",
                    "enum": ["pnl", "opened_at", "size", "hold_minutes"],
                    "description": "What to sort by.",
                },
                "ascending": {
                    "type": "boolean",
                    "description": "True for ascending (worst first if sorting by pnl).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (1-10).",
                },
            },
            "required": ["sort_by"],
        },
    },
    {
        "name": "compare_subsets",
        "description": (
            "Compare two filter subsets head-to-head. Returns summary stats "
            "for each plus the delta. Useful for 'how does my BTC compare to "
            "ETH' or 'do I do better in uptrend vs chop'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filters_a": _FILTER_SCHEMA,
                "filters_b": _FILTER_SCHEMA,
                "label_a":   {"type": "string"},
                "label_b":   {"type": "string"},
            },
            "required": ["filters_a", "filters_b"],
        },
    },
]


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #


def _apply_filters(df: pd.DataFrame, filters: dict | None) -> pd.DataFrame:
    """Apply tool-style filters to a trades DataFrame.

    Uses the bucket columns attached by streamlit_app._add_bucket_columns +
    _attach_regime when available. Filters that reference columns the df
    doesn't have are silently ignored.
    """
    if not filters:
        return df
    out = df
    if "hour" in filters and "opened_at" in out.columns:
        out = out[out["opened_at"].dt.hour == int(filters["hour"])]
    if "day_of_week" in filters and "opened_at" in out.columns:
        out = out[out["opened_at"].dt.dayofweek == int(filters["day_of_week"])]
    if "side" in filters and "side" in out.columns:
        out = out[out["side"].astype(str).str.lower() == str(filters["side"]).lower()]
    if "symbol" in filters and "symbol" in out.columns:
        out = out[out["symbol"].astype(str) == str(filters["symbol"])]
    if "streak_bucket" in filters and "_streak_b" in out.columns:
        out = out[out["_streak_b"].astype(str) == str(filters["streak_bucket"])]
    if "size_quartile" in filters and "_size_q" in out.columns:
        out = out[out["_size_q"].astype(str) == str(filters["size_quartile"])]
    if "hold_bucket" in filters and "_hold_b" in out.columns:
        out = out[out["_hold_b"].astype(str) == str(filters["hold_bucket"])]
    if "regime" in filters and "regime" in out.columns:
        out = out[out["regime"].astype(str) == str(filters["regime"])]
    return out


def _summary_stats(df: pd.DataFrame) -> dict:
    """Quick summary stats — same shape Claude can reason about."""
    if df is None or df.empty:
        return {
            "n_trades": 0, "winrate": None, "total_pnl": 0,
            "expectancy": None, "avg_hold_minutes": None,
            "best_trade_pnl": None, "worst_trade_pnl": None,
        }
    pnl = df["pnl"].dropna()
    n = len(pnl)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    winrate = len(wins) / n if n else 0.0
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss_mag = abs(float(losses.mean())) if len(losses) else 0.0
    expectancy = avg_win * winrate - avg_loss_mag * (1 - winrate)
    hold_min = None
    if {"opened_at", "closed_at"}.issubset(df.columns):
        hold = (df["closed_at"] - df["opened_at"]).dt.total_seconds() / 60.0
        hold_min = float(hold.mean())
    return {
        "n_trades":         int(n),
        "winrate":          round(winrate, 4),
        "total_pnl":        round(float(pnl.sum()), 2),
        "expectancy":       round(expectancy, 2),
        "avg_pnl":          round(float(pnl.mean()), 2),
        "avg_hold_minutes": round(hold_min, 1) if hold_min is not None else None,
        "best_trade_pnl":   round(float(pnl.max()), 2),
        "worst_trade_pnl":  round(float(pnl.min()), 2),
    }


def _tool_get_filtered_summary(trades_df: pd.DataFrame, args: dict) -> dict:
    filtered = _apply_filters(trades_df, args.get("filters"))
    return {"filters_applied": args.get("filters", {}), **_summary_stats(filtered)}


def _tool_get_full_breakdown(
    trades_df: pd.DataFrame,
    slices_dict: dict,
    args: dict,
) -> dict:
    """One-shot tool: returns overall stats + every dimension's breakdown in
    a single payload. Massively reduces tool-call round trips for broad
    questions (1 call instead of 8+)."""
    filters = args.get("filters") or {}
    filtered = _apply_filters(trades_df, filters)

    # If no filters, reuse the precomputed slices dict. Otherwise recompute.
    if not filters:
        all_slices = slices_dict
    else:
        all_slices = slicer_slice_all(filtered)

    breakdowns: dict[str, list[dict]] = {}
    for dim_key, sl in (all_slices or {}).items():
        if sl is None or sl.empty:
            breakdowns[dim_key] = []
            continue
        bucket_col = next(
            (c for c in sl.columns
             if c not in ("n_trades", "winrate", "avg_pnl", "expectancy",
                          "total_pnl", "avg_hold_minutes")),
            None,
        )
        rows = []
        for _, row in sl.iterrows():
            rows.append({
                "bucket":           str(row[bucket_col]) if bucket_col else "—",
                "n_trades":         int(row.get("n_trades", 0) or 0),
                "winrate":          round(float(row.get("winrate", 0) or 0), 4),
                "expectancy":       round(float(row.get("expectancy", 0) or 0), 2),
                "total_pnl":        round(float(row.get("total_pnl", 0) or 0), 2),
                "avg_hold_minutes": (
                    round(float(row["avg_hold_minutes"]), 1)
                    if "avg_hold_minutes" in row and pd.notna(row["avg_hold_minutes"])
                    else None
                ),
            })
        breakdowns[dim_key] = rows

    return {
        "overall":          _summary_stats(filtered),
        "filters_applied":  filters,
        "breakdowns":       breakdowns,
    }


def _tool_get_slice_breakdown(
    trades_df: pd.DataFrame,
    slices_dict: dict,
    args: dict,
) -> dict:
    dim = args.get("dimension")
    filters = args.get("filters")

    # If no extra filters, we can reuse the precomputed slicer output.
    if not filters and slices_dict and dim in slices_dict:
        sl = slices_dict[dim]
    else:
        # Re-compute on filtered data.
        sub = _apply_filters(trades_df, filters)
        recomputed = slicer_slice_all(sub)
        sl = recomputed.get(dim)

    if sl is None or sl.empty:
        return {"dimension": dim, "buckets": [], "filters_applied": filters or {}}

    # Find the key column (the bucket label) — it varies per dimension.
    bucket_col = next(
        (c for c in sl.columns
         if c not in ("n_trades", "winrate", "avg_pnl", "expectancy",
                      "total_pnl", "avg_hold_minutes")),
        None,
    )

    buckets: list[dict] = []
    for _, row in sl.iterrows():
        item = {
            "bucket":           str(row[bucket_col]) if bucket_col else "—",
            "n_trades":         int(row.get("n_trades", 0) or 0),
            "winrate":          round(float(row.get("winrate", 0) or 0), 4),
            "expectancy":       round(float(row.get("expectancy", 0) or 0), 2),
            "total_pnl":        round(float(row.get("total_pnl", 0) or 0), 2),
            "avg_hold_minutes": (
                round(float(row["avg_hold_minutes"]), 1)
                if "avg_hold_minutes" in row and pd.notna(row["avg_hold_minutes"])
                else None
            ),
        }
        buckets.append(item)
    return {
        "dimension":       dim,
        "buckets":         buckets,
        "filters_applied": filters or {},
    }


def _tool_list_top_trades(trades_df: pd.DataFrame, args: dict) -> dict:
    filtered = _apply_filters(trades_df, args.get("filters"))
    if filtered.empty:
        return {"trades": [], "filters_applied": args.get("filters", {})}

    sort_by = args.get("sort_by", "pnl")
    ascending = bool(args.get("ascending", True))
    limit = max(1, min(int(args.get("limit", 5) or 5), 10))

    # Translate to actual column names.
    col_map = {
        "pnl":           "pnl",
        "opened_at":     "opened_at",
        "size":          "size",
        "hold_minutes":  "_hold_minutes",
    }
    sort_col = col_map.get(sort_by, "pnl")
    work = filtered.copy()
    if sort_col == "_hold_minutes" and {"opened_at", "closed_at"}.issubset(work.columns):
        work["_hold_minutes"] = (
            work["closed_at"] - work["opened_at"]
        ).dt.total_seconds() / 60.0
    if sort_col not in work.columns:
        sort_col = "pnl"
    work = work.sort_values(sort_col, ascending=ascending).head(limit)

    out: list[dict] = []
    for _, row in work.iterrows():
        item = {
            "opened_at": (
                row["opened_at"].isoformat()
                if "opened_at" in row and pd.notna(row["opened_at"]) else None
            ),
            "symbol":    str(row.get("symbol", "")) or None,
            "side":      str(row.get("side", "")) or None,
            "pnl":       round(float(row.get("pnl", 0) or 0), 2),
            "size_usd":  (
                round(float(row["size"]) * float(row.get("entry_price", 0) or 0), 0)
                if "size" in row and pd.notna(row["size"])
                else None
            ),
            "hold_minutes": (
                round(float(row["_hold_minutes"]), 1)
                if "_hold_minutes" in row else None
            ),
        }
        out.append(item)
    return {
        "trades":          out,
        "filters_applied": args.get("filters", {}),
        "sort_by":         sort_by,
        "ascending":       ascending,
    }


def _tool_compare_subsets(trades_df: pd.DataFrame, args: dict) -> dict:
    a = _apply_filters(trades_df, args.get("filters_a"))
    b = _apply_filters(trades_df, args.get("filters_b"))
    stats_a = _summary_stats(a)
    stats_b = _summary_stats(b)
    delta = {
        "n_trades":   stats_a["n_trades"] - stats_b["n_trades"],
        "winrate":    (stats_a["winrate"] or 0) - (stats_b["winrate"] or 0),
        "expectancy": (stats_a["expectancy"] or 0) - (stats_b["expectancy"] or 0),
        "total_pnl":  (stats_a["total_pnl"] or 0) - (stats_b["total_pnl"] or 0),
    }
    return {
        "label_a":   args.get("label_a") or "A",
        "label_b":   args.get("label_b") or "B",
        "filters_a": args.get("filters_a", {}),
        "filters_b": args.get("filters_b", {}),
        "a":         stats_a,
        "b":         stats_b,
        "delta_a_minus_b": delta,
    }


def _make_tool_executor(
    trades_df: pd.DataFrame,
    slices_dict: dict,
) -> Callable[[str, dict], dict]:
    """Bind the tool implementations to the current dataset."""
    def execute(name: str, args: dict) -> dict:
        try:
            if name == "get_full_breakdown":
                return _tool_get_full_breakdown(trades_df, slices_dict, args)
            if name == "get_filtered_summary":
                return _tool_get_filtered_summary(trades_df, args)
            if name == "get_slice_breakdown":
                return _tool_get_slice_breakdown(trades_df, slices_dict, args)
            if name == "list_top_trades":
                return _tool_list_top_trades(trades_df, args)
            if name == "compare_subsets":
                return _tool_compare_subsets(trades_df, args)
            return {"error": f"unknown tool: {name}"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}
    return execute


# --------------------------------------------------------------------------- #
# Conversation loop
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """You are Edgework's trade analysis assistant.

You answer questions about a trader's own SoDEX perpetuals history. Every \
single numeric claim you make MUST come from a tool call — never invent or \
estimate numbers. If the tools don't give you what you need, say so plainly.

TOOL-USE EFFICIENCY (very important — each call costs money):
- For ANY broad diagnostic question, your FIRST call MUST be get_full_breakdown. \
It returns overall stats + every dimension's per-bucket breakdown in one payload. \
This single call answers ~80% of questions.
- Only call additional tools when get_full_breakdown is insufficient:
  - list_top_trades: when the user asks about specific trades.
  - compare_subsets: when filtering on two combined conditions the breakdown can't show.
  - get_filtered_summary: when you need a very specific filter combo.
  - get_slice_breakdown: when the user asked about ONE dimension and you only want that.
- HARD LIMIT: do not exceed 3 tool calls per question. Plan before calling.
- Don't call list_top_trades just to "show examples" — only when the user asks \
about specific trades.

Style:
- Direct, second person ("you"). Trader-to-trader. No hype, no emoji.
- Cite sample size for every stat (e.g. "-$54/trade across 18 trades").
- Use Markdown sparingly: bold for key numbers, simple tables when comparing buckets, \
short paragraphs over long bullet lists.
- End with one concrete action ("Avoid 18:00 UTC entirely", "Cap size to Q2").
- If the answer is "your sample is too small", say that and stop.

After you have enough data, write your final answer."""


def answer_question(
    question: str,
    trades_df: pd.DataFrame,
    slices_dict: dict,
    *,
    max_turns: int = 4,
    max_tokens: int = 1500,
    model: str | None = None,
    client: Anthropic | None = None,
) -> tuple[str, list[dict], dict]:
    """Run the tool-use loop and return (final_answer, trace).

    ``trace`` is a list of {"tool": name, "input": dict, "output": dict}
    entries — useful for showing a "this is how I got that number" view.
    """
    s = get_settings()
    client = client or Anthropic(api_key=s.anthropic_api_key)
    model = model or s.anthropic_model

    execute = _make_tool_executor(trades_df, slices_dict)
    messages: list[dict] = [{"role": "user", "content": question}]
    trace: list[dict] = []

    usage_total = {
        "input_tokens":             0,
        "output_tokens":            0,
        "cache_creation_input":     0,
        "cache_read_input":         0,
        "api_calls":                0,
    }

    for _turn in range(max_turns):
        # Prompt-cache the system prompt + tools — they're static between
        # questions so we only pay the full input cost on the first call
        # of a session.
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=TOOLS,
            messages=messages,
        )

        # Accumulate token usage for cost reporting.
        u = getattr(response, "usage", None)
        if u is not None:
            usage_total["input_tokens"]         += getattr(u, "input_tokens", 0) or 0
            usage_total["output_tokens"]        += getattr(u, "output_tokens", 0) or 0
            usage_total["cache_creation_input"] += getattr(u, "cache_creation_input_tokens", 0) or 0
            usage_total["cache_read_input"]     += getattr(u, "cache_read_input_tokens", 0) or 0
        usage_total["api_calls"] += 1

        if response.stop_reason == "tool_use":
            tool_results: list[dict] = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    out = execute(block.name, dict(block.input or {}))
                    trace.append({
                        "tool":   block.name,
                        "input":  dict(block.input or {}),
                        "output": out,
                    })
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps(out, default=str),
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",      "content": tool_results})
            continue

        # No more tool calls — final answer.
        text = "".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", None) == "text"
        ).strip()
        return text, trace, usage_total

    return ("(stopped after max_turns without a final answer)", trace, usage_total)


# --------------------------------------------------------------------------- #
# Full diagnostic — the canonical "tell me everything" prompt
# --------------------------------------------------------------------------- #


DIAGNOSTIC_PROMPT_PT = """Faça uma autópsia completa do meu histórico de trading na SoDEX.

Chame get_full_breakdown PRIMEIRO (chamada única — te dá toda informação \
necessária). Não chame outras ferramentas a menos que precise de trades \
específicos como exemplo.

Estruture a resposta EXATAMENTE assim:

## 🔍 Os 5 Maiores Problemas

Para cada um dos 5 piores padrões/comportamentos custando dinheiro \
(ordenados por impacto financeiro absoluto):

### N. Título concreto nomeando o problema
*(Exemplo: "Tamanho máximo (Q4) está destruindo sua conta")*

Uma tabela Markdown com os dados relevantes (bucket / trades / winrate / \
expectancy / total). Use formatação `$X,XX` ou `$X.XXX`.

1-3 frases interpretando o que os dados mostram. Quantifique o **custo \
absoluto** que esse problema específico gera (valor em dólares e/ou \
porcentagem da perda total).

## ✅ Ações Prioritárias

3-5 regras específicas e acionáveis. Cada uma começa com o tipo da \
regra em negrito (ex: **Stop por tempo:**, **Cortar Q4:**, **Parar de \
operar:**).

Regras de estilo:
- Português, voz direta de trader-para-trader.
- Sem rodeios ("talvez", "poderia"). Afirme fatos.
- Sempre cite o tamanho da amostra ao lado de cada estatística.
- Use ✅ apenas para o melhor bucket de cada dimensão e ⚠️ apenas para o pior.
- Coloque os números mais importantes em negrito."""


DIAGNOSTIC_PROMPT_EN = """Run a full autopsy of my SoDEX trading history.

Call get_full_breakdown FIRST (single call — gives you every piece of \
data you need). Do not call other tools unless you need specific trades \
as examples.

Structure the response EXACTLY like this:

## 🔍 The 5 Biggest Problems

For each of the 5 worst patterns/behaviors costing money (ordered by \
absolute financial impact):

### N. Concrete title naming the problem
*(Example: "Max size (Q4) is destroying your account")*

A Markdown table with the relevant data (bucket / trades / winrate / \
expectancy / total). Use `$X.XX` or `$X,XXX` formatting.

1-3 sentences interpreting what the data shows. Quantify the **absolute \
cost** this specific problem generates (dollar amount and/or percentage \
of total loss).

## ✅ Priority Actions

3-5 specific, actionable rules. Each one starts with the rule type in \
bold (e.g. **Time stop:**, **Cut Q4:**, **Stop trading:**).

Style rules:
- English, direct trader-to-trader voice.
- No hedging ("might", "could"). State facts.
- Always cite sample size next to every statistic.
- Use ✅ only for the best bucket of each dimension and ⚠️ only for the \
worst.
- Bold the most important numbers."""

# Back-compat default.
DIAGNOSTIC_PROMPT = DIAGNOSTIC_PROMPT_EN


def full_diagnostic(
    trades_df: pd.DataFrame,
    slices_dict: dict,
    *,
    max_turns: int = 3,
    max_tokens: int = 2500,
    client: Anthropic | None = None,
    model: str | None = None,
    lang: str = "EN",
) -> tuple[str, list[dict], dict]:
    """Run the canonical full diagnostic.

    Same engine as ``answer_question`` but with a fixed prompt that's been
    tuned to:
      - Always call ``get_full_breakdown`` first (1 cheap call covers ~all data).
      - Produce a numbered "5 biggest problems + 3-5 actions" output.
      - Cap at 3 turns to keep cost predictable.
    """
    prompt = DIAGNOSTIC_PROMPT_PT if (lang or "EN").upper() == "PT" else DIAGNOSTIC_PROMPT_EN
    return answer_question(
        prompt,
        trades_df,
        slices_dict,
        max_turns=max_turns,
        max_tokens=max_tokens,
        client=client,
        model=model,
    )
