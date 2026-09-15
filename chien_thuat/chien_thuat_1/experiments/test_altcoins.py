import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, "/home/tuan/vn30_quant_lab/crypto_btc_quant_lab")
from src.features import build_features
from src.model import BTC5mPredictor
from src.engine import BinanceFuturesEngine, compute_crypto_metrics

def evaluate_symbol(csv_path, symbol_name):
    df_raw = pd.read_csv(csv_path)
    df_features, feature_cols = build_features(df_raw)
    
    split_idx = int(len(df_features) * 0.70)
    train_df = df_features.iloc[:split_idx].copy()
    test_df = df_features.iloc[split_idx:].copy().reset_index(drop=True)
    
    X_train = train_df[feature_cols].to_numpy()
    y_train_cls = train_df["target_direction"].to_numpy()
    X_test = test_df[feature_cols].to_numpy()
    
    model_gb = BTC5mPredictor(model_type="gradient_boosting")
    model_gb.train(X_train, y_train_cls)
    signals_raw = model_gb.predict_signals(X_test, top_percentile=90.0)
    
    # Session filter (London + US) + Trend filter
    test_hours = pd.to_datetime(test_df["datetime"]).dt.hour.to_numpy()
    is_active_session = (test_hours >= 15) | (test_hours <= 2)
    signals = np.where(is_active_session & (test_df["trend_dist"].to_numpy() > 0), signals_raw, 0)
    
    engine = BinanceFuturesEngine(
        initial_capital_usdt=6.0,
        leverage=5.0,
        fee_rate=0.00015,
        stop_loss_pct=0.005,
        take_profit_pct=0.010
    )
    
    df_res, trades = engine.run(test_df, signals)
    m = compute_crypto_metrics(df_res, trades, 6.0)
    m["Symbol"] = symbol_name
    return m

print("=" * 80)
print("     ĐÁNH GIÁ ĐA TÀI SẢN (CROSS-ASSET EVALUATION ON BINANCE FUTURES)")
print("=" * 80)

m_btc = evaluate_symbol("/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m.csv", "BTCUSDT")
m_eth = evaluate_symbol("/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/ETHUSDT_5m.csv", "ETHUSDT")
m_sol = evaluate_symbol("/home/tuan/vn30_quant_lab/crypto_btc_quant_lab/data/SOLUSDT_5m.csv", "SOLUSDT")

summary_df = pd.DataFrame([m_btc, m_eth, m_sol])
cols = ["Symbol", "Initial Capital (USDT)", "Final Capital (USDT)", "Total Return (%)", "Sharpe Ratio", "Win Rate (%)", "Profit Factor", "Total Trades"]
print(summary_df[[c for c in cols if c in summary_df.columns]].to_string(index=False))
print("=" * 80)
