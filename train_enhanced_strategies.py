"""
Research & Training Lab: Enhanced Crypto Strategies
Testing:
1. Dual-Direction AI (Long + Short)
2. ATR-Dynamic Risk/Reward (Adaptive to market volatility)
3. Higher Leverage (7x vs 5x) with strict trailing risk control
"""
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

# ATR calculation
tr = np.zeros(n)
for i in range(1, n):
    tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
atr_14 = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().to_numpy()
atr_pct = atr_14 / c

# Features
ret_1 = pd.Series(c).pct_change(1).to_numpy()
ret_3 = pd.Series(c).pct_change(3).to_numpy()
ret_6 = pd.Series(c).pct_change(6).to_numpy()
ret_12 = pd.Series(c).pct_change(12).to_numpy()
vol_spike = v / pd.Series(v).rolling(12).mean().to_numpy()
ema_50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
trend_dist = (c - ema_50) / ema_50
rsi_14 = pd.Series(np.where(ret_1 > 0, ret_1, 0.0)).ewm(alpha=1/14).mean() / (
    pd.Series(np.where(ret_1 < 0, -ret_1, 0.0)).ewm(alpha=1/14).mean() + 1e-9)
rsi_14 = 100 - (100 / (1 + rsi_14.to_numpy()))

# Target definition
# Dual Labels:
# Up target: touches +1.2% before -0.5%
# Down target: touches -1.2% before +0.5%
tp_pct = 0.012
sl_pct = 0.005
max_bars = 18

labels_up = np.zeros(n, dtype=int)
labels_down = np.zeros(n, dtype=int)

for i in range(n - max_bars):
    entry = c[i]
    for j in range(1, max_bars + 1):
        idx = i + j
        # UP test
        if h[idx] >= entry * (1.0 + tp_pct):
            labels_up[i] = 1
            break
        if l[idx] <= entry * (1.0 - sl_pct):
            labels_up[i] = 0
            break
            
    for j in range(1, max_bars + 1):
        idx = i + j
        # DOWN test
        if l[idx] <= entry * (1.0 - tp_pct):
            labels_down[i] = 1
            break
        if h[idx] >= entry * (1.0 + sl_pct):
            labels_down[i] = 0
            break

feat_df = pd.DataFrame({
    "ret_1": ret_1, "ret_3": ret_3, "ret_6": ret_6, "ret_12": ret_12,
    "vol_spike": vol_spike, "trend_dist": trend_dist, "rsi_14": rsi_14,
    "atr_pct": atr_pct, "body": (c - o) / o, "hour": hours,
    "label_up": labels_up, "label_down": labels_down
}).iloc[50: n - max_bars].reset_index(drop=True)

# 70% Train - 30% Test Out-Of-Sample
split = int(len(feat_df) * 0.70)
train_df = feat_df.iloc[:split].copy()
test_df = feat_df.iloc[split:].copy().reset_index(drop=True)

feature_cols = ["ret_1", "ret_3", "ret_6", "ret_12", "vol_spike", "trend_dist", "rsi_14", "atr_pct", "body"]
X_tr = train_df[feature_cols].to_numpy()
X_te = test_df[feature_cols].to_numpy()

print(f"[Training] Model UP on {len(train_df)} bars...")
clf_up = HistGradientBoostingClassifier(class_weight="balanced", max_iter=200, learning_rate=0.03, max_depth=5, random_state=42)
clf_up.fit(X_tr, train_df["label_up"].to_numpy())
probs_up = clf_up.predict_proba(X_te)[:, 1]

print(f"[Training] Model DOWN on {len(train_df)} bars...")
clf_down = HistGradientBoostingClassifier(class_weight="balanced", max_iter=200, learning_rate=0.03, max_depth=5, random_state=42)
clf_down.fit(X_tr, train_df["label_down"].to_numpy())
probs_down = clf_down.predict_proba(X_te)[:, 1]

test_raw = df.iloc[50 + split: 50 + split + len(test_df)].copy().reset_index(drop=True)
c_te = test_raw["close"].to_numpy()
h_te = test_raw["high"].to_numpy()
l_te = test_raw["low"].to_numpy()
o_te = test_raw["open"].to_numpy()
hr_te = test_df["hour"].to_numpy()
atr_te = test_df["atr_pct"].to_numpy()

# Simulation function
def simulate_advanced(mode="long_only", leverage=5.0, top_pct=88, use_atr_tp=False):
    capital = 6.0
    initial = 6.0
    pos = 0 # 1: Long, -1: Short, 0: Flat
    entry_p = 0.0
    bars = 0
    trades = []
    
    th_up = np.percentile(probs_up, top_pct)
    th_dn = np.percentile(probs_down, top_pct)
    fee_rate = 0.00015
    
    for i in range(len(test_df) - 1):
        hr = hr_te[i]
        is_active = (hr >= 15) or (hr <= 2)
        cur_atr = atr_te[i]
        
        cur_tp = max(0.010, cur_atr * 2.5) if use_atr_tp else tp_pct
        cur_sl = max(0.004, cur_atr * 1.0) if use_atr_tp else sl_pct
        
        if pos != 0:
            bars += 1
            cur_h = h_te[i + 1]
            cur_l = l_te[i + 1]
            cur_c = c_te[i + 1]
            closed = False
            pnl_pct = 0.0
            
            if pos == 1:
                if cur_h >= entry_p * (1.0 + cur_tp):
                    pnl_pct = cur_tp
                    closed = True
                elif cur_l <= entry_p * (1.0 - cur_sl):
                    pnl_pct = -cur_sl
                    closed = True
            elif pos == -1:
                if cur_l <= entry_p * (1.0 - cur_tp):
                    pnl_pct = cur_tp
                    closed = True
                elif cur_h >= entry_p * (1.0 + cur_sl):
                    pnl_pct = -cur_sl
                    closed = True
                    
            if not closed and bars >= max_bars:
                pnl_pct = (cur_c / entry_p - 1.0) if pos == 1 else (1.0 - cur_c / entry_p)
                closed = True
                
            if closed:
                pos_val = max(5.0, capital * leverage)
                net_pnl = pos_val * pnl_pct - pos_val * (fee_rate * 2)
                capital += net_pnl
                trades.append(net_pnl)
                pos = 0
                
        # Entry logic
        if pos == 0 and is_active and capital > 1.0:
            p_u = probs_up[i]
            p_d = probs_down[i]
            td = test_df["trend_dist"].iloc[i]
            
            # LONG check
            if p_u >= th_up and td > 0:
                pos = 1
                entry_p = o_te[i + 1]
                bars = 0
            # SHORT check (if mode supports short)
            elif mode in ["dual", "short_only"] and p_d >= th_dn and td < 0:
                pos = -1
                entry_p = o_te[i + 1]
                bars = 0
                
    win_t = [t for t in trades if t > 0]
    wr = len(win_t) / len(trades) * 100 if trades else 0
    tot_ret = (capital / initial - 1.0) * 100
    pnl_s = pd.Series(trades) if trades else pd.Series([0])
    sharpe = (pnl_s.mean() / (pnl_s.std() + 1e-9)) * np.sqrt(288 * 30)
    
    # Calculate Max Drawdown
    equity_series = pd.Series([initial] + [initial + sum(trades[:k+1]) for k in range(len(trades))])
    cummax = equity_series.cummax()
    max_dd = ((cummax - equity_series) / cummax * 100).max()
    
    return {
        "Capital": round(capital, 2),
        "Return (%)": round(tot_ret, 2),
        "Sharpe": round(sharpe, 2),
        "Max DD (%)": round(max_dd, 2),
        "Win Rate (%)": round(wr, 1),
        "Trades": len(trades)
    }

print("\n" + "=" * 80)
print("             SO SÁNH CÁC CHIẾN THUẬT NÂNG CAO TRÊN 50,000 NẾN (OUT-OF-SAMPLE)")
print("=" * 80)

res_long = simulate_advanced(mode="long_only", leverage=5.0, top_pct=88)
print(f"Chiến thuật 1 (Long Only - 5x):        Final=${res_long['Capital']:5.2f} | Lãi: {res_long['Return (%)']:+6.2f}% | Sharpe: {res_long['Sharpe']:4.2f} | MaxDD: {res_long['Max DD (%)']:4.1f}% | Lệnh: {res_long['Trades']}")

res_dual_5x = simulate_advanced(mode="dual", leverage=5.0, top_pct=88)
print(f"Chiến thuật 2 (Dual Long+Short - 5x):   Final=${res_dual_5x['Capital']:5.2f} | Lãi: {res_dual_5x['Return (%)']:+6.2f}% | Sharpe: {res_dual_5x['Sharpe']:4.2f} | MaxDD: {res_dual_5x['Max DD (%)']:4.1f}% | Lệnh: {res_dual_5x['Trades']}")

res_dual_7x = simulate_advanced(mode="dual", leverage=7.0, top_pct=88)
print(f"Chiến thuật 2 (Dual Long+Short - 7x):   Final=${res_dual_7x['Capital']:5.2f} | Lãi: {res_dual_7x['Return (%)']:+6.2f}% | Sharpe: {res_dual_7x['Sharpe']:4.2f} | MaxDD: {res_dual_7x['Max DD (%)']:4.1f}% | Lệnh: {res_dual_7x['Trades']}")

res_atr_5x = simulate_advanced(mode="dual", leverage=5.0, top_pct=88, use_atr_tp=True)
print(f"Chiến thuật 3 (Adaptive ATR TP/SL - 5x): Final=${res_atr_5x['Capital']:5.2f} | Lãi: {res_atr_5x['Return (%)']:+6.2f}% | Sharpe: {res_atr_5x['Sharpe']:4.2f} | MaxDD: {res_atr_5x['Max DD (%)']:4.1f}% | Lệnh: {res_atr_5x['Trades']}")

res_atr_7x = simulate_advanced(mode="dual", leverage=7.0, top_pct=88, use_atr_tp=True)
print(f"Chiến thuật 3 (Adaptive ATR TP/SL - 7x): Final=${res_atr_7x['Capital']:5.2f} | Lãi: {res_atr_7x['Return (%)']:+6.2f}% | Sharpe: {res_atr_7x['Sharpe']:4.2f} | MaxDD: {res_atr_7x['Max DD (%)']:4.1f}% | Lệnh: {res_atr_7x['Trades']}")
print("=" * 80)
