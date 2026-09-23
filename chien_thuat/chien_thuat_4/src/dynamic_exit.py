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
        trailing_activation_pct: Optional[float] = None,
        trailing_callback_pct: Optional[float] = None,
        profit_lock_floor_pct: float = 0.0010,
        tier1_trigger_pct: Optional[float] = None,
        tier1_lock_pct: Optional[float] = None,
        tier2_trigger_pct: Optional[float] = None,
        max_duration_seconds: float = 3 * 3600,  # 3 hours
    ):
        self.min_holding_score = min_holding_score
        self.trailing_activation_r = trailing_activation_r
        self.trailing_activation_pct = trailing_activation_pct
        self.trailing_callback_pct = trailing_callback_pct
        self.profit_lock_floor_pct = profit_lock_floor_pct
        self.tier1_trigger_pct = tier1_trigger_pct
        self.tier1_lock_pct = tier1_lock_pct
        self.tier2_trigger_pct = tier2_trigger_pct
        self.max_duration_seconds = max_duration_seconds
        self.last_active_tier = 0  # 0: Inactive, 1: Tier 1 (Protected Lock), 2: Tier 2 (Dynamic Runner)

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
        Returns new trailing stop price if activation threshold is reached.
        Supports Two-Tier Profit Ratchet (Anti-Wick Lock + Dynamic Peak Runner),
        as well as classical adaptive trailing stop.
        """
        if position_direction == 1:
            profit_pct = (current_price - entry_price) / entry_price
            peak_profit_pct = (current_highest_price - entry_price) / entry_price

            # 1. Two-Tier Profit Ratchet (Chống quét râu)
            if self.tier1_trigger_pct is not None and self.tier1_lock_pct is not None:
                if self.tier2_trigger_pct is not None and peak_profit_pct >= self.tier2_trigger_pct:
                    self.last_active_tier = 2  # Tầng 2: Bùng nổ bám đỉnh
                    trail_dist_pct = (
                        self.trailing_callback_pct
                        if self.trailing_callback_pct is not None
                        else max(1.2 * atr_5m_pct, sl_distance_pct * 0.5)
                    )
                    trail_distance = trail_dist_pct * current_highest_price
                    new_sl = current_highest_price - trail_distance
                    min_floor = entry_price * (1.0 + self.tier1_lock_pct)
                    return max(new_sl, min_floor)
                elif peak_profit_pct >= self.tier1_trigger_pct:
                    self.last_active_tier = 1  # Tầng 1: Khóa bảo hộ râu nến
                    return entry_price * (1.0 + self.tier1_lock_pct)
                return None

            # Fallback: Classical single-tier trailing
            is_triggered = (
                profit_pct >= self.trailing_activation_pct
                if self.trailing_activation_pct is not None
                else profit_pct >= self.trailing_activation_r * sl_distance_pct
            )
            if is_triggered:
                self.last_active_tier = 1
                trail_dist_pct = (
                    self.trailing_callback_pct
                    if self.trailing_callback_pct is not None
                    else max(1.2 * atr_5m_pct, sl_distance_pct * 0.5)
                )
                trail_distance = trail_dist_pct * current_highest_price
                new_sl = current_highest_price - trail_distance
                lock_price = entry_price * (1.0 + self.profit_lock_floor_pct)
                return max(new_sl, lock_price)

        else:
            profit_pct = (entry_price - current_price) / entry_price
            peak_profit_pct = (entry_price - current_lowest_price) / entry_price

            # 1. Two-Tier Profit Ratchet for Short
            if self.tier1_trigger_pct is not None and self.tier1_lock_pct is not None:
                if self.tier2_trigger_pct is not None and peak_profit_pct >= self.tier2_trigger_pct:
                    self.last_active_tier = 2  # Tầng 2: Bùng nổ bám đáy
                    trail_dist_pct = (
                        self.trailing_callback_pct
                        if self.trailing_callback_pct is not None
                        else max(1.2 * atr_5m_pct, sl_distance_pct * 0.5)
                    )
                    trail_distance = trail_dist_pct * current_lowest_price
                    new_sl = current_lowest_price + trail_distance
                    max_floor = entry_price * (1.0 - self.tier1_lock_pct)
                    return min(new_sl, max_floor)
                elif peak_profit_pct >= self.tier1_trigger_pct:
                    self.last_active_tier = 1  # Tầng 1: Khóa bảo hộ râu nến cho Short
                    return entry_price * (1.0 - self.tier1_lock_pct)
                return None

            # Fallback: Classical single-tier trailing for Short
            is_triggered = (
                profit_pct >= self.trailing_activation_pct
                if self.trailing_activation_pct is not None
                else profit_pct >= self.trailing_activation_r * sl_distance_pct
            )
            if is_triggered:
                self.last_active_tier = 1
                trail_dist_pct = (
                    self.trailing_callback_pct
                    if self.trailing_callback_pct is not None
                    else max(1.2 * atr_5m_pct, sl_distance_pct * 0.5)
                )
                trail_distance = trail_dist_pct * current_lowest_price
                new_sl = current_lowest_price + trail_distance
                lock_price = entry_price * (1.0 - self.profit_lock_floor_pct)
                return min(new_sl, lock_price)

        return None
