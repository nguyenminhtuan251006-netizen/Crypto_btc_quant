"""
AFCX Flow & Microstructure Feature Engine
==========================================
Implements Sections 8 & 9 of the AFCX Specification:
Extracts and normalizes order flow, momentum, OI, order book, funding, and basis features.
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional


def winsorize_z(z_val: float, limit: float = 3.0) -> float:
    """Clamps Z-score to [-limit, +limit] (Section 8)."""
    return float(np.clip(z_val, -limit, limit))


def normalize_score_100(abs_z_score: float) -> int:
    """Convert absolute Z-score to intuitive 0-100 scale using sigmoid mapping.

    Mapping landmarks:
        |Z| = 0.0  -> 50  (neutral)
        |Z| = 1.25 -> ~75 (LIQUID threshold)
        |Z| = 1.55 -> ~80 (ASIA/RANGE threshold)
        |Z| = 2.0  -> ~88
        |Z| >= 3.0 -> ~95 (cap)
    """
    # Sigmoid-like: score = 50 + 50 * tanh(k * |Z|),  k calibrated so |Z|=1.25 -> ~75
    k = 0.8  # tanh(0.8 * 1.25) = tanh(1.0) ≈ 0.762 -> 50 + 50*0.762 = 88.1 (too high)
    # Better calibration: k=0.55 -> tanh(0.55*1.25)=tanh(0.6875)≈0.596 -> 50+50*0.596=79.8
    # k=0.48 -> tanh(0.48*1.25)=tanh(0.60)≈0.537 -> 50+50*0.537=76.9 ✓
    k = 0.48
    raw = 50.0 + 50.0 * float(np.tanh(k * abs(abs_z_score)))
    return int(np.clip(round(raw), 0, 100))


class FlowFeatureEngine:
    """Calculates order flow, microstructural, and crowding indicators for a single symbol."""

    @staticmethod
    def compute_symbol_features(
        symbol: str,
        candles_15m: pd.DataFrame,
        candles_1h: Optional[pd.DataFrame] = None,
        orderbook: Optional[Dict[str, Any]] = None,
        trades_5m: Optional[list] = None,
        funding_rate: float = 0.0001,
        mark_price: float = 0.0,
        index_price: float = 0.0,
        open_interest: float = 0.0,
        prev_open_interest: float = 0.0,
        taker_buy_sell_ratio: float = 1.0,
        long_short_ratio: float = 1.0,
    ) -> Dict[str, float]:
        """
        Extract raw features for a single symbol.
        """
        if candles_15m is None or len(candles_15m) < 15:
            return {}

        c15 = candles_15m
        close_15m = c15["close"].to_numpy(dtype=float)
        vol_15m = c15["volume"].to_numpy(dtype=float) if "volume" in c15.columns else np.ones(len(c15))
        cur_price = close_15m[-1]

        # 1. Momentum (M_1h, M_4h) (Section 9.1)
        # 1h = 4 bars of 15m; 4h = 16 bars of 15m
        m_1h = (close_15m[-1] - close_15m[-5]) / (close_15m[-5] + 1e-9) if len(close_15m) > 5 else 0.0
        m_4h = (close_15m[-1] - close_15m[-17]) / (close_15m[-17] + 1e-9) if len(close_15m) > 17 else m_1h

        # 2. Order Flow Imbalance (OFI_15m) & CVD from trades or taker volume (Section 9.2 & 9.3)
        ofi_15m = 0.0
        cvd_slope = 0.0
        if "taker_buy_base_asset_volume" in c15.columns:
            taker_buy = c15["taker_buy_base_asset_volume"].to_numpy(dtype=float)
            total_vol = vol_15m
            taker_sell = np.maximum(total_vol - taker_buy, 0.0)

            # OFI on last 15m bar
            buy_vol = taker_buy[-1]
            sell_vol = taker_sell[-1]
            tot = buy_vol + sell_vol
            if tot > 0:
                ofi_15m = (buy_vol - sell_vol) / tot

            # CVD slope over last 4 bars (1h)
            cvd = np.cumsum(taker_buy[-4:] - taker_sell[-4:])
            if len(cvd) >= 2:
                cvd_slope = float(np.polyfit(np.arange(len(cvd)), cvd, 1)[0])
                cvd_slope = cvd_slope / (np.mean(total_vol[-4:]) + 1e-9)

        elif trades_5m and len(trades_5m) > 0:
            buy_vol = sum(float(t.get("qty", 0)) for t in trades_5m if not t.get("isBuyerMaker", True))
            sell_vol = sum(float(t.get("qty", 0)) for t in trades_5m if t.get("isBuyerMaker", False))
            tot = buy_vol + sell_vol
            ofi_15m = (buy_vol - sell_vol) / (tot + 1e-9)

        # 3. Open Interest Confirmation (Section 9.4)
        oi_change_pct = 0.0
        if prev_open_interest > 0 and open_interest > 0:
            oi_change_pct = (open_interest - prev_open_interest) / prev_open_interest
        ret_15m = (close_15m[-1] - close_15m[-2]) / close_15m[-2] if len(close_15m) >= 2 else 0.0
        oi_confirmation = np.sign(ret_15m) * oi_change_pct * 10.0  # Scaled

        # 4. Order Book Imbalance (Section 9.7)
        book_imbalance = 0.0
        if orderbook and "bids" in orderbook and "asks" in orderbook:
            bids = orderbook["bids"][:10]
            asks = orderbook["asks"][:10]
            bid_depth = sum(float(b[1]) for b in bids)
            ask_depth = sum(float(a[1]) for a in asks)
            tot_depth = bid_depth + ask_depth
            if tot_depth > 0:
                book_imbalance = (bid_depth - ask_depth) / tot_depth

        # 5. Relative Volume (Section 9.8)
        avg_vol = np.mean(vol_15m[-20:]) if len(vol_15m) >= 20 else np.mean(vol_15m)
        rel_volume = (vol_15m[-1] / (avg_vol + 1e-9)) - 1.0  # Centered around 0.0

        # 6. Funding & Basis (Sections 9.5 & 9.6)
        # Typical 8h funding is 0.01% (0.0001)
        funding_centered = (funding_rate - 0.0001) / 0.0002

        basis = 0.0
        if mark_price > 0 and index_price > 0:
            basis = (mark_price - index_price) / index_price
        basis_centered = basis / 0.0005  # Typical basis std 5 bps

        # 7. Volatility (ATR 14 on 15m)
        high_15m = c15["high"].to_numpy(dtype=float)
        low_15m = c15["low"].to_numpy(dtype=float)
        tr = np.maximum(high_15m[1:] - low_15m[1:], np.maximum(np.abs(high_15m[1:] - close_15m[:-1]), np.abs(low_15m[1:] - close_15m[:-1])))
        atr14 = pd.Series(tr).rolling(14).mean().iloc[-1] if len(tr) >= 14 else (high_15m[-1] - low_15m[-1])
        atr_pct = float(atr14 / (cur_price + 1e-9))

        # 8. Taker Buy/Sell Bias (Multi-Agent Analyzer §3 & §7)
        # ratio > 1.0 = taker buy dominant, < 1.0 = taker sell dominant
        taker_bias = float(taker_buy_sell_ratio - 1.0)  # Centered around 0

        # 9. Long/Short Account Ratio Bias (Multi-Agent Analyzer §3)
        # ratio > 1.0 = more longs than shorts (potential crowding if extreme)
        ls_bias = float(long_short_ratio - 1.0)  # Centered around 0

        return {
            "symbol": symbol,
            "current_price": cur_price,
            "atr_pct": atr_pct,
            "m_1h": float(m_1h),
            "m_4h": float(m_4h),
            "ofi_15m": float(ofi_15m),
            "cvd_slope": float(cvd_slope),
            "oi_confirmation": float(oi_confirmation),
            "book_imbalance": float(book_imbalance),
            "rel_volume": float(rel_volume),
            "funding_raw": float(funding_rate),
            "funding_z": float(funding_centered),
            "basis_z": float(basis_centered),
            "taker_bias": taker_bias,
            "ls_bias": ls_bias,
        }
