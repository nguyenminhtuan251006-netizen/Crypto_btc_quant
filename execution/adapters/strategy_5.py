"""
Strategy 5 Adapter: AFCX Micro-Capital Edition (Vốn 150.000 VNĐ / ~6 USDT)
==========================================================================
Tối ưu hóa riêng cho số vốn nhỏ từ 150k VNĐ (~6 USDT).
Tự động giới hạn sàn vị thế 5.5 USDT để vượt bộ lọc sàn Binance MIN_NOTIONAL.
"""
import os
import sys
from typing import Dict, Any

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, base_dir)

from execution.strategy_interface import BaseStrategy, StrategyDecision
from chien_thuat.chien_thuat_5.strategy import MicroAFCXStrategy


class Strategy5Adapter(BaseStrategy):
    """Adapter for Chien Thuat 5: AFCX Micro-Capital Edition."""

    def __init__(self):
        super().__init__(
            name="chien_thuat_5",
            symbol="ETHUSDT",
            leverage=10,
            default_qty=0.001,
            take_profit_pct=0.012,
            stop_loss_pct=0.006,
        )
        self.strat = MicroAFCXStrategy(name="chien_thuat_5", leverage=self.leverage)
        self.min_notional_target = self.strat.min_notional_target
        self.micro_capital_mode = self.strat.micro_capital_mode
        self.session_mgr = self.strat.session_mgr
        self.last_trade_close_time = self.strat.last_trade_close_time

        # Trailing Parameters (Bậc Thang 2 Tầng)
        self.enable_trailing = self.strat.enable_trailing
        self.tier1_trigger_pct = getattr(self.strat, 'tier1_trigger_pct', None)
        self.tier1_lock_pct = getattr(self.strat, 'tier1_lock_pct', None)
        self.tier2_trigger_pct = getattr(self.strat, 'tier2_trigger_pct', None)
        self.trailing_callback_pct = self.strat.trailing_callback_pct
        self.profit_lock_floor_pct = self.strat.profit_lock_floor_pct
        self.wide_tp_pct = self.strat.wide_tp_pct

    @property
    def last_trade_close_time(self):
        return self.strat.last_trade_close_time

    @last_trade_close_time.setter
    def last_trade_close_time(self, value):
        self.strat.last_trade_close_time = value

    @property
    def cached_ranking(self):
        """Always return real-time cached ranking from underlying strategy."""
        return getattr(self.strat, 'cached_ranking', [])

    @property
    def last_rank_time(self):
        return getattr(self.strat, 'last_rank_time', 0.0)

    def refresh_ranking(self):
        """Refresh universe ranking on-demand while holding position."""
        if hasattr(self.strat, 'scan_and_rank_universe'):
            return self.strat.scan_and_rank_universe()
        return []

    def initialize(self):
        """Initialize universe and cache metadata."""
        self.strat.initialize()
        self.symbol = self.strat.symbol

    def analyze(self, market_data: Dict[str, Any]) -> StrategyDecision:
        """Forward market analysis to Micro-AFCX engine."""
        decision = self.strat.analyze(market_data)
        # Update current target symbol from decision
        if decision.extra_metrics and "selected_symbol" in decision.extra_metrics:
            self.symbol = decision.extra_metrics["selected_symbol"]
        return decision
