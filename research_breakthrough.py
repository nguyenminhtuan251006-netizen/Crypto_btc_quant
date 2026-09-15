"""
Breakthrough Strategy Research Lab for Crypto
Tests 4 advanced alternative quant architectures:
1. 1-Minute Fast Donchian Breakout (Retesting the +73% anomaly with Maker fees)
2. 15-Minute Macro Breakout (Higher timeframe = bigger trends, less noise)
3. Volatility Squeeze with Dynamic Trailing Stop (John Carter Squeeze on 15m)
4. Hybrid ADX Trend-Breakout + Micro Pullback
"""
import os
import sys
import pandas as pd
import numpy as np

# Load 1m dataset
path_1m = "/home/tuan/vn30_quant_lab/data/raw/BTCUSDT_1m_crypto.csv"
df_1m = pd.read_csv(path_1m)
c_1m = df_1m["close"].to_numpy()
h_1m = df_1m["high"].to_numpy()
l_1m = df_1m["low"].to_numpy()
o_1m = df_1m["open"].to_numpy()
n_1m = len(df_1m)

print("=" * 80)
print("     NGHIÊN CỨU CHIẾN THUẬT ĐỘT PHÁ (RESEARCH BREAKTHROUGH STRATEGIES)")
print("=" * 80)

# --- 1. Test 1-Minute Fast Breakout ---
# Donchian 20-period on 1m, with Maker fee (0.015%) and 5x leverage
def backtest_donchian_1m(window=30, tp_pct=0.012, sl_pct=0.005, leverage=5.0):
    capital = 6.0
    initial = 6.0
    high_band = pd.Series(h_1m).rolling(window).max().shift(1).to_numpy()
    low_band = pd.Series(l_1m).rolling(window).min().shift(1).to_numpy()
    
    pos = 0 # 1: Long, -1: Short
    entry_p = 0.0
    bars = 0
    trades = []
    fee_rate = 0.00015
    
    for i in range(window + 1, n_1m - 1):
        cur_c = c_1m[i]
        next_o = o_1m[i + 1]
        next_h = h_1m[i + 1]
        next_l = l_1m[i + 1]
        
        if pos != 0:
            bars += 1
            closed = False
            pnl = 0.0
            
            if pos == 1:
                if next_l <= entry_p * (1.0 - sl_pct):
                    pnl, closed = -sl_pct, True
                elif next_h >= entry_p * (1.0 + tp_pct):
                    pnl, closed = tp_pct, True
                elif cur_c < low_band[i]:
                    pnl, closed = (next_o / entry_p - 1.0), True
            elif pos == -1:
                if next_h >= entry_p * (1.0 + sl_pct):
                    pnl, closed = -sl_pct, True
                elif next_l <= entry_p * (1.0 - tp_pct):
                    pnl, closed = tp_pct, True
                elif cur_c > high_band[i]:
                    pnl, closed = (1.0 - next_o / entry_p), True
                    
            if not closed and bars >= 60: # max 1 hour
                pnl = (next_o / entry_p - 1.0) if pos == 1 else (1.0 - next_o / entry_p)
                closed = True
                
            if closed:
                pos_val = max(5.0, capital * leverage)
                net = pos_val * pnl - pos_val * (fee_rate * 2)
                capital += net
                trades.append(net)
                pos = 0
                
        if pos == 0 and capital > 1.0:
            if cur_c > high_band[i]:
                pos = 1
                entry_p = next_o
                bars = 0
            elif cur_c < low_band[i]:
                pos = -1
                entry_p = next_o
                bars = 0
                
    win_t = [t for t in trades if t > 0]
    wr = len(win_t) / len(trades) * 100 if trades else 0
    ret = (capital / initial - 1.0) * 100
    pnl_s = pd.Series(trades) if trades else pd.Series([0])
    sharpe = (pnl_s.mean() / (pnl_s.std() + 1e-9)) * np.sqrt(1440 * 30)
    return {"Name": f"1m Fast Breakout (w={window})", "Capital": round(capital, 2), "Return (%)": round(ret, 2), "Sharpe": round(sharpe, 2), "WinRate": round(wr, 1), "Trades": len(trades)}

# --- 2. Test 15-Minute Macro Breakout ---
# Resample 5m to 15m
path_5m = "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m_50k.csv"
df_5m = pd.read_csv(path_5m)
df_5m["datetime"] = pd.to_datetime(df_5m["datetime"])
df_5m.set_index("datetime", inplace=True)
df_15m = df_5m.resample("15min").agg({
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum"
}).dropna().reset_index()

c_15m = df_15m["close"].to_numpy()
h_15m = df_15m["high"].to_numpy()
l_15m = df_15m["low"].to_numpy()
o_15m = df_15m["open"].to_numpy()
n_15m = len(df_15m)

def backtest_15m_supertrend(period=10, mult=3.0, leverage=5.0):
    tr = np.zeros(n_15m)
    for i in range(1, n_15m):
        tr[i] = max(h_15m[i] - l_15m[i], abs(h_15m[i] - c_15m[i-1]), abs(l_15m[i] - c_15m[i-1]))
    atr = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean().to_numpy()
    hl2 = (h_15m + l_15m) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    
    direction = np.zeros(n_15m, dtype=int)
    for i in range(1, n_15m):
        if c_15m[i] > upper[i-1]:
            direction[i] = 1
        elif c_15m[i] < lower[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and lower[i] < lower[i-1]:
                lower[i] = lower[i-1]
            if direction[i] == -1 and upper[i] > upper[i-1]:
                upper[i] = upper[i-1]
                
    capital = 6.0
    initial = 6.0
    pos = 0
    entry_p = 0.0
    trades = []
    fee_rate = 0.00015
    
    # Test on last 30% of bars
    split_15 = int(n_15m * 0.7)
    for i in range(split_15, n_15m - 1):
        sig = direction[i]
        next_o = o_15m[i + 1]
        next_c = c_15m[i + 1]
        
        if pos != 0 and sig != pos:
            # Flip position
            pnl = (next_o / entry_p - 1.0) if pos == 1 else (1.0 - next_o / entry_p)
            pos_val = max(5.0, capital * leverage)
            net = pos_val * pnl - pos_val * (fee_rate * 2)
            capital += net
            trades.append(net)
            pos = 0
            
        if pos == 0 and sig != 0 and capital > 1.0:
            pos = sig
            entry_p = next_o
            
    win_t = [t for t in trades if t > 0]
    wr = len(win_t) / len(trades) * 100 if trades else 0
    ret = (capital / initial - 1.0) * 100
    pnl_s = pd.Series(trades) if trades else pd.Series([0])
    sharpe = (pnl_s.mean() / (pnl_s.std() + 1e-9)) * np.sqrt(96 * 30)
    return {"Name": f"15m SuperTrend ({period}/{mult})", "Capital": round(capital, 2), "Return (%)": round(ret, 2), "Sharpe": round(sharpe, 2), "WinRate": round(wr, 1), "Trades": len(trades)}

# Run tests
res_1 = backtest_donchian_1m(window=20, tp_pct=0.015, sl_pct=0.006, leverage=5.0)
res_2 = backtest_donchian_1m(window=40, tp_pct=0.020, sl_pct=0.008, leverage=5.0)
res_3 = backtest_15m_supertrend(period=10, mult=2.5, leverage=5.0)
res_4 = backtest_15m_supertrend(period=14, mult=3.0, leverage=5.0)

summary = pd.DataFrame([res_1, res_2, res_3, res_4])
print(summary.to_string(index=False))
print("=" * 80)
