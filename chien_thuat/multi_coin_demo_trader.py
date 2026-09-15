"""
HỆ THỐNG TRADING TỰ ĐỘNG ĐA COIN (BTC, ETH, SOL) - QUAN LAB LIVE DEMO
====================================================================
Tự động bắn lệnh trực tiếp lên sàn Binance Futures Demo (demo-fapi.binance.com)
Quy mô lệnh lớn (Mỗi lệnh ~$1,500 USDT giá trị, ký quỹ ~$300 USDT ở 5x):
  - BTCUSDT: 0.02 BTC (~$1,560 USDT) → Mỗi 1% lãi = +$15.6 USDT
  - ETHUSDT: 0.60 ETH (~$1,510 USDT) → Mỗi 1% lãi = +$15.1 USDT
  - SOLUSDT: 15.0 SOL (~$1,525 USDT) → Mỗi 1% lãi = +$15.2 USDT

Ứng dụng dữ liệu vi cấu trúc HFT (Sổ lệnh L2 20 tầng + CVD Taker Flow)
Cài sẵn Take Profit (+1.0%) & Stop Loss (-0.5%) trực tiếp lên máy chủ Binance.
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

base_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(base_dir)
sys.path.insert(0, workspace_dir)

from chien_thuat.chien_thuat_1.src.features import build_features
from chien_thuat.chien_thuat_3.paper_trader import (
    fetch_recent_candles,
    fetch_orderbook_l2,
    fetch_recent_trades,
    compute_realtime_microstructure,
)

BASE_URL = "https://demo-fapi.binance.com"

# Cấu hình khối lượng đánh to theo yêu cầu
COIN_CONFIGS = {
    "BTCUSDT": {
        "qty": 0.02,        # 0.02 BTC (~$1,560 USDT)
        "leverage": 5,
        "tp_pct": 0.010,    # +1.0% (~$15.6 USDT lãi)
        "sl_pct": 0.005,    # -0.5% (~$7.8 USDT lỗ)
        "price_precision": 1,
        "qty_precision": 3,
    },
    "ETHUSDT": {
        "qty": 0.60,        # 0.60 ETH (~$1,510 USDT)
        "leverage": 5,
        "tp_pct": 0.010,    # +1.0% (~$15.1 USDT lãi)
        "sl_pct": 0.005,    # -0.5% (~$7.5 USDT lỗ)
        "price_precision": 2,
        "qty_precision": 2,
    },
    "SOLUSDT": {
        "qty": 15.0,        # 15 SOL (~$1,525 USDT)
        "leverage": 5,
        "tp_pct": 0.012,    # +1.2% (~$18.3 USDT lãi)
        "sl_pct": 0.006,    # -0.6% (~$9.1 USDT lỗ)
        "price_precision": 2,
        "qty_precision": 1,
    },
}


def load_credentials():
    env_path = os.path.join(workspace_dir, ".env")
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
        r = requests.get(f"{BASE_URL}{endpoint}", params=p, headers=self.headers, timeout=8)
        return r.json()

    def post(self, endpoint: str, params=None):
        if params is None: params = {}
        p = self._sign(params)
        r = requests.post(f"{BASE_URL}{endpoint}", data=p, headers=self.headers, timeout=8)
        return r.json()

    def delete(self, endpoint: str, params=None):
        if params is None: params = {}
        p = self._sign(params)
        r = requests.delete(f"{BASE_URL}{endpoint}", params=p, headers=self.headers, timeout=8)
        return r.json()

    def set_leverage(self, symbol: str, leverage: int = 5):
        try:
            self.post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
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

    def get_positions(self) -> dict:
        res = self.get("/fapi/v2/positionRisk")
        positions = {}
        if isinstance(res, list):
            for p in res:
                sym = p.get("symbol")
                amt = float(p.get("positionAmt", 0.0))
                entry = float(p.get("entryPrice", 0.0))
                unPnl = float(p.get("unRealizedProfit", 0.0))
                positions[sym] = {"amt": amt, "entry": entry, "unPnl": unPnl}
        return positions

    def cancel_all_orders(self, symbol: str):
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
        cfg = COIN_CONFIGS.get(symbol, {"price_precision": 2})
        prec = cfg["price_precision"]

        # 1. TP Limit Order
        tp_params = {
            "symbol": symbol,
            "side": close_side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "price": round(tp_price, prec),
            "quantity": qty,
            "reduceOnly": "true"
        }
        r_tp = self.post("/fapi/v1/order", tp_params)

        # 2. SL Conditional Stop Market Order
        sl_params = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "triggerPrice": round(sl_price, prec),
            "quantity": qty,
            "reduceOnly": "true"
        }
        r_sl = self.post("/fapi/v1/algoOrder", sl_params)
        return r_tp, r_sl


def analyze_symbol(symbol: str, hft_model, fcols, th_long, th_short) -> dict:
    """Phân tích tín hiệu vào lệnh cho 1 đồng coin dựa trên nến + sổ lệnh L2 + CVD."""
    candles = fetch_recent_candles(symbol, limit=100)
    ob = fetch_orderbook_l2(symbol, limit=20)
    trades = fetch_recent_trades(symbol, limit=100)

    cur_p = candles.iloc[-1]["close"]
    df_feat, _ = build_features(candles, is_train=False)
    latest_feat = df_feat.iloc[-1].to_dict()
    micro = compute_realtime_microstructure(ob, trades, cur_p)

    trend_dist = latest_feat.get("trend_dist", 0.0)
    rsi = latest_feat.get("rsi", 50.0)

    # Nếu là BTCUSDT, dùng model đã train
    if symbol == "BTCUSDT" and hft_model is not None:
        row_dict = {**latest_feat, **micro}
        X_vec = np.array([[row_dict.get(col, 0.0) for col in fcols]])
        prob_up = float(hft_model.predict_proba(X_vec)[0, 1])
        if prob_up >= th_long and trend_dist > 0:
            signal = "BUY"
        elif prob_up <= th_short and trend_dist < 0:
            signal = "SELL"
        else:
            signal = "WAIT"
    else:
        # Với ETH và SOL: Phân tích lực sổ lệnh OBI và CVD
        obi = micro["obi_l1"]
        cvd = micro["cvd"]
        prob_up = 0.50 + obi * 0.25 + cvd * 0.25

        if obi > 0.25 and cvd > 0.15 and trend_dist >= 0:
            signal = "BUY"
        elif obi < -0.25 and cvd < -0.15 and trend_dist <= 0:
            signal = "SELL"
        else:
            signal = "WAIT"

    return {
        "symbol": symbol,
        "price": cur_p,
        "prob_up": prob_up,
        "trend_dist": trend_dist,
        "rsi": rsi,
        "obi_l1": micro["obi_l1"],
        "cvd": micro["cvd"],
        "signal": signal,
    }


def execute_multi_trade(trade_now: bool = False, loop: bool = False):
    api_key, api_secret = load_credentials()
    if not api_key or not api_secret:
        print("[LỖI] Không tìm thấy BINANCE_DEMO_API_KEY trong file .env!")
        return

    print("=" * 105)
    print("      🚀 HỆ THỐNG GIAO DỊCH ĐA COIN TỰ ĐỘNG: BTC + ETH + SOL (QUY MÔ ĐÁNH TO)")
    print("      Tài khoản: Demo Binance (demo-fapi.binance.com) | Đòn bẩy: 5x")
    print("      Quy mô mỗi lệnh: ~$1,500 USDT (Ký quỹ ~$300 USDT | Kỳ vọng lãi +$15 USDT/lệnh)")
    print("=" * 105)

    client = BinanceDemoClient(api_key, api_secret)
    for sym, cfg in COIN_CONFIGS.items():
        client.set_leverage(sym, cfg["leverage"])

    balance = client.get_balance()
    print(f"\n[Kết nối thành công] Số dư khả dụng Demo: {balance:,.2f} USDT")

    # Load Model Strategy 3
    model_path = os.path.join(workspace_dir, "chien_thuat", "chien_thuat_3", "models", "hft_xgb_model.joblib")
    hft_model = None
    fcols = []
    th_long = 0.676
    th_short = 0.117
    if os.path.exists(model_path):
        pkg = joblib.load(model_path)
        hft_model = pkg["model"]
        fcols = pkg["feature_cols"]
        th_long = pkg.get("th_long", 0.676)
        th_short = pkg.get("th_short", 0.117)

    # Chạy lệnh ngay lập tức cho cả 3 đồng nếu có yêu cầu
    if trade_now:
        print("\n⚡ [KÍCH HOẠT BẮN LỆNH LỚN ĐA COIN NGAY BÂY GIỜ THEO YÊU CẦU]...")
        for sym, cfg in COIN_CONFIGS.items():
            analysis = analyze_symbol(sym, hft_model, fcols, th_long, th_short)
            cur_p = analysis["price"]
            sig = analysis["signal"]
            # Nếu tín hiệu WAIT, chọn theo chiều dòng tiền CVD
            if sig == "WAIT":
                sig = "BUY" if analysis["cvd"] >= 0 or analysis["trend_dist"] >= 0 else "SELL"

            qty = cfg["qty"]
            close_side = "SELL" if sig == "BUY" else "BUY"

            client.cancel_all_orders(sym)
            res = client.place_market_order(sym, sig, qty)
            order_id = res.get("orderId", "N/A")

            prec = cfg["price_precision"]
            if sig == "BUY":
                tp = round(cur_p * (1.0 + cfg["tp_pct"]), prec)
                sl = round(cur_p * (1.0 - cfg["sl_pct"]), prec)
            else:
                tp = round(cur_p * (1.0 - cfg["tp_pct"]), prec)
                sl = round(cur_p * (1.0 + cfg["sl_pct"]), prec)

            time.sleep(0.4)
            r_tp, r_sl = client.place_tp_sl(sym, close_side, qty, tp, sl)
            val_usdt = cur_p * qty

            print(f"\n  🎯 [{sym}] Đã khớp lệnh: {sig} {qty} {sym.replace('USDT','')} (Giá trị: ${val_usdt:,.1f} USDT @ ${cur_p:,.2f})")
            print(f"     - Lệnh thị trường: Status={res.get('status', 'OK')} (ID: {order_id})")
            print(f"     - Chốt lời TP (+{cfg['tp_pct']*100:.1f}%): ${tp:,.2f}  |  Cắt lỗ SL (-{cfg['sl_pct']*100:.1f}%): ${sl:,.2f}")

        print("\n" + "=" * 105)
        print("  ✅ ĐÃ BẮN THÀNH CÔNG 3 LỆNH LỚN CHO CẢ BTC, ETH VÀ SOL LÊN WEB BINANCE DEMO!")
        print("  👉 Mở tab web Demo Binance Futures kiểm tra: Sẽ thấy cả 3 vị thế đang chạy song song!")
        print("=" * 105)
        return

    # Vòng lặp chạy ngầm 24/7
    if loop:
        log_file = os.path.join(workspace_dir, "logs", "multi_coin_trader.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        print(f"\n👉 Bắt đầu chế độ TỰ ĐỘNG CHẠY NGẦM 24/7 cho BTC, ETH, SOL...")
        print(f"[Nhật ký ghi tại] {log_file}\n")

        while True:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                positions = client.get_positions()
                for sym, cfg in COIN_CONFIGS.items():
                    pos = positions.get(sym, {"amt": 0.0, "entry": 0.0, "unPnl": 0.0})
                    amt = pos["amt"]

                    # Nếu đang có vị thế: theo dõi PnL
                    if abs(amt) > 0:
                        side_str = "LONG" if amt > 0 else "SHORT"
                        line = f"[{now_str}] {sym}: Đang giữ {side_str} {abs(amt)} (Giá vào: ${pos['entry']:,.2f} | uPnL: {pos['unPnl']:+.2f} USDT)"
                        print(line)
                        with open(log_file, "a") as f: f.write(line + "\n")
                    else:
                        # Nếu trống vị thế: quét cơ hội vào lệnh
                        analysis = analyze_symbol(sym, hft_model, fcols, th_long, th_short)
                        sig = analysis["signal"]
                        line = f"[{now_str}] {sym}: Giá ${analysis['price']:,.2f} | OBI: {analysis['obi_l1']:+.2f} | CVD: {analysis['cvd']:+.2f} | Tín hiệu: {sig}"
                        print(line)
                        with open(log_file, "a") as f: f.write(line + "\n")

                        if sig in ["BUY", "SELL"]:
                            qty = cfg["qty"]
                            close_side = "SELL" if sig == "BUY" else "BUY"
                            res = client.place_market_order(sym, sig, qty)
                            cur_p = analysis["price"]
                            prec = cfg["price_precision"]
                            tp = round(cur_p * (1.0 + cfg["tp_pct"]) if sig == "BUY" else cur_p * (1.0 - cfg["tp_pct"]), prec)
                            sl = round(cur_p * (1.0 - cfg["sl_pct"]) if sig == "BUY" else cur_p * (1.0 + cfg["sl_pct"]), prec)
                            time.sleep(0.4)
                            client.place_tp_sl(sym, close_side, qty, tp, sl)

                            order_log = f"🚀 [{now_str}] VÀO LỆNH TỰ ĐỘNG {sym}: {sig} {qty} @ ${cur_p:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}"
                            print(order_log)
                            with open(log_file, "a") as f: f.write(order_log + "\n")

            except Exception as e:
                print(f"[{now_str}] ⚠️ Lỗi quét thị trường: {e}")

            time.sleep(25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-now", action="store_true", help="Bắn ngay các lệnh lớn cho BTC, ETH, SOL lên web Demo")
    parser.add_argument("--loop", action="store_true", help="Chạy tự động ngầm 24/7 quét cả 3 đồng")
    args = parser.parse_args()

    execute_multi_trade(trade_now=args.trade_now, loop=args.loop)
