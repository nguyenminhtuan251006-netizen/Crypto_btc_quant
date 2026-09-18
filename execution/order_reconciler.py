"""
Protection Order Lifecycle & Reconciler Module
===============================================
Implements Sections 1, 5, 6, 7 of the Binance Futures Safety Specification
+ AFCX v3 Dual Session Architecture Sections 10, 11, 12, 13:

1. Reconciles fills and eliminates orphan orders.
2. If position is flat (closed), cancels remaining counterpart TP or SL orders.
3. Enforces reduce-only semantics and Mark Price trigger protection.
4. Prevents accidental reverse positions.
5. (v3) Normal Reconcile: Cancel by specific order_id from Registry.
6. (v3) Fallback Reconcile: cancel_all only when entire account is flat (safety net).
7. (v3) Client Order ID namespace support (AFCX-LIQ / AFCX-ASI).
"""
import time
from typing import Dict, Any, Tuple, Optional


class OrderReconciler:
    """Manages Binance protection order lifecycles and cleans up orphan orders."""

    def __init__(self, client, symbol: str = "BTCUSDT"):
        self.client = client
        self.symbol = symbol

    # --------------------------------------------------------------------------
    # v3 Normal Reconcile: Cancel by specific order IDs (Spec Section 12 & 13)
    # --------------------------------------------------------------------------
    def reconcile_trade_closure(self, trade_record: Optional[Dict[str, Any]] = None) -> int:
        """
        Normal mode (v3): Cancel protection orders by their registered order IDs.
        This prevents accidentally cancelling orders belonging to another session profile.
        
        Falls back to reconcile_and_cleanup_orphans if no trade_record is available.
        
        Returns count of cancelled orders.
        """
        if trade_record is None:
            # No registry data — use fallback
            return self.reconcile_and_cleanup_orphans(0.0)

        cancelled = 0
        tp_id = trade_record.get("tp_order_id")
        sl_id = trade_record.get("sl_order_id")

        # Cancel TP (regular limit order)
        if tp_id:
            try:
                self.client.delete("/fapi/v1/order", {"symbol": self.symbol, "orderId": tp_id})
                cancelled += 1
            except Exception:
                pass

        # Cancel SL (algo/conditional order)
        if sl_id:
            try:
                self.client.delete("/fapi/v1/algoOrder", {"algoId": sl_id})
                cancelled += 1
            except Exception:
                pass

        return cancelled

    # --------------------------------------------------------------------------
    # Fallback Reconcile: cancel_all when account is fully flat (Review Issue 2)
    # --------------------------------------------------------------------------
    def reconcile_and_cleanup_orphans(self, current_pos_amt: float) -> int:
        """
        Fallback mode: If position is completely flat (0.0), cancel ALL remaining
        open orders for this symbol. Used as safety net when Registry is unavailable
        or after startup recovery.
        
        WARNING (v3 Section 12): This uses cancel_all and should only be used when
        Registry-based reconciliation is not possible.
        
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

    # --------------------------------------------------------------------------
    # Place Protection Orders with optional Client Order IDs (v3 Spec Section 10)
    # --------------------------------------------------------------------------
    def place_verified_protection_orders(
        self,
        position_side: int,   # 1 for Long, -1 for Short
        qty: float,
        tp_price: float,
        sl_price: float,
        client_order_ids: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Immediately place both Hard Take Profit and Hard Stop Loss directly on Binance
        using reduceOnly, Mark Price trigger, and optional Client Order IDs (v3 Section 10 & 11).
        
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
        if client_order_ids and "tp_cid" in client_order_ids:
            tp_params["newClientOrderId"] = client_order_ids["tp_cid"]

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
        if client_order_ids and "sl_cid" in client_order_ids:
            sl_params["clientAlgoId"] = client_order_ids["sl_cid"]

        time.sleep(0.3)
        res_sl = self.client.post("/fapi/v1/algoOrder", sl_params)

        return res_tp, res_sl

    # --------------------------------------------------------------------------
    # Emergency Flatten (Global Kill Switch only — Spec Section 15 GLOBAL_KILL)
    # --------------------------------------------------------------------------
    def emergency_flatten(self) -> Dict[str, Any]:
        """Emergency circuit breaker: Cancel all orders and market-close entire position."""
        self.client.cancel_all_orders(self.symbol)
        amt, _, _ = self.client.get_position(self.symbol)
        if abs(amt) > 1e-5:
            close_side = "SELL" if amt > 0 else "BUY"
            return self.client.place_market_order(self.symbol, close_side, abs(amt))
        return {"status": "ALREADY_FLAT"}
