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

    # 5. Future Target: Triple Barrier Method (Polymarket / Event Driven)
    # TP = +0.8%, SL = -0.4% (Risk/Reward 2:1) within next 12 bars (60 minutes)
    c_arr = c.to_numpy()
    h_arr = h.to_numpy()
    l_arr = l.to_numpy()
    n = len(df)
    
    tp_pct = 0.008
    sl_pct = 0.004
    max_bars = 12
    
    tb_labels = np.zeros(n, dtype=int)
    for i in range(n - max_bars):
        entry = c_arr[i]
        for j in range(1, max_bars + 1):
            if h_arr[i + j] >= entry * (1.0 + tp_pct):
                tb_labels[i] = 1 # Won TP
                break
            if l_arr[i + j] <= entry * (1.0 - sl_pct):
                tb_labels[i] = 0 # Stopped out
                break
                
    df["target_direction"] = tb_labels
    df["target_return"] = (c.shift(-1) / c) - 1.0
    
    # Clean rows with NaNs caused by rolling/lags/shift
    df = df.iloc[20: n - max_bars].reset_index(drop=True)
    return df, feature_cols
