"""
HFT Data Preprocessing Pipeline
=================================
Batch-processes all daily HFT parquet files (coinm_perp orderbook + trades)
to produce a single consolidated file: data/hft_features_5m.parquet

This file contains 11 microstructure features per 5-minute interval,
covering the full date range of available HFT data (~139 days).

Usage:
    python -m src.preprocess_hft
    # or
    python src/preprocess_hft.py
"""
import os
import sys
import time
import glob
import polars as pl

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.hft_feature_builder import compute_hft_features_for_day, HFT_FEATURE_COLS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OB_DIR = "/home/data/hft/coinm_perp/orderbook"
TRADES_DIR = "/home/data/hft/coinm_perp/trades"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(BASE_DIR, "data", "hft_features_5m.parquet")


def get_available_dates() -> list[str]:
    """Find dates where both orderbook and trades files exist."""
    ob_files = {os.path.basename(f) for f in glob.glob(os.path.join(OB_DIR, "*.parquet"))}
    tr_files = {os.path.basename(f) for f in glob.glob(os.path.join(TRADES_DIR, "*.parquet"))}
    common = sorted(ob_files & tr_files)
    return common


def run_preprocessing():
    """Process all available daily HFT files and save consolidated features."""
    print("=" * 80)
    print("  HFT MICROSTRUCTURE DATA PREPROCESSING PIPELINE")
    print("  Source: COIN-M Perpetual (Binance) — Orderbook L2 (20 levels) + Trades")
    print("=" * 80)

    dates = get_available_dates()
    print(f"\n[INFO] Found {len(dates)} dates with both orderbook & trades data.")
    print(f"[INFO] Date range: {dates[0]} → {dates[-1]}")
    print(f"[INFO] Output: {OUTPUT_PATH}\n")

    all_features: list[pl.DataFrame] = []
    processed = 0
    skipped = 0
    t_start = time.time()

    for i, date_file in enumerate(dates):
        ob_path = os.path.join(OB_DIR, date_file)
        tr_path = os.path.join(TRADES_DIR, date_file)
        date_str = date_file.replace(".parquet", "")

        print(f"[{i+1:3d}/{len(dates)}] Processing {date_str}...", end=" ", flush=True)

        result = compute_hft_features_for_day(ob_path, tr_path)

        if result is not None and len(result) > 0:
            all_features.append(result)
            processed += 1
            print(f"✓ {len(result)} intervals (5m bars)")
        else:
            skipped += 1
            print("✗ skipped")

    if not all_features:
        print("\n[ERROR] No data was processed successfully!")
        return

    # Concatenate all days
    print(f"\n[INFO] Concatenating {processed} days...")
    combined = pl.concat(all_features).sort("interval_ts")

    # Remove duplicates (edge case: overlapping intervals at day boundaries)
    combined = combined.unique(subset=["interval_ts"], keep="last").sort("interval_ts")

    # Convert interval_ts from epoch ms to readable datetime for joining with candle data
    combined = combined.with_columns(
        pl.from_epoch(pl.col("interval_ts"), time_unit="ms")
        .dt.convert_time_zone("Asia/Ho_Chi_Minh")
        .dt.replace_time_zone(None)
        .alias("datetime")
    )

    # Final stats
    elapsed = time.time() - t_start
    print(f"\n{'=' * 80}")
    print(f"  PREPROCESSING COMPLETE")
    print(f"{'=' * 80}")
    print(f"  Days processed:    {processed}")
    print(f"  Days skipped:      {skipped}")
    print(f"  Total 5m intervals: {len(combined):,}")
    print(f"  Date range:        {combined['datetime'].min()} → {combined['datetime'].max()}")
    print(f"  Features:          {len(HFT_FEATURE_COLS)} microstructure features")
    print(f"  Elapsed time:      {elapsed:.1f}s")
    print(f"  Output file:       {OUTPUT_PATH}")

    # Feature summary statistics
    print(f"\n  Feature Statistics (sample):")
    for col in HFT_FEATURE_COLS:
        vals = combined[col]
        print(f"    {col:22s}  mean={vals.mean():+12.6f}  std={vals.std():12.6f}  "
              f"min={vals.min():+12.4f}  max={vals.max():+12.4f}")

    # Save
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    combined.write_parquet(OUTPUT_PATH)
    file_size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"\n  ✓ Saved to {OUTPUT_PATH} ({file_size_mb:.1f} MB)")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    run_preprocessing()
