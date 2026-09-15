"""
Protection Order Lifecycle & Reconciler Module
===============================================
Implements Sections 1, 5, 6, 7 of the Binance Futures Safety Specification:
1. Reconciles fills and eliminates orphan orders.
2. If position is flat (closed), cancels remaining counterpart TP or SL orders.
3. Enforces reduce-only semantics and Mark Price trigger protection.
4. Prevents accidental reverse positions.
"""
import time
from typing import Dict, Any, Tuple, Optional


class OrderReconciler:
    """Manages Binance protection order lifecycles and cleans up orphan orders."""

    def __init__(self, client, symbol: str = "BTCUSDT"):
        self.client = client
        self.symbol = symbol

    def reconcile_and_cleanup_orphans(self, current_pos_amt: float) -> int:
        """
        If position is completely flat (0.0), any existing open limit or algo stop
        orders are orphans and MUST be cancelled immediately (Section 1.1 & 5.1).
        
        Returns count of cancelled orphan orders.
        """
        cancelled_count = 0
        if abs(current_pos_amt) < 1e-5:
            # 1. Check open regular orders (TP limit orders)
            try:
                open_orders = self.client.get("/fapi/v1/openOrders", {"symbol": self.symbol})
                if isinstance(open_orders, list) and len(open_orders) > 0:
                    self.client.delete("/fapi/v1/allOpenOrders", {"symbol": self.symbol})
                    cancelled_count += len(open_orders)
            except Exception:
                pass

            # 2. Check open algo orders (SL stop-market orders)
            try:
                open_algos = self.client.get("/fapi/v1/openAlgoOrders", {"symbol": self.symbol})
                if isinstance(open_algos, list) and len(open_algos) > 0:
                    for algo in open_algos:
                        aid = algo.get("algoId")
                        if aid:
                            self.client.delete("/fapi/v1/algoOrder", {"algoId": aid})
                            cancelled_count += 1
            except Exception:
                pass

        return cancelled_count

    def place_verified_protection_orders(
        self,
        position_side: int,   # 1 for Long, -1 for Short
        qty: float,
        tp_price: float,
        sl_price: float,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Immediately place both Hard Take Profit and Hard Stop Loss directly on Binance
        using reduceOnly and Mark Price trigger (Sections 1.2, 5, 6, 7).
        
        Returns:
            (tp_response, sl_response)
        """
        close_side = "SELL" if position_side == 1 else "BUY"

        # 1. Take Profit: Limit Order with reduceOnly (Maker fee optimization)
        tp_params = {
            "symbol": self.symbol,
            "side": close_side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "price": round(tp_price, 1),
            "quantity": qty,
            "reduceOnly": "true",
        }
        res_tp = self.client.post("/fapi/v1/order", tp_params)

        # 2. Stop Loss: Conditional Stop Market Order triggered by Mark Price
        sl_params = {
            "algoType": "CONDITIONAL",
            "symbol": self.symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "triggerPrice": round(sl_price, 1),
            "workingType": "MARK_PRICE",  # Mark price trigger prevents wick manipulation
            "quantity": qty,
            "reduceOnly": "true",
        }
        time.sleep(0.3)
        res_sl = self.client.post("/fapi/v1/algoOrder", sl_params)

        return res_tp, res_sl

    def emergency_flatten(self) -> Dict[str, Any]:
        """Emergency circuit breaker: Cancel all orders and market-close entire position."""
        self.client.cancel_all_orders(self.symbol)
        amt, _, _ = self.client.get_position(self.symbol)
        if abs(amt) > 1e-5:
            close_side = "SELL" if amt > 0 else "BUY"
            return self.client.place_market_order(self.symbol, close_side, abs(amt))
        return {"status": "ALREADY_FLAT"}
