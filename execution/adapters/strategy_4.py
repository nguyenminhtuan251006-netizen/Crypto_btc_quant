"""
Strategy 4 Adapter: AFCX (Adaptive Flow Cross-Sectional Strategy)
==================================================================
Scans top liquid perpetual contracts across Binance USDT-M.
Selects the #1 highest qualified opportunity after confidence, consensus, crowding, and cost gates.
Enforces strictly one open position at a time and dynamic ATR(14) risk sizing.
"""
import os
import sys
from typing import Dict, Any

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, base_dir)

from execution.strategy_interface import BaseStrategy, StrategyDecision
from chien_thuat.chien_thuat_4.strategy import AFCXStrategy


class Strategy4Adapter(BaseStrategy):
    """Adapter for Chien Thuat 4: AFCX Strategy."""

    def __init__(self):
        super().__init__(
            name="chien_thuat_4",
            symbol="BTCUSDT",
            leverage=5,
            default_qty=0.001,
            take_profit_pct=0.012,
            stop_loss_pct=0.006,
        )
        self.afcx = AFCXStrategy(name="chien_thuat_4", leverage=self.leverage)
        self.session_mgr = self.afcx.session_mgr

    def initialize(self):
        """Initialize AFCX universe and cache metadata."""
        self.afcx.initialize()
        self.symbol = self.afcx.symbol

    def analyze(self, market_data: Dict[str, Any]) -> StrategyDecision:
        """Forward market analysis to AFCX engine."""
        decision = self.afcx.analyze(market_data)
        # Update current target symbol from decision
        if decision.extra_metrics and "selected_symbol" in decision.extra_metrics:
            self.symbol = decision.extra_metrics["selected_symbol"]
        return decision
