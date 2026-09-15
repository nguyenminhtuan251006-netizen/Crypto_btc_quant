"""
Alternative Quantitative Strategies for BTCUSDT (5m & 1m)
Explores 4 distinct alpha archetypes:
1. Squeeze Momentum (Bollinger inside Keltner Channel breakout)
2. SuperTrend Dynamic Breakout (ATR Trend-Following)
3. US Session High-Volatility Momentum (19:00 - 02:00 VN Time)
4. Multi-Timeframe EMA Trend Pullback
"""
import os
import sys
import pandas as pd
import numpy as np

data_path = "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m.csv"
df = pd.read_csv(data_path)
df["datetime"] = pd.to_datetime(df["datetime"])

c = df["close"].to_numpy()
h = df["high"].to_numpy()
l = df["low"].to_numpy()
o = df["open"].to_numpy()
v = df["volume"].to_numpy()
n = len(df)

# Split 70% train / 30% test (out of sample evaluation)
split = int(n * 0.70)
test_df = df.iloc[split:].copy().reset_index(drop=True)
n_test = len(test_df)
c_t = test_df["close"].to_numpy()
h_t = test_df["high"].to_numpy()
l_t = test_df["low"].to_numpy()
o_t = test_df["open"].to_numpy()
dts_t = test_df["datetime"].to_numpy()

# ATR helper
def get_atr(high, low, close, period=14):
    tr = np.zeros(len(close))
    for i in range(1, len(close)):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    return pd.Series(tr).ewm(alpha=1.0/period, adjust=False).mean().to_numpy()

# Generic Backtester for Out-Of-Sample
def backtest_signals(signals, tp_pct=0.015, sl_pct=0.006, leverage=5.0, fee_rate=0.00015):
    capital = 6.0
    initial = 6.0
    in_pos = 0 # 1: Long, -1: Short, 0: Flat
    entry_p = 0.0
    bars = 0
    trades = []
    
    for i in range(n_test - 1):
        sig = signals[i]
        next_o = o_t[i + 1]
        next_h = h_t[i + 1]
        next_l = l_t[i + 1]
        next_c = c_t[i + 1]
        
        if in_pos != 0:
            bars += 1
            closed = False
            pnl = 0.0
            
            if in_pos == 1:
                if next_l <= entry_p * (1.0 - sl_pct):
                    pnl = -sl_pct
                    closed = True
                elif next_h >= entry_p * (1.0 + tp_pct):
                    pnl = tp_pct
                    closed = True
            elif in_pos == -1:
                if next_h >= entry_p * (1.0 + sl_pct):
                    pnl = -sl_pct
                    closed = True
                elif next_l <= entry_p * (1.0 - tp_pct):
                    pnl = tp_pct
                    closed = True
                    
            if not closed and bars >= 24: # max 2 hours
                pnl = (next_c / entry_p - 1.0) if in_pos == 1 else (1.0 - next_c / entry_p)
                closed = True
                
            if closed:
                pos_val = max(5.0, capital * leverage)
                net = pos_val * pnl - pos_val * (fee_rate * 2)
                capital += net
                trades.append(net)
                in_pos = 0
                
        if in_pos == 0 and sig != 0 and capital > 1.0:
            in_pos = sig
            entry_p = next_o
            bars = 0
            
    win_t = [t for t in trades if t > 0]
    wr = len(win_t) / len(trades) * 100 if trades else 0
    ret = (capital / initial - 1.0) * 100
    pnl_s = pd.Series(trades) if trades else pd.Series([0])
    sharpe = (pnl_s.mean() / (pnl_s.std() + 1e-9)) * np.sqrt(288 * 30) if len(trades) > 1 else 0
    return {
        "Capital": round(capital, 2),
        "Return (%)": round(ret, 2),
        "Sharpe": round(sharpe, 2),
        "Win Rate (%)": round(wr, 1),
        "Trades": len(trades)
    }

print("=" * 75)
print("   EVALUATING ALTERNATIVE CRYPTO QUANT STRATEGIES (OUT-OF-SAMPLE)")
print("=" * 75)

# --- STRATEGY 1: Squeeze Momentum (John Carter) ---
# Bollinger Bands (20, 2.0) vs Keltner Channels (20, 1.5 ATR)
sma_20 = pd.Series(c_t).rolling(20).mean().to_numpy()
std_20 = pd.Series(c_t).rolling(20).std().to_numpy()
bb_up = sma_20 + 2.0 * std_20
bb_dn = sma_20 - 2.0 * std_20
atr_20 = get_atr(h_t, l_t, c_t, 20)
kc_up = sma_20 + 1.5 * atr_20
kc_dn = sma_20 - 1.5 * atr_20

# Squeeze is on when BB is inside KC
squeeze_on = (bb_up < kc_up) & (bb_dn > kc_dn)
squeeze_fired = (~squeeze_on) & pd.Series(squeeze_on).shift(1).fillna(False).to_numpy()

sig_squeeze = np.zeros(n_test, dtype=int)
for i in range(1, n_test):
    if squeeze_fired[i]:
        if c_t[i] > sma_20[i]:
            sig_squeeze[i] = 1
        elif c_t[i] < sma_20[i]:
            sig_squeeze[i] = -1

res_squeeze = backtest_signals(sig_squeeze, tp_pct=0.015, sl_pct=0.006)
print(f"1. Squeeze Momentum Breakout    => Return: {res_squeeze['Return (%)']:+6.2f}% | Sharpe: {res_squeeze['Sharpe']:4.2f} | WR: {res_squeeze['Win Rate (%)']:4.1f}% | Trades: {res_squeeze['Trades']}")

# --- STRATEGY 2: SuperTrend Dynamic Trend Following ---
def compute_supertrend(high, low, close, period=10, multiplier=3.0):
    atr = get_atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    n = len(close)
    st = np.zeros(n)
    direction = np.zeros(n, dtype=int) # 1: Up, -1: Down
    
    for i in range(1, n):
        if close[i] > upper[i-1]:
            direction[i] = 1
        elif close[i] < lower[i-1]:
            direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1 and lower[i] < lower[i-1]:
                lower[i] = lower[i-1]
            if direction[i] == -1 and upper[i] > upper[i-1]:
                upper[i] = upper[i-1]
                
    # Flip signals
    signals = np.zeros(n, dtype=int)
    for i in range(1, n):
        if direction[i] == 1 and direction[i-1] == -1:
            signals[i] = 1
        elif direction[i] == -1 and direction[i-1] == 1:
            signals[i] = -1
    return signals

sig_st = compute_supertrend(h_t, l_t, c_t, period=10, multiplier=2.5)
res_st = backtest_signals(sig_st, tp_pct=0.018, sl_pct=0.007)
print(f"2. SuperTrend 10/2.5 Breakout   => Return: {res_st['Return (%)']:+6.2f}% | Sharpe: {res_st['Sharpe']:4.2f} | WR: {res_st['Win Rate (%)']:4.1f}% | Trades: {res_st['Trades']}")

# --- STRATEGY 3: US Session Momentum (19:00 - 02:00 VN Time) ---
# High liquidity when US NYSE/CME opens
dts_series = pd.Series(test_df["datetime"])
hours = dts_series.dt.hour.to_numpy()
is_us_session = (hours >= 19) | (hours <= 2)

# Donchian 20 specifically traded ONLY during US session
dc_high = pd.Series(h_t).rolling(20).max().shift(1).to_numpy()
dc_low = pd.Series(l_t).rolling(20).min().shift(1).to_numpy()

sig_us_dc = np.zeros(n_test, dtype=int)
for i in range(20, n_test):
    if is_us_session[i]:
        if c_t[i] > dc_high[i]:
            sig_us_dc[i] = 1
        elif c_t[i] < dc_low[i]:
            sig_us_dc[i] = -1

res_us = backtest_signals(sig_us_dc, tp_pct=0.015, sl_pct=0.006)
print(f"3. US Session Donchian (19h-02h) => Return: {res_us['Return (%)']:+6.2f}% | Sharpe: {res_us['Sharpe']:4.2f} | WR: {res_us['Win Rate (%)']:4.1f}% | Trades: {res_us['Trades']}")

# --- STRATEGY 4: Multi-Timeframe EMA Trend + Volume Confirmation ---
ema_50 = pd.Series(c_t).ewm(span=50, adjust=False).mean().to_numpy()
ema_200 = pd.Series(c_t).ewm(span=200, adjust=False).mean().to_numpy()
vol_sma = pd.Series(test_df["volume"]).rolling(20).mean().to_numpy()
vol_surge = test_df["volume"].to_numpy() > (1.8 * vol_sma)

sig_ema_vol = np.zeros(n_test, dtype=int)
for i in range(200, n_test):
    # Bullish Trend + Volume Surge
    if ema_50[i] > ema_200[i] and c_t[i] > ema_50[i] and vol_surge[i] and c_t[i] > o_t[i]:
        sig_ema_vol[i] = 1
    # Bearish Trend + Volume Surge
    elif ema_50[i] < ema_200[i] and c_t[i] < ema_50[i] and vol_surge[i] and c_t[i] < o_t[i]:
        sig_ema_vol[i] = -1

res_ema_vol = backtest_signals(sig_ema_vol, tp_pct=0.012, sl_pct=0.005)
print(f"4. EMA Trend + Volume Surge     => Return: {res_ema_vol['Return (%)']:+6.2f}% | Sharpe: {res_ema_vol['Sharpe']:4.2f} | WR: {res_ema_vol['Win Rate (%)']:4.1f}% | Trades: {res_ema_vol['Trades']}")
print("=" * 75)
