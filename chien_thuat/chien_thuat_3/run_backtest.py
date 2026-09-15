"""
Backtest Runner: V1 (Original 14 Features) vs V2 (14 + 11 HFT Microstructure)
===============================================================================
Compares the original XGBoost model using only 5m candle features against
the upgraded model enriched with HFT orderbook and trade microstructure data.

Both models use identical:
  - Train/Test split (70/30)
  - Session filter (London + NY: 15:00-02:00 VN time)
  - Trend filter (EMA50)
  - Backtest engine (6 USDT, 5x leverage, 0.015% maker fee)
  - High-conviction threshold (top 10% probability)

Usage:
    python run_backtest_hft.py
"""
import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.features import build_features
from src.features_v2 import build_features_v2, load_hft_features
from src.model import BTC5mPredictor
from src.engine import BinanceFuturesEngine, compute_crypto_metrics


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.dirname(os.path.dirname(base_dir))
    data_dir = os.path.join(workspace_dir, "data") if os.path.exists(os.path.join(workspace_dir, "data")) else os.path.join(base_dir, "data")

    # =========================================================================
    # 1. Load Data
    # =========================================================================
    data_50k = os.path.join(data_dir, "BTCUSDT_5m_50k.csv")
    data_10k = os.path.join(data_dir, "BTCUSDT_5m.csv")
    data_path = data_50k if os.path.exists(data_50k) else data_10k

    hft_path = os.path.join(data_dir, "hft_features_5m.parquet")

    if not os.path.exists(data_path):
        print(f"[Error] Candle data not found: {data_path}")
        return

    if not os.path.exists(hft_path):
        print(f"[Error] HFT features not found: {hft_path}")
        print(f"        Run 'python src/preprocess_hft.py' first.")
        return

    print("=" * 95)
    print("   ⚡ HFT MICROSTRUCTURE UPGRADE: BACKTEST COMPARISON V1 vs V2")
    print("   V1: 14 Original Features (5m Candles Only)")
    print("   V2: 25 Features (14 Original + 11 HFT Orderbook/Trades Microstructure)")
    print("=" * 95)

    df_raw = pd.read_csv(data_path)
    hft_df = load_hft_features(hft_path)

    # Find overlapping date range between candle data and HFT features
    df_raw["datetime"] = pd.to_datetime(df_raw["datetime"])
    hft_min_dt = hft_df["datetime"].min()
    hft_max_dt = hft_df["datetime"].max()

    # Filter candle data to only the period covered by HFT data
    mask = (df_raw["datetime"] >= hft_min_dt) & (df_raw["datetime"] <= hft_max_dt)
    df_hft_period = df_raw[mask].copy().reset_index(drop=True)

    print(f"\n[Data] Full candle dataset:   {len(df_raw):,} bars ({df_raw['datetime'].iloc[0]} → {df_raw['datetime'].iloc[-1]})")
    print(f"[Data] HFT features range:   {hft_min_dt} → {hft_max_dt}")
    print(f"[Data] Overlapping period:   {len(df_hft_period):,} bars")
    print(f"[Data] HFT features loaded:  {len(hft_df):,} 5m intervals, 11 microstructure features")

    if len(df_hft_period) < 1000:
        print(f"\n[Warning] Only {len(df_hft_period)} bars in overlapping period. Using full dataset for V1 comparison.")
        df_hft_period = df_raw.copy()

    # =========================================================================
    # 2. Build Features: V1 (original) and V2 (with HFT)
    # =========================================================================
    print(f"\n[Features V1] Building 14 original features...")
    df_v1, v1_cols = build_features(df_hft_period, is_train=True)
    print(f"  → {len(v1_cols)} features, {len(df_v1):,} bars")

    print(f"[Features V2] Building 25 features (14 original + 11 HFT microstructure)...")
    df_v2, v2_cols = build_features_v2(df_hft_period, hft_df=hft_df, is_train=True)
    print(f"  → {len(v2_cols)} features, {len(df_v2):,} bars")

    # Show which new features were added
    new_cols = [c for c in v2_cols if c not in v1_cols]
    print(f"  → New HFT features: {', '.join(new_cols)}")

    # Check HFT feature coverage (how many rows have non-zero HFT data)
    hft_coverage = (df_v2[new_cols].abs().sum(axis=1) > 0).mean() * 100
    print(f"  → HFT feature coverage: {hft_coverage:.1f}% of bars have non-zero HFT data")

    # =========================================================================
    # 3. Train/Test Split (70% Train / 30% Test)
    # =========================================================================
    split_v1 = int(len(df_v1) * 0.70)
    train_v1 = df_v1.iloc[:split_v1].copy()
    test_v1 = df_v1.iloc[split_v1:].copy().reset_index(drop=True)

    split_v2 = int(len(df_v2) * 0.70)
    train_v2 = df_v2.iloc[:split_v2].copy()
    test_v2 = df_v2.iloc[split_v2:].copy().reset_index(drop=True)

    print(f"\n[Split] V1 Train: {len(train_v1):,} bars | Test: {len(test_v1):,} bars")
    print(f"[Split] V2 Train: {len(train_v2):,} bars | Test: {len(test_v2):,} bars")
    print(f"[Split] Test period: {test_v2['datetime'].iloc[0]} → {test_v2['datetime'].iloc[-1]}")

    # =========================================================================
    # 4. Train Models
    # =========================================================================
    print(f"\n[Training] V1 XGBoost (14 features)...")
    model_v1 = BTC5mPredictor(model_type="gradient_boosting")
    model_v1.train(train_v1[v1_cols].to_numpy(), train_v1["target_direction"].to_numpy())

    print(f"[Training] V2 XGBoost (25 features)...")
    model_v2 = BTC5mPredictor(model_type="gradient_boosting")
    model_v2.train(train_v2[v2_cols].to_numpy(), train_v2["target_direction"].to_numpy())

    # =========================================================================
    # 5. Generate Signals with Session + Trend Filter
    # =========================================================================
    # =========================================================================
    # 5. Generate Signals with Session + Trend Filter
    # =========================================================================
    # V1 signals: baseline with 90th percentile
    signals_v1_raw = model_v1.predict_signals(test_v1[v1_cols].to_numpy(), top_percentile=90.0)
    test_hours_v1 = pd.to_datetime(test_v1["datetime"]).dt.hour.to_numpy()
    is_active_v1 = (test_hours_v1 >= 15) | (test_hours_v1 <= 2)
    trend_v1 = test_v1["trend_dist"].to_numpy()
    signals_v1 = np.zeros_like(signals_v1_raw)
    signals_v1[(is_active_v1) & (signals_v1_raw == 1) & (trend_v1 > 0)] = 1
    signals_v1[(is_active_v1) & (signals_v1_raw == -1) & (trend_v1 < 0)] = -1

    # V2 Taker signals: same 90th percentile both directions
    signals_v2_raw = model_v2.predict_signals(test_v2[v2_cols].to_numpy(), top_percentile=90.0)
    test_hours_v2 = pd.to_datetime(test_v2["datetime"]).dt.hour.to_numpy()
    is_active_v2 = (test_hours_v2 >= 15) | (test_hours_v2 <= 2)
    trend_v2 = test_v2["trend_dist"].to_numpy()
    signals_v2_taker = np.zeros_like(signals_v2_raw)
    signals_v2_taker[(is_active_v2) & (signals_v2_raw == 1) & (trend_v2 > 0)] = 1
    signals_v2_taker[(is_active_v2) & (signals_v2_raw == -1) & (trend_v2 < 0)] = -1

    # V2 Maker signals (Oxford Paper: Top 5% selective conviction, Long + Trend filter)
    probs_v2_train = model_v2.model.predict_proba(train_v2[v2_cols].to_numpy())[:, 1]
    th_long_v2 = np.percentile(probs_v2_train, 95.0)
    probs_v2_test = model_v2.model.predict_proba(test_v2[v2_cols].to_numpy())[:, 1]
    signals_v2_maker = np.zeros_like(signals_v2_raw)
    signals_v2_maker[(is_active_v2) & (probs_v2_test >= th_long_v2) & (trend_v2 > 0)] = 1

    # Accuracy comparison
    acc_v1 = np.mean(model_v1.model.predict(test_v1[v1_cols].to_numpy()) == test_v1["target_direction"].to_numpy()) * 100
    acc_v2 = np.mean(model_v2.model.predict(test_v2[v2_cols].to_numpy()) == test_v2["target_direction"].to_numpy()) * 100
    print(f"\n[Accuracy] V1 Directional Accuracy: {acc_v1:.2f}%")
    print(f"[Accuracy] V2 Directional Accuracy: {acc_v2:.2f}% ({acc_v2 - acc_v1:+.2f}%)")

    # =========================================================================
    # 6. Backtest Comparison
    # =========================================================================
    engine_taker = BinanceFuturesEngine(
        initial_capital_usdt=6.0,
        leverage=5.0,
        fee_rate=0.0004,      # 0.04% Taker fee
        stop_loss_pct=0.004,  # 0.4% SL
        take_profit_pct=0.004 # 0.4% TP
    )

    engine_maker = BinanceFuturesEngine(
        initial_capital_usdt=6.0,
        leverage=5.0,
        fee_rate=0.0002,      # 0.02% Maker fee
        stop_loss_pct=0.004,  # 0.4% SL
        take_profit_pct=0.004, # 0.4% TP
        execution_mode="maker"
    )

    results = []

    # Buy & Hold baseline
    bh_ret = (test_v1["close"].iloc[-1] / test_v1["close"].iloc[0] - 1.0) * 100
    results.append({
        "Model": "Buy & Hold (BTC)",
        "Features": "-",
        "Accuracy (%)": "-",
        "Initial Capital (USDT)": 6.0,
        "Final Capital (USDT)": round(6.0 * (1 + bh_ret / 100), 2),
        "Total Return (%)": round(bh_ret, 2),
        "Max Drawdown (%)": "-",
        "Sharpe Ratio": "-",
        "Win Rate (%)": "-",
        "Profit Factor": "-",
        "Total Trades": 1,
    })

    # V1 Backtest
    df_res_v1, trades_v1 = engine_taker.run(test_v1, signals_v1)
    m_v1 = compute_crypto_metrics(df_res_v1, trades_v1, engine_taker.initial_capital)
    m_v1["Model"] = "V1: Original XGBoost"
    m_v1["Features"] = f"{len(v1_cols)} (candles only)"
    m_v1["Accuracy (%)"] = round(acc_v1, 2)
    results.append(m_v1)

    # V2 Taker Backtest
    df_res_v2_t, trades_v2_t = engine_taker.run(test_v2, signals_v2_taker)
    m_v2_t = compute_crypto_metrics(df_res_v2_t, trades_v2_t, engine_taker.initial_capital)
    m_v2_t["Model"] = "V2: HFT Taker (0.04% fee)"
    m_v2_t["Features"] = f"{len(v2_cols)} (candles + HFT)"
    m_v2_t["Accuracy (%)"] = round(acc_v2, 2)
    results.append(m_v2_t)

    # V2 Maker Backtest (Oxford Paper Optimized)
    df_res_v2_m, trades_v2_m = engine_maker.run(test_v2, signals_v2_maker)
    m_v2_m = compute_crypto_metrics(df_res_v2_m, trades_v2_m, engine_maker.initial_capital)
    m_v2_m["Model"] = "V2: HFT Maker (Oxford Paper)"
    m_v2_m["Features"] = f"{len(v2_cols)} (candles + HFT)"
    m_v2_m["Accuracy (%)"] = round(acc_v2, 2)
    results.append(m_v2_m)

    # =========================================================================
    # 7. Print Comparison Results
    # =========================================================================
    summary_df = pd.DataFrame(results)
    cols_order = [
        "Model", "Features", "Accuracy (%)",
        "Initial Capital (USDT)", "Final Capital (USDT)", "Total Return (%)",
        "Max Drawdown (%)", "Sharpe Ratio", "Win Rate (%)",
        "Profit Factor", "Total Trades",
    ]
    summary_df = summary_df[[c for c in cols_order if c in summary_df.columns]]

    print("\n" + "=" * 120)
    print("         KẾT QUẢ SO SÁNH: V1 (ORIGINAL) vs V2 (HFT MICROSTRUCTURE UPGRADE)")
    print("=" * 120)
    print(summary_df.to_string(index=False))
    print("=" * 120)

    # =========================================================================
    # 8. Feature Importance Analysis (V2 model)
    # =========================================================================
    if hasattr(model_v2.model, "feature_importances_"):
        importances = model_v2.model.feature_importances_
        if len(importances) == len(v2_cols):
            fi_df = pd.DataFrame({
                "Feature": v2_cols,
                "Importance": importances,
                "Source": ["📊 Original" if c not in new_cols else "⚡ HFT" for c in v2_cols],
            }).sort_values("Importance", ascending=False)

            print("\n" + "=" * 80)
            print("   TOP 15 FEATURE IMPORTANCE (V2 MODEL — XGBoost)")
            print("=" * 80)
            for _, row in fi_df.head(15).iterrows():
                bar_len = int(row["Importance"] * 200)
                bar = "█" * bar_len
                print(f"  {row['Source']} {row['Feature']:22s}  {row['Importance']:.4f}  {bar}")

            # How many HFT features in top 10?
            top10_hft = fi_df.head(10)["Source"].str.contains("HFT").sum()
            print(f"\n  → HFT features in Top 10: {top10_hft}/10")
            print(f"  → Total HFT importance share: {fi_df[fi_df['Source'].str.contains('HFT')]['Importance'].sum():.1%}")
            print("=" * 80)

    # =========================================================================
    # 9. Save Results
    # =========================================================================
    reports_dir = os.path.join(workspace_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    summary_df.to_csv(os.path.join(reports_dir, "hft_upgrade_comparison.csv"), index=False)

    if len(trades_v2_m) > 0:
        trades_v2_m.to_csv(os.path.join(reports_dir, "v2_hft_trades_log.csv"), index=False)

    print(f"\n[Saved] Reports → {reports_dir}/")
    print(f"  - hft_upgrade_comparison.csv")
    if len(trades_v2_m) > 0:
        print(f"  - v2_hft_trades_log.csv ({len(trades_v2_m)} trades)")


if __name__ == "__main__":
    main()
