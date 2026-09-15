"""
HFT Microstructure Feature Builder
===================================
Computes 11 institutional-grade microstructure features from raw Level-2 Orderbook
(20 levels) and Tick Trades data, aggregated into 5-minute intervals.

Uses Polars for high-performance processing of 130M+ rows.

Features computed:
  From Orderbook L2:
    1. obi_l1       - Order Book Imbalance (Level 1 only)
    2. obi_l5       - Order Book Imbalance (Top 5 levels)
    3. obi_l20      - Order Book Imbalance (All 20 levels)
    4. spread_mean  - Average bid-ask spread in 5m window
    5. spread_vol   - Spread volatility (std dev) in 5m window
    6. depth_ratio  - Total bid depth / Total ask depth (20 levels)
    7. microprice   - Volume-weighted mid-price at L1

  From Tick Trades:
    8. cvd           - Cumulative Volume Delta (taker buy - taker sell)
    9. trade_intensity - Number of trades per 5m interval
    10. vwap_deviation - (VWAP - microprice) / microprice
    11. large_trade_ratio - Volume from large trades (>= P90) / total volume
"""
import polars as pl
import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INTERVAL_MS = 5 * 60 * 1000  # 5 minutes in milliseconds

BID_P_COLS = [f"bid_p{i}" for i in range(20)]
BID_Q_COLS = [f"bid_q{i}" for i in range(20)]
ASK_P_COLS = [f"ask_p{i}" for i in range(20)]
ASK_Q_COLS = [f"ask_q{i}" for i in range(20)]


# ---------------------------------------------------------------------------
# Orderbook Feature Computation (per-tick level, then aggregate to 5m)
# ---------------------------------------------------------------------------
def _compute_orderbook_tick_features(ob: pl.DataFrame) -> pl.DataFrame:
    """
    Compute per-tick orderbook features, then aggregate to 5-minute intervals.

    Parameters
    ----------
    ob : pl.DataFrame
        Raw orderbook data with columns: timestamp, local_time,
        bid_p0..bid_p19, bid_q0..bid_q19, ask_p0..ask_p19, ask_q0..ask_q19.

    Returns
    -------
    pl.DataFrame
        Aggregated features with columns: interval_ts, obi_l1, obi_l5, obi_l20,
        spread_mean, spread_vol, depth_ratio, microprice.
    """
    # Assign each tick to a 5-minute interval bucket
    ob = ob.with_columns(
        (pl.col("timestamp") // INTERVAL_MS * INTERVAL_MS).alias("interval_ts")
    )

    # --- Per-tick computations using expressions ---
    # L1 quantities
    bid_q0 = pl.col("bid_q0")
    ask_q0 = pl.col("ask_q0")

    # OBI L1
    obi_l1_expr = (bid_q0 - ask_q0) / (bid_q0 + ask_q0 + 1e-9)

    # OBI L5: sum of bid_q0..bid_q4 vs ask_q0..ask_q4
    bid_sum_5 = sum(pl.col(f"bid_q{i}") for i in range(5))
    ask_sum_5 = sum(pl.col(f"ask_q{i}") for i in range(5))
    obi_l5_expr = (bid_sum_5 - ask_sum_5) / (bid_sum_5 + ask_sum_5 + 1e-9)

    # OBI L20: sum of all 20 levels
    bid_sum_20 = sum(pl.col(c) for c in BID_Q_COLS)
    ask_sum_20 = sum(pl.col(c) for c in ASK_Q_COLS)
    obi_l20_expr = (bid_sum_20 - ask_sum_20) / (bid_sum_20 + ask_sum_20 + 1e-9)

    # Depth-Weighted OBI (Albers et al. 2021 Oxford paper: decay weights w_i = 1 / sqrt(i+1))
    weights = [1.0 / np.sqrt(i + 1) for i in range(20)]
    bid_weighted = sum(weights[i] * pl.col(f"bid_q{i}") for i in range(20))
    ask_weighted = sum(weights[i] * pl.col(f"ask_q{i}") for i in range(20))
    obi_weighted_expr = (bid_weighted - ask_weighted) / (bid_weighted + ask_weighted + 1e-9)

    # Spread
    spread_expr = pl.col("ask_p0") - pl.col("bid_p0")

    # Depth ratio (bid_total / ask_total)
    depth_ratio_expr = bid_sum_20 / (ask_sum_20 + 1e-9)

    # Microprice: volume-weighted mid at L1
    # microprice = (bid_p0 * ask_q0 + ask_p0 * bid_q0) / (bid_q0 + ask_q0)
    microprice_expr = (
        pl.col("bid_p0") * ask_q0 + pl.col("ask_p0") * bid_q0
    ) / (bid_q0 + ask_q0 + 1e-9)

    # Add computed columns
    ob = ob.with_columns(
        obi_l1_expr.alias("_obi_l1"),
        obi_l5_expr.alias("_obi_l5"),
        obi_l20_expr.alias("_obi_l20"),
        obi_weighted_expr.alias("_obi_weighted"),
        spread_expr.alias("_spread"),
        depth_ratio_expr.alias("_depth_ratio"),
        microprice_expr.alias("_microprice"),
    )

    # Aggregate to 5-minute intervals
    agg = ob.group_by("interval_ts").agg(
        # OBI: mean over the 5-minute window (snapshot frequency weighted)
        pl.col("_obi_l1").mean().alias("obi_l1"),
        pl.col("_obi_l5").mean().alias("obi_l5"),
        pl.col("_obi_l20").mean().alias("obi_l20"),
        pl.col("_obi_weighted").mean().alias("obi_weighted"),
        # Spread: mean and std dev
        pl.col("_spread").mean().alias("spread_mean"),
        pl.col("_spread").std().alias("spread_vol"),
        # Depth ratio: mean
        pl.col("_depth_ratio").mean().alias("depth_ratio"),
        # Microprice: last value in interval (most recent state)
        pl.col("_microprice").last().alias("microprice"),
    ).sort("interval_ts")

    return agg


# ---------------------------------------------------------------------------
# Trades Feature Computation (aggregate ticks to 5m)
# ---------------------------------------------------------------------------
def _compute_trades_features(trades: pl.DataFrame) -> pl.DataFrame:
    """
    Compute trade-based microstructure features aggregated to 5-minute intervals.

    Parameters
    ----------
    trades : pl.DataFrame
        Raw trades data with columns: timestamp, local_time, agg_id, price,
        quantity, first_id, last_id, is_buyer_maker.

    Returns
    -------
    pl.DataFrame
        Aggregated features with columns: interval_ts, cvd, trade_intensity,
        vwap, large_trade_ratio.
    """
    # Assign interval bucket
    trades = trades.with_columns(
        (pl.col("timestamp") // INTERVAL_MS * INTERVAL_MS).alias("interval_ts")
    )

    # Signed volume: is_buyer_maker=True means the buyer was the maker,
    # so the seller was the taker (taker sell). We want:
    #   taker_buy_volume  = quantity where is_buyer_maker=False
    #   taker_sell_volume = quantity where is_buyer_maker=True
    trades = trades.with_columns(
        pl.when(pl.col("is_buyer_maker"))
        .then(-pl.col("quantity"))   # taker sell → negative
        .otherwise(pl.col("quantity"))  # taker buy → positive
        .alias("_signed_qty"),
        (pl.col("price") * pl.col("quantity")).alias("_notional"),
    )

    # Compute the P90 threshold for large trades (global for this day)
    p90_qty = trades.select(pl.col("quantity").quantile(0.90)).item()

    trades = trades.with_columns(
        pl.when(pl.col("quantity") >= p90_qty)
        .then(pl.col("quantity"))
        .otherwise(pl.lit(0.0))
        .alias("_large_qty")
    )

    # Aggregate to 5-minute intervals
    agg = trades.group_by("interval_ts").agg(
        # CVD: sum of signed volumes
        pl.col("_signed_qty").sum().alias("cvd"),
        # Trade intensity: count of trades
        pl.col("agg_id").count().alias("trade_intensity"),
        # VWAP: sum(price * qty) / sum(qty)
        (pl.col("_notional").sum() / (pl.col("quantity").sum() + 1e-9)).alias("vwap"),
        # Large trade ratio: large_qty_sum / total_qty_sum
        (pl.col("_large_qty").sum() / (pl.col("quantity").sum() + 1e-9)).alias("large_trade_ratio"),
    ).sort("interval_ts")

    return agg


# ---------------------------------------------------------------------------
# Public API: Combine Orderbook + Trades features for a single day
# ---------------------------------------------------------------------------
def compute_hft_features_for_day(
    ob_path: str,
    trades_path: str,
) -> pl.DataFrame | None:
    """
    Compute all 11 microstructure features for a single day's data.

    Parameters
    ----------
    ob_path : str
        Path to the orderbook parquet file for the day.
    trades_path : str
        Path to the trades parquet file for the day.

    Returns
    -------
    pl.DataFrame or None
        DataFrame with columns: interval_ts, obi_l1, obi_l5, obi_l20,
        spread_mean, spread_vol, depth_ratio, microprice, cvd,
        trade_intensity, vwap_deviation, large_trade_ratio.
        Returns None if files are corrupted or empty.
    """
    try:
        ob = pl.read_parquet(ob_path)
        trades = pl.read_parquet(trades_path)
    except Exception as e:
        print(f"  [SKIP] Cannot read files: {e}")
        return None

    if len(ob) == 0 or len(trades) == 0:
        print(f"  [SKIP] Empty data: ob={len(ob)}, trades={len(trades)}")
        return None

    # Compute features from each source
    ob_features = _compute_orderbook_tick_features(ob)
    trades_features = _compute_trades_features(trades)

    # Join on interval_ts
    merged = ob_features.join(trades_features, on="interval_ts", how="outer_coalesce")

    # Compute VWAP deviation: (vwap - microprice) / microprice
    merged = merged.with_columns(
        ((pl.col("vwap") - pl.col("microprice")) / (pl.col("microprice") + 1e-9))
        .alias("vwap_deviation")
    ).drop("vwap")  # vwap is intermediate, not a final feature

    # Fill nulls with 0 for intervals where one source had no data
    fill_cols = [
        "obi_l1", "obi_l5", "obi_l20", "obi_weighted", "spread_mean", "spread_vol",
        "depth_ratio", "microprice", "cvd", "trade_intensity",
        "vwap_deviation", "large_trade_ratio",
    ]
    merged = merged.with_columns(
        [pl.col(c).fill_null(0.0) for c in fill_cols]
    )

    # Also fill spread_vol NaN (happens when only 1 tick in interval)
    merged = merged.with_columns(
        pl.col("spread_vol").fill_nan(0.0)
    )

    return merged.sort("interval_ts")


# ---------------------------------------------------------------------------
# Feature column names (for downstream consumers)
# ---------------------------------------------------------------------------
HFT_FEATURE_COLS = [
    "obi_l1", "obi_l5", "obi_l20", "obi_weighted",
    "spread_mean", "spread_vol", "depth_ratio", "microprice",
    "cvd", "trade_intensity", "vwap_deviation", "large_trade_ratio",
]
