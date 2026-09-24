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
        # Override risk: reduce from 0.5% to 0.2% per trade while validating long-term performance
        self.afcx.risk_pct = 0.002
        self.risk_fraction = 0.002
        self.session_mgr = self.afcx.session_mgr

        # Trailing Parameters (Bậc Thang 2 Tầng)
        self.enable_trailing = self.afcx.enable_trailing
        self.tier1_trigger_pct = getattr(self.afcx, 'tier1_trigger_pct', None)
        self.tier1_lock_pct = getattr(self.afcx, 'tier1_lock_pct', None)
        self.tier2_trigger_pct = getattr(self.afcx, 'tier2_trigger_pct', None)
        self.trailing_callback_pct = self.afcx.trailing_callback_pct
        self.profit_lock_floor_pct = self.afcx.profit_lock_floor_pct
        self.wide_tp_pct = self.afcx.wide_tp_pct

    @property
    def last_trade_close_time(self):
        return self.afcx.last_trade_close_time

    @last_trade_close_time.setter
    def last_trade_close_time(self, value):
        self.afcx.last_trade_close_time = value

    @property
    def cached_ranking(self):
        """Always return real-time cached ranking from underlying strategy."""
        return getattr(self.afcx, 'cached_ranking', [])

    @property
    def last_rank_time(self):
        return getattr(self.afcx, 'last_rank_time', 0.0)

    def refresh_ranking(self):
        """Refresh universe ranking on-demand while holding position."""
        if hasattr(self.afcx, 'scan_and_rank_universe'):
            return self.afcx.scan_and_rank_universe()
        return []

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
