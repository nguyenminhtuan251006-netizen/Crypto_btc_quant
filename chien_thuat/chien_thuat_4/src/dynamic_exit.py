"""
AFCX Dynamic Exit & Trailing Management
========================================
Implements Sections 22, 23, 24 of the AFCX Specification:
- Re-scores active position every 15 minutes.
- Score Decay Exit: Closes trade if |Score| < 0.40 or sign flips.
- Trailing Winner: Activates dynamic trailing stop once profit reaches +1R.
- Time Stop: Closes trade after 3 hours if price remains flat and score decays.
"""
import time
from typing import Tuple, Dict, Any, Optional


class DynamicExitManager:
    """Manages active position re-evaluation, trailing stops, and time stops."""

    def __init__(
        self,
        min_holding_score: float = 0.40,
        trailing_activation_r: float = 1.0,
        max_duration_seconds: float = 3 * 3600,  # 3 hours
    ):
        self.min_holding_score = min_holding_score
        self.trailing_activation_r = trailing_activation_r
        self.max_duration_seconds = max_duration_seconds

    def check_dynamic_exit(
        self,
        entry_time: float,
        entry_price: float,
        current_price: float,
        position_direction: int,  # 1 for Long, -1 for Short
        sl_distance_pct: float,
        current_score: float,
        current_rank: int = 1,
    ) -> Tuple[bool, str]:
        """
        Evaluates whether an active position should be closed early.
        
        Returns:
            (should_exit: bool, exit_reason: str)
        """
        # Calculate current profit in R-multiples
        if position_direction == 1:
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price

        r_multiple = profit_pct / (sl_distance_pct + 1e-9)

        # 1. Sign Flip Check (Section 22)
        if (position_direction == 1 and current_score < -0.20) or (position_direction == -1 and current_score > 0.20):
            return True, f"🚨 ĐẢO CHIỀU DÒNG TIỀN: Score đảo hướng thành {current_score:+.2f} (Thoát lệnh để bảo vệ vốn)"

        # 2. Score Decay Check (Section 22)
        if abs(current_score) < self.min_holding_score and r_multiple < 0.5:
            return True, f"⚠️ DÒNG TIỀN SUY YẾU: Điểm số hiện tại |{current_score:+.2f}| < {self.min_holding_score} và chưa đạt +0.5R"

        # 3. Severe Rank Drop Check (Section 22)
        if current_rank >= 6 and r_multiple < 0.3:
            return True, f"⚠️ TỤT HẠNG DÒNG TIỀN: Thứ hạng rơi từ Top 1 xuống Rank #{current_rank}"

        # 4. Time Stop Check (Section 24)
        elapsed_seconds = time.time() - entry_time
        if elapsed_seconds >= self.max_duration_seconds:
            if abs(r_multiple) < 0.5 and abs(current_score) < 0.80:
                return True, f"⏰ TIME STOP: Vị thế đã giữ quá 3 giờ ({elapsed_seconds/3600:.1f}h) mà không bứt phá và động lượng suy giảm"

        return False, f"Vị thế bình thường (Lãi hiện tại: {r_multiple:+.2f}R, Score: {current_score:+.2f})"

    def calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        position_direction: int,
        sl_distance_pct: float,
        atr_5m_pct: float,
        current_highest_price: float,
        current_lowest_price: float,
    ) -> Optional[float]:
        """
        Returns new trailing stop price if +1R is reached (Section 23).
        """
        if position_direction == 1:
            profit_pct = (current_price - entry_price) / entry_price
            if profit_pct >= self.trailing_activation_r * sl_distance_pct:
                # Trail by 1.2 * ATR_5m from the highest price reached
                trail_distance = max(1.2 * atr_5m_pct * current_highest_price, sl_distance_pct * 0.5 * current_highest_price)
                new_sl = current_highest_price - trail_distance
                # Trailing stop must be at least breakeven
                return max(new_sl, entry_price * 1.0005)
        else:
            profit_pct = (entry_price - current_price) / entry_price
            if profit_pct >= self.trailing_activation_r * sl_distance_pct:
                trail_distance = max(1.2 * atr_5m_pct * current_lowest_price, sl_distance_pct * 0.5 * current_lowest_price)
                new_sl = current_lowest_price + trail_distance
                return min(new_sl, entry_price * 0.9995)

        return None
