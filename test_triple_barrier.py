import os
import sys
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

data_path = "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m.csv"
df = pd.read_csv(data_path)

c = df["close"].to_numpy()
h = df["high"].to_numpy()
l = df["low"].to_numpy()
n = len(df)

# Triple barrier labeling: 1.0% TP vs 0.5% SL within 12 bars (60m)
tp = 0.010
sl = 0.005
max_bars = 12

labels = np.zeros(n)
for i in range(n - max_bars):
    entry = c[i]
    for j in range(1, max_bars + 1):
        idx = i + j
        # check TP
        if h[idx] >= entry * (1.0 + tp):
            labels[i] = 1 # Won
            break
        # check SL
        if l[idx] <= entry * (1.0 - sl):
            labels[i] = -1 # Lost
            break

df["tb_label"] = labels

# Features
ret_1 = pd.Series(c).pct_change(1).to_numpy()
ret_3 = pd.Series(c).pct_change(3).to_numpy()
ret_6 = pd.Series(c).pct_change(6).to_numpy()
ret_12 = pd.Series(c).pct_change(12).to_numpy()
vol_ratio = df["volume"] / df["volume"].rolling(12).mean()

features_df = pd.DataFrame({
    "ret_1": ret_1,
    "ret_3": ret_3,
    "ret_6": ret_6,
    "ret_12": ret_12,
    "vol_ratio": vol_ratio,
    "body": (df["close"] - df["open"]) / df["open"],
    "tb_label": labels
}).dropna().reset_index(drop=True)

# Train only on events where label != 0
events = features_df[features_df["tb_label"] != 0].copy().reset_index(drop=True)
split = int(len(events) * 0.7)
train_ev = events.iloc[:split]
test_ev = events.iloc[split:].copy().reset_index(drop=True)

X_cols = ["ret_1", "ret_3", "ret_6", "ret_12", "vol_ratio", "body"]
X_tr = train_ev[X_cols]
y_tr = (train_ev["tb_label"] == 1).astype(int)

X_te = test_ev[X_cols]
y_te = (test_ev["tb_label"] == 1).astype(int)

clf = HistGradientBoostingClassifier(max_iter=100, learning_rate=0.03, max_depth=4, random_state=42)
clf.fit(X_tr, y_tr)

probs = clf.predict_proba(X_te)[:, 1]

print("--- Triple Barrier Model Accuracy ---")
for conf in [0.50, 0.55, 0.60, 0.65]:
    selected = probs >= conf
    if np.sum(selected) > 0:
        win_rate = np.mean(y_te[selected]) * 100
        print(f"Conf >= {conf*100:.0f}%: Trades={np.sum(selected)} | Win Rate (TP 1.0% vs SL 0.5%) = {win_rate:.2f}%")
