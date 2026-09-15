"""
Binance Futures Bot Safety & Risk Management Module
===================================================
Implements institutional-grade risk management conforming to:
'Binance Futures Bot Safety & Risk Management Specification'

Features:
1. Risk-Based Position Sizing (Notional = Risk Amount / Stop Distance %)
2. Volatility-Aware Dynamic Stops (ATR-based SL & R-Multiple TP)
3. Account-Level Kill Switch (Consecutive losses, daily loss %, spread spike filter)
4. Leverage & Exchange Limits Verification
"""
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, date
from typing import Tuple, Dict, Any, Optional


class RiskManager:
    """Institutional Risk Manager for Binance Futures Trading."""

    def __init__(
        self,
        risk_fraction: float = 0.005,       # 0.5% risk of equity per trade
        max_consecutive_losses: int = 3,    # Kill switch after 3 consecutive losses
        max_daily_loss_pct: float = 0.02,   # Kill switch after 2% loss in a single day
        max_spread_pct: float = 0.0005,     # 0.05% max spread allowed for entry
        atr_multiplier_sl: float = 1.2,     # k * ATR for Stop Loss (baseline 1.2)
        r_multiple_tp: float = 1.5,         # Take profit = 1.5 * Stop distance
        min_sl_pct: float = 0.003,          # Minimum 0.3% stop distance
        max_sl_pct: float = 0.012,          # Maximum 1.2% stop distance
        max_leverage: int = 5,
        min_qty: float = 0.001,
        state_file: Optional[str] = None,
    ):
        self.risk_fraction = risk_fraction
        self.max_consecutive_losses = max_consecutive_losses
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_spread_pct = max_spread_pct
        self.atr_multiplier_sl = atr_multiplier_sl
        self.r_multiple_tp = r_multiple_tp
        self.min_sl_pct = min_sl_pct
        self.max_sl_pct = max_sl_pct
        self.max_leverage = max_leverage
        self.min_qty = min_qty

        # State persistence
        if state_file is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            state_file = os.path.join(base_dir, "logs", "kill_switch_state.json")
        self.state_file = state_file

        self.state = {
            "consecutive_losses": 0,
            "daily_loss_amount": 0.0,
            "day_start_equity": 0.0,
            "current_date": str(date.today()),
            "is_tripped": False,
            "trip_reason": "",
        }
        self._load_state()

    # --------------------------------------------------------------------------
    # 1. State Persistence & Daily Reset
    # --------------------------------------------------------------------------
    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    saved = json.load(f)
                    today_str = str(date.today())
                    # Check for daily reset
                    if saved.get("current_date") != today_str:
                        saved["current_date"] = today_str
                        saved["daily_loss_amount"] = 0.0
                        saved["is_tripped"] = False
                        saved["trip_reason"] = ""
                    self.state.update(saved)
            except Exception:
                pass

    def _save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # 2. Risk-Based Position Sizing (Section 2 of Spec)
    # --------------------------------------------------------------------------
    def calculate_position_size(
        self,
        equity: float,
        stop_distance_pct: float,
        current_price: float,
    ) -> Tuple[float, float, Dict[str, Any]]:
        """
        Calculate quantity and notional based on intended equity risk.
        
        Formula:
            risk_amount = equity * risk_fraction
            position_notional = risk_amount / stop_distance_pct
            qty = position_notional / current_price
        """
        if equity <= 0 or stop_distance_pct <= 0 or current_price <= 0:
            return self.min_qty, self.min_qty * current_price, {}

        # 1. Intended dollar risk
        risk_amount = equity * self.risk_fraction

        # 2. Position notional from risk
        clamped_stop = max(stop_distance_pct, 0.001)
        position_notional = risk_amount / clamped_stop

        # 3. Leverage and Margin Constraints
        max_notional_by_leverage = equity * self.max_leverage * 0.95  # 5% safety buffer for fees
        position_notional = min(position_notional, max_notional_by_leverage)

        # 4. Exchange Minimums and Precision
        raw_qty = position_notional / current_price
        # Quantize to 3 decimal places (Binance BTC step size = 0.001)
        qty = round(max(int(raw_qty * 1000) / 1000.0, self.min_qty), 3)
        actual_notional = qty * current_price

        sizing_info = {
            "equity": round(equity, 2),
            "risk_fraction": self.risk_fraction,
            "risk_amount_usdt": round(risk_amount, 3),
            "stop_distance_pct": round(stop_distance_pct * 100, 3),
            "position_notional": round(actual_notional, 2),
            "allocated_qty": qty,
            "margin_required_usdt": round(actual_notional / self.max_leverage, 2),
        }
        return qty, actual_notional, sizing_info

    # --------------------------------------------------------------------------
    # 3. Volatility-Aware Dynamic Stops (ATR-Based) (Sections 3 & 4 of Spec)
    # --------------------------------------------------------------------------
    def compute_dynamic_stops(
        self,
        candles: pd.DataFrame,
        current_price: float,
        direction: int,  # 1 for Long, -1 for Short
    ) -> Tuple[float, float, float, float]:
        """
        Calculates Stop-Loss and Take-Profit using ATR(14) and Reward/Risk multiplier.
        
        Returns:
            (sl_pct, tp_pct, sl_price, tp_price)
        """
        if len(candles) < 15:
            # Fallback to conservative defaults if insufficient candles
            sl_pct = self.min_sl_pct
            tp_pct = sl_pct * self.r_multiple_tp
        else:
            high = candles["high"].to_numpy()
            low = candles["low"].to_numpy()
            close = candles["close"].to_numpy()

            # True Range
            tr1 = high[1:] - low[1:]
            tr2 = np.abs(high[1:] - close[:-1])
            tr3 = np.abs(low[1:] - close[:-1])
            tr = np.maximum(tr1, np.maximum(tr2, tr3))

            # ATR 14 (exponential moving average of TR)
            atr = pd.Series(tr).ewm(span=14, adjust=False).mean().iloc[-1]
            atr_pct = atr / (current_price + 1e-9)

            # Volatility-based stop
            sl_pct = atr_pct * self.atr_multiplier_sl
            sl_pct = float(np.clip(sl_pct, self.min_sl_pct, self.max_sl_pct))
            tp_pct = float(sl_pct * self.r_multiple_tp)

        # Exact price levels
        if direction == 1:
            sl_price = round(current_price * (1.0 - sl_pct), 1)
            tp_price = round(current_price * (1.0 + tp_pct), 1)
        else:
            sl_price = round(current_price * (1.0 + sl_pct), 1)
            tp_price = round(current_price * (1.0 - tp_pct), 1)

        return sl_pct, tp_pct, sl_price, tp_price

    # --------------------------------------------------------------------------
    # 4. Account-Level Kill Switch (Section 8 of Spec)
    # --------------------------------------------------------------------------
    def check_kill_switch(
        self,
        current_equity: float,
        current_spread_pct: float = 0.0,
        data_freshness_seconds: float = 0.0,
    ) -> Tuple[bool, str]:
        """
        Verifies all circuit breakers before allowing a new trade entry.
        
        Returns:
            (can_trade: bool, message: str)
        """
        self._load_state()

        # Update day start equity if not initialized
        if self.state["day_start_equity"] <= 0:
            self.state["day_start_equity"] = current_equity
            self._save_state()

        # 1. Already tripped check
        if self.state["is_tripped"]:
            return False, f"🚨 KILL SWITCH ACTIVE: {self.state['trip_reason']}"

        # 2. Consecutive Losses Check
        if self.state["consecutive_losses"] >= self.max_consecutive_losses:
            self.state["is_tripped"] = True
            self.state["trip_reason"] = f"Vượt quá số lệnh thua liên tiếp ({self.state['consecutive_losses']}/{self.max_consecutive_losses})"
            self._save_state()
            return False, f"🚨 KILL SWITCH KÍCH HOẠT: {self.state['trip_reason']}"

        # 3. Daily Loss Drawdown Check
        day_start = self.state["day_start_equity"]
        if day_start > 0:
            daily_loss = day_start - current_equity
            daily_loss_pct = daily_loss / day_start
            if daily_loss_pct >= self.max_daily_loss_pct:
                self.state["is_tripped"] = True
                self.state["trip_reason"] = f"Mức lỗ trong ngày đạt {daily_loss_pct*100:.2f}% (Trần cho phép: {self.max_daily_loss_pct*100:.1f}%)"
                self._save_state()
                return False, f"🚨 KILL SWITCH KÍCH HOẠT: {self.state['trip_reason']}"

        # 4. Spread Spike Filter
        if current_spread_pct > self.max_spread_pct:
            return False, f"⚠️ SPREAD QUÁ RỘNG: {current_spread_pct*100:.3f}% > {self.max_spread_pct*100:.3f}% (Bảo vệ trượt giá)"

        # 5. Data Freshness Filter
        if data_freshness_seconds > 60.0:
            return False, f"⚠️ DỮ LIỆU BỊ TRỄ: {data_freshness_seconds:.1f}s > 60s (Dừng vào lệnh chờ kết nối ổn định)"

        return True, "OK"

    def record_trade_outcome(self, net_pnl_usdt: float, current_equity: float):
        """Record trade result to update loss counters and daily drawdown."""
        self._load_state()

        if net_pnl_usdt < 0:
            self.state["consecutive_losses"] += 1
            self.state["daily_loss_amount"] += abs(net_pnl_usdt)
        else:
            # Win resets consecutive losses counter
            self.state["consecutive_losses"] = 0

        self._save_state()

    def reset_kill_switch(self, new_start_equity: Optional[float] = None):
        """Manually reset the kill switch."""
        self.state["consecutive_losses"] = 0
        self.state["daily_loss_amount"] = 0.0
        self.state["is_tripped"] = False
        self.state["trip_reason"] = ""
        if new_start_equity:
            self.state["day_start_equity"] = new_start_equity
        self._save_state()
        print("[RiskManager] Đã đặt lại Kill Switch thành công.")
