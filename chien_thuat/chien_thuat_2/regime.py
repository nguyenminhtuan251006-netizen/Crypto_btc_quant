"""
1H Macro Regime Filter for Strategy 2
"""
import numpy as np
import pandas as pd

def compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(close)
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    
    for i in range(1, n):
        h_diff = high[i] - high[i - 1]
        l_diff = low[i - 1] - low[i]
        
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        
        if h_diff > l_diff and h_diff > 0:
            plus_dm[i] = h_diff
        else:
            plus_dm[i] = 0.0
            
        if l_diff > h_diff and l_diff > 0:
            minus_dm[i] = l_diff
        else:
            minus_dm[i] = 0.0
            
    atr = pd.Series(tr).ewm(alpha=1.0/period, adjust=False).mean().to_numpy()
    plus_di = 100.0 * pd.Series(plus_dm).ewm(alpha=1.0/period, adjust=False).mean().to_numpy() / np.where(atr == 0, 1e-9, atr)
    minus_di = 100.0 * pd.Series(minus_dm).ewm(alpha=1.0/period, adjust=False).mean().to_numpy() / np.where(atr == 0, 1e-9, atr)
    
    dx = 100.0 * np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) == 0, 1e-9, (plus_di + minus_di))
    adx = pd.Series(dx).ewm(alpha=1.0/period, adjust=False).mean().to_numpy()
    return adx, plus_di, minus_di

def compute_1h_regime(df_1h: pd.DataFrame, config) -> pd.DataFrame:
    """
    Computes 1H Macro Regime:
    LONG (1):  Close > EMA200 and EMA50_slope > 0 and ADX > 20
    SHORT (-1): Close < EMA200 and EMA50_slope < 0 and ADX > 20
    NO_TRADE (0): Otherwise
    """
    df = df_1h.copy().reset_index(drop=True)
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    
    # 1. EMAs
    ema_200 = pd.Series(c).ewm(span=config.regime_ema_trend, adjust=False).mean().to_numpy()
    ema_50 = pd.Series(c).ewm(span=config.regime_ema_slope, adjust=False).mean().to_numpy()
    ema_50_slope = pd.Series(ema_50).diff(3).to_numpy() # 3-hour slope
    
    # 2. ADX
    adx_14, plus_di, minus_di = compute_adx(h, l, c, period=config.regime_adx_period)
    
    # 3. Regime classification
    regime = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if c[i] > ema_200[i] and ema_50_slope[i] > 0 and adx_14[i] > config.regime_adx_threshold:
            regime[i] = 1 # LONG
        elif c[i] < ema_200[i] and ema_50_slope[i] < 0 and adx_14[i] > config.regime_adx_threshold:
            regime[i] = -1 # SHORT
        else:
            regime[i] = 0 # NO TRADE / CHOPPY SIDEWAY
            
    df["ema_200_1h"] = ema_200
    df["ema_50_1h"] = ema_50
    df["ema_50_slope_1h"] = ema_50_slope
    df["adx_14_1h"] = adx_14
    df["regime_1h"] = regime
    return df
