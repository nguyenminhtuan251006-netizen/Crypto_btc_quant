"""
Configuration for Strategy 2: BTC 15M Regime-Pullback + AI Meta Filter
"""
from dataclasses import dataclass

@dataclass
class Strategy2Config:
    # Asset & Timeframes
    symbol: str = "BTCUSDT"
    signal_tf: str = "15m"
    regime_tf: str = "1h"
    
    # 1H Regime Filter Parameters
    regime_ema_trend: int = 200
    regime_ema_slope: int = 50
    regime_adx_period: int = 14
    regime_adx_threshold: float = 20.0
    
    # 15M Pullback Setup Parameters
    pullback_ema_fast: int = 20
    pullback_ema_slow: int = 50
    pullback_rsi_period: int = 14
    pullback_rsi_long_min: float = 40.0
    pullback_rsi_long_max: float = 65.0
    pullback_rsi_short_min: float = 35.0
    pullback_rsi_short_max: float = 60.0
    
    # Adaptive ATR Target Parameters
    atr_period: int = 14
    sl_atr_mult: float = 1.0    # 1.0 * ATR
    tp_atr_mult: float = 1.8    # 1.8 * ATR (1.8 : 1 Reward/Risk)
    timeout_bars: int = 8       # 8 bars of 15m = 2 hours
    
    # Expected Value (EV) Filter Parameters
    ev_minimum: float = 0.10    # Minimum EV in R-units (after costs)
    est_cost_r: float = 0.08    # Round-trip fee + slippage in R-units
    
    # Volatility Filter
    atr_pct_min: float = 15.0   # Skip if ATR percentile < 15% (dead market)
    atr_pct_max: float = 95.0   # Skip if ATR percentile > 95% (wild shock)
    
    # Risk Management & Kill-Switch
    daily_loss_limit_r: float = 2.0  # Stop trading if day PnL <= -2R
    consecutive_loss_limit: int = 3  # Cooldown if 3 consecutive losses
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    
    # Default initial capital & leverage
    initial_capital: float = 6.0
    leverage: float = 5.0
    maker_fee_rate: float = 0.00015
    taker_fee_rate: float = 0.00040
    default_slippage_bps: float = 2.0  # 2 basis points
