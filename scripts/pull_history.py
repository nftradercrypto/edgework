"""One-shot script: pull your full SoDEX trade history into local parquet.

Usage:
    python scripts/pull_history.py [--symbol BTC-USD] [--days 90]

Caches to data/history.parquet so the Streamlit app loads fast and you
don't hammer the API on every reload.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

# Allow running from repo root: `python scripts/pull_history.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edgework import slicer  # noqa: E402
from edgework.config import get_settings  # noqa: E402
from edgework.sodex_client import SodexClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="Limit to one symbol")
    parser.add_argument("--days", type=int, default=90, help="History window")
    parser.add_argument("--out", default="data/history.parquet")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_data_dir()

    if not settings.sodex_api_key:
        print("ERROR: SODEX_API_KEY not set in .env", file=sys.stderr)
        sys.exit(2)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 86_400_000

    with SodexClient() as client:
        print(f"Fetching fills since {pd.Timestamp(start_ms, unit='ms', tz='UTC')}…")
        try:
            fills = client.get_fills(
                symbol=args.symbol, start_ms=start_ms, end_ms=end_ms, limit=1000
            )
        except Exception as e:  # noqa: BLE001
            print(f"Fills endpoint failed ({e}); falling back to order history.")
            fills = client.get_order_history(
                symbol=args.symbol, start_ms=start_ms, end_ms=end_ms, limit=1000
            )

    print(f"Pulled {len(fills)} raw records")

    df = slicer.normalize_orders(fills)
    print(f"Normalized to {len(df)} closed trades")

    if df.empty:
        print("No closed trades to save. Check the API response shape.")
        sys.exit(0)

    out_path = Path(args.out)
    df.to_parquet(out_path, index=False)
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
