"""
AFCX Market Regime Engine
==========================
Implements Section 10 of the AFCX Specification:
Detects overall market regime (TREND, RANGE, TRANSITION, STRESS) across 1H and 4H timeframes.
When regime is STRESS, new trade entries are strictly blocked.
In RANGE or TRANSITION, entry thresholds are raised to prioritize high-conviction setups.
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple


class MarketRegimeEngine:
    """Classifies market conditions into TREND, RANGE, FLAT, TRANSITION, or STRESS."""

    def __init__(
        self,
        trend_efficiency_threshold: float = 0.20,  # Kaufman Efficiency Ratio threshold for trend
        max_spread_pct: float = 0.0008,            # 0.08%
        flat_efficiency_threshold: float = 0.07,   # Below this = pure chop / zero net progress
        flat_vol_threshold: float = 0.016,         # Compressed volatility threshold
    ):
        self.trend_efficiency_threshold = trend_efficiency_threshold
        self.max_spread_pct = max_spread_pct
        self.flat_efficiency_threshold = flat_efficiency_threshold
        self.flat_vol_threshold = flat_vol_threshold

    def evaluate_regime(
        self,
        btc_candles_1h: pd.DataFrame,
        market_spread_pct: float = 0.0002,
        market_breadth: float = 0.5,  # Ratio of coins in universe with positive 1h return (0.0 to 1.0)
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Evaluate overall market regime.
        
        Returns:
            (regime_name: str, explanation: str, metrics: dict)
        """
        if btc_candles_1h is None or len(btc_candles_1h) < 20:
            return "RANGE", "Dữ liệu nến 1H đang được cập nhật", {"trend_ratio": 0.0}

        close = btc_candles_1h["close"].to_numpy(dtype=float)
        high = btc_candles_1h["high"].to_numpy(dtype=float)
        low = btc_candles_1h["low"].to_numpy(dtype=float)

        # 1. Realized Volatility (rolling 24-bar std)
        returns = np.diff(np.log(close))
        realized_vol = float(np.std(returns[-24:]) * np.sqrt(24)) if len(returns) >= 24 else 0.01

        # Check STRESS Condition 1: Spread spike (Section 10)
        if market_spread_pct > self.max_spread_pct:
            return "STRESS", f"Spread thị trường giãn nở nguy hiểm ({market_spread_pct*100:.3f}% > {self.max_spread_pct*100:.3f}%)", {"spread": market_spread_pct}

        # Check STRESS Condition 2: Extreme volatility spike
        hist_vol = float(np.std(returns) * np.sqrt(24)) if len(returns) > 24 else realized_vol
        if hist_vol > 0 and (realized_vol / hist_vol) > 3.0:
            return "STRESS", f"Biến động giá cực đại bất thường (Vol Spike: {realized_vol/hist_vol:.2f}x)", {"realized_vol": realized_vol}

        # 2. Kaufman Efficiency Ratio (ER = Net Move / Total Path)
        net_move = abs(close[-1] - close[-14]) if len(close) >= 14 else abs(close[-1] - close[0])
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        sum_tr = float(np.sum(tr[-14:])) if len(tr) >= 14 else float(np.sum(tr))
        efficiency_ratio = net_move / (sum_tr + 1e-9)

        # EMA direction
        ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().iloc[-1]

        metrics = {
            "realized_vol": round(realized_vol, 4),
            "efficiency_ratio": round(efficiency_ratio, 3),
            "market_breadth": round(market_breadth, 2),
        }

        # 3. Regime Classification (Section 10)

        # FLAT detection — prolonged sideway with compressed volatility or pure chop
        if (efficiency_ratio < self.flat_efficiency_threshold) or (efficiency_ratio < 0.10 and realized_vol < self.flat_vol_threshold):
            return "FLAT", (
                f"🚫 THỊ TRƯỜNG SIDEWAY KÉO DÀI (Hiệu suất: {efficiency_ratio:.3f}, "
                f"Vol: {realized_vol:.4f}) — KHÓA MỌI LỆNH MỚI"
            ), metrics

        # Strong directional market: High efficiency ratio + broad consensus
        if efficiency_ratio >= self.trend_efficiency_threshold and (market_breadth >= 0.55 or market_breadth <= 0.45):
            direction = "TĂNG (Bullish)" if ema12 >= ema26 else "GIẢM (Bearish)"
            return "TREND", f"Thị trường XU HƯỚNG {direction} (Hiệu suất: {efficiency_ratio:.2f}, Breadth: {market_breadth*100:.0f}%)", metrics

        elif efficiency_ratio < 0.12:
            return "RANGE", f"Thị trường SIDEWAY đi ngang (Hiệu suất: {efficiency_ratio:.2f} < 0.12, Breadth: {market_breadth*100:.0f}%)", metrics

        else:
            return "TRANSITION", f"Thị trường CHUYỂN PHA (Hiệu suất: {efficiency_ratio:.2f}, Breadth: {market_breadth*100:.0f}%)", metrics

