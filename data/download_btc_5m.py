"""
Binance Futures 5m Klines Downloader
Downloads historical 5-minute candles directly from Binance Futures public API.
"""
import os
import sys
import time
import requests
import pandas as pd
from datetime import datetime

def download_btc_5m(symbol: str = "BTCUSDT", target_bars: int = 10000, output_path: str = "") -> pd.DataFrame:
    print(f"[Binance] Downloading {target_bars} bars of {symbol} (5m)...")
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
            
        r = requests.get(base_url, params=params, timeout=10)
        if r.status_code != 200:
            print(f"Error fetching Binance: {r.text}")
            break
            
        raw = r.json()
        if not raw:
            break
            
        all_data = raw + all_data
        fetched += len(raw)
        end_time = raw[0][0] - 1
        print(f"-> Fetched {fetched}/{target_bars} bars...", end="\r", flush=True)
        time.sleep(0.15)
        
    print(f"\n[Success] Downloaded total {len(all_data)} raw bars.")
    
    # Columns: [open_time, open, high, low, close, volume, ...]
    df = pd.DataFrame(all_data)
    df = df.iloc[:, [0, 1, 2, 3, 4, 5]]
    df.columns = ["datetime", "open", "high", "low", "close", "volume"]
    
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
        
    df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"[Saved] Saved to: {output_path}")
        
    return df

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(base_dir, "BTCUSDT_5m.csv")
    download_btc_5m(symbol="BTCUSDT", target_bars=10000, output_path=out_file)
