import os
import sys
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

data_path = "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m_50k.csv"
df = pd.read_csv(data_path)
df["datetime"] = pd.to_datetime(df["datetime"])

c = df["close"].to_numpy()
o = df["open"].to_numpy()
h = df["high"].to_numpy()
l = df["low"].to_numpy()
v = df["volume"].to_numpy()
hours = df["datetime"].dt.hour.to_numpy()
n = len(df)

# Triple barrier target: TP = +1.2%, SL = -0.5% (2.4:1 R/R) within 18 bars (90m)
tp_pct = 0.012
sl_pct = 0.005
max_bars = 18

labels = np.zeros(n, dtype=int)
for i in range(n - max_bars):
    entry = c[i]
    for j in range(1, max_bars + 1):
        idx = i + j
        if h[idx] >= entry * (1.0 + tp_pct):
            labels[i] = 1
            break
        if l[idx] <= entry * (1.0 - sl_pct):
            labels[i] = 0
            break

# Technical Features
ret_1 = pd.Series(c).pct_change(1).to_numpy()
ret_3 = pd.Series(c).pct_change(3).to_numpy()
ret_6 = pd.Series(c).pct_change(6).to_numpy()
ret_12 = pd.Series(c).pct_change(12).to_numpy()
vol_spike = v / pd.Series(v).rolling(12).mean().to_numpy()
ema_50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
trend_dist = (c - ema_50) / ema_50

feat_df = pd.DataFrame({
    "ret_1": ret_1,
    "ret_3": ret_3,
    "ret_6": ret_6,
    "ret_12": ret_12,
    "vol_spike": vol_spike,
    "trend_dist": trend_dist,
    "body": (c - o) / o,
    "hour": hours,
    "label": labels
}).iloc[50: n - max_bars].reset_index(drop=True)

# 70% Train, 30% Test Out-Of-Sample
split = int(len(feat_df) * 0.70)
train_df = feat_df.iloc[:split].copy()
test_df = feat_df.iloc[split:].copy().reset_index(drop=True)

cols = ["ret_1", "ret_3", "ret_6", "ret_12", "vol_spike", "trend_dist", "body"]
X_tr = train_df[cols].to_numpy()
y_tr = train_df["label"].to_numpy()
X_te = test_df[cols].to_numpy()

print(f"Training XGBoost on {len(train_df)} bars (March - July 2026)...")
clf = HistGradientBoostingClassifier(class_weight="balanced", max_iter=200, learning_rate=0.03, max_depth=5, random_state=42)
clf.fit(X_tr, y_tr)

probs = clf.predict_proba(X_te)[:, 1]

test_raw = df.iloc[50 + split: 50 + split + len(test_df)].copy().reset_index(drop=True)
c_te = test_raw["close"].to_numpy()
h_te = test_raw["high"].to_numpy()
l_te = test_raw["low"].to_numpy()
o_te = test_raw["open"].to_numpy()
hr_te = test_df["hour"].to_numpy()

print(f"Evaluating Out-Of-Sample on {len(test_df)} bars (July - Sept 2026 ~ 52 days)...")

def simulate(top_pct=90, session_filter="london_us", leverage=5.0):
    capital = 6.0
    initial = 6.0
    in_pos = False
    entry_p = 0.0
    bars = 0
    trades = []
    
    threshold = np.percentile(probs, top_pct)
    fee_rate = 0.00015
    
    for i in range(len(test_df) - 1):
        p_up = probs[i]
        hr = hr_te[i]
        
        if session_filter == "us_only":
            is_active = (hr >= 19) or (hr <= 2)
        elif session_filter == "london_us":
            is_active = (hr >= 15) or (hr <= 2)
        else:
            is_active = True
            
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
                pos_val = max(5.0, capital * leverage)
                net_pnl = pos_val * pnl_pct - pos_val * (fee_rate * 2)
                capital += net_pnl
                trades.append(net_pnl)
                in_pos = False
                
        if not in_pos and is_active and p_up >= threshold and test_df["trend_dist"].iloc[i] > 0 and capital > 1.0:
            in_pos = True
            entry_p = o_te[i + 1]
            bars = 0
            
    win_t = [t for t in trades if t > 0]
    wr = len(win_t) / len(trades) * 100 if trades else 0
    tot_ret = (capital / initial - 1.0) * 100
    pnl_s = pd.Series(trades) if trades else pd.Series([0])
    sharpe = (pnl_s.mean() / (pnl_s.std() + 1e-9)) * np.sqrt(288 * 30)
    return capital, tot_ret, sharpe, wr, len(trades)

print("\n--- 6-MONTH HISTORICAL BACKTEST RESULTS (Vốn 6.0 USDT ~ 150k VNĐ) ---")
for filter_mode in ["london_us", "us_only"]:
    for pct in [88, 90, 92]:
        cap, ret, sh, wr, n_tr = simulate(top_pct=pct, session_filter=filter_mode, leverage=5.0)
        print(f"Session: {filter_mode:10s} | Top {100-pct:2d}% Conviction => Final: ${cap:6.2f} | Return: {ret:+6.2f}% | Sharpe: {sh:5.2f} | WinRate: {wr:4.1f}% | Trades: {n_tr}")
