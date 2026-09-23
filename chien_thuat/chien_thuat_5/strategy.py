"""
CHIẾN THUẬT 5: AFCX Micro-Capital Edition (Tối ưu cho vốn 150.000 VNĐ / ~6 USDT)
==============================================================================
Kế thừa toàn bộ kiến trúc AFCX v3 Dual-Session Architecture:
1. Dual-Session Frame: ASIA (04:00 - 15:00 VN) & LIQUID (15:00 - 04:00 VN).
2. Persistence Gate cho phiên ASIA: Duy trì Top 1 liên tục >= 2 lượt quét.
3. Market Regime Engine: 1H BTC Trend & Breadth, khóa STRESS.
4. Cross-Sectional Ranking: Chọn lọc cơ hội số 1 trong Top Altcoin Binance.
5. Micro-Capital Floor Notional: Cố định vị thế tối thiểu 5.5 USDT để vừa vặn
   vượt ngưỡng sàn Binance MIN_NOTIONAL (5.0 USDT) với số vốn chỉ từ 150.000 VNĐ (~6 USDT).
6. Quản trị rủi ro: Ký quỹ chỉ ~1.1 USDT (5x), Stop Loss mất tối đa ~2.000 VNĐ/lệnh.
"""
import os
import sys
from typing import Dict, Any, List, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, workspace_dir)

from execution.strategy_interface import BaseStrategy, StrategyDecision
from chien_thuat.chien_thuat_4.strategy import AFCXStrategy

# Danh sách Top Altcoin thanh khoản cao trên Binance Futures USDT-M hỗ trợ Min Notional 5.0 USDT
MICRO_CAPITAL_UNIVERSE = [
    "ETHUSDT", "SOLUSDT", "ARBUSDT", "OPUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT", "LINKUSDT",
    "NEARUSDT", "APTUSDT", "INJUSDT", "BNBUSDT", "LTCUSDT",
]


class MicroAFCXStrategy(AFCXStrategy):
    """
    Chiến Thuật 5: Phiên bản AFCX Micro-Capital tối ưu riêng cho tài khoản vốn nhỏ
    (từ 150.000 VNĐ ~ 6 USDT đến dưới 50 USDT).
    """

    def __init__(
        self,
        name: str = "chien_thuat_5",
        symbol: str = "ETHUSDT",
        leverage: int = 10,
        default_qty: float = 0.001,
        take_profit_pct: float = 0.012,
        stop_loss_pct: float = 0.006,
        min_notional_target: float = 15.0,
    ):
        super().__init__(
            name=name,
            symbol=symbol,
            leverage=leverage,
            default_qty=default_qty,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            universe_symbols=MICRO_CAPITAL_UNIVERSE,
        )
        self.min_notional_target = min_notional_target  # 15.0 USDT sàn (ký quỹ ~1.5 USDT ở đòn bẩy 10x)
        self.micro_capital_mode = True

        # Trailing Take Profit: Cơ chế Bậc Thang 2 Tầng (Chống quét râu)
        self.enable_trailing = True
        self.tier1_trigger_pct = 0.012          # Tầng 1: Đạt +1.2% (mốc cũ)
        self.tier1_lock_pct = 0.010             # Ghim cứng SL tại +1.0% (chống quét râu nến)
        self.tier2_trigger_pct = 0.018          # Tầng 2: Vượt +1.8% bùng nổ bám đỉnh
        self.trailing_callback_pct = 0.0045     # Lùi 0.45% bám sát theo sau đỉnh
        self.profit_lock_floor_pct = 0.0010     # Khóa tối thiểu hòa vốn
        self.wide_tp_pct = 0.08                 # Trần chốt lời khẩn cấp +8.0%

    def analyze(self, market_data: Dict[str, Any]) -> StrategyDecision:
        """Kế thừa phân tích của AFCX và đính kèm nhãn Micro-Capital."""
        decision = super().analyze(market_data)
        if decision.signal != 0:
            decision.reason = f"[MICRO-CAPITAL / {self.min_notional_target}$ / {self.leverage}X] {decision.reason}"
        return decision
