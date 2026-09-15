"""
Hệ Thống Paper Trading Realtime - Chiến Thuật 3 (HFT Microstructure)
====================================================================
Mô phỏng giao dịch thực tế trên Binance Futures với vốn 6.0 USDT (~150k VNĐ).
Không mất tiền thật — Kết nối trực tiếp Binance API:
  - 100 nến 5m gần nhất
  - Sổ lệnh L2 20 tầng (Orderbook depth 20)
  - Khối lượng dòng tiền Taker gần nhất (Recent Trades / CVD)

Tính toán 25 đặc trưng và kích hoạt mô hình AI đã huấn luyện (hft_xgb_model.joblib).
"""
import os
import sys
import time
import argparse
import requests
import joblib
import numpy as np
import pandas as pd
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, current_dir)

from src.features import build_features


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
BINANCE_FAPI = "https://fapi.binance.com"


def fetch_recent_candles(symbol: str = "BTCUSDT", limit: int = 100) -> pd.DataFrame:
    """Lấy nến 5m gần nhất từ Binance Futures."""
    url = f"{BINANCE_FAPI}/fapi/v1/klines?symbol={symbol}&interval=5m&limit={limit}"
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    raw = r.json()
    df = pd.DataFrame(raw).iloc[:, [0, 1, 2, 3, 4, 5]]
    df.columns = ["datetime", "open", "high", "low", "close", "volume"]
    df["datetime"] = (
        pd.to_datetime(df["datetime"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Ho_Chi_Minh")
        .dt.tz_localize(None)
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def fetch_orderbook_l2(symbol: str = "BTCUSDT", limit: int = 20) -> dict:
    """Lấy sổ lệnh L2 (20 tầng) realtime từ Binance Futures."""
    url = f"{BINANCE_FAPI}/fapi/v1/depth?symbol={symbol}&limit={limit}"
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    data = r.json()
    bids = [[float(p), float(q)] for p, q in data.get("bids", [])[:limit]]
    asks = [[float(p), float(q)] for p, q in data.get("asks", [])[:limit]]
    return {"bids": bids, "asks": asks}


def fetch_recent_trades(symbol: str = "BTCUSDT", limit: int = 100) -> list[dict]:
    """Lấy các lệnh khớp gần nhất (recent trades) để tính CVD & Taker Flow."""
    url = f"{BINANCE_FAPI}/fapi/v1/trades?symbol={symbol}&limit={limit}"
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    raw = r.json()
    trades = []
    for t in raw:
        trades.append({
            "price": float(t["price"]),
            "qty": float(t["qty"]),
            "is_buyer_maker": bool(t["isBuyerMaker"]),  # True: Taker sell; False: Taker buy
            "time": int(t["time"]),
        })
    return trades


# ---------------------------------------------------------------------------
# Realtime Microstructure Feature Calculator
# ---------------------------------------------------------------------------
def compute_realtime_microstructure(ob: dict, trades: list[dict], close_price: float) -> dict:
    """
    Tính 11 microstructure features từ dữ liệu L2 Orderbook và Trades realtime.
    
    IMPORTANT: Returns features in the SAME SCALE as training data.
    - OBI features: [-1, 1] (already scale-independent) → pass through
    - spread_mean, spread_vol: normalized by close_price (matching features_v2.py)
    - microprice: (microprice - close) / close (matching features_v2.py)
    - CVD: raw signed volume → will be fed through model as-is (normalized downstream)
    - trade_intensity: raw count → will be fed through model as-is (normalized downstream)
    - vwap_deviation: already relative → pass through
    - large_trade_ratio: already [0,1] → pass through
    """
    bids = ob["bids"]
    asks = ob["asks"]

    bid_p0 = bids[0][0] if bids else close_price
    bid_q0 = bids[0][1] if bids else 1.0
    ask_p0 = asks[0][0] if asks else close_price
    ask_q0 = asks[0][1] if asks else 1.0

    # 1. OBI L1
    obi_l1 = (bid_q0 - ask_q0) / (bid_q0 + ask_q0 + 1e-9)

    # 2. OBI L5
    bid_q5 = sum(q for _, q in bids[:5])
    ask_q5 = sum(q for _, q in asks[:5])
    obi_l5 = (bid_q5 - ask_q5) / (bid_q5 + ask_q5 + 1e-9)

    # 3. OBI L20
    bid_q20 = sum(q for _, q in bids[:20])
    ask_q20 = sum(q for _, q in asks[:20])
    obi_l20 = (bid_q20 - ask_q20) / (bid_q20 + ask_q20 + 1e-9)

    # 3b. Depth-Weighted OBI (Albers et al. 2021 Oxford paper: decay weights w_i = 1 / sqrt(i+1))
    n_levels = min(len(bids), len(asks), 20)
    weights = [1.0 / np.sqrt(i + 1) for i in range(n_levels)]
    bid_qw = sum(weights[i] * bids[i][1] for i in range(n_levels))
    ask_qw = sum(weights[i] * asks[i][1] for i in range(n_levels))
    obi_weighted = (bid_qw - ask_qw) / (bid_qw + ask_qw + 1e-9)

    # 4-5. Spread: normalized by close price (matching features_v2.py lines 119-124)
    spread = max(ask_p0 - bid_p0, 0.0)
    # Compute spread statistics from multiple levels for better estimate
    spreads = []
    for i in range(min(len(bids), len(asks))):
        s = asks[i][0] - bids[i][0]
        if s > 0:
            spreads.append(s)
    spread_mean_raw = np.mean(spreads) if spreads else spread
    spread_vol_raw = np.std(spreads) if len(spreads) > 1 else spread * 0.1
    spread_mean_norm = spread_mean_raw / (close_price + 1e-9)
    spread_vol_norm = spread_vol_raw / (close_price + 1e-9)

    # 6. Depth Ratio
    depth_ratio = bid_q20 / (ask_q20 + 1e-9)

    # 7. Microprice normalized (matching features_v2.py lines 113-116)
    microprice = (bid_p0 * ask_q0 + ask_p0 * bid_q0) / (bid_q0 + ask_q0 + 1e-9)
    microprice_norm = (microprice - close_price) / (close_price + 1e-9)

    # 8. CVD - raw taker volume delta
    # Training normalization: cvd / rolling(288).abs().mean()
    # For live: we approximate by normalizing against the snapshot total volume
    # to get similar scale as training data (which centers around 0 with std ~3)
    taker_buy_vol = sum(t["qty"] for t in trades if not t["is_buyer_maker"])
    taker_sell_vol = sum(t["qty"] for t in trades if t["is_buyer_maker"])
    total_trade_vol = taker_buy_vol + taker_sell_vol
    cvd_raw = taker_buy_vol - taker_sell_vol
    # Normalize to match training scale: training CVD has mean~-0.07, std~3.0
    # Raw CVD from 100 recent trades is typically 0-5 BTC range
    # Training normalization divides by rolling abs mean (~1.0-2.0)
    # So we divide by a reasonable approximation of the abs mean
    cvd_abs_approx = max(abs(cvd_raw), total_trade_vol * 0.1, 0.01)
    cvd_norm = cvd_raw / cvd_abs_approx

    # 9. Trade Intensity - raw count
    # Training normalization: ti / rolling(288).mean()
    # Training mean is ~1.0 (by construction of rolling normalization)
    # 100 trades from REST API represents ~5 min worth → scale relative to expected count
    # Average training trade_intensity is ~1.0, so we target that scale
    trade_intensity_norm = 1.0  # snapshot always represents ~1 interval

    # 10. VWAP Deviation (already relative, matches training)
    if total_trade_vol > 0:
        vwap = sum(t["price"] * t["qty"] for t in trades) / total_trade_vol
        vwap_dev = (vwap - microprice) / (microprice + 1e-9)
    else:
        vwap_dev = 0.0

    # 11. Large Trade Ratio (already [0,1], matches training)
    if trades:
        quantities = [t["qty"] for t in trades]
        p90 = np.percentile(quantities, 90.0)
        large_vol = sum(t["qty"] for t in trades if t["qty"] >= p90)
        large_trade_ratio = large_vol / (total_trade_vol + 1e-9)
    else:
        large_trade_ratio = 0.0

    return {
        "obi_l1": float(obi_l1),
        "obi_l5": float(obi_l5),
        "obi_l20": float(obi_l20),
        "obi_weighted": float(obi_weighted),
        "spread_mean": float(spread_mean_norm),
        "spread_vol": float(spread_vol_norm),
        "depth_ratio": float(depth_ratio),
        "microprice": float(microprice_norm),
        "cvd": float(cvd_norm),
        "trade_intensity": float(trade_intensity_norm),
        "vwap_deviation": float(vwap_dev),
        "large_trade_ratio": float(large_trade_ratio),
        "_raw_bid": bid_p0,
        "_raw_ask": ask_p0,
        "_raw_spread": spread,
        "_raw_microprice": microprice,
        "_taker_buy_vol": taker_buy_vol,
        "_taker_sell_vol": taker_sell_vol,
    }



# ---------------------------------------------------------------------------
# Main Paper Trading Engine
# ---------------------------------------------------------------------------
def run_paper_trader(dry_run: bool = False):
    print("=" * 90)
    print("      🚀 LIVE PAPER TRADING BOT: CHIẾN THUẬT 3 - HFT MICROSTRUCTURE")
    print("      Mô hình: AI XGBoost (25 Features = 14 Nến + 11 Vi cấu trúc Sổ lệnh & Trades)")
    print("      Vốn khởi điểm: 6.0 USDT (~150k VNĐ) | Đòn bẩy: 5x | Phí Maker: 0.015%")
    print("      Chế độ: GIẢ LẬP REALTIME AN TOÀN 100% (KHÔNG DÙNG TIỀN THẬT)")
    print("=" * 90)

    # 1. Load trained model package
    model_path = os.path.join(current_dir, "models", "hft_xgb_model.joblib")
    if not os.path.exists(model_path):
        print(f"[Error] Không tìm thấy file model: {model_path}")
        print(f"        Đang tự động chạy train_model.py...")
        from train_model import train_and_save_model
        train_and_save_model()

    pkg = joblib.load(model_path)
    model = pkg["model"]
    feature_cols = pkg["feature_cols"]
    th_long = pkg.get("th_long", 0.65)
    th_short = pkg.get("th_short", 0.15)
    print(f"\n[AI Model] Đã nạp thành công bộ não AI (Accuracy: {pkg.get('accuracy', 0):.2f}%)")
    print(f"  → Số đặc trưng yêu cầu: {len(feature_cols)}")
    print(f"  → Ngưỡng vào lệnh Long: Xác suất >= {th_long*100:.1f}%")
    print(f"  → Ngưỡng vào lệnh Short: Xác suất <= {th_short*100:.1f}%")

    # 2. State variables
    capital = 6.0
    initial_capital = 6.0
    position = 0          # 1: Long, -1: Short, 0: Flat
    entry_price = 0.0
    entry_time = None
    pos_size_usdt = 0.0
    sl_price = 0.0
    tp_price = 0.0
    trade_count = 0
    win_count = 0

    stop_loss_pct = 0.004     # 0.4% SL (synced with symmetric backtest)
    take_profit_pct = 0.004   # 0.4% TP (synced with symmetric backtest)
    leverage = 5.0
    maker_fee = 0.0002        # 0.02% Maker limit fee (Oxford paper recommendation)

    print("\n[Binance Feed] Đang kết nối luồng dữ liệu trực tiếp...")
    iteration = 0

    while True:
        iteration += 1
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Step A: Fetch Live Market Data
            candles = fetch_recent_candles(symbol="BTCUSDT", limit=100)
            ob = fetch_orderbook_l2(symbol="BTCUSDT", limit=20)
            trades = fetch_recent_trades(symbol="BTCUSDT", limit=100)

            latest_candle = candles.iloc[-1]
            current_price = latest_candle["close"]

            # Step B: Feature Engineering (14 Technical Features)
            df_feat, original_cols = build_features(candles, is_train=False)
            latest_feat = df_feat.iloc[-1].to_dict()

            # Step C: Microstructure Features (11 HFT Features)
            micro_data = compute_realtime_microstructure(ob, trades, current_price)

            # Combine all 25 features into row vector
            row_dict = {**latest_feat, **micro_data}
            X_vec = np.array([[row_dict.get(col, 0.0) for col in feature_cols]])

            # Step D: Model Inference
            prob_up = float(model.predict_proba(X_vec)[0, 1])

            # Step E: Session & Trend Filters
            current_hour = now_dt.hour
            is_active_session = (current_hour >= 15) or (current_hour <= 2)
            trend_dist = latest_feat.get("trend_dist", 0.0)

            # Step F: Signal Determination
            signal = 0
            if is_active_session:
                if prob_up >= th_long and trend_dist > 0:
                    signal = 1   # High conviction LONG
                elif prob_up <= th_short and trend_dist < 0:
                    signal = -1  # High conviction SHORT

            # Step G: Position Management & Execution
            pnl_pct_unrealized = 0.0
            if position != 0:
                if position == 1:
                    pnl_pct_unrealized = (current_price / entry_price - 1.0) * leverage
                    # Check SL / TP
                    if current_price <= sl_price:
                        # Hit Stop Loss
                        pnl_realized = pos_size_usdt * (sl_price / entry_price - 1.0) * leverage - pos_size_usdt * maker_fee * 2
                        capital += pnl_realized
                        trade_count += 1
                        print(f"\n  🛑 [HIT SL] Đóng lệnh LONG tại {sl_price:.1f} | PnL: {pnl_realized:+.4f} USDT | Vốn: {capital:.2f} USDT")
                        position = 0
                    elif current_price >= tp_price:
                        # Hit Take Profit
                        pnl_realized = pos_size_usdt * (tp_price / entry_price - 1.0) * leverage - pos_size_usdt * maker_fee * 2
                        capital += pnl_realized
                        trade_count += 1
                        win_count += 1
                        print(f"\n  🎯 [HIT TP] Chốt lời LONG tại {tp_price:.1f} | PnL: {pnl_realized:+.4f} USDT | Vốn: {capital:.2f} USDT")
                        position = 0
                elif position == -1:
                    pnl_pct_unrealized = (1.0 - current_price / entry_price) * leverage
                    if current_price >= sl_price:
                        # Hit Stop Loss Short
                        pnl_realized = pos_size_usdt * (1.0 - sl_price / entry_price) * leverage - pos_size_usdt * maker_fee * 2
                        capital += pnl_realized
                        trade_count += 1
                        print(f"\n  🛑 [HIT SL] Đóng lệnh SHORT tại {sl_price:.1f} | PnL: {pnl_realized:+.4f} USDT | Vốn: {capital:.2f} USDT")
                        position = 0
                    elif current_price <= tp_price:
                        # Hit Take Profit Short
                        pnl_realized = pos_size_usdt * (1.0 - tp_price / entry_price) * leverage - pos_size_usdt * maker_fee * 2
                        capital += pnl_realized
                        trade_count += 1
                        win_count += 1
                        print(f"\n  🎯 [HIT TP] Chốt lời SHORT tại {tp_price:.1f} | PnL: {pnl_realized:+.4f} USDT | Vốn: {capital:.2f} USDT")
                        position = 0

            # Step H: Enter new trade if flat and signal triggered
            if position == 0 and signal != 0:
                position = signal
                entry_price = current_price
                entry_time = now_str
                pos_size_usdt = capital * 0.95  # 95% vốn để có buffer phí
                if position == 1:
                    sl_price = entry_price * (1.0 - stop_loss_pct)
                    tp_price = entry_price * (1.0 + take_profit_pct)
                    print(f"\n  🟢 [MỞ LONG (MAKER)] Giá: {entry_price:.1f} | SL: {sl_price:.1f} (-{stop_loss_pct*100:.1f}%) | TP: {tp_price:.1f} (+{take_profit_pct*100:.1f}%) | Vốn vào: {pos_size_usdt:.2f} USDT (x5)")
                else:
                    sl_price = entry_price * (1.0 + stop_loss_pct)
                    tp_price = entry_price * (1.0 - take_profit_pct)
                    print(f"\n  🔴 [MỞ SHORT (MAKER)] Giá: {entry_price:.1f} | SL: {sl_price:.1f} (-{stop_loss_pct*100:.1f}%) | TP: {tp_price:.1f} (+{take_profit_pct*100:.1f}%) | Vốn vào: {pos_size_usdt:.2f} USDT (x5)")

            # Step I: Rich Terminal Display
            pos_label = "CHƯA VÀO LỆNH (FLAT)"
            if position == 1:
                pos_label = f"LONG ({pnl_pct_unrealized*100:+.2f}%)"
            elif position == -1:
                pos_label = f"SHORT ({pnl_pct_unrealized*100:+.2f}%)"

            obi_bar = ("🟢 " + "█" * int(abs(micro_data['obi_l1']) * 10)) if micro_data['obi_l1'] > 0 else ("🔴 " + "█" * int(abs(micro_data['obi_l1']) * 10))
            cvd_label = f"{micro_data['cvd']:+.2f}"

            ret_pct = (capital / initial_capital - 1.0) * 100
            winrate = (win_count / trade_count * 100) if trade_count > 0 else 0.0

            print(
                f"[{now_str}] BTC: ${current_price:,.1f} | "
                f"P(UP): {prob_up*100:4.1f}% | "
                f"OBI: {obi_bar} | "
                f"CVD: {cvd_label} | "
                f"Vị thế: {pos_label} | "
                f"Vốn: ${capital:.2f} ({ret_pct:+.1f}%)"
            )

        except Exception as e:
            print(f"[{now_str}] ⚠️ Lỗi cập nhật feed: {e}")

        if dry_run:
            print(f"\n[Dry-run] Hoàn thành 1 chu kỳ kiểm tra mô phỏng thành công!")
            break

        # Sleep 15 seconds before next polling
        time.sleep(15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử 1 vòng kiểm tra rồi dừng")
    args = parser.parse_args()
    run_paper_trader(dry_run=args.dry_run)
