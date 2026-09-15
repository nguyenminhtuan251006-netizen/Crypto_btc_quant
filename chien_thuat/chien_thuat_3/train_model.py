"""
Huấn luyện và Đóng gói Mô hình AI Chiến thuật 3 (HFT Microstructure)
=====================================================================
Sử dụng 25 đặc trưng (14 chỉ báo nến 5m + 11 vi cấu trúc sổ lệnh L2 & trades)
Huấn luyện trên 44,000 nến (~139 ngày) và lưu mô hình vào models/hft_xgb_model.joblib
"""
import os
import sys
import joblib
import numpy as np
import pandas as pd
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, current_dir)

from src.features_v2 import build_features_v2, load_hft_features
from src.model import BTC5mPredictor


def train_and_save_model():
    print("=" * 80)
    print("   🤖 HUẤN LUYỆN MÔ HÌNH CHIẾN THUẬT 3: HFT MICROSTRUCTURE")
    print("   Nguồn: 14 Nến 5m + 11 Chỉ số Vi cấu trúc Sổ lệnh L2 (20 tầng) & Trades")
    print("=" * 80)

    # 1. Load Data
    data_dir = os.path.join(workspace_dir, "data")
    data_path = os.path.join(data_dir, "BTCUSDT_5m_50k.csv")
    if not os.path.exists(data_path):
        data_path = os.path.join(data_dir, "BTCUSDT_5m.csv")

    hft_path = os.path.join(data_dir, "hft_features_5m.parquet")

    if not os.path.exists(data_path) or not os.path.exists(hft_path):
        print(f"[Error] Không tìm thấy dữ liệu tại {data_path} hoặc {hft_path}")
        return

    print(f"\n[1/4] Đang nạp dữ liệu lịch sử...")
    df_raw = pd.read_csv(data_path)
    df_raw["datetime"] = pd.to_datetime(df_raw["datetime"])
    hft_df = load_hft_features(hft_path)

    # Align overlapping date range
    mask = (df_raw["datetime"] >= hft_df["datetime"].min()) & (df_raw["datetime"] <= hft_df["datetime"].max())
    df_period = df_raw[mask].copy().reset_index(drop=True)
    print(f"  → Khung thời gian: {df_period['datetime'].iloc[0]} đến {df_period['datetime'].iloc[-1]}")
    print(f"  → Tổng số nến khớp: {len(df_period):,} nến 5m")

    # 2. Build 25 Features
    print(f"\n[2/4] Đang trích xuất 25 đặc trưng (14 Technical + 11 HFT Microstructure)...")
    df_v2, feature_cols = build_features_v2(df_period, hft_df=hft_df, is_train=True)
    print(f"  → Số đặc trưng: {len(feature_cols)}")
    print(f"  → Danh sách HFT features: obi_l1, obi_l5, obi_l20, spread_mean, spread_vol, depth_ratio, microprice, cvd, trade_intensity, vwap_deviation, large_trade_ratio")

    # 3. Train/Test Split
    split_idx = int(len(df_v2) * 0.70)
    train_df = df_v2.iloc[:split_idx].copy()
    test_df = df_v2.iloc[split_idx:].copy().reset_index(drop=True)

    X_train = train_df[feature_cols].to_numpy()
    y_train = train_df["target_direction"].to_numpy()

    X_test = test_df[feature_cols].to_numpy()
    y_test = test_df["target_direction"].to_numpy()

    print(f"\n[3/4] Đang huấn luyện mô hình Gradient Boosting...")
    print(f"  → Tập huấn luyện (Train): {len(train_df):,} nến")
    print(f"  → Tập kiểm thử (Test OOS): {len(test_df):,} nến")

    predictor = BTC5mPredictor(model_type="gradient_boosting")
    predictor.train(X_train, y_train)

    # Evaluate accuracy
    test_preds = predictor.model.predict(X_test)
    test_probs = predictor.model.predict_proba(X_test)[:, 1]
    acc = np.mean(test_preds == y_test) * 100.0
    print(f"  → Độ chính xác tập Test (Directional Accuracy): {acc:.2f}%")

    # Determine high-conviction threshold (top 5% probability: Oxford paper selective alpha)
    all_train_probs = predictor.model.predict_proba(X_train)[:, 1]
    th_long = float(np.percentile(all_train_probs, 95.0))
    th_short = float(np.percentile(all_train_probs, 5.0))
    print(f"  → Ngưỡng vào lệnh Long (Top 5% cao nhất): {th_long*100:.1f}%")
    print(f"  → Ngưỡng vào lệnh Short (Top 5% thấp nhất): {th_short*100:.1f}%")

    # 4. Save Model Package
    model_dir = os.path.join(current_dir, "models")
    os.makedirs(model_dir, exist_ok=True)
    save_path = os.path.join(model_dir, "hft_xgb_model.joblib")

    model_package = {
        "model": predictor.model,
        "feature_cols": feature_cols,
        "th_long": th_long,
        "th_short": th_short,
        "percentile": 95.0,
        "accuracy": acc,
        "train_samples": len(train_df),
        "test_samples": len(test_df),
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    joblib.dump(model_package, save_path)
    file_size_kb = os.path.getsize(save_path) / 1024
    print(f"\n[4/4] Đã lưu mô hình thành công!")
    print(f"  → Đường dẫn: {save_path} ({file_size_kb:.1f} KB)")
    print("=" * 80)


if __name__ == "__main__":
    train_and_save_model()
