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

# Triple barrier target
tp_pct = 0.010
sl_pct = 0.005
max_bars = 18

labels = np.zeros(n, dtype=int)
for i in range(n - max_bars):
    entry = c[i]
    for j in range(1, max_bars + 1):
        if h[idx := i + j] >= entry * (1.0 + tp_pct):
            labels[i] = 1
            break
        if l[idx] <= entry * (1.0 - sl_pct):
            labels[i] = 0
            break

ret_1 = pd.Series(c).pct_change(1).to_numpy()
ret_3 = pd.Series(c).pct_change(3).to_numpy()
ret_6 = pd.Series(c).pct_change(6).to_numpy()
vol_spike = v / pd.Series(v).rolling(12).mean().to_numpy()
ema_50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
trend_dist = (c - ema_50) / ema_50

feat_df = pd.DataFrame({
    "ret_1": ret_1,
    "ret_3": ret_3,
    "ret_6": ret_6,
    "vol_spike": vol_spike,
    "trend_dist": trend_dist,
    "body": (c - o) / o,
    "label": labels
}).iloc[50: n - max_bars].reset_index(drop=True)

split = int(len(feat_df) * 0.70)
train_df = feat_df.iloc[:split].copy()
test_df = feat_df.iloc[split:].copy().reset_index(drop=True)

cols = ["ret_1", "ret_3", "ret_6", "vol_spike", "trend_dist", "body"]
X_tr = train_df[cols].to_numpy()
y_tr = train_df["label"].to_numpy()
X_te = test_df[cols].to_numpy()

clf = HistGradientBoostingClassifier(class_weight="balanced", max_iter=150, learning_rate=0.03, max_depth=4, random_state=42)
clf.fit(X_tr, y_tr)

probs = clf.predict_proba(X_te)[:, 1]

test_raw = df.iloc[50 + split: 50 + split + len(test_df)].copy().reset_index(drop=True)
c_te = test_raw["close"].to_numpy()
h_te = test_raw["high"].to_numpy()
l_te = test_raw["low"].to_numpy()
o_te = test_raw["open"].to_numpy()

def simulate_trailing(trail_trigger=0.008, trail_callback=0.0035, leverage=5.0, top_pct=90):
    capital = 6.0
    initial = 6.0
    in_pos = False
    entry_p = 0.0
    best_p = 0.0
    bars = 0
    trades = []
    
    threshold = np.percentile(probs, top_pct)
    fee_rate = 0.00015
    
    for i in range(len(test_df) - 1):
        p_up = probs[i]
        
        if in_pos:
            bars += 1
            cur_h = h_te[i + 1]
            cur_l = l_te[i + 1]
            cur_c = c_te[i + 1]
            closed = False
            pnl_pct = 0.0
            
            best_p = max(best_p, cur_h)
            
            # 1. Check Trailing Stop
            if best_p >= entry_p * (1.0 + trail_trigger):
                # Trailing active: stop level moves up
                stop_level = best_p * (1.0 - trail_callback)
                if cur_l <= stop_level:
                    exit_price = min(cur_c, stop_level)
                    pnl_pct = (exit_price / entry_p - 1.0)
                    closed = True
            elif cur_l <= entry_p * (1.0 - sl_pct):
                pnl_pct = -sl_pct
                closed = True
            elif bars >= max_bars:
                pnl_pct = (cur_c / entry_p - 1.0)
                closed = True
                
            if closed:
                # Dynamic Compounding Position
                pos_val = max(5.0, capital * leverage)
                net_pnl = pos_val * pnl_pct - pos_val * (fee_rate * 2)
                capital += net_pnl
                trades.append(net_pnl)
                in_pos = False
                
        if not in_pos and p_up >= threshold and test_df["trend_dist"].iloc[i] > 0 and capital > 1.0:
            in_pos = True
            entry_p = o_te[i + 1]
            best_p = entry_p
            bars = 0
            
    win_trades = [t for t in trades if t > 0]
    wr = len(win_trades) / len(trades) * 100 if trades else 0
    tot_ret = (capital / initial - 1.0) * 100
    return capital, tot_ret, len(trades), wr

print("--- Testing Trailing Stop + Compounding ---")
for trig in [0.006, 0.008, 0.010]:
    for cb in [0.0025, 0.0035, 0.0045]:
        for lev in [5.0, 7.0]:
            cap, ret, n_trades, wr = simulate_trailing(trail_trigger=trig, trail_callback=cb, leverage=lev)
            print(f"Trigger={trig*100:.1f}% Callback={cb*100:.2f}% Lev={lev}x => Capital=${cap:.2f} | Return={ret:+.2f}% | Trades={n_trades} | WinRate={wr:.1f}%")
