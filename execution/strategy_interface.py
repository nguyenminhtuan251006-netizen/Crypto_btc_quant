"""
Unified Strategy Interface for Crypto BTC Quant Lab
===================================================
Standard interface that all strategies (Chien Thuat 1, 2, 3, 4, etc.) must implement
to run on the 24/7 background trading daemon.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class StrategyDecision:
    signal: int               # 1: BUY (Long), -1: SELL (Short), 0: FLAT (Wait/Hold)
    confidence: float         # 0.0 to 1.0 (e.g. 0.72)
    reason: str               # Human-readable rationale (e.g. "P(UP)=72.1% > th_long, Trend>0")
    tp_pct: float = 0.004     # Take profit percentage (default 0.4%)
    sl_pct: float = 0.004     # Stop loss percentage (default 0.4%)
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    extra_metrics: Optional[Dict[str, Any]] = None


class BaseStrategy(ABC):
    """Abstract Base Class for all quantitative strategies."""
    
    def __init__(
        self,
        name: str,
        symbol: str = "BTCUSDT",
        leverage: int = 5,
        default_qty: float = 0.001,
        take_profit_pct: float = 0.004,
        stop_loss_pct: float = 0.004
    ):
        self.name = name
        self.symbol = symbol
        self.leverage = leverage
        self.default_qty = default_qty
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        
    @abstractmethod
    def initialize(self):
        """Load AI models, config, weights, and precomputed thresholds."""
        pass

    @abstractmethod
    def analyze(self, market_data: Dict[str, Any]) -> StrategyDecision:
        """
        Analyze incoming market data and return trading decision.
        
        Parameters
        ----------
        market_data : dict
            Contains:
            - 'candles': pd.DataFrame (recent OHLCV candles)
            - 'orderbook': dict (bids/asks L2 snapshot)
            - 'trades': list of dicts (recent tick trades)
            - 'current_price': float
            - 'timestamp': datetime
            
        Returns
        -------
        StrategyDecision
            The trading decision with signal, confidence, and risk parameters.
        """
        pass
