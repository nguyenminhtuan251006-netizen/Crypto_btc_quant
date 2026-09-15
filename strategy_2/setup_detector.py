"""
15M Pullback Setup Detector for Strategy 2
"""
import numpy as np
import pandas as pd

def compute_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    diff = np.diff(close)
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    
    avg_gain = pd.Series(gain).ewm(alpha=1.0/period, adjust=False).mean().to_numpy()
    avg_loss = pd.Series(loss).ewm(alpha=1.0/period, adjust=False).mean().to_numpy()
    
    rs = avg_gain / np.where(avg_loss == 0, 1e-9, avg_loss)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return np.insert(rsi, 0, 50.0)

def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr = pd.Series(tr).ewm(alpha=1.0/period, adjust=False).mean().to_numpy()
    return atr

def detect_pullback_setups(df_15m: pd.DataFrame, df_1h: pd.DataFrame, config) -> pd.DataFrame:
    """
    Merges 1H regime onto 15M candles (strictly without forward-looking bias),
    and detects rule-based Pullback Candidate Setups.
    """
    df = df_15m.copy().sort_values("datetime").reset_index(drop=True)
    df_1h_clean = df_1h.copy().sort_values("datetime").reset_index(drop=True)
    
    # Forward-fill 1H regime onto 15M:
    # IMPORTANT: 1H candle is ONLY available when closed!
    # For a 15M candle at 14:15, only the 1H candle up to 14:00 is closed!
    df_1h_clean["available_time"] = df_1h_clean["datetime"] + pd.Timedelta(hours=1)
    
    merged = pd.merge_asof(
        df,
        df_1h_clean[["available_time", "regime_1h", "ema_200_1h", "ema_50_1h", "adx_14_1h"]],
        left_on="datetime",
        right_on="available_time",
        direction="backward"
    ).drop(columns=["available_time"]).fillna(0)
    
    c = merged["close"].to_numpy()
    o = merged["open"].to_numpy()
    h = merged["high"].to_numpy()
    l = merged["low"].to_numpy()
    v = merged["volume"].to_numpy()
    regime = merged["regime_1h"].to_numpy()
    
    # 15M Indicators
    ema_20 = pd.Series(c).ewm(span=config.pullback_ema_fast, adjust=False).mean().to_numpy()
    ema_50 = pd.Series(c).ewm(span=config.pullback_ema_slow, adjust=False).mean().to_numpy()
    rsi_14 = compute_rsi(c, period=config.pullback_rsi_period)
    atr_14 = compute_atr(h, l, c, period=config.atr_period)
    vol_sma20 = pd.Series(v).rolling(20).mean().to_numpy()
    
    merged["ema_20"] = ema_20
    merged["ema_50"] = ema_50
    merged["rsi_14"] = rsi_14
    merged["atr_14"] = atr_14
    merged["vol_sma20"] = vol_sma20
    
    # Candidate setup identification
    candidate_setup = np.zeros(len(merged), dtype=int) # 1: Long, -1: Short, 0: None
    sl_prices = np.zeros(len(merged))
    tp_prices = np.zeros(len(merged))
    
    for i in range(len(merged)):
        cur_c = c[i]
        cur_l = l[i]
        cur_h = h[i]
        cur_v = v[i]
        cur_rsi = rsi_14[i]
        cur_atr = atr_14[i]
        v_ma = vol_sma20[i] if vol_sma20[i] > 0 else 1.0
        
        # Volatility percentile sanity check
        if cur_atr <= 0:
            continue
            
        # 1. SETUP LONG
        if regime[i] == 1:
            pullback_touched = (cur_l <= ema_20[i] * 1.002) or (cur_l <= ema_50[i] * 1.002)
            closed_above_ema20 = cur_c > ema_20[i]
            rsi_valid = config.pullback_rsi_long_min <= cur_rsi <= config.pullback_rsi_long_max
            no_dump_vol = (cur_c >= o[i]) or (cur_v < v_ma * 2.5) # Not a panic dump bar
            
            if pullback_touched and closed_above_ema20 and rsi_valid and no_dump_vol:
                candidate_setup[i] = 1
                sl_prices[i] = cur_c - config.sl_atr_mult * cur_atr
                tp_prices[i] = cur_c + config.tp_atr_mult * cur_atr
                
        # 2. SETUP SHORT
        elif regime[i] == -1:
            pullback_touched = (cur_h >= ema_20[i] * 0.998) or (cur_h >= ema_50[i] * 0.998)
            closed_below_ema20 = cur_c < ema_20[i]
            rsi_valid = config.pullback_rsi_short_min <= cur_rsi <= config.pullback_rsi_short_max
            no_pump_vol = (cur_c <= o[i]) or (cur_v < v_ma * 2.5)
            
            if pullback_touched and closed_below_ema20 and rsi_valid and no_pump_vol:
                candidate_setup[i] = -1
                sl_prices[i] = cur_c + config.sl_atr_mult * cur_atr
                tp_prices[i] = cur_c - config.tp_atr_mult * cur_atr
                
    merged["candidate_setup"] = candidate_setup
    merged["setup_sl"] = sl_prices
    merged["setup_tp"] = tp_prices
    return merged
