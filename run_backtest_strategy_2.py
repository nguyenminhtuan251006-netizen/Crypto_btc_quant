"""
Institutional Research & Backtest Runner for Strategy 2:
BTC 15M Regime-Pullback + AI Meta Filter
"""
import os
import sys
import pandas as pd
import numpy as np

# Ensure local imports
scratch_dir = "/home/tuan/.gemini/antigravity-ide/scratch"
sys.path.insert(0, scratch_dir)

from config import Strategy2Config
from regime import compute_1h_regime
from setup_detector import detect_pullback_setups
from features import build_strategy2_features, label_setup_outcomes
from model import Strategy2AIFilter
from ev_filter import evaluate_setup_ev
from backtest_engine import Strategy2Backtester, compute_strategy2_metrics

def main():
    print("=" * 90)
    print("      RESEARCH LAB: CHIẾN THUẬT 2 - BTC 15M REGIME-PULLBACK + AI META FILTER")
    print("=" * 90)
    
    config = Strategy2Config()
    
    # 1. Load 5m raw data and resample cleanly to 15m and 1h
    data_path = "/run/media/tuan/449AA0129A9FFE94/vn30_quant_lab/crypto_btc_quant_lab/data/BTCUSDT_5m_50k.csv"
    print(f"[1/6] Nạp 50,000 nến 5m từ {os.path.basename(data_path)} và resample sang 15M & 1H...")
    
    df_raw = pd.read_csv(data_path)
    df_raw["datetime"] = pd.to_datetime(df_raw["datetime"])
    df_raw = df_raw.sort_values("datetime").drop_duplicates("datetime").set_index("datetime")
    
    df_15m = df_raw.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    
    df_1h = df_raw.resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    
    print(f" -> Dữ liệu 15M: {len(df_15m):,} nến ({df_15m['datetime'].iloc[0]} đến {df_15m['datetime'].iloc[-1]})")
    print(f" -> Dữ liệu 1H:  {len(df_1h):,} nến (Dùng cho Macro Regime Filter)")
    
    # 2. Compute 1H Regime
    print("\n[2/6] Tính toán Macro Regime Filter trên khung 1H (EMA200, EMA50 Slope, ADX14)...")
    df_1h_regime = compute_1h_regime(df_1h, config)
    long_regimes = (df_1h_regime["regime_1h"] == 1).sum()
    short_regimes = (df_1h_regime["regime_1h"] == -1).sum()
    sideway_regimes = (df_1h_regime["regime_1h"] == 0).sum()
    print(f" -> Regime 1H: LONG {long_regimes} giờ ({long_regimes/len(df_1h_regime)*100:.1f}%) | "
          f"SHORT {short_regimes} giờ ({short_regimes/len(df_1h_regime)*100:.1f}%) | "
          f"SIDEWAY/NO-TRADE {sideway_regimes} giờ ({sideway_regimes/len(df_1h_regime)*100:.1f}%)")
          
    # 3. Detect 15M Pullback Candidate Setups
    print("\n[3/6] Quét các setup Pullback (EMA20/50, RSI 40-65, Volume Check, Nến đóng)...")
    df_setups = detect_pullback_setups(df_15m, df_1h_regime, config)
    candidate_count = (df_setups["candidate_setup"] != 0).sum()
    print(f" -> Tổng số candidate setups phát hiện trên 15M: {candidate_count} setups")
    
    # 4. Feature Engineering & Target Labeling
    print("\n[4/6] Trích xuất 17 đặc trưng kỹ thuật & gắn nhãn mục tiêu thích nghi theo ATR (+1.8 ATR vs -1.0 ATR)...")
    df_feat, feature_cols = build_strategy2_features(df_setups)
    df_labeled = label_setup_outcomes(df_feat, config)
    
    # 5. Split Train (70%) / Test Out-of-Sample (30%)
    split_idx = int(len(df_labeled) * 0.70)
    train_df = df_labeled.iloc[:split_idx].copy()
    test_df = df_labeled.iloc[split_idx:].copy().reset_index(drop=True)
    
    print(f" -> Train set: {len(train_df):,} nến 15M ({train_df['datetime'].iloc[0]} đến {train_df['datetime'].iloc[-1]})")
    print(f" -> Test set (Out-Of-Sample): {len(test_df):,} nến 15M ({test_df['datetime'].iloc[0]} đến {test_df['datetime'].iloc[-1]})")
    
    # Filter only candidates for model training
    train_candidates = train_df[train_df["candidate_setup"] != 0].copy()
    X_train = train_candidates[feature_cols].to_numpy()
    y_train = train_candidates["target_win"].to_numpy()
    
    print(f"\n[5/6] Huấn luyện AI Meta Filter (XGBoost) trên {len(train_candidates)} candidate setups trong tập Train...")
    ai_filter = Strategy2AIFilter(max_iter=150, learning_rate=0.03, max_depth=4)
    ai_filter.train(X_train, y_train, feature_cols)
    print(" -> AI Meta Filter đã huấn luyện xong!")
    
    # Evaluate Out-Of-Sample Setups
    test_setups = test_df["candidate_setup"].to_numpy()
    test_atr = test_df["atr_14"].to_numpy()
    test_atr_pct = test_df["atr_pct"].to_numpy()
    atr_ranks = pd.Series(test_atr_pct).rank(pct=True).to_numpy() * 100.0
    
    signals = np.zeros(len(test_df), dtype=int)
    approved_count = 0
    skipped_count = 0
    
    # Only run AI when setup != 0
    for i in range(len(test_df)):
        if test_setups[i] != 0:
            feat_vec = test_df[feature_cols].iloc[i].to_numpy().reshape(1, -1)
            prob_win = ai_filter.predict_probability(feat_vec)[0]
            
            is_take, ev_val, reason = evaluate_setup_ev(
                prob_win=prob_win,
                atr_val=test_atr[i],
                atr_pct_rank=atr_ranks[i],
                config=config
            )
            
            if is_take:
                signals[i] = test_setups[i]
                approved_count += 1
            else:
                skipped_count += 1
                
    print(f"\n[6/6] Đánh giá Out-Of-Sample với Expected Value (EV >= {config.ev_minimum}R):")
    print(f" -> Tổng số candidate setups trên tập Test: {approved_count + skipped_count}")
    print(f" -> AI Meta Filter duyệt lệnh (TAKE):       {approved_count} lệnh")
    print(f" -> AI Meta Filter từ chối (SKIP):         {skipped_count} lệnh (loại bỏ bẫy rủi ro)")
    
    # Run Backtest on Out-of-Sample
    sl_prices = test_df["setup_sl"].to_numpy()
    tp_prices = test_df["setup_tp"].to_numpy()
    
    backtester = Strategy2Backtester(
        initial_capital=config.initial_capital,
        leverage=config.leverage,
        fee_rate=config.maker_fee_rate,
        slippage_bps=config.default_slippage_bps
    )
    
    df_res, trades_df = backtester.run(test_df, signals, sl_prices, tp_prices, timeout_bars=config.timeout_bars)
    m = compute_strategy2_metrics(df_res, trades_df, config.initial_capital)
    
    print("\n" + "=" * 90)
    print("          KẾT QUẢ KIỂM THỬ OUT-OF-SAMPLE CHIẾN THUẬT 2 (15M REGIME-PULLBACK)")
    print("=" * 90)
    print(f"💰 Vốn ban đầu (Initial Capital):       ${m['Initial Capital']:.2f} USDT")
    print(f"🚀 Vốn kết thúc (Final Capital):        ${m['Final Capital']:.2f} USDT")
    print(f"📈 Lợi nhuận ròng (Total Return):       {m['Total Return (%)']:+.2f}%")
    print(f"⚖️ Profit Factor sau thuế phí:          {m['Profit Factor']:.2f}")
    print(f"🎯 Hệ số an toàn Sharpe (OOS):          {m['Sharpe Ratio']:.2f}")
    print(f"🛡️ Drawdown tối đa (Max Drawdown):      {m['Max Drawdown (%)']:.2f}%")
    print(f"⚡ Tỷ lệ lệnh Thắng (Win Rate):         {m['Win Rate (%)']:.2f}%")
    print(f"📊 Tổng số lệnh thực hiện:              {m['Total Trades']} lệnh / ~52 ngày")
    print(f"💵 Lãi trung bình mỗi lệnh thắng:       +${m['Avg Win ($)']:.2f} USDT")
    print(f"🛡️ Lỗ trung bình mỗi lệnh thua:         -${m['Avg Loss ($)']:.2f} USDT")
    print("=" * 90)
    
    # STRESS TEST SLIPPAGE (Section 10)
    print("\n" + "=" * 90)
    print("          STRESS TEST TRƯỢT GIÁ (SLIPPAGE STRESS TEST - SECTION 10)")
    print("=" * 90)
    print(f"{'Kịch bản Slippage':<25} | {'Trượt giá':<12} | {'Vốn cuối':<12} | {'Lợi nhuận (%)':<15} | {'Profit Factor':<15} | {'Sharpe'}")
    print("-" * 90)
    
    scenarios = [
        ("Lý tưởng (Ideal)", 0.0),
        ("Bình thường (Normal)", 2.0),
        ("Khá xấu (Moderate)", 5.0),
        ("Xấu (Severe)", 10.0),
        ("Rất xấu (Extreme)", 20.0)
    ]
    
    for sc_name, slip_bps in scenarios:
        bt = Strategy2Backtester(
            initial_capital=config.initial_capital,
            leverage=config.leverage,
            fee_rate=config.maker_fee_rate,
            slippage_bps=slip_bps
        )
        d_res, t_df = bt.run(test_df, signals, sl_prices, tp_prices, timeout_bars=config.timeout_bars)
        sm = compute_strategy2_metrics(d_res, t_df, config.initial_capital)
        print(f"{sc_name:<25} | {slip_bps:4.1f} bps    | ${sm['Final Capital']:<10.2f} | {sm['Total Return (%)']:+12.2f}% | {sm['Profit Factor']:<15.2f} | {sm['Sharpe Ratio']:.2f}")
    print("=" * 90)

if __name__ == "__main__":
    main()
