"""
Download fresh, unseen 5m candle data for Chien Thuat 5 backtesting.
Universe: BTCUSDT (Regime) + 15 Micro-Capital Altcoins
Coverage: ~6,000 bars (~21 days) directly leading up to present moment.
"""
import os
import sys
import time
import requests
import pandas as pd

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(base_dir, "data", "unseen_test")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT", "SOLUSDT", "ARBUSDT", "OPUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT", "LINKUSDT",
    "NEARUSDT", "APTUSDT", "INJUSDT", "BNBUSDT", "LTCUSDT"
]

TARGET_BARS = 6000  # ~21 days of 5m candles

def download_symbol(symbol: str, target_bars: int = TARGET_BARS):
    out_file = os.path.join(OUTPUT_DIR, f"{symbol}_5m_unseen.csv")
    print(f"📥 [{symbol}] Downloading {target_bars} bars...")
    base_url = "https://fapi.binance.com/fapi/v1/klines"
    
    all_data = []
    end_time = None
    fetched = 0
    
    while fetched < target_bars:
        limit = min(1500, target_bars - fetched)
        params = {"symbol": symbol, "interval": "5m", "limit": limit}
        if end_time:
            params["endTime"] = end_time
            
        res = requests.get(base_url, params=params, timeout=10)
        if res.status_code != 200:
            print(f"  ❌ Error {symbol}: {res.status_code}")
            break
        raw = res.json()
        if not raw:
            break
            
        all_data = raw + all_data
        fetched += len(raw)
        end_time = raw[0][0] - 1
        time.sleep(0.1)
        
    if not all_data:
        print(f"  ❌ No data for {symbol}")
        return None
        
    df = pd.DataFrame(all_data).iloc[:, [0, 1, 2, 3, 4, 5]]
    df.columns = ["datetime", "open", "high", "low", "close", "volume"]
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
        
    df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    df.to_csv(out_file, index=False)
    print(f"  ✅ Saved {len(df)} bars: {df['datetime'].min()} → {df['datetime'].max()}")
    return df

if __name__ == "__main__":
    print(f"=== DOWNLOADING UNSEEN DATASET: {len(SYMBOLS)} COINS x {TARGET_BARS} BARS ===")
    for sym in SYMBOLS:
        download_symbol(sym)
    print("=== DOWNLOAD COMPLETED ===")
