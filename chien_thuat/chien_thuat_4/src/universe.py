"""
AFCX Trading Universe Manager
=============================
Manages the liquid Binance USDT-M Perpetual Futures universe (Section 5).
Ensures minimum listing age, liquidity filters, and symbol metadata (precisions, limits).
"""
import time
import requests
from typing import List, Dict, Any, Optional

# Core default liquid universe (Top 20 high-volume perpetual contracts on Binance)
DEFAULT_UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
    "NEARUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "ATOMUSDT",
    "INJUSDT",
    "RENDERUSDT",
    "PEPEUSDT",
]

# Static fallback metadata if network call fails
FALLBACK_METADATA: Dict[str, Dict[str, Any]] = {
    "BTCUSDT": {"price_precision": 1, "qty_precision": 3, "min_qty": 0.001, "step_size": 0.001, "tick_size": 0.1},
    "ETHUSDT": {"price_precision": 2, "qty_precision": 2, "min_qty": 0.01, "step_size": 0.01, "tick_size": 0.01},
    "SOLUSDT": {"price_precision": 2, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.01},
    "BNBUSDT": {"price_precision": 2, "qty_precision": 2, "min_qty": 0.01, "step_size": 0.01, "tick_size": 0.01},
    "DOGEUSDT": {"price_precision": 5, "qty_precision": 0, "min_qty": 1.0, "step_size": 1.0, "tick_size": 0.00001},
    "XRPUSDT": {"price_precision": 4, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.0001},
    "ADAUSDT": {"price_precision": 4, "qty_precision": 0, "min_qty": 1.0, "step_size": 1.0, "tick_size": 0.0001},
    "AVAXUSDT": {"price_precision": 3, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.001},
    "LINKUSDT": {"price_precision": 3, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.001},
    "SUIUSDT": {"price_precision": 4, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.0001},
    "NEARUSDT": {"price_precision": 3, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.001},
    "APTUSDT": {"price_precision": 3, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.001},
    "ARBUSDT": {"price_precision": 4, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.0001},
    "OPUSDT": {"price_precision": 4, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.0001},
    "DOTUSDT": {"price_precision": 3, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.001},
    "LTCUSDT": {"price_precision": 2, "qty_precision": 3, "min_qty": 0.001, "step_size": 0.001, "tick_size": 0.01},
    "ATOMUSDT": {"price_precision": 3, "qty_precision": 2, "min_qty": 0.01, "step_size": 0.01, "tick_size": 0.001},
    "INJUSDT": {"price_precision": 3, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.001},
    "RENDERUSDT": {"price_precision": 3, "qty_precision": 1, "min_qty": 0.1, "step_size": 0.1, "tick_size": 0.001},
    "PEPEUSDT": {"price_precision": 7, "qty_precision": 0, "min_qty": 1000.0, "step_size": 1000.0, "tick_size": 0.0000001},
}


class UniverseManager:
    """Manages Binance Perpetual trading universe, limits, and dynamic updates."""

    def __init__(self, symbols: Optional[List[str]] = None):
        self.symbols = symbols or list(DEFAULT_UNIVERSE)
        self.metadata_cache: Dict[str, Dict[str, Any]] = dict(FALLBACK_METADATA)
        self.last_metadata_refresh = 0.0

    def refresh_exchange_metadata(self, base_url: str = "https://fapi.binance.com"):
        """Fetch live precision and filter rules from Binance exchangeInfo."""
        now = time.time()
        if now - self.last_metadata_refresh < 3600:  # Cache for 1 hour
            return

        try:
            r = requests.get(f"{base_url}/fapi/v1/exchangeInfo", timeout=10)
            if r.status_code == 200:
                data = r.json()
                for s in data.get("symbols", []):
                    sym = s.get("symbol")
                    if sym in self.symbols:
                        price_prec = int(s.get("pricePrecision", 2))
                        qty_prec = int(s.get("quantityPrecision", 2))
                        step_size = 0.001
                        min_qty = 0.001
                        tick_size = 0.01

                        for f in s.get("filters", []):
                            if f.get("filterType") == "LOT_SIZE":
                                step_size = float(f.get("stepSize", 0.001))
                                min_qty = float(f.get("minQty", 0.001))
                            elif f.get("filterType") == "PRICE_FILTER":
                                tick_size = float(f.get("tickSize", 0.01))

                        self.metadata_cache[sym] = {
                            "price_precision": price_prec,
                            "qty_precision": qty_prec,
                            "min_qty": min_qty,
                            "step_size": step_size,
                            "tick_size": tick_size,
                        }
                self.last_metadata_refresh = now
        except Exception:
            pass

    def get_symbol_metadata(self, symbol: str) -> Dict[str, Any]:
        """Return precision, step size, and min qty for a given symbol."""
        return self.metadata_cache.get(
            symbol,
            {"price_precision": 2, "qty_precision": 2, "min_qty": 0.01, "step_size": 0.01, "tick_size": 0.01},
        )

    def quantize_price(self, symbol: str, price: float) -> float:
        """Round price to the symbol's exact tick precision."""
        meta = self.get_symbol_metadata(symbol)
        prec = meta.get("price_precision", 2)
        return round(price, prec)

    def quantize_qty(self, symbol: str, raw_qty: float) -> float:
        """Quantize order quantity to step size and ensure it meets min_qty."""
        meta = self.get_symbol_metadata(symbol)
        min_qty = meta.get("min_qty", 0.001)
        prec = meta.get("qty_precision", 3)
        if prec == 0:
            qty = max(float(int(raw_qty)), min_qty)
        else:
            qty = max(round(raw_qty, prec), min_qty)
        return qty
