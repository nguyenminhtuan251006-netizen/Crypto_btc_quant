"""
Binance Futures Demo Live Trader (Tự Động Bắn Lệnh Vào Tài Khoản Demo Binance)
Sử dụng API Key & Secret Key của tài khoản Demo Trading.
Khối lượng: 0.001 BTC (~78 USDT giá trị, ký quỹ ~15 USDT ở 5x).
Cài sẵn Take Profit (+1.2%) & Stop Loss (-0.5%) trực tiếp lên hệ thống Binance.
"""
import os
import sys
import time
import hmac
import hashlib
import requests
import argparse
from urllib.parse import urlencode
from datetime import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from src.features import build_features
    from src.model import BTC5mPredictor
except ImportError:
    from crypto_btc_quant_lab.src.features import build_features
    from crypto_btc_quant_lab.src.model import BTC5mPredictor

BASE_URL = "https://demo-fapi.binance.com"

def load_credentials():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    api_key = ""
    api_secret = ""
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("BINANCE_DEMO_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("BINANCE_DEMO_API_SECRET="):
                    api_secret = line.split("=", 1)[1].strip().strip('"').strip("'")
    return api_key, api_secret

class BinanceDemoClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
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
        r = requests.get(f"{BASE_URL}{endpoint}", params=p, headers=self.headers, timeout=6)
        return r.json()

    def post(self, endpoint: str, params=None):
        if params is None: params = {}
        p = self._sign(params)
        r = requests.post(f"{BASE_URL}{endpoint}", data=p, headers=self.headers, timeout=6)
        return r.json()

    def delete(self, endpoint: str, params=None):
        if params is None: params = {}
        p = self._sign(params)
        r = requests.delete(f"{BASE_URL}{endpoint}", params=p, headers=self.headers, timeout=6)
        return r.json()

    def init_account_settings(self, symbol="BTCUSDT", leverage=5):
        # 1. Set leverage
        try:
            self.post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        except Exception:
            pass
        # 2. Set margin type
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
        return None, None, None

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
        # 1. Take Profit: Limit Order (Maker fee 0.015%, appears in 'Basic' Open Orders)
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

        # 2. Stop Loss: Conditional Stop Market Order (appears in 'Conditional' Open Orders)
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

def fetch_live_candles(limit=60) -> pd.DataFrame:
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit={limit}"
    r = requests.get(url, timeout=5)
    data = r.json()
    df = pd.DataFrame(data).iloc[:, [0, 1, 2, 3, 4, 5]]
    df.columns = ["datetime", "open", "high", "low", "close", "volume"]
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df

def run_live_bot(test_buy_now=False):
    api_key, api_secret = load_credentials()
    if not api_key or not api_secret:
        print("[LỖI] Chưa tìm thấy API Key trong file .env!")
        return

    print("=" * 85)
    print("   🤖 BOT TỰ ĐỘNG BẮN LỆNH DEMO TRADING TRÊN BINANCE FUTURES")
    print("   Tài khoản: Demo Binance (Tự động cập nhật trực tiếp lên giao diện Web)")
    print("   Khối lượng: 0.001 BTC (~78 USDT giá trị | Đòn bẩy 5x)")
    print("   Quy tắc: AI XGBoost High-Conviction | TP: +1.2% | SL: -0.5%")
    print("=" * 85)

    client = BinanceDemoClient(api_key, api_secret)
    client.init_account_settings("BTCUSDT", leverage=5)
    
    balance = client.get_balance()
    amt, entry, unPnl = client.get_position("BTCUSDT")
    print(f"\n[Kết nối thành công] Số dư khả dụng Demo: {balance:,.2f} USDT")
    print(f"[Vị thế hiện tại] Đang giữ: {amt:+.4f} BTC | Giá vào: ${entry:,.1f} | Lãi/Lỗ tạm thời: {unPnl:+.2f} USDT")

    # Bảo vệ vị thế hiện tại nếu chưa có sẵn lệnh chờ TP/SL
    if amt > 0:
        orders = client.get("/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
        algo_orders = client.get("/fapi/v1/openAlgoOrders", {"symbol": "BTCUSDT"})
        if not orders and not algo_orders:
            tp = entry * 1.012
            sl = entry * 0.995
            print(f"[Bảo vệ vị thế] Đang cài sẵn TP/SL cho vị thế đang giữ: TP ${tp:,.1f} | SL ${sl:,.1f}")
            client.place_tp_sl("BTCUSDT", "SELL", abs(amt), tp, sl)

    # If user wants a test order immediately
    if test_buy_now:
        print("\n🚀 [KÍCH HOẠT LỆNH TEST NGAY BÂY GIỜ THEO YÊU CẦU]...")
        client.cancel_all_orders("BTCUSDT")
        cur_p = fetch_live_candles(limit=2).iloc[-1]["close"]
        qty = 0.001
        res = client.place_market_order("BTCUSDT", "BUY", qty)
        print(f" -> Lệnh Mua 0.001 BTC @ ~${cur_p:,.1f}: {res.get('status', res)}")
        tp = cur_p * 1.012
        sl = cur_p * 0.995
        r_tp, r_sl = client.place_tp_sl("BTCUSDT", "SELL", qty, tp, sl)
        print(f" -> Đã đặt sẵn TP Chốt lời @ ${tp:,.1f}: {r_tp.get('status', 'OK')}")
        print(f" -> Đã đặt sẵn SL Cắt lỗ  @ ${sl:,.1f}: {r_sl.get('status', 'OK')}")
        print("\n👉 Bác mở ngay tab web demo.binance.com xem: Lệnh đã xuất hiện ở mục Positions và Open Orders!")
        return

    # Train model on historical dataset
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base_dir, "data", "BTCUSDT_5m_50k.csv")
    print(f"\n[Đang nạp dữ liệu lịch sử & huấn luyện AI XGBoost]...")
    df_raw = pd.read_csv(data_path)
    df_feat, feature_cols = build_features(df_raw)
    
    model = BTC5mPredictor(model_type="gradient_boosting")
    # Chia train/validation: 80% train, 20% cuối làm validation (OOS)
    n_total = len(df_feat)
    n_train = int(n_total * 0.8)
    X_all = df_feat[feature_cols].to_numpy()
    y_all = df_feat["target_direction"].to_numpy()
    
    model.train(X_all[:n_train], y_all[:n_train])
    
    # Tính ngưỡng trên OOS data (không overfit)
    oos_probs = model.model.predict_proba(X_all[n_train:])[:, 1]
    th_long = np.percentile(oos_probs, 75.0)
    print(f"[Huấn luyện hoàn tất] Ngưỡng OOS kích hoạt LONG: Cửa tăng >= {th_long*100:.1f}%")
    print(f"[OOS Stats] Prob range: {oos_probs.min()*100:.1f}% - {oos_probs.max()*100:.1f}% | Median: {np.median(oos_probs)*100:.1f}%\n")
    print("[Bắt đầu lắng nghe thị trường thời gian thực - Bấm Ctrl+C để dừng]...")

    sys.stdout.reconfigure(line_buffering=True)
    last_amt = amt

    while True:
        try:
            df_live = fetch_live_candles(limit=60)
            df_live_feat, _ = build_features(df_live, is_train=False)
            
            if len(df_live_feat) > 0:
                last_bar = df_live_feat.iloc[-1]
                X_now = last_bar[feature_cols].to_numpy().reshape(1, -1)
                prob_up = model.model.predict_proba(X_now)[0, 1] * 100
                cur_price = last_bar["close"]
                cur_time = last_bar["datetime"]
                cur_hour = cur_time.hour
                
                is_session = (cur_hour >= 9) or (cur_hour <= 2)
                session_str = "🟢 PHIÊN CHIỀU/TỐI (SÔI ĐỘNG)" if is_session else "⚪ PHIÊN SÁNG (CHỜ NHỊP)"
                
                # Check current position on Binance Demo
                amt, entry, unPnl = client.get_position("BTCUSDT")
                if amt is None:
                    time.sleep(5)
                    continue
                
                # Detect position close event (TP or SL hit)
                if last_amt > 0 and amt == 0:
                    # Double check to prevent network glitch false positive
                    time.sleep(2)
                    c_amt, _, _ = client.get_position("BTCUSDT")
                    if c_amt == 0:
                        print(f"\n🔔 [{datetime.now().strftime('%H:%M:%S')}] VỊ THẾ VỪA ĐÓNG XONG (Đã chạm Chốt lời TP hoặc Cắt lỗ SL)!")
                        client.cancel_all_orders("BTCUSDT")
                        bal_now = client.get_balance()
                        print(f" -> Đã dọn sạch lệnh chờ dư thừa. Số dư ví mới: {bal_now:,.2f} USDT\n", flush=True)
                        last_amt = 0
                else:
                    last_amt = amt

                pos_status = f"Đang giữ {amt:+.4f} BTC (Lãi: {unPnl:+.2f} USDT)" if amt != 0 else "Chưa có vị thế"
                action = "ĐỨNG NGOÀI (Chờ điểm đẹp)"
                
                # If no position, evaluate entry
                if amt == 0 and is_session:
                    if prob_up >= th_long * 100:
                        action = "⚡ KÍCH HOẠT LỆNH MUA LONG!"
                        qty = 0.001
                        print(f"\n[{cur_time.strftime('%H:%M:%S')}] 🚀 {action} @ ${cur_price:,.1f}", flush=True)
                        client.cancel_all_orders("BTCUSDT")
                        client.place_market_order("BTCUSDT", "BUY", qty)
                        tp = cur_price * 1.012
                        sl = cur_price * 0.995
                        client.place_tp_sl("BTCUSDT", "SELL", qty, tp, sl)
                        print(f" -> Đã gửi lệnh lên Binance Demo: TP ${tp:,.1f} | SL ${sl:,.1f}\n", flush=True)
                        amt, entry, unPnl = client.get_position("BTCUSDT")
                        last_amt = amt
                        
                print(f"[{cur_time.strftime('%H:%M:%S')}] {session_str} | BTC: ${cur_price:,.1f} | Cửa Tăng: {prob_up:4.1f}% | Vị thế: {pos_status}", flush=True)
            
            time.sleep(30)
        except KeyboardInterrupt:
            print("\n[Đã dừng bot]", flush=True)
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [Cảnh báo mạng] Thử kết nối lại... ({e})", flush=True)
            time.sleep(10)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-order", action="store_true", help="Bắn ngay 1 lệnh test vào tài khoản Demo để kiểm tra")
    args = parser.parse_args()
    run_live_bot(test_buy_now=args.test_order)
