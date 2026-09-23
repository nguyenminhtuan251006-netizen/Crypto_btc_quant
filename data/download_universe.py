"""
Download 50,000 bars of 5m candle data for 12 additional altcoins from Binance Futures.
Used to expand the AFCX cross-sectional universe from 3 coins to 15 coins.
"""
import os
import sys

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_dir)
from data.download_btc_5m import download_btc_5m

ALTCOINS = [
    "ARBUSDT", "OPUSDT", "SUIUSDT", "DOGEUSDT",
    "AVAXUSDT", "LINKUSDT", "ADAUSDT", "XRPUSDT",
    "BNBUSDT", "DOTUSDT", "NEARUSDT", "APTUSDT",
]

TARGET_BARS = 50000
OUTPUT_DIR = os.path.join(base_dir, "data")

if __name__ == "__main__":
    print(f"=== Downloading {TARGET_BARS} bars x {len(ALTCOINS)} altcoins ===")
    for sym in ALTCOINS:
        out_path = os.path.join(OUTPUT_DIR, f"{sym}_5m_50k.csv")
        if os.path.exists(out_path):
            print(f"[SKIP] {sym} already exists at {out_path}")
            continue
        try:
            download_btc_5m(symbol=sym, target_bars=TARGET_BARS, output_path=out_path)
        except Exception as e:
            print(f"[ERROR] {sym}: {e}")
    print("=== ALL DONE ===")
