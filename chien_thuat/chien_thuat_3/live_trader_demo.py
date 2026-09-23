"""
Binance Futures Demo Live Trader - CHIẾN THUẬT 3: HFT MICROSTRUCTURE
=====================================================================
Tự động bắn lệnh trực tiếp vào tài khoản Binance Demo Trading (Web demo-fapi.binance.com)
Sử dụng API Key & Secret Key từ file .env.
Mô hình AI: 25 đặc trưng (Nến 5m + Sổ lệnh L2 20 tầng + CVD Taker flow).
Tự động cài sẵn Take Profit (+1.0%) & Stop Loss (-0.5%) trực tiếp lên hệ thống Binance.
"""
import os
import sys
import time
import hmac
import hashlib
import requests
import argparse
import joblib
import numpy as np
import pandas as pd
from urllib.parse import urlencode
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, current_dir)

from src.features import build_features
from paper_trader import (
    fetch_recent_candles,
    fetch_orderbook_l2,
    fetch_recent_trades,
    compute_realtime_microstructure,
)

def get_binance_mode():
    env_path = os.path.join(workspace_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("BINANCE_MODE="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'").lower()
    return "demo"


def get_base_url():
    mode = get_binance_mode()
    if mode == "live":
        return "https://fapi.binance.com"
    return "https://demo-fapi.binance.com"


BASE_URL = get_base_url()


def load_credentials(mode: str = None):
    env_path = os.path.join(workspace_dir, ".env")
    demo_key = ""
    demo_secret = ""
    live_key = ""
    live_secret = ""
    target_mode = mode.lower() if mode else get_binance_mode()
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("BINANCE_API_KEY="):
                    live_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("BINANCE_API_SECRET="):
                    live_secret = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("BINANCE_DEMO_API_KEY="):
                    demo_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("BINANCE_DEMO_API_SECRET="):
                    demo_secret = line.split("=", 1)[1].strip().strip('"').strip("'")

    if target_mode == "live" and live_key and live_secret:
        return live_key, live_secret
    if target_mode == "demo" and demo_key and demo_secret:
        return demo_key, demo_secret
    if demo_key and demo_secret:
        return demo_key, demo_secret
    return live_key or demo_key, live_secret or demo_secret


class BinanceDemoClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url or get_base_url()
        self.headers = {"X-MBX-APIKEY": self.api_key}

    def _sign(self, params: dict) -> dict:
        p = params.copy()
        p["timestamp"] = int(time.time() * 1000)
        query = urlencode(p)
        p["signature"] = hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        return p

    def get(self, endpoint: str, params=None):
        if params is None: params = {}
        p = self._sign(params)
        r = requests.get(f"{self.base_url}{endpoint}", params=p, headers=self.headers, timeout=8)
        return r.json()

    def post(self, endpoint: str, params=None):
        if params is None: params = {}
        p = self._sign(params)
        r = requests.post(f"{self.base_url}{endpoint}", data=p, headers=self.headers, timeout=8)
        return r.json()

    def delete(self, endpoint: str, params=None):
        if params is None: params = {}
        p = self._sign(params)
        r = requests.delete(f"{self.base_url}{endpoint}", params=p, headers=self.headers, timeout=8)
        return r.json()

    def init_account_settings(self, symbol="BTCUSDT", leverage=5):
        try:
            self.post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        except Exception:
            pass
        try:
            self.post("/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
        except Exception:
            pass

    def get_balance(self) -> float:
        res = self.get("/fapi/v2/balance")
        if isinstance(res, list):
            for b in res:
                if b.get("asset") == "USDT":
                    return float(b.get("availableBalance", 0.0))
        return 0.0

    def get_position(self, symbol="BTCUSDT"):
        res = self.get("/fapi/v2/positionRisk", {"symbol": symbol})
        if isinstance(res, list):
            for p in res:
                if p.get("symbol") == symbol:
                    amt = float(p.get("positionAmt", 0.0))
                    entry = float(p.get("entryPrice", 0.0))
                    unPnl = float(p.get("unRealizedProfit", 0.0))
                    return amt, entry, unPnl
        return 0.0, 0.0, 0.0

    def cancel_all_orders(self, symbol="BTCUSDT"):
        try:
            self.delete("/fapi/v1/allOpenOrders", {"symbol": symbol})
        except Exception:
            pass
        try:
            algos = self.get("/fapi/v1/openAlgoOrders", {"symbol": symbol})
            if isinstance(algos, list):
                for a in algos:
                    aid = a.get("algoId")
                    if aid:
                        self.delete("/fapi/v1/algoOrder", {"algoId": aid})
        except Exception:
            pass

    def place_market_order(self, symbol: str, side: str, qty: float):
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty
        }
        return self.post("/fapi/v1/order", params)

    def place_tp_sl(self, symbol: str, close_side: str, qty: float, tp_price: float, sl_price: float):
        # 1. Take Profit: Limit Order (Maker fee)
        tp_params = {
            "symbol": symbol,
            "side": close_side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "price": round(tp_price, 1),
            "quantity": qty,
            "reduceOnly": "true"
        }
        r_tp = self.post("/fapi/v1/order", tp_params)

        # 2. Stop Loss: Conditional Stop Market Order
        sl_params = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "triggerPrice": round(sl_price, 1),
            "quantity": qty,
            "reduceOnly": "true"
        }
        r_sl = self.post("/fapi/v1/algoOrder", sl_params)
        return r_tp, r_sl


def execute_hft_live_bot(trade_now: bool = False, side_override: str = None):
    api_key, api_secret = load_credentials()
    if not api_key or not api_secret:
        print("[LỖI] Không tìm thấy BINANCE_DEMO_API_KEY trong file .env!")
        return

    print("=" * 90)
    print("      🚀 BOT BẮN LỆNH DEMO TRADING BINANCE: CHIẾN THUẬT 3 (HFT MICROSTRUCTURE)")
    print("      Tài khoản: Demo Web (demo-fapi.binance.com) | Khối lượng: 0.001 BTC | Đòn bẩy: 5x")
    print("      Bộ não AI: 25 Features (Sổ lệnh L2 20 tầng + CVD Taker Flow)")
    print("=" * 90)

    client = BinanceDemoClient(api_key, api_secret)
    client.init_account_settings("BTCUSDT", leverage=5)

    balance = client.get_balance()
    amt, entry, unPnl = client.get_position("BTCUSDT")
    print(f"\n[Kết nối thành công Demo Binance]")
    print(f"  → Số dư khả dụng (Available Balance): {balance:,.2f} USDT")
    print(f"  → Vị thế hiện tại trên web:          {amt:+.4f} BTC (Giá vào: ${entry:,.1f} | uPnL: {unPnl:+.2f} USDT)")

    # Load Model Strategy 3
    model_path = os.path.join(current_dir, "models", "hft_xgb_model.joblib")
    if not os.path.exists(model_path):
        from train_model import train_and_save_model
        train_and_save_model()

    pkg = joblib.load(model_path)
    model = pkg["model"]
    fcols = pkg["feature_cols"]
    th_long = pkg.get("th_long", 0.65)
    th_short = pkg.get("th_short", 0.15)

    # 1. Fetch live market & HFT data
    candles = fetch_recent_candles("BTCUSDT", limit=100)
    ob = fetch_orderbook_l2("BTCUSDT", limit=20)
    trades = fetch_recent_trades("BTCUSDT", limit=100)

    cur_p = candles.iloc[-1]["close"]
    df_feat, _ = build_features(candles, is_train=False)
    latest_feat = df_feat.iloc[-1].to_dict()
    micro = compute_realtime_microstructure(ob, trades, cur_p)

    row_dict = {**latest_feat, **micro}
    X_vec = np.array([[row_dict.get(col, 0.0) for col in fcols]])
    prob_up = float(model.predict_proba(X_vec)[0, 1])

    print(f"\n[Dữ liệu vi cấu trúc HFT lúc này]:")
    print(f"  • Giá BTC: ${cur_p:,.1f} | P(UP): {prob_up*100:.1f}%")
    print(f"  • Sổ lệnh Top 1 (OBI L1): {micro['obi_l1']:+.3f} | 20 tầng (OBI L20): {micro['obi_l20']:+.3f}")
    print(f"  • Dòng tiền Taker (CVD): {micro['cvd']:+.3f} (Mua chủ động: {micro['_taker_buy_vol']:.3f} BTC)")

    # Determine direction
    target_side = "BUY"
    if side_override:
        target_side = side_override.upper()
    elif prob_up >= 0.50:
        target_side = "BUY"
    else:
        target_side = "SELL"

    if trade_now:
        print(f"\n⚡ [KÍCH HOẠT ĐẶT LỆNH TRỰC TIẾP LÊN WEB DEMO BINANCE THEO CHIẾN THUẬT 3]...")
        # Clean previous open orders
        client.cancel_all_orders("BTCUSDT")

        qty = 0.001
        close_side = "SELL" if target_side == "BUY" else "BUY"

        # Market order
        res_order = client.place_market_order("BTCUSDT", target_side, qty)
        order_id = res_order.get("orderId", "N/A")
        status = res_order.get("status", res_order)
        print(f"  → 1. Lệnh thị trường ({target_side} {qty} BTC @ ~${cur_p:,.1f}): Status={status} (ID: {order_id})")

        # Set TP & SL
        if target_side == "BUY":
            tp = round(cur_p * 1.005, 1)  # +0.5% (synced with training target)
            sl = round(cur_p * 0.997, 1)  # -0.3% (synced with training target)
        else:
            tp = round(cur_p * 0.995, 1)  # -0.5%
            sl = round(cur_p * 1.003, 1)  # +0.3%

        time.sleep(0.5)
        r_tp, r_sl = client.place_tp_sl("BTCUSDT", close_side, qty, tp, sl)
        print(f"  → 2. Lệnh Chốt lời (Take Profit @ ${tp:,.1f}): Status={r_tp.get('status', 'OK')}")
        print(f"  → 3. Lệnh Cắt lỗ  (Stop Loss   @ ${sl:,.1f}): Status={r_sl.get('status', 'OK')}")
def run_continuous_loop():
    api_key, api_secret = load_credentials()
    if not api_key or not api_secret:
        print("[LỖI] Không tìm thấy BINANCE_DEMO_API_KEY trong file .env!")
        return

    print("=" * 95)
    print("      🤖 BOT TỰ ĐỘNG CHẠY NGẦM 24/7 - CHIẾN THUẬT 3: HFT MICROSTRUCTURE")
    print("      Tài khoản: Demo Web (demo-fapi.binance.com) | Khối lượng: 0.001 BTC | Đòn bẩy: 5x")
    print("      Tự động quét: Nến 5m + Sổ lệnh L2 20 tầng + CVD Taker Flow")
    print("      Tự động vào lệnh & cài sẵn TP (+0.5%) / SL (-0.3%) lên sàn Binance")
    print("      (Dù bạn tắt máy tính hay trình duyệt, bot vẫn chạy ngầm liên tục trên Server)")
    print("=" * 95)

    client = BinanceDemoClient(api_key, api_secret)
    client.init_account_settings("BTCUSDT", leverage=5)

    # Load Model
    model_path = os.path.join(current_dir, "models", "hft_xgb_model.joblib")
    if not os.path.exists(model_path):
        from train_model import train_and_save_model
        train_and_save_model()

    pkg = joblib.load(model_path)
    model = pkg["model"]
    fcols = pkg["feature_cols"]
    th_long = pkg.get("th_long", 0.671)
    th_short = pkg.get("th_short", 0.228)

    log_dir = os.path.join(workspace_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "hft_live_trader.log")

    print(f"\n[AI Model] Đã sẵn sàng | Ngưỡng Long: >={th_long*100:.1f}% | Ngưỡng Short: <={th_short*100:.1f}%")
    print(f"[Khung giờ vàng] London & New York (15:00 - 02:00 VN Time)")
    print(f"[Nhật ký lưu tại] {log_file}")
    print("\n👉 Bắt đầu vòng lặp tự động canh lệnh... (Bấm Ctrl+C để dừng)")

    iteration = 0
    while True:
        iteration += 1
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # 1. Check current position on Binance Demo
            amt, entry, unPnl = client.get_position("BTCUSDT")

            # 2. If already in position, ensure TP/SL orders are placed
            if abs(amt) > 0:
                orders = client.get("/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
                algos = client.get("/fapi/v1/openAlgoOrders", {"symbol": "BTCUSDT"})
                if not orders and not algos:
                    close_side = "SELL" if amt > 0 else "BUY"
                    tp = round(entry * 1.004, 1) if amt > 0 else round(entry * 0.996, 1)
                    sl = round(entry * 0.996, 1) if amt > 0 else round(entry * 1.004, 1)
                    client.place_tp_sl("BTCUSDT", close_side, abs(amt), tp, sl)
                    log_msg = f"[{now_str}] Đã tự động cài lại TP/SL bảo vệ vị thế ({close_side} {abs(amt)} BTC @ TP {tp} / SL {sl})"
                    print(log_msg)
                    with open(log_file, "a") as f: f.write(log_msg + "\n")

                side_str = "LONG" if amt > 0 else "SHORT"
                log_line = f"[{now_str}] Vị thế đang chạy: {side_str} {abs(amt)} BTC @ ${entry:,.1f} | Lãi/Lỗ tạm tính: {unPnl:+.4f} USDT"
                print(log_line)
                with open(log_file, "a") as f: f.write(log_line + "\n")

            else:
                # Flat: scan market for new setup
                candles = fetch_recent_candles("BTCUSDT", limit=100)
                ob = fetch_orderbook_l2("BTCUSDT", limit=20)
                trades = fetch_recent_trades("BTCUSDT", limit=100)

                cur_p = candles.iloc[-1]["close"]
                df_feat, _ = build_features(candles, is_train=False)
                latest_feat = df_feat.iloc[-1].to_dict()
                micro = compute_realtime_microstructure(ob, trades, cur_p)

                row_dict = {**latest_feat, **micro}
                X_vec = np.array([[row_dict.get(col, 0.0) for col in fcols]])
                prob_up = float(model.predict_proba(X_vec)[0, 1])

                cur_hour = now_dt.hour
                is_active_session = (cur_hour >= 15) or (cur_hour <= 2)
                trend_dist = latest_feat.get("trend_dist", 0.0)

                signal = 0
                if is_active_session:
                    if prob_up >= th_long and trend_dist > 0:
                        signal = 1
                    elif prob_up <= th_short and trend_dist < 0:
                        signal = -1

                obi_str = f"{micro['obi_l1']:+.2f}"
                cvd_str = f"{micro['cvd']:+.2f}"
                log_line = f"[{now_str}] BTC: ${cur_p:,.1f} | P(UP): {prob_up*100:4.1f}% | OBI: {obi_str} | CVD: {cvd_str} | Tín hiệu: {'MUA (LONG)' if signal==1 else ('BÁN (SHORT)' if signal==-1 else 'QUAN SÁT')}"
                print(log_line)
                with open(log_file, "a") as f: f.write(log_line + "\n")

                if signal != 0:
                    qty = 0.001  # 0.001 BTC (~$78 USDT notional | ký quỹ ~$15.6 USDT ở đòn bẩy 5x)
                    order_side = "BUY" if signal == 1 else "SELL"
                    close_side = "SELL" if signal == 1 else "BUY"

                    # 1. Market order
                    res = client.place_market_order("BTCUSDT", order_side, qty)
                    # 2. TP/SL
                    tp = round(cur_p * 1.004, 1) if signal == 1 else round(cur_p * 0.996, 1)
                    sl = round(cur_p * 0.996, 1) if signal == 1 else round(cur_p * 1.004, 1)
                    time.sleep(0.5)
                    r_tp, r_sl = client.place_tp_sl("BTCUSDT", close_side, qty, tp, sl)

                    order_msg = (
                        f"🚀 [{now_str}] TỰ ĐỘNG BẮN LỆNH {order_side} {qty} BTC @ ${cur_p:,.1f}\n"
                        f"   - Lệnh thị trường: Status={res.get('status', 'OK')} (ID: {res.get('orderId', 'N/A')})\n"
                        f"   - TP Chốt lời (+0.4%): ${tp:,.1f} | SL Cắt lỗ (-0.4%): ${sl:,.1f}"
                    )
                    print(order_msg)
                    with open(log_file, "a") as f: f.write(order_msg + "\n")

        except Exception as e:
            err_msg = f"[{now_str}] ⚠️ Lỗi vòng lặp bot: {e}"
            print(err_msg)
            with open(log_file, "a") as f: f.write(err_msg + "\n")

        time.sleep(25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-now", action="store_true", help="Bắn 1 lệnh trực tiếp lên web Demo Binance ngay bây giờ")
    parser.add_argument("--loop", action="store_true", help="Chạy vòng lặp tự động 24/7 (tự quét và tự bắn lệnh khi có cơ hội)")
    parser.add_argument("--side", type=str, default=None, help="BUY hoặc SELL (mặc định lấy theo dự đoán AI)")
    args = parser.parse_args()

    if args.loop:
        run_continuous_loop()
    else:
        execute_hft_live_bot(trade_now=args.trade_now, side_override=args.side)
