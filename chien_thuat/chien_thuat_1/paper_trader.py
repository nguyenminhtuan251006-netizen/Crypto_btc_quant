"""
Live Paper Trading Bot (Binance Futures Realtime Simulation)
Simulates live trading with 6 USDT (150k VNĐ) without spending real money.
Fetches real-time candles from Binance, computes features, generates XGBoost signals.
Active Session: London & New York (15:00 - 02:00 VN Time).
"""
import os
import sys
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.features import build_features
from src.model import BTC5mPredictor

def fetch_recent_candles(limit=100) -> pd.DataFrame:
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit={limit}"
    r = requests.get(url, timeout=5)
    data = r.json()
    df = pd.DataFrame(data).iloc[:, [0, 1, 2, 3, 4, 5]]
    df.columns = ["datetime", "open", "high", "low", "close", "volume"]
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df

def run_paper_trader():
    print("=" * 80)
    print("   LIVE PAPER TRADING BOT: BTC 5M XGBOOST (BINANCE FUTURES)")
    print("   Vốn khởi điểm: 6.0 USDT (~150k VNĐ) | Đòn bẩy: 5x | R/R: 2.4:1 (TP 1.2% / SL 0.5%)")
    print("   Chế độ: GIẢ LẬP REALTIME (AN TOÀN 100% - KHÔNG MẤT TIỀN THẬT)")
    print("   Khung giờ vàng: Phiên London & Mỹ (15:00 - 02:00 VN Time)")
    print("=" * 80)
    
    # 1. Train model on historical dataset (prefer 50k bars if available)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_50k = os.path.join(base_dir, "data", "BTCUSDT_5m_50k.csv")
    data_10k = os.path.join(base_dir, "data", "BTCUSDT_5m.csv")
    data_path = data_50k if os.path.exists(data_50k) else data_10k
    
    print(f"[1/2] Loading 6-month historical data ({os.path.basename(data_path)}) & training XGBoost...")
    df_raw = pd.read_csv(data_path)
    df_feat, feature_cols = build_features(df_raw)
    
    model = BTC5mPredictor(model_type="gradient_boosting")
    model.train(df_feat[feature_cols].to_numpy(), df_feat["target_direction"].to_numpy())
    
    # Calculate conviction threshold (Top 10% highest conviction)
    all_probs = model.model.predict_proba(df_feat[feature_cols].to_numpy())[:, 1]
    th_long = np.percentile(all_probs, 88.0)
    print(f"[Success] Model trained on {len(df_feat)} bars! Top conviction threshold: {th_long*100:.1f}%")
    
    # 2. Live Loop
    print("\n[2/2] Connecting to Binance realtime feed... (Ctrl+C to stop)")
    capital = 6.0
    initial_capital = 6.0
    pos = 0 # 1: Long, -1: Short, 0: Flat
    entry_price = 0.0
    bars_held = 0
    trades_count = 0
    
    try:
        while True:
            df_live = fetch_recent_candles(limit=60)
            df_live_feat, _ = build_features(df_live, is_train=False)
            
            if len(df_live_feat) > 0:
                last_bar = df_live_feat.iloc[-1]
                X_now = last_bar[feature_cols].to_numpy().reshape(1, -1)
                
                # Predict
                prob_up = model.model.predict_proba(X_now)[0, 1] * 100
                cur_price = last_bar["close"]
                cur_time = last_bar["datetime"]
                cur_hour = cur_time.hour
                
                # Session status
                is_london_us = (cur_hour >= 15) or (cur_hour <= 2)
                session_tag = "🟢 LONDON/US OPEN (SÔI ĐỘNG)" if is_london_us else "⚪ ASIA (CHỜ PHIÊN CHIỀU)"
                
                # Signal recommendation
                action = "FLAT (Chờ tín hiệu)"
                if is_london_us:
                    if prob_up >= th_long * 100 and last_bar["trend_dist"] > 0:
                        action = "LONG (MUA TĂNG 📈)"
                    elif prob_up <= (1.0 - th_long) * 100 and last_bar["trend_dist"] < 0:
                        action = "SHORT (BÁN GIẢM 📉)"
                        
                # Live PnL if in trade
                pnl_str = "Chưa có lệnh"
                if pos != 0:
                    bars_held += 1
                    cur_pnl = (cur_price / entry_price - 1.0) if pos == 1 else (1.0 - cur_price / entry_price)
                    pnl_str = f"Đang giữ {'LONG' if pos==1 else 'SHORT'} @ ${entry_price:,.1f} | Lãi: {cur_pnl*100:+.2f}%"
                    
                    # Check TP (+1.2%) or SL (-0.5%)
                    if cur_pnl >= 0.012 or cur_pnl <= -0.005 or bars_held >= 18:
                        pos_val = max(5.0, capital * 5.0)
                        net = pos_val * cur_pnl - pos_val * 0.0003
                        capital += net
                        trades_count += 1
                        print(f"\n🔔 [CHỐT LỆNH] {'THẮNG' if net>0 else 'CẮT LỖ'} | PnL: {net:+.3f} USDT | Vốn mới: ${capital:.2f}")
                        pos = 0
                        bars_held = 0
                        
                elif pos == 0 and "LONG" in action and capital > 1.0:
                    pos = 1
                    entry_price = cur_price
                    bars_held = 0
                    print(f"\n🚀 [VÀO LỆNH GIẢ LẬP] Mua LONG 1 hợp đồng @ ${cur_price:,.1f} | TP: ${cur_price*1.012:,.1f} | SL: ${cur_price*0.995:,.1f}")
                elif pos == 0 and "SHORT" in action and capital > 1.0:
                    pos = -1
                    entry_price = cur_price
                    bars_held = 0
                    print(f"\n🔻 [VÀO LỆNH GIẢ LẬP] Bán SHORT 1 hợp đồng @ ${cur_price:,.1f} | TP: ${cur_price*0.988:,.1f} | SL: ${cur_price*1.005:,.1f}")
                    
                print(f"[{cur_time.strftime('%H:%M:%S')}] {session_tag} | BTC: ${cur_price:,.1f} | Cửa Tăng: {prob_up:4.1f}% | Lệnh: {action:20s} | Vốn: ${capital:.2f} (Lãi: {(capital/initial_capital-1)*100:+.1f}%)")
                
            time.sleep(30) # Refresh every 30s
    except KeyboardInterrupt:
        print("\n[Stopped] Paper trading stopped by user.")

if __name__ == "__main__":
    run_paper_trader()
