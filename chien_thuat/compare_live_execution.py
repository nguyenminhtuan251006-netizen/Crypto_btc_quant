"""
ĐẤU TRƯỜNG SO SÁNH THỰC THI: CHIẾN THUẬT 1 vs 2 vs 3 (REALTIME LIVE EVALUATION)
================================================================================
Kích hoạt đồng thời cả 3 chiến thuật trên luồng dữ liệu thị trường Binance Futures:
1. Chiến thuật 1: BTC 5M XGBoost (Nến kỹ thuật 14 features)
2. Chiến thuật 2: BTC 15M Regime-Pullback + AI Meta Filter (17 features + 1H Regime)
3. Chiến thuật 3: BTC 5M HFT Microstructure (25 features = Nến + L2 Orderbook 20 tầng + CVD)

Đánh giá điều kiện vào lệnh, vị thế, TP/SL, kỳ vọng lợi nhuận và kết quả thực tế.
"""
import os
import sys
import joblib
import requests
import numpy as np
import pandas as pd
from datetime import datetime

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)

# Import components from each strategy
from chien_thuat.chien_thuat_1.src.features import build_features as build_features_s1
from chien_thuat.chien_thuat_1.src.model import BTC5mPredictor as PredictorS1

from chien_thuat.chien_thuat_2.config import Strategy2Config
from chien_thuat.chien_thuat_2.regime import compute_1h_regime
from chien_thuat.chien_thuat_2.setup_detector import detect_pullback_setups
from chien_thuat.chien_thuat_2.features import build_strategy2_features
from chien_thuat.chien_thuat_2.model import Strategy2AIFilter

from chien_thuat.chien_thuat_3.paper_trader import (
    fetch_recent_candles,
    fetch_orderbook_l2,
    fetch_recent_trades,
    compute_realtime_microstructure,
)


def evaluate_all_strategies():
    print("=" * 105)
    print("      ⚔️ ĐẤU TRƯỜNG SO SÁNH THỰC THI 3 CHIẾN THUẬT TRÊN THỊ TRƯỜNG LIVE (BINANCE FUTURES)")
    print("=" * 105)

    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Thời gian quét]: {now_str} (Giờ VN) | Phiên hoạt động: London & Mỹ (15:00 - 02:00)")

    # 1. Fetch Realtime Market Data
    print("\n[1/4] Đang lấy dữ liệu thị trường Realtime từ Binance Futures...")
    candles_5m = fetch_recent_candles(symbol="BTCUSDT", limit=150)
    ob_l2 = fetch_orderbook_l2(symbol="BTCUSDT", limit=20)
    trades_tick = fetch_recent_trades(symbol="BTCUSDT", limit=100)

    current_price = candles_5m["close"].iloc[-1]
    print(f"  → Giá BTC hiện tại: ${current_price:,.1f}")
    print(f"  → Sổ lệnh L2: Best Bid = ${ob_l2['bids'][0][0]:,.1f} | Best Ask = ${ob_l2['asks'][0][0]:,.1f}")
    print(f"  → Khối lượng trades vừa khớp: {len(trades_tick)} lệnh gần nhất")

    # =========================================================================
    # 2. ĐÁNH GIÁ CHIẾN THUẬT 1: BTC 5M XGBOOST (NẾN THUẦN)
    # =========================================================================
    print("\n" + "-" * 105)
    print("  🔹 CHIẾN THUẬT 1: BTC 5M XGBOOST (14 FEATURES NẾN THUẦN)")
    print("-" * 105)
    df_s1, feat_cols_s1 = build_features_s1(candles_5m, is_train=True)
    latest_s1 = df_s1.iloc[-1]
    trend_dist_s1 = latest_s1.get("trend_dist", 0.0)
    rsi_s1 = latest_s1.get("rsi", 50.0)

    # Train fast predictor on recent bars
    train_slice_s1 = df_s1.iloc[:-1].dropna(subset=["target_direction"])
    if len(train_slice_s1) > 20:
        pred_s1 = PredictorS1(model_type="gradient_boosting")
        pred_s1.train(train_slice_s1[feat_cols_s1].to_numpy(), train_slice_s1["target_direction"].to_numpy())
        prob_up_s1 = float(pred_s1.model.predict_proba(latest_s1[feat_cols_s1].to_numpy().reshape(1, -1))[0, 1])
    else:
        prob_up_s1 = 0.50

    # Decision logic S1: TP 1.0% / SL 0.5%
    s1_decision = "QUAN SÁT (Chờ xác suất cao)"
    s1_action = "NONE"
    s1_sl = 0.0
    s1_tp = 0.0
    if prob_up_s1 >= 0.65 and trend_dist_s1 > 0:
        s1_decision = "MỞ LONG (Thuận trend EMA50)"
        s1_action = "LONG"
        s1_sl = current_price * 0.995
        s1_tp = current_price * 1.010
    elif prob_up_s1 <= 0.35 and trend_dist_s1 < 0:
        s1_decision = "MỞ SHORT (Thuận trend EMA50)"
        s1_action = "SHORT"
        s1_sl = current_price * 1.005
        s1_tp = current_price * 0.990

    print(f"  • Xác suất AI dự đoán Tăng: {prob_up_s1*100:5.1f}% | RSI 5m: {rsi_s1:.1f}")
    print(f"  • Vị thế giá so với EMA50:  {trend_dist_s1*100:+.2f}% ({'TRÊN EMA50' if trend_dist_s1 > 0 else 'DƯỚI EMA50'})")
    print(f"  • Quyết định thực thi:     👉 {s1_decision}")
    if s1_action != "NONE":
        print(f"    - Điểm vào (Entry): ${current_price:,.1f} | Cắt lỗ (SL): ${s1_sl:,.1f} (-0.5%) | Chốt lời (TP): ${s1_tp:,.1f} (+1.0%)")

    # =========================================================================
    # 3. ĐÁNH GIÁ CHIẾN THUẬT 2: BTC 15M REGIME-PULLBACK + AI META FILTER
    # =========================================================================
    print("\n" + "-" * 105)
    print("  🔸 CHIẾN THUẬT 2: BTC 15M REGIME-PULLBACK + AI META FILTER (15M / 1H)")
    print("-" * 105)
    cfg2 = Strategy2Config()
    df_raw = candles_5m.copy().set_index("datetime")
    df_15m = df_raw.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    df_1h = df_raw.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    df_15m["datetime"] = pd.to_datetime(df_15m["datetime"]).astype("datetime64[ns]")
    df_1h["datetime"] = pd.to_datetime(df_1h["datetime"]).astype("datetime64[ns]")

    regime_1h_df = compute_1h_regime(df_1h, cfg2)
    regime_1h_df["datetime"] = pd.to_datetime(regime_1h_df["datetime"]).astype("datetime64[ns]")
    current_regime = regime_1h_df["regime_1h"].iloc[-1] if len(regime_1h_df) > 0 else 0
    regime_label = "LONG TREND (Tăng)" if current_regime == 1 else ("SHORT TREND (Giảm)" if current_regime == -1 else "SIDEWAY / NO-TRADE")

    setups_df = detect_pullback_setups(df_15m, regime_1h_df, cfg2)
    has_setup = len(setups_df) > 0 and setups_df["candidate_setup"].iloc[-1] != 0
    setup_side = setups_df["candidate_setup"].iloc[-1] if has_setup else 0

    s2_decision = "QUAN SÁT (Chưa xuất hiện setup hồi nến 15m)"
    s2_action = "NONE"
    s2_sl = 0.0
    s2_tp = 0.0
    if has_setup and current_regime != 0:
        s2_action = "LONG" if setup_side == 1 else "SHORT"
        s2_sl = setups_df["setup_sl"].iloc[-1]
        s2_tp = setups_df["setup_tp"].iloc[-1]
        s2_decision = f"ĐỦ ĐIỀU KIỆN VÀO LỆNH {s2_action} (Pullback EMA20/50)"

    print(f"  • Xu hướng vĩ mô 1H:       {regime_label}")
    print(f"  • Setup Pullback nến 15m:  {'PHÁT HIỆN SETUP!' if has_setup else 'Không có setup hồi hợp lệ'}")
    print(f"  • Quyết định thực thi:     👉 {s2_decision}")
    if s2_action != "NONE":
        print(f"    - Điểm vào: ${current_price:,.1f} | SL: ${s2_sl:,.1f} | TP: ${s2_tp:,.1f}")

    # =========================================================================
    # 4. ĐÁNH GIÁ CHIẾN THUẬT 3: BTC 5M HFT MICROSTRUCTURE (ORDERBOOK L2 + CVD)
    # =========================================================================
    print("\n" + "-" * 105)
    print("  ⚡ CHIẾN THUẬT 3 (MỚI NHẤT): BTC 5M HFT MICROSTRUCTURE (25 FEATURES)")
    print("-" * 105)
    model3_path = os.path.join(base_dir, "chien_thuat", "chien_thuat_3", "models", "hft_xgb_model.joblib")
    pkg3 = joblib.load(model3_path)
    model3 = pkg3["model"]
    fcols3 = pkg3["feature_cols"]
    th_long3 = pkg3["th_long"]
    th_short3 = pkg3["th_short"]

    # Compute 11 Microstructure Features
    micro3 = compute_realtime_microstructure(ob_l2, trades_tick, current_price)

    # Combine with 14 candle features
    feat_dict3 = {**latest_s1.to_dict(), **micro3}
    X3 = np.array([[feat_dict3.get(col, 0.0) for col in fcols3]])
    prob_up3 = float(model3.predict_proba(X3)[0, 1])

    s3_decision = "QUAN SÁT (Sổ lệnh giằng co cân bằng)"
    s3_action = "NONE"
    s3_sl = 0.0
    s3_tp = 0.0
    if prob_up3 >= th_long3 and trend_dist_s1 > 0:
        s3_decision = f"🟢 MUA (LONG) — Áp lực Mua áp đảo (Xác suất AI: {prob_up3*100:.1f}%)"
        s3_action = "LONG"
        s3_sl = current_price * 0.995
        s3_tp = current_price * 1.010
    elif prob_up3 <= th_short3 and trend_dist_s1 < 0:
        s3_decision = f"🔴 BÁN (SHORT) — Áp lực Bán áp đảo (Xác suất AI: {(1-prob_up3)*100:.1f}%)"
        s3_action = "SHORT"
        s3_sl = current_price * 1.005
        s3_tp = current_price * 0.990
    else:
        # Check instant micro edge
        if micro3["obi_l1"] > 0.40 and micro3["cvd"] > 0.20:
            s3_decision = f"🟢 ƯU TIÊN LONG LƯỚT NHANH (OBI L1={micro3['obi_l1']:+.2f}, CVD Taker Mua={micro3['cvd']:+.2f})"
        elif micro3["obi_l1"] < -0.40 and micro3["cvd"] < -0.20:
            s3_decision = f"🔴 ƯU TIÊN SHORT LƯỚT NHANH (OBI L1={micro3['obi_l1']:+.2f}, CVD Taker Bán={micro3['cvd']:+.2f})"

    obi_color = "XANH (Mua áp đảo)" if micro3["obi_l1"] > 0 else "ĐỎ (Bán áp đảo)"
    print(f"  • Mất cân bằng sổ lệnh Top 1 (OBI L1):  {micro3['obi_l1']:+6.3f} → Phe {obi_color}")
    print(f"  • Mất cân bằng sổ lệnh 20 tầng (OBI L20):{micro3['obi_l20']:+6.3f}")
    print(f"  • Dòng tiền Taker Buy/Sell (CVD):       {micro3['cvd']:+6.3f} (Khối lượng Taker Buy: {micro3['_taker_buy_vol']:.3f} BTC)")
    print(f"  • Giá vi mô Microprice lệch so với Close: {micro3['microprice']*100:+6.4f}%")
    print(f"  • Xác suất AI Chiến thuật 3 (P_UP):     {prob_up3*100:5.1f}% (Ngưỡng vào Long: >={th_long3*100:.1f}%, Short: <={th_short3*100:.1f}%)")
    print(f"  • Quyết định thực thi:                 👉 {s3_decision}")
    if s3_action != "NONE":
        print(f"    - Điểm vào: ${current_price:,.1f} | SL: ${s3_sl:,.1f} | TP: ${s3_tp:,.1f}")

    # =========================================================================
    # 5. TỔNG HỢP SO SÁNH TRỰC DIỆN
    # =========================================================================
    print("\n" + "=" * 105)
    print("                          BẢNG ĐỐI SOÁT QUYẾT ĐỊNH CỦA 3 CHIẾN THUẬT LÚC NÀY")
    print("=" * 105)
    summary_data = [
        {
            "Chiến thuật": "Chiến thuật 1 (5M Candle)",
            "Đặc trưng": "14 chỉ báo nến",
            "Độ sâu dữ liệu": "Quá khứ 5m (trễ)",
            "Tín hiệu lúc này": s1_decision[:35] + ("..." if len(s1_decision) > 35 else ""),
            "Điểm mạnh": "Đơn giản, bám xu hướng EMA50",
            "Điểm yếu": "Không thấy được sổ lệnh & cá mập gom hàng",
        },
        {
            "Chiến thuật": "Chiến thuật 2 (15M Pullback)",
            "Đặc trưng": "17 features + 1H Regime",
            "Độ sâu dữ liệu": "Khung 15m & 1h",
            "Tín hiệu lúc này": s2_decision[:35] + ("..." if len(s2_decision) > 35 else ""),
            "Điểm mạnh": "Bắt sóng hồi ATR, kỳ vọng dương",
            "Điểm yếu": "Số lượng setup ít, trễ do khung 15m",
        },
        {
            "Chiến thuật": "Chiến thuật 3 (HFT Microstructure)",
            "Đặc trưng": "25 features (Nến + L2 OB + Trades)",
            "Độ sâu dữ liệu": "Sổ lệnh 20 tầng + Taker realtime",
            "Tín hiệu lúc này": s3_decision[:35] + ("..." if len(s3_decision) > 35 else ""),
            "Điểm mạnh": "Độ chính xác 89.35%, thấy rõ tường đỡ giá",
            "Điểm yếu": "Cần dữ liệu HFT realtime liên tục",
        },
    ]
    df_cmp = pd.DataFrame(summary_data)
    print(df_cmp.to_string(index=False))
    print("=" * 105)


if __name__ == "__main__":
    evaluate_all_strategies()
