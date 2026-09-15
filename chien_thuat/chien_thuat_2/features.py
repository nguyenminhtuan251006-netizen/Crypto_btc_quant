"""
Features and Target Generation for Strategy 2 AI Meta Filter
"""
import numpy as np
import pandas as pd

def build_strategy2_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    v = df["volume"].to_numpy()
    n = len(df)
    
    # 1. Price Momentum Lags
    ret_s = pd.Series(c).pct_change()
    ret_1 = ret_s.to_numpy()
    ret_2 = pd.Series(c).pct_change(2).to_numpy()
    ret_3 = pd.Series(c).pct_change(3).to_numpy()
    ret_4 = pd.Series(c).pct_change(4).to_numpy()
    ret_8 = pd.Series(c).pct_change(8).to_numpy()
    
    # 2. Candlestick Ratios
    hl_range = np.where((h - l) == 0, 1e-9, h - l)
    body_ratio = np.abs(c - o) / hl_range
    upper_wick = (h - np.maximum(o, c)) / hl_range
    lower_wick = (np.minimum(o, c) - l) / hl_range
    
    # 3. Moving Average Distances
    dist_ema20 = (c - df["ema_20"].to_numpy()) / np.where(df["ema_20"].to_numpy() == 0, 1.0, df["ema_20"].to_numpy())
    dist_ema50 = (c - df["ema_50"].to_numpy()) / np.where(df["ema_50"].to_numpy() == 0, 1.0, df["ema_50"].to_numpy())
    dist_ema200_1h = (c - df["ema_200_1h"].to_numpy()) / np.where(df["ema_200_1h"].to_numpy() == 0, 1.0, df["ema_200_1h"].to_numpy())
    
    # 4. Volume Z-score
    v_mean20 = pd.Series(v).rolling(20).mean().to_numpy()
    v_std20 = pd.Series(v).rolling(20).std().to_numpy()
    vol_zscore = (v - v_mean20) / np.where(v_std20 == 0, 1e-9, v_std20)
    
    # 5. Volatility Features
    atr_pct = df["atr_14"].to_numpy() / np.where(c == 0, 1.0, c)
    realized_vol_8 = pd.Series(ret_1).rolling(8).std().to_numpy()
    
    # 6. Hour of day
    hours = pd.to_datetime(df["datetime"]).dt.hour.to_numpy()
    
    feature_dict = {
        "ret_1": ret_1,
        "ret_2": ret_2,
        "ret_3": ret_3,
        "ret_4": ret_4,
        "ret_8": ret_8,
        "body_ratio": body_ratio,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "dist_ema20": dist_ema20,
        "dist_ema50": dist_ema50,
        "dist_ema200_1h": dist_ema200_1h,
        "adx_14_1h": df["adx_14_1h"].to_numpy(),
        "rsi_14": df["rsi_14"].to_numpy(),
        "vol_zscore": vol_zscore,
        "atr_pct": atr_pct,
        "realized_vol_8": realized_vol_8,
        "hour": hours
    }
    
    feature_cols = list(feature_dict.keys())
    for col, arr in feature_dict.items():
        df[col] = arr
        
    return df, feature_cols

def label_setup_outcomes(df: pd.DataFrame, config) -> pd.DataFrame:
    """
    Labels ONLY candidate setups:
    1: TP (+1.8 ATR) touched before SL (-1.0 ATR) within timeout_bars (8 bars = 2h)
    0: SL touched before TP (or timeout with loss)
    """
    df = df.copy()
    n = len(df)
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    setups = df["candidate_setup"].to_numpy()
    sl_arr = df["setup_sl"].to_numpy()
    tp_arr = df["setup_tp"].to_numpy()
    
    target_win = np.zeros(n, dtype=int)
    has_target = np.zeros(n, dtype=bool)
    
    for i in range(n - config.timeout_bars):
        setup = setups[i]
        if setup == 0:
            continue
            
        sl = sl_arr[i]
        tp = tp_arr[i]
        won = False
        resolved = False
        
        for j in range(1, config.timeout_bars + 1):
            cur_idx = i + j
            if setup == 1: # LONG
                if h[cur_idx] >= tp:
                    won = True
                    resolved = True
                    break
                elif l[cur_idx] <= sl:
                    won = False
                    resolved = True
                    break
            elif setup == -1: # SHORT
                if l[cur_idx] <= tp:
                    won = True
                    resolved = True
                    break
                elif h[cur_idx] >= sl:
                    won = False
                    resolved = True
                    break
                    
        if not resolved:
            # Timeout exit: won if price moved in favorable direction
            last_c = c[i + config.timeout_bars]
            won = (last_c > c[i]) if setup == 1 else (last_c < c[i])
            
        target_win[i] = 1 if won else 0
        has_target[i] = True
        
    df["target_win"] = target_win
    df["has_target"] = has_target
    return df
