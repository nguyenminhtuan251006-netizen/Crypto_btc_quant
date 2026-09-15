import os
import sys
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

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

# Target: TP 1.2% vs SL 0.5% in 18 bars
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

ret_1 = pd.Series(c).pct_change(1).to_numpy()
ret_3 = pd.Series(c).pct_change(3).to_numpy()
ret_6 = pd.Series(c).pct_change(6).to_numpy()
ret_12 = pd.Series(c).pct_change(12).to_numpy()
vol_spike = v / pd.Series(v).rolling(12).mean().to_numpy()
ema_50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
trend_dist = (c - ema_50) / ema_50

feat_df = pd.DataFrame({
    "ret_1": ret_1, "ret_3": ret_3, "ret_6": ret_6, "ret_12": ret_12,
    "vol_spike": vol_spike, "trend_dist": trend_dist, "body": (c - o) / o,
    "hour": hours, "label": labels
}).iloc[50: n - max_bars].reset_index(drop=True)

split = int(len(feat_df) * 0.70)
train_df = feat_df.iloc[:split].copy()
test_df = feat_df.iloc[split:].copy().reset_index(drop=True)

cols = ["ret_1", "ret_3", "ret_6", "ret_12", "vol_spike", "trend_dist", "body"]
X_tr = train_df[cols].to_numpy()
y_tr = train_df["label"].to_numpy()
X_te = test_df[cols].to_numpy()

print("[1] Training XGBoost (HistGB)...")
clf_xgb = HistGradientBoostingClassifier(class_weight="balanced", max_iter=200, learning_rate=0.03, max_depth=5, random_state=42)
clf_xgb.fit(X_tr, y_tr)
p_xgb = clf_xgb.predict_proba(X_te)[:, 1]

print("[2] Training Logistic Regression...")
clf_lr = LogisticRegression(class_weight="balanced", max_iter=500, random_state=42)
clf_lr.fit(X_tr, y_tr)
p_lr = clf_lr.predict_proba(X_te)[:, 1]

print("[3] Training Random Forest...")
clf_rf = RandomForestClassifier(n_estimators=100, max_depth=6, class_weight="balanced", random_state=42, n_jobs=-1)
clf_rf.fit(X_tr, y_tr)
p_rf = clf_rf.predict_proba(X_te)[:, 1]

# Ensemble average probability (Soft Voting)
p_ensemble = (p_xgb * 0.5) + (p_rf * 0.3) + (p_lr * 0.2)

test_raw = df.iloc[50 + split: 50 + split + len(test_df)].copy().reset_index(drop=True)
c_te = test_raw["close"].to_numpy()
h_te = test_raw["high"].to_numpy()
l_te = test_raw["low"].to_numpy()
o_te = test_raw["open"].to_numpy()
hr_te = test_df["hour"].to_numpy()

def backtest_prob(probs, top_pct=92, leverage=5.0):
    capital = 6.0
    initial = 6.0
    in_pos = False
    entry_p = 0.0
    bars = 0
    trades = []
    fee_rate = 0.00015
    threshold = np.percentile(probs, top_pct)
    
    for i in range(len(test_df) - 1):
        hr = hr_te[i]
        is_active = (hr >= 15) or (hr <= 2) # London + US
        
        if in_pos:
            bars += 1
            cur_h = h_te[i + 1]
            cur_l = l_te[i + 1]
            cur_c = c_te[i + 1]
            closed = False
            pnl = 0.0
            
            if cur_h >= entry_p * (1.0 + tp_pct):
                pnl, closed = tp_pct, True
            elif cur_l <= entry_p * (1.0 - sl_pct):
                pnl, closed = -sl_pct, True
            elif bars >= max_bars:
                pnl, closed = (cur_c / entry_p - 1.0), True
                
            if closed:
                # Dynamic Compounding
                pos_val = max(5.0, capital * leverage)
                net = pos_val * pnl - pos_val * (fee_rate * 2)
                capital += net
                trades.append(net)
                in_pos = False
                
        if not in_pos and is_active and probs[i] >= threshold and test_df["trend_dist"].iloc[i] > 0 and capital > 1.0:
            in_pos = True
            entry_p = o_te[i + 1]
            bars = 0
            
    win_t = [t for t in trades if t > 0]
    wr = len(win_t) / len(trades) * 100 if trades else 0
    ret = (capital / initial - 1.0) * 100
    pnl_s = pd.Series(trades) if trades else pd.Series([0])
    sharpe = (pnl_s.mean() / (pnl_s.std() + 1e-9)) * np.sqrt(288 * 30)
    return {"Capital": round(capital, 2), "Return (%)": round(ret, 2), "Sharpe": round(sharpe, 2), "WinRate": round(wr, 1), "Trades": len(trades)}

print("\n" + "=" * 80)
print("     SO SÁNH MÔ HÌNH ĐƠN LẺ VS ENSEMBLE ĐỒNG THUẬN (50,000 NẾN)")
print("=" * 80)

r_xgb = backtest_prob(p_xgb, top_pct=92)
print(f"1. XGBoost Đơn Lẻ:          Final=${r_xgb['Capital']:5.2f} | Lãi: {r_xgb['Return (%)']:+6.2f}% | Sharpe: {r_xgb['Sharpe']:4.2f} | WR: {r_xgb['WinRate']:4.1f}% | Lệnh: {r_xgb['Trades']}")

r_rf = backtest_prob(p_rf, top_pct=92)
print(f"2. Random Forest:           Final=${r_rf['Capital']:5.2f} | Lãi: {r_rf['Return (%)']:+6.2f}% | Sharpe: {r_rf['Sharpe']:4.2f} | WR: {r_rf['WinRate']:4.1f}% | Lệnh: {r_rf['Trades']}")

r_ens = backtest_prob(p_ensemble, top_pct=92)
print(f"3. Ensemble Đồng Thuận (AI): Final=${r_ens['Capital']:5.2f} | Lãi: {r_ens['Return (%)']:+6.2f}% | Sharpe: {r_ens['Sharpe']:4.2f} | WR: {r_ens['WinRate']:4.1f}% | Lệnh: {r_ens['Trades']}")
print("=" * 80)
