import os
import sys
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

data_path = "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m.csv"
df = pd.read_csv(data_path)

c = df["close"].to_numpy()
o = df["open"].to_numpy()
h = df["high"].to_numpy()
l = df["low"].to_numpy()
v = df["volume"].to_numpy()
n = len(df)

# 1. Advanced Quant Features:
# A. Order Flow Proxy (Intrabar buying/selling delta)
spread = np.where((h - l) == 0, 1e-9, h - l)
buy_vol_ratio = (c - l) / spread
vol_delta = v * (buy_vol_ratio - 0.5) * 2 # -v to +v
cvd_6 = pd.Series(vol_delta).rolling(6).sum().to_numpy() # 30m cumulative delta
cvd_12 = pd.Series(vol_delta).rolling(12).sum().to_numpy() # 60m cumulative delta

# B. Multi-timeframe Trend Filter (EMA 50 on 5m = ~4h trend)
ema_50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
trend_dist = (c - ema_50) / ema_50

# C. Momentum Lags & Volatility
ret_1 = pd.Series(c).pct_change(1).to_numpy()
ret_3 = pd.Series(c).pct_change(3).to_numpy()
ret_6 = pd.Series(c).pct_change(6).to_numpy()
vol_spike = v / pd.Series(v).rolling(12).mean().to_numpy()

# 2. Triple Barrier Target with 2.5:1 Risk/Reward
# TP = +1.5%, SL = -0.6% within 24 bars (2 hours)
tp_pct = 0.015
sl_pct = 0.006
max_bars = 24

labels = np.zeros(n, dtype=int)
for i in range(n - max_bars):
    entry = c[i]
    for j in range(1, max_bars + 1):
        idx = i + j
        # If long along trend
        if h[idx] >= entry * (1.0 + tp_pct):
            labels[i] = 1 # Won
            break
        if l[idx] <= entry * (1.0 - sl_pct):
            labels[i] = 0 # Lost
            break

feat_df = pd.DataFrame({
    "ret_1": ret_1,
    "ret_3": ret_3,
    "ret_6": ret_6,
    "vol_spike": vol_spike,
    "cvd_6": cvd_6,
    "cvd_12": cvd_12,
    "trend_dist": trend_dist,
    "body": (c - o) / o,
    "label": labels
}).iloc[50: n - max_bars].reset_index(drop=True)

# Split 70% Train - 30% Test
split = int(len(feat_df) * 0.70)
train_df = feat_df.iloc[:split].copy()
test_df = feat_df.iloc[split:].copy().reset_index(drop=True)

cols = ["ret_1", "ret_3", "ret_6", "vol_spike", "cvd_6", "cvd_12", "trend_dist", "body"]
X_tr = train_df[cols].to_numpy()
y_tr = train_df["label"].to_numpy()
X_te = test_df[cols].to_numpy()
y_te = test_df["label"].to_numpy()

clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.03, max_depth=4, random_state=42)
clf.fit(X_tr, y_tr)

probs = clf.predict_proba(X_te)[:, 1]

# Simulate on Test set
test_raw = df.iloc[50 + split: 50 + split + len(test_df)].copy().reset_index(drop=True)
c_te = test_raw["close"].to_numpy()
h_te = test_raw["high"].to_numpy()
l_te = test_raw["low"].to_numpy()
o_te = test_raw["open"].to_numpy()

def simulate(threshold=0.60, fee_rate=0.00015, leverage=5.0):
    capital = 6.0
    initial = 6.0
    in_pos = False
    entry_p = 0.0
    bars = 0
    trades = []
    
    for i in range(len(test_df) - 1):
        p_up = probs[i]
        
        # In trade: check TP / SL
        if in_pos:
            bars += 1
            cur_h = h_te[i + 1]
            cur_l = l_te[i + 1]
            cur_c = c_te[i + 1]
            closed = False
            pnl_pct = 0.0
            
            if cur_h >= entry_p * (1.0 + tp_pct):
                pnl_pct = tp_pct
                closed = True
            elif cur_l <= entry_p * (1.0 - sl_pct):
                pnl_pct = -sl_pct
                closed = True
            elif bars >= max_bars:
                pnl_pct = (cur_c / entry_p - 1.0)
                closed = True
                
            if closed:
                pos_val = capital * leverage
                net_pnl = pos_val * pnl_pct - pos_val * (fee_rate * 2)
                capital += net_pnl
                trades.append(net_pnl)
                in_pos = False
                
        # Enter trade: Only high conviction + trend confirmation
        if not in_pos and p_up >= threshold and test_df["trend_dist"].iloc[i] > 0:
            in_pos = True
            entry_p = o_te[i + 1]
            bars = 0
            
    win_trades = [t for t in trades if t > 0]
    wr = len(win_trades) / len(trades) * 100 if trades else 0
    tot_ret = (capital / initial - 1.0) * 100
    return capital, tot_ret, len(trades), wr

print("--- Testing Solution 1 + 2 + 3 ---")
for th in [0.55, 0.58, 0.60, 0.62, 0.65]:
    cap, ret, n_trades, wr = simulate(threshold=th, fee_rate=0.00015, leverage=5.0)
    print(f"Threshold={th:.2f} => Capital=${cap:.2f} | Return={ret:+.2f}% | Trades={n_trades} | WinRate={wr:.1f}%")
