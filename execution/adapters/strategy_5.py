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
            leverage=5,
            default_qty=0.001,
            take_profit_pct=0.012,
            stop_loss_pct=0.006,
        )
        self.strat = MicroAFCXStrategy(name="chien_thuat_5", leverage=self.leverage)
        self.min_notional_target = self.strat.min_notional_target
        self.micro_capital_mode = self.strat.micro_capital_mode
        self.session_mgr = self.strat.session_mgr
        self.cached_ranking = self.strat.cached_ranking
        self.last_trade_close_time = self.strat.last_trade_close_time

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
        self.cached_ranking = self.strat.cached_ranking
        return decision
