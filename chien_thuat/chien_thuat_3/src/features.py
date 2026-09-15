"""
Feature Engineering for BTC 5-minute Prediction
Generates technical features, volume dynamics, and Polymarket-style binary targets.
"""
import numpy as np
import pandas as pd

def compute_rsi(series: pd.Series, period: int = 14) -> np.ndarray:
    delta = series.diff().to_numpy()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    
    alpha = 1.0 / period
    avg_gain = pd.Series(gain).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    avg_loss = pd.Series(loss).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    
    rs = np.where(avg_loss == 0, 100.0, avg_gain / (avg_loss + 1e-9))
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    alpha = 1.0 / period
    atr = pd.Series(tr).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    return atr

def build_features(df: pd.DataFrame, is_train: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """
    Extracts features for 5m prediction and builds future targets.
    NO LOOK-AHEAD in features: all features at index t only use info up to bar t.
    """
    df = df.copy()
    c = df["close"]
    o = df["open"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    
    feature_cols = []
    
    # 1. Momentum Returns
    for lag in [1, 2, 3, 6, 12]:
        col = f"ret_{lag}"
        df[col] = (c / c.shift(lag) - 1.0)
        feature_cols.append(col)
        
    # 2. Candle Shape
    df["body"] = (c - o) / o
    df["range"] = (h - l) / l
    df["upper_shadow"] = (h - np.maximum(o, c)) / o
    df["lower_shadow"] = (np.minimum(o, c) - l) / o
    feature_cols.extend(["body", "range", "upper_shadow", "lower_shadow"])
    
    # 3. Indicators
    df["rsi_14"] = compute_rsi(c, 14)
    df["atr_14_pct"] = compute_atr(h.to_numpy(), l.to_numpy(), c.to_numpy(), 14) / c
    
    sma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std()
    df["bb_zscore"] = (c - sma_20) / (std_20 + 1e-9)
    
    ema_50 = c.ewm(span=50, adjust=False).mean()
    df["trend_dist"] = (c - ema_50) / ema_50
    feature_cols.extend(["rsi_14", "atr_14_pct", "bb_zscore", "trend_dist"])
    
    # 4. Volume Dynamics
    vol_sma = v.rolling(12).mean()
    df["vol_ratio"] = v / (vol_sma + 1e-9)
    feature_cols.append("vol_ratio")
    
    # For live inference, return real-time features without waiting for future targets
    if not is_train:
        df = df.iloc[20:].reset_index(drop=True)
        return df, feature_cols

    # 5. Future Target: Forward Return Direction (Symmetric for Long/Short)
    # Predict direction of next 6 bars (30 minutes) forward return
    # This gives model equal ability to learn Long AND Short patterns
    c_arr = c.to_numpy()
    n = len(df)
    
    forward_bars = 6  # 30 minutes lookahead
    threshold = 0.0015  # 0.15% minimum move to classify as directional (filters noise)
    
    # Forward return over next forward_bars candles
    fwd_return = np.zeros(n)
    for i in range(n - forward_bars):
        fwd_return[i] = (c_arr[i + forward_bars] / c_arr[i]) - 1.0
    
    # Label: 1 = bullish move (>+threshold), 0 = bearish/flat move (<-threshold)
    # Bars between -threshold and +threshold are labeled 0 (neutral/bearish)
    labels = np.zeros(n, dtype=int)
    labels[fwd_return > threshold] = 1   # Bullish
    # labels remain 0 for bearish/flat
    
    df["target_direction"] = labels
    df["target_return"] = fwd_return
    
    # Clean rows with NaNs caused by rolling/lags/shift
    df = df.iloc[20: n - forward_bars].reset_index(drop=True)
    return df, feature_cols

