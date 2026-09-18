"""
Order Registry & Position Ownership Manager
============================================
Implements AFCX v3 Dual-Session Architecture Sections 7, 8, 11:
1. Global Position Lock: MAX_OPEN_POSITIONS = 1
2. Position Ownership: Tracks which session profile (LIQUID or ASIA) owns the running position.
3. Order Namespace: Generates standardized Client Order IDs (AFCX-LIQ / AFCX-ASI).
4. Order Registry: Tracks entry_order_id, sl_order_id, tp_order_id for targeted cancellation.
5. Startup Reconciliation: Syncs registry with actual Binance positions on daemon restart (Review Issue 5).
"""
import os
import json
import time
from typing import Dict, Any, Optional


class OrderRegistry:
    """Manages active trade ownership and Binance order tracking."""

    def __init__(self, registry_file: Optional[str] = None):
        if registry_file is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            registry_file = os.path.join(base_dir, "logs", "trade_registry.json")
        self.registry_file = registry_file
        self.data: Dict[str, Any] = {
            "active_trade": None,
            "trade_counter": 0,
            "closed_trades": [],
        }
        self._load()

    def _load(self):
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, "r") as f:
                    saved = json.load(f)
                    self.data.update(saved)
            except Exception:
                pass

    def _save(self):
        os.makedirs(os.path.dirname(self.registry_file), exist_ok=True)
        try:
            with open(self.registry_file, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # Global Position Lock & Ownership (Spec Section 7)
    # --------------------------------------------------------------------------
    def is_locked(self) -> bool:
        """Returns True if a position is currently open and active."""
        self._load()
        trade = self.data.get("active_trade")
        return trade is not None and trade.get("status") == "OPEN"

    def get_active_trade(self) -> Optional[Dict[str, Any]]:
        """Returns the currently active trade dict, if any."""
        self._load()
        trade = self.data.get("active_trade")
        if trade and trade.get("status") == "OPEN":
            return trade
        return None

    def get_owner(self) -> Optional[str]:
        """Returns the profile name ("LIQUID" or "ASIA") that owns the active trade."""
        trade = self.get_active_trade()
        return trade.get("owner") if trade else None

    # --------------------------------------------------------------------------
    # Client Order ID Generation (Spec Section 10)
    # --------------------------------------------------------------------------
    def generate_client_order_ids(self, owner: str) -> Dict[str, str]:
        """
        Generates unique Client Order IDs:
        AFCX-LIQ-E-0001-123456, AFCX-LIQ-TP-0001-123456, etc.
        """
        prefix = "AFCX-LIQ" if owner == "LIQUID" else "AFCX-ASI"
        ts_suffix = str(int(time.time()))[-6:]
        seq = self.data.get("trade_counter", 0) + 1

        return {
            "entry_cid": f"{prefix}-E-{seq:04d}-{ts_suffix}",
            "sl_cid": f"{prefix}-SL-{seq:04d}-{ts_suffix}",
            "tp_cid": f"{prefix}-TP-{seq:04d}-{ts_suffix}",
            "prefix": prefix,
            "seq": seq,
        }

    # --------------------------------------------------------------------------
    # Trade Registration (Spec Section 8 & 11)
    # --------------------------------------------------------------------------
    def register_new_trade(
        self,
        owner: str,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        tp_price: float,
        sl_price: float,
        entry_order_id: Optional[Any] = None,
        sl_order_id: Optional[Any] = None,
        tp_order_id: Optional[Any] = None,
        client_order_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Registers a newly opened trade and activates Global Position Lock."""
        self._load()
        self.data["trade_counter"] = self.data.get("trade_counter", 0) + 1
        seq = self.data["trade_counter"]
        prefix = "AFCX-LIQ" if owner == "LIQUID" else "AFCX-ASI"
        trade_id = f"{prefix}-{time.strftime('%Y%m%d')}-{symbol}-{seq:04d}"

        trade = {
            "trade_id": trade_id,
            "owner": owner,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": entry_price,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "entry_order_id": entry_order_id,
            "sl_order_id": sl_order_id,
            "tp_order_id": tp_order_id,
            "client_order_ids": client_order_ids or {},
            "status": "OPEN",
            "entry_time": time.time(),
        }

        self.data["active_trade"] = trade
        self._save()
        return trade

    def update_protection_order_ids(
        self,
        tp_order_id: Optional[Any] = None,
        sl_order_id: Optional[Any] = None,
    ):
        """Updates TP and SL order IDs after exchange confirmation."""
        trade = self.get_active_trade()
        if trade:
            if tp_order_id:
                trade["tp_order_id"] = tp_order_id
            if sl_order_id:
                trade["sl_order_id"] = sl_order_id
            self._save()

    def mark_trade_closed(
        self,
        exit_price: float = 0.0,
        net_pnl: float = 0.0,
        close_reason: str = "TP/SL hit",
    ) -> Optional[Dict[str, Any]]:
        """
        Marks active trade as closed and releases Global Position Lock (Flat Handoff).
        """
        self._load()
        trade = self.data.get("active_trade")
        if trade and trade.get("status") == "OPEN":
            trade["status"] = "CLOSED"
            trade["exit_price"] = exit_price
            trade["net_pnl"] = net_pnl
            trade["close_reason"] = close_reason
            trade["close_time"] = time.time()

            # Keep last 50 closed trades in history
            history = self.data.get("closed_trades", [])
            history.append(trade)
            if len(history) > 50:
                history = history[-50:]
            self.data["closed_trades"] = history
            self.data["active_trade"] = None
            self._save()
            return trade
        return None

    # --------------------------------------------------------------------------
    # Startup Reconciliation (Review Issue 5)
    # --------------------------------------------------------------------------
    def startup_reconciliation(self, client) -> str:
        """
        Syncs Registry state with actual Binance positions on daemon start.
        Handles two mismatch cases:
        1. Binance has position but Registry says flat → Adopt as UNKNOWN_RECOVERY
        2. Registry says OPEN but Binance is flat → Mark closed
        
        Returns a human-readable status string.
        """
        self._load()

        # 1. Query actual positions on Binance
        all_pos = client.get("/fapi/v2/positionRisk")
        active_pos = []
        if isinstance(all_pos, list):
            active_pos = [p for p in all_pos if abs(float(p.get("positionAmt", 0.0))) > 1e-5]

        has_binance_pos = len(active_pos) > 0
        has_registry_pos = self.is_locked()

        # Case 1: Binance has position, Registry is empty → Adopt
        if has_binance_pos and not has_registry_pos:
            pos = active_pos[0]
            sym = pos.get("symbol", "UNKNOWN")
            amt = float(pos.get("positionAmt", 0.0))
            entry_p = float(pos.get("entryPrice", 0.0))
            side = "BUY" if amt > 0 else "SELL"

            self.register_new_trade(
                owner="RECOVERY",
                symbol=sym,
                side=side,
                qty=abs(amt),
                entry_price=entry_p,
                tp_price=0.0,
                sl_price=0.0,
            )
            return f"⚠️ STARTUP RECOVERY: Phát hiện vị thế {side} {abs(amt)} {sym} trên Binance không có trong Registry. Đã adopt."

        # Case 2: Registry says OPEN, Binance is flat → Mark closed
        if not has_binance_pos and has_registry_pos:
            trade = self.get_active_trade()
            sym = trade.get("symbol", "N/A") if trade else "N/A"
            self.mark_trade_closed(close_reason="Detected flat on startup reconciliation")
            return f"⚠️ STARTUP RECOVERY: Registry ghi {sym} OPEN nhưng Binance flat. Đã đánh dấu CLOSED."

        # Both agree
        if has_binance_pos and has_registry_pos:
            return "✅ STARTUP: Registry và Binance đồng bộ (có vị thế đang mở)."

        return "✅ STARTUP: Tài khoản flat, Registry trống. Sẵn sàng giao dịch."

    def emergency_clear_all(self):
        """Used ONLY by Global Kill Switch (Spec Section 15)."""
        self.data["active_trade"] = None
        self._save()
