"""
Feature Engineering V2: Original 14 Features + 11 HFT Microstructure Features
==============================================================================
Extends the original build_features() from features.py by merging in
microstructure features computed from HFT orderbook and trades data.

Total: 25 features (14 original + 11 HFT)
"""
import os
import numpy as np
import pandas as pd

from src.features import build_features


# The 11 HFT feature column names (must match hft_feature_builder.py)
HFT_FEATURE_COLS = [
    "obi_l1", "obi_l5", "obi_l20",
    "spread_mean", "spread_vol", "depth_ratio", "microprice",
    "cvd", "trade_intensity", "vwap_deviation", "large_trade_ratio",
]


def load_hft_features(hft_path: str = None) -> pd.DataFrame:
    """
    Load pre-computed HFT features from parquet file.

    Parameters
    ----------
    hft_path : str, optional
        Path to hft_features_5m.parquet. If None, uses default location.

    Returns
    -------
    pd.DataFrame
        HFT features indexed by datetime.
    """
    if hft_path is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hft_path = os.path.join(base_dir, "data", "hft_features_5m.parquet")

    if not os.path.exists(hft_path):
        raise FileNotFoundError(
            f"HFT features file not found: {hft_path}\n"
            f"Run 'python src/preprocess_hft.py' first to generate it."
        )

    df_hft = pd.read_parquet(hft_path)

    # Ensure datetime column exists and is proper type
    if "datetime" in df_hft.columns:
        df_hft["datetime"] = pd.to_datetime(df_hft["datetime"])
    elif "interval_ts" in df_hft.columns:
        df_hft["datetime"] = pd.to_datetime(df_hft["interval_ts"], unit="ms")

    return df_hft


def build_features_v2(
    df: pd.DataFrame,
    hft_df: pd.DataFrame = None,
    hft_path: str = None,
    is_train: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Build 25 features: 14 original technical features + 11 HFT microstructure features.

    Parameters
    ----------
    df : pd.DataFrame
        Raw 5m candle data with columns: datetime, open, high, low, close, volume.
    hft_df : pd.DataFrame, optional
        Pre-loaded HFT features DataFrame. If None, loads from hft_path.
    hft_path : str, optional
        Path to hft_features_5m.parquet.
    is_train : bool
        If True, computes future targets for training.

    Returns
    -------
    tuple[pd.DataFrame, list[str]]
        (df_with_features, feature_column_names)
    """
    # Step 1: Build original 14 features
    df_feat, original_cols = build_features(df, is_train=is_train)

    # Step 2: Load HFT features if not provided
    if hft_df is None:
        hft_df = load_hft_features(hft_path)

    # Step 3: Prepare datetime for merge
    df_feat["datetime"] = pd.to_datetime(df_feat["datetime"])
    hft_df = hft_df.copy()
    hft_df["datetime"] = pd.to_datetime(hft_df["datetime"])

    # Step 4: Align HFT timestamps to match candle timestamps
    # Candle data uses local time (Asia/Ho_Chi_Minh), HFT data should be the same
    # after preprocessing. We merge on exact datetime match.
    hft_subset = hft_df[["datetime"] + HFT_FEATURE_COLS].copy()

    # Step 5: Left-join: keep all candle rows, add HFT features where available
    n_before = len(df_feat)
    df_merged = pd.merge(df_feat, hft_subset, on="datetime", how="left")
    assert len(df_merged) == n_before, "Merge should not change row count"

    # Step 6: Forward-fill HFT features for gaps (missing HFT days)
    # then fill remaining NaNs with 0 (start of series before HFT data begins)
    for col in HFT_FEATURE_COLS:
        df_merged[col] = df_merged[col].ffill().fillna(0.0)

    # Step 7: Normalize HFT features for model stability
    # microprice is in absolute price units — convert to relative deviation from close
    if "microprice" in df_merged.columns and "close" in df_merged.columns:
        df_merged["microprice"] = (
            (df_merged["microprice"] - df_merged["close"]) / (df_merged["close"] + 1e-9)
        )

    # spread_mean: normalize by close price to make it scale-independent
    if "spread_mean" in df_merged.columns and "close" in df_merged.columns:
        df_merged["spread_mean"] = df_merged["spread_mean"] / (df_merged["close"] + 1e-9)

    # spread_vol: normalize by close price
    if "spread_vol" in df_merged.columns and "close" in df_merged.columns:
        df_merged["spread_vol"] = df_merged["spread_vol"] / (df_merged["close"] + 1e-9)

    # cvd: normalize by rolling average volume to be scale-independent
    if "cvd" in df_merged.columns:
        cvd_abs_mean = df_merged["cvd"].abs().rolling(288, min_periods=1).mean()
        df_merged["cvd"] = df_merged["cvd"] / (cvd_abs_mean + 1e-9)

    # trade_intensity: normalize by rolling average
    if "trade_intensity" in df_merged.columns:
        ti_mean = df_merged["trade_intensity"].rolling(288, min_periods=1).mean()
        df_merged["trade_intensity"] = df_merged["trade_intensity"] / (ti_mean + 1e-9)

    # Combine feature lists
    all_feature_cols = original_cols + HFT_FEATURE_COLS

    return df_merged, all_feature_cols
