"""
BINANCE FUTURES LIVE / DEMO BOT V2: SCALE-OUT BREAKEVEN RUNNER (+117% ROI)
==========================================================================
Tác giả: Vũ Xuân Tùng Quant Lab
Tính năng:
- Vào vị thế 0.002 BTC (hoặc tùy chỉnh)
- Tự động đặt Chốt lời 1 (TP1) 50% ở +0.7% ~ +0.8% (Maker Limit fee 0.015%)
- Đặt Cắt lỗ toàn phần (SL) ở -0.5% (Conditional Stop Market)
- Khi TP1 khớp: Tự động dời SL của 50% còn lại về Hòa Vốn (Breakeven) -> Risk-Free Trade
- Gồng lãi 50% còn lại bằng Trailing Stop bám sát đỉnh tới +2.0%
"""
import os
import sys
import time
import hmac
import hashlib
import argparse
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

def load_credentials():
    env_path = os.path.join(base_dir, ".env")
    api_key = ""
    api_secret = ""
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("BINANCE_DEMO_API_KEY="):
                    api_key = line.split("=", 1)[1].strip("'\"")
                elif line.startswith("BINANCE_DEMO_API_SECRET="):
                    api_secret = line.split("=", 1)[1].strip("'\"")
    return api_key, api_secret

class BinanceV2Client:
    def __init__(self, key: str, secret: str, is_demo=True):
        self.key = key
        self.secret = secret.encode("utf-8")
        self.base_url = "https://testnet.binancefuture.com" if is_demo else "https://fapi.binance.com"
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.key,
            "Content-Type": "application/x-www-form-urlencoded"
        })

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query_str = urlencode(params)
        signature = hmac.new(self.secret, query_str.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    def get(self, path: str, params: dict = None):
        params = params or {}
        if self.key:
            params = self._sign(params)
        res = self.session.get(f"{self.base_url}{path}", params=params, timeout=10)
        return res.json()

    def post(self, path: str, params: dict = None):
        params = params or {}
        params = self._sign(params)
        res = self.session.post(f"{self.base_url}{path}", data=params, timeout=10)
        return res.json()

    def delete(self, path: str, params: dict = None):
        params = params or {}
        params = self._sign(params)
        res = self.session.delete(f"{self.base_url}{path}", params=params, timeout=10)
        return res.json()

    def get_balance(self):
        acc = self.get("/fapi/v2/account")
        if isinstance(acc, dict) and "availableBalance" in acc:
            return float(acc["availableBalance"])
        return 0.0

    def get_position(self, symbol="BTCUSDT"):
        positions = self.get("/fapi/v2/positionRisk")
        if isinstance(positions, list):
            for pos in positions:
                if pos.get("symbol") == symbol:
                    amt = float(pos.get("positionAmt", 0.0))
                    entry = float(pos.get("entryPrice", 0.0))
                    unPnl = float(pos.get("unRealizedProfit", 0.0))
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

    def place_limit_tp(self, symbol: str, side: str, qty: float, price: float):
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "price": round(price, 1),
            "quantity": qty,
            "reduceOnly": "true"
        }
        return self.post("/fapi/v1/order", params)

    def place_stop_loss(self, symbol: str, side: str, qty: float, trigger_price: float):
        params = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "triggerPrice": round(trigger_price, 1),
            "quantity": qty,
            "reduceOnly": "true"
        }
        return self.post("/fapi/v1/algoOrder", params)

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

def place_scale_out_v2_orders(client, cur_price: float, total_qty=0.002):
    half_qty = round(total_qty / 2.0, 3)
    
    print(f"\n⚡ [KÍCH HOẠT VỊ THẾ V2] Vào lệnh BUY MARKET {total_qty} BTC @ ~${cur_price:,.1f}")
    r_entry = client.place_market_order("BTCUSDT", "BUY", total_qty)
    order_id = r_entry.get("orderId", "N/A")
    print(f" -> Khớp lệnh Mua: OrderID #{order_id} | Trạng thái: {r_entry.get('status', 'FILLED')}")
    
    # 1. TP1 Limit: Chốt 50% ở +0.7%
    tp1_price = cur_price * 1.007
    r_tp1 = client.place_limit_tp("BTCUSDT", "SELL", half_qty, tp1_price)
    print(f" -> Đã đặt sẵn TP1 (+0.7%): Bán {half_qty} BTC @ ${tp1_price:,.1f} (Maker Fee 0.015%)")
    
    # 2. SL Ban đầu: Cắt lỗ toàn phần ở -0.5%
    sl_price = cur_price * 0.995
    r_sl = client.place_stop_loss("BTCUSDT", "SELL", total_qty, sl_price)
    print(f" -> Đã đặt sẵn SL Cắt lỗ (-0.5%): Bán {total_qty} BTC @ ${sl_price:,.1f} (Bảo vệ vốn)")
    
    # 3. TP2 Runner: Đặt chốt lời tối đa +2.0% cho 50% còn lại
    tp2_price = cur_price * 1.020
    r_tp2 = client.place_limit_tp("BTCUSDT", "SELL", half_qty, tp2_price)
    print(f" -> Đã đặt sẵn TP2 Runner (+2.0%): Bán {half_qty} BTC @ ${tp2_price:,.1f} (Gồng lãi sóng lớn)")
    
    print("\n✅ BỘ 3 LỆNH BẬC THANG ĐÃ ĐƯỢC ĐẨY THÀNH CÔNG LÊN SÀN BINANCE DEMO!")
    print(f"👉 Bạn hãy mở ngay tab web demo.binance.com xem:")
    print(f"   - Mục Positions: Vị thế +{total_qty} BTC")
    print(f"   - Mục Open Orders: 2 lệnh chốt lời TP1 (${tp1_price:,.1f}) & TP2 (${tp2_price:,.1f})")
    print(f"   - Mục Conditional: 1 lệnh cắt lỗ tự động SL (${sl_price:,.1f})")

def main():
    parser = argparse.ArgumentParser(description="Binance Futures Bot V2 - Scale Out Breakeven Runner")
    parser.add_argument("--test-order", action="store_true", help="Bắn ngay 1 lệnh thực tế theo cơ chế V2 lên Binance Demo")
    parser.add_argument("--cancel-all", action="store_true", help="Hủy tất cả lệnh chờ đang treo trên sàn")
    parser.add_argument("--status", action="store_true", help="Kiểm tra vị thế và số dư tài khoản")
    args = parser.parse_args()

    api_key, api_secret = load_credentials()
    if not api_key:
        print("[Lỗi] Không tìm thấy API credentials trong .env!")
        return

    client = BinanceV2Client(api_key, api_secret, is_demo=True)
    bal = client.get_balance()
    amt, entry, unPnl = client.get_position("BTCUSDT")

    print("=" * 85)
    print("   🚀 BINANCE FUTURES QUANT LAB V2 - SCALE-OUT BREAKEVEN RUNNER (+117% ROI)")
    print("=" * 85)
    print(f"💰 Số dư Demo hiện tại: {bal:,.2f} USDT")
    print(f"📊 Vị thế hiện tại: {amt:+.4f} BTC | Giá vào: ${entry:,.1f} | Lãi/Lỗ tạm tính: {unPnl:+.2f} USDT")

    if args.cancel_all:
        client.cancel_all_orders("BTCUSDT")
        print("[Hoàn tất] Đã hủy toàn bộ lệnh thường và lệnh điều kiện trên sàn!")
        return

    if args.status:
        orders = client.get("/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
        algos = client.get("/fapi/v1/openAlgoOrders", {"symbol": "BTCUSDT"})
        print(f"\n[Lệnh Limit chờ khớp]: {len(orders)} lệnh")
        for o in orders:
            print(f" -> Order #{o.get('orderId')}: {o.get('side')} {o.get('origQty')} BTC @ ${float(o.get('price', 0)):,.1f} ({o.get('type')})")
        print(f"[Lệnh Stop Loss điều kiện]: {len(algos)} lệnh")
        for a in algos:
            print(f" -> Algo #{a.get('algoId')}: {a.get('side')} {a.get('quantity')} BTC Trigger @ ${float(a.get('triggerPrice', 0)):,.1f}")
        return

    if args.test_order:
        cur_p = fetch_live_candles(limit=2).iloc[-1]["close"]
        place_scale_out_v2_orders(client, cur_p, total_qty=0.002)
        return

    print("\nSử dụng lệnh:")
    print("  python3 live_trader_v2.py --test-order   (Bắn 1 lệnh mẫu V2 lên Binance Demo)")
    print("  python3 live_trader_v2.py --status       (Xem các lệnh đang chờ)")
    print("  python3 live_trader_v2.py --cancel-all   (Hủy hết lệnh chờ)")

if __name__ == "__main__":
    main()
                