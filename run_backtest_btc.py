"""
Main Runner for BTC 5m Machine Learning Strategy (Binance Futures)
Addresses directive from anh Vũ Xuân Tùng:
- Target: x2 tài khoản trong 1 tháng
- Models: Linear Regression & Gradient Boosting (XGBoost style)
- Prediction horizon: 5-minute bars (Polymarket style)
- Capital: 6 USDT (150k VNĐ)
"""
import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.features import build_features
from src.model import BTC5mPredictor
from src.engine import BinanceFuturesEngine, compute_crypto_metrics

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_50k = os.path.join(base_dir, "data", "BTCUSDT_5m_50k.csv")
    data_10k = os.path.join(base_dir, "data", "BTCUSDT_5m.csv")
    data_path = data_50k if os.path.exists(data_50k) else data_10k
    
    if not os.path.exists(data_path):
        print(f"[Error] Data file not found at {data_path}. Please run download_btc_5m.py first.")
        return
        
    print("=" * 80)
    print(f"      BTC 5-MINUTE MACHINE LEARNING QUANT LAB (BINANCE FUTURES)")
    print(f"      Dữ liệu: {os.path.basename(data_path)} | Vốn: 6.0 USDT (~150k VNĐ) | Đòn bẩy: 5x")
    print("=" * 80)
    
    # 1. Load & Feature Engineering
    df_raw = pd.read_csv(data_path)
    df_features, feature_cols = build_features(df_raw)
    print(f"[Features] Successfully built {len(feature_cols)} features across {len(df_features)} 5m bars.")
    print(f"Features list: {', '.join(feature_cols[:8])}...")
    
    # 2. Train / Test Split (70% Train - 30% Test Out-Of-Sample)
    split_idx = int(len(df_features) * 0.70)
    train_df = df_features.iloc[:split_idx].copy()
    test_df = df_features.iloc[split_idx:].copy().reset_index(drop=True)
    
    X_train = train_df[feature_cols].to_numpy()
    y_train_reg = train_df["target_return"].to_numpy()
    y_train_cls = train_df["target_direction"].to_numpy()
    
    X_test = test_df[feature_cols].to_numpy()
    y_test_cls = test_df["target_direction"].to_numpy()
    
    print(f"\n[Dataset Split]")
    print(f"-> Train Set: {len(train_df)} bars ({train_df['datetime'].iloc[0]} to {train_df['datetime'].iloc[-1]})")
    print(f"-> Test Set (Out-Of-Sample): {len(test_df)} bars ({test_df['datetime'].iloc[0]} to {test_df['datetime'].iloc[-1]})")
    
    # 3. Model 1: Linear / Ridge Regression
    print("\n[Model 1] Training Linear Regression Predictor...")
    model_linear = BTC5mPredictor(model_type="linear")
    model_linear.train(X_train, y_train_reg)
    signals_linear = model_linear.predict_signals(X_test, top_percentile=90.0)
    
    # 4. Model 2: Gradient Boosting (XGB / Polymarket style)
    print("[Model 2] Training Gradient Boosting (XGBoost Style) Predictor...")
    model_gb = BTC5mPredictor(model_type="gradient_boosting")
    model_gb.train(X_train, y_train_cls)
    signals_gb_raw = model_gb.predict_signals(X_test, top_percentile=90.0)
    
    # Filter by London & US Golden Hours (15:00 - 02:00) + Trend Filter
    test_hours = pd.to_datetime(test_df["datetime"]).dt.hour.to_numpy()
    is_active_session = (test_hours >= 15) | (test_hours <= 2)
    signals_gb = np.where(is_active_session & (test_df["trend_dist"].to_numpy() > 0), signals_gb_raw, 0)
    
    # Accuracy on Test
    test_preds = model_gb.model.predict(X_test)
    acc = np.mean(test_preds == y_test_cls) * 100
    print(f"-> XGB Directional Accuracy on Test Set: {acc:.2f}% (Polymarket Up/Down edge)")
    
    # 5. Backtest Simulation with Binance Futures Engine (Quarterly Maker Fee Model)
    engine = BinanceFuturesEngine(
        initial_capital_usdt=6.0,  # 150k VNĐ
        leverage=5.0,              # 5x leverage
        fee_rate=0.00015,          # 0.015% Maker fee on Binance Quarterly Futures
        stop_loss_pct=0.005,       # 0.5% stop loss
        take_profit_pct=0.010      # 1.0% take profit (2:1 Risk/Reward)
    )
    
    results = []
    
    # Benchmark Baseline: Buy & Hold
    bh_ret = (test_df["close"].iloc[-1] / test_df["close"].iloc[0] - 1.0) * 100
    results.append({
        "Model": "Buy & Hold (Bitcoin)",
        "Initial Capital (USDT)": 6.0,
        "Final Capital (USDT)": round(6.0 * (1 + bh_ret / 100), 2),
        "Total Return (%)": round(bh_ret, 2),
        "Is Doubled (x2)?": "YES (Đã x2)" if bh_ret >= 100 else "Chưa",
        "Max Drawdown (%)": round((test_df["close"].cummax() - test_df["close"]).max() / test_df["close"].max() * 100, 2),
        "Sharpe Ratio": "-",
        "Win Rate (%)": "-",
        "Profit Factor": "-",
        "Total Trades": 1
    })
    
    # Model 1 Test
    df_res_lin, trades_lin = engine.run(test_df, signals_linear)
    m_lin = compute_crypto_metrics(df_res_lin, trades_lin, engine.initial_capital)
    m_lin["Model"] = "Linear Regression"
    results.append(m_lin)
    
    # Model 2 Test (XGBoost)
    df_res_gb, trades_gb = engine.run(test_df, signals_gb)
    m_gb = compute_crypto_metrics(df_res_gb, trades_gb, engine.initial_capital)
    m_gb["Model"] = "XGBoost (Polymarket 5m)"
    results.append(m_gb)
    
    summary_df = pd.DataFrame(results)
    cols_order = [
        "Model", "Initial Capital (USDT)", "Final Capital (USDT)", "Total Return (%)",
        "Is Doubled (x2)?", "Max Drawdown (%)", "Sharpe Ratio", "Win Rate (%)",
        "Profit Factor", "Total Trades"
    ]
    summary_df = summary_df[[c for c in cols_order if c in summary_df.columns]]
    
    print("\n" + "=" * 95)
    print("                 KẾT QUẢ KIỂM THỬ OUT-OF-SAMPLE (DỮ LIỆU THỰC TẾ BINANCE)")
    print("=" * 95)
    print(summary_df.to_string(index=False))
    print("=" * 95)
    
    # Save reports
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    summary_df.to_csv(os.path.join(reports_dir, "btc_5m_ml_results.csv"), index=False)
    if len(trades_gb) > 0:
        trades_gb.to_csv(os.path.join(reports_dir, "xgb_trades_log.csv"), index=False)
    print(f"\n[Saved] Reports saved to: {reports_dir}")

if __name__ == "__main__":
    main()
