"""
Download 1 Year (~105,000 bars) of 5m candle data from Binance Futures.
Covers ~365 days across major liquid assets:
BTC, ETH, SOL, DOGE, BNB, XRP, ADA, AVAX, LINK, NEAR, DOT, OP, ARB
"""
import os
import sys
import time
import requests
import pandas as pd

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)

TARGET_BARS = 105000  # 365 days * 288 bars/day = 105,120 bars
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "DOGEUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "NEARUSDT", "DOTUSDT", "ARBUSDT"
]

OUTPUT_DIR = os.path.join(base_dir, "data", "1year")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def download_symbol_1year(symbol: str, target_bars: int = TARGET_BARS):
    out_path = os.path.join(OUTPUT_DIR, f"{symbol}_5m_1y.csv")
    if os.path.exists(out_path):
        df_exist = pd.read_csv(out_path)
        if len(df_exist) >= target_bars * 0.95:
            print(f"[SKIP] {symbol} already exists with {len(df_exist):,} bars.")
            return

    print(f"\n[Binance] Downloading {target_bars:,} bars (~1 year) for {symbol}...")
    base_url = "https://fapi.binance.com/fapi/v1/klines"
    
    all_data = []
    end_time = None
    fetched = 0
    
    while fetched < target_bars:
        batch_limit = min(1500, target_bars - fetched)
        params = {
            "symbol": symbol.upper(),
            "interval": "5m",
            "limit": batch_limit
        }
        if end_time:
            params["endTime"] = end_time
            
        try:
            r = requests.get(base_url, params=params, timeout=10)
            if r.status_code != 200:
                print(f"\n[ERROR] {symbol}: {r.text}")
                break
                
            raw = r.json()
            if not raw or not isinstance(raw, list):
                break
                
            all_data = raw + all_data
            fetched += len(raw)
            end_time = raw[0][0] - 1
            pct = (fetched / target_bars) * 100
            print(f"  → {symbol}: {fetched:,}/{target_bars:,} bars ({pct:.1f}%)...", end="\r", flush=True)
            time.sleep(0.12)
        except Exception as e:
            print(f"\n[RETRY] {e}")
            time.sleep(1.0)
            
    if all_data:
        df = pd.DataFrame(all_data)
        df = df.iloc[:, [0, 1, 2, 3, 4, 5]]
        df.columns = ["datetime", "open", "high", "low", "close", "volume"]
        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        df.to_csv(out_path, index=False)
        start_d = str(df["datetime"].min())[:10]
        end_d = str(df["datetime"].max())[:10]
        print(f"\n  ✅ Đã lưu {symbol}: {len(df):,} nến ({start_d} → {end_d})")

if __name__ == "__main__":
    print(f"=== TẢI DỮ LIỆU 1 NĂM (105,000 NẾN 5M) CHO {len(SYMBOLS)} COINS ===")
    for sym in SYMBOLS:
        download_symbol_1year(sym)
    print("\n=== HOÀN TẤT TOÀN BỘ 1 NĂM DỮ LIỆU ===")
