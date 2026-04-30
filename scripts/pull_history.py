"""One-shot script: pull your full SoDEX position history into local parquet.

Usage:
    python scripts/pull_history.py [--symbol BTC-USD] [--days 90]

Requires SODEX_USER_ADDRESS in .env (your wallet's public address).
No API key needed — SoDEX read endpoints are fully public; the address
in the URL is sufficient.

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
    parser = argparse.ArgumentParser(
        description="Pull your SoDEX position history into local parquet."
    )
    parser.add_argument("--symbol", default=None, help="Limit to one symbol (e.g. BTC-USD)")
    parser.add_argument("--days", type=int, default=90, help="History window in days")
    parser.add_argument("--out", default="data/history.parquet")
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max positions per request (API max is 500)",
    )
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_data_dir()

    if not settings.sodex_user_address:
        print(
            "ERROR: SODEX_USER_ADDRESS not set in .env.\n"
            "Set it to your SoDEX wallet address (0x...) and rerun.",
            file=sys.stderr,
        )
        sys.exit(2)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - args.days * 86_400_000
    start_str = pd.Timestamp(start_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M UTC")

    print(f"Wallet: {settings.sodex_user_address}")
    print(f"Window: last {args.days} days (since {start_str})")
    if args.symbol:
        print(f"Symbol: {args.symbol}")
    print()

    with SodexClient() as client:
        print("Fetching closed position history...")
        try:
            positions = client.get_position_history(
                symbol=args.symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                limit=args.limit,
            )
        except Exception as e:  # noqa: BLE001
            print(f"ERROR fetching position history: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Pulled {len(positions)} closed positions.")

    if not positions:
        print("No closed positions in this window. Nothing to save.")
        sys.exit(0)

    # Show one sample so we can confirm the schema looks right
    print("\nSample position (first record):")
    sample = positions[0]
    for k, v in list(sample.items())[:12]:
        print(f"  {k}: {v}")
    print()

    df = slicer.normalize_orders(positions)
    print(f"Normalized to {len(df)} usable trades.")

    if df.empty:
        print(
            "WARNING: 0 trades after normalization. The schema fields may have "
            "changed — share the sample output above and I'll adjust the slicer."
        )
        sys.exit(0)

    out_path = Path(args.out)
    df.to_parquet(out_path, index=False)
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
