import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab")
from src.features import build_features
from src.model import BTC5mPredictor
from src.engine import BinanceFuturesEngine, compute_crypto_metrics

data_path = "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m.csv"
df_raw = pd.read_csv(data_path)
df_features, feature_cols = build_features(df_raw)

split_idx = int(len(df_features) * 0.70)
train_df = df_features.iloc[:split_idx].copy()
test_df = df_features.iloc[split_idx:].copy().reset_index(drop=True)

X_train = train_df[feature_cols].to_numpy()
y_train_cls = train_df["target_direction"].to_numpy()
X_test = test_df[feature_cols].to_numpy()

model_gb = BTC5mPredictor(model_type="gradient_boosting")
model_gb.train(X_train, y_train_cls)

print("--- Testing Confidence Thresholds ---")
for th in [0.52, 0.55, 0.58, 0.60, 0.62, 0.65]:
    for sl, tp in [(0.005, 0.012), (0.008, 0.016), (0.01, 0.02)]:
        sig = model_gb.predict_signals(X_test, threshold=th)
        engine = BinanceFuturesEngine(initial_capital_usdt=6.0, leverage=5.0, stop_loss_pct=sl, take_profit_pct=tp)
        df_res, trades = engine.run(test_df, sig)
        m = compute_crypto_metrics(df_res, trades, 6.0)
        if m["Total Trades"] > 5:
            print(f"Th={th:.2f} | SL={sl*100:.1f}% TP={tp*100:.1f}% => Return={m['Total Return (%)']}% | Final=${m['Final Capital (USDT)']} | Trades={m['Total Trades']} | WinRate={m['Win Rate (%)']}% | PF={m['Profit Factor']}")
