"""
Universal 24/7 Background Trading Daemon
=========================================
Runs any registered strategy (Chien Thuat 1, 2, 3, 4: AFCX...) persistently in the background.
Survives client PC shutdowns, SSH disconnections, and network drops.
Strictly adheres to 'Binance Futures Bot Safety & Risk Management Specification':
1. One Position at a Time (Section 1.1)
2. Hard Stop-Loss & Take-Profit on Binance directly (Section 1.2)
3. Risk-Based Position Sizing: Notional = Equity * Risk% / StopDistance% (Section 2)
4. Dynamic ATR-based Stop Loss & R-Multiple Take Profit (Sections 3 & 4)
5. Protection Order Lifecycle & Zero Orphan Orders Reconciler (Section 5 & 6)
6. Mark Price Trigger Selection (Section 7)
7. Account-Level Kill Switch (Consecutive losses, daily loss %, spread spike, staleness) (Section 8)
8. Multi-Asset Cross-Sectional Support for Strategy 4 (AFCX)
"""
import os
import sys
import time
import signal
import argparse
from datetime import datetime
import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(current_dir)
sys.path.insert(0, workspace_dir)

from execution.registry import get_strategy
from execution.risk_manager import RiskManager
from execution.order_reconciler import OrderReconciler
from chien_thuat.chien_thuat_3.live_trader_demo import load_credentials, BinanceDemoClient
from chien_thuat.chien_thuat_3.paper_trader import (
    fetch_recent_candles,
    fetch_orderbook_l2,
    fetch_recent_trades,
)
from chien_thuat.chien_thuat_4.src.universe import UniverseManager
from chien_thuat.chien_thuat_4.src.dynamic_exit import DynamicExitManager

running = True

def handle_sigterm(signum, frame):
    global running
    print(f"\n[DAEMON] Nhận tín hiệu dừng (Signal {signum}), đang thoát an toàn...")
    running = False

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)


def run_daemon(strategy_name: str = "chien_thuat_3", poll_interval: int = 25):
    global running
    print("=" * 95)
    print("      🛡️ UNIVERSAL 24/7 QUANT TRADING DAEMON — SAFETY & RISK ENFORCED")
    print(f"      Chiến thuật hoạt động: {strategy_name.upper()}")
    print("      Tiêu chuẩn: Institutional Risk & Safety Specification (Binance Futures)")
    print("      Cơ chế: Chạy ngầm độc lập trên Linux Server (Tắt máy tính cá nhân vẫn chạy 24/7)")
    print("=" * 95)

    # 1. Credentials
    api_key, api_secret = load_credentials()
    if not api_key or not api_secret:
        print("[LỖI] Không tìm thấy API Key trong file .env!")
        return

    # 2. Strategy instantiation
    try:
        strategy = get_strategy(strategy_name)
    except Exception as e:
        print(f"[LỖI KHỞI TẠO CHIẾN THUẬT] {e}")
        return

    # 3. Binance Client, Risk Manager, and Universe Manager
    client = BinanceDemoClient(api_key, api_secret)
    client.init_account_settings(strategy.symbol, leverage=strategy.leverage)
    risk_mgr = RiskManager(max_leverage=strategy.leverage)
    universe_mgr = UniverseManager()

    log_dir = os.path.join(workspace_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"live_{strategy.name}.log")

    # Initial equity fetch
    acc_info = client.get("/fapi/v2/account")
    equity = float(acc_info.get("totalMarginBalance", 0.0)) if isinstance(acc_info, dict) else 0.0

    print(f"[Khởi tạo thành công] Chiến thuật: {strategy.name} | Đòn bẩy tối đa: {strategy.leverage}x")
    print(f"[Vốn tài khoản hiện tại]: ${equity:,.2f} USDT")
    print(f"[Cơ chế quản trị rủi ro]: Risk {risk_mgr.risk_fraction*100:.1f}% vốn/lệnh | Dynamic ATR Stops")
    print(f"[Kill Switch Circuit Breaker]: Max {risk_mgr.max_consecutive_losses} lệnh thua | Max {risk_mgr.max_daily_loss_pct*100:.1f}% lỗ/ngày")
    print(f"[Bảo hiểm Binance]: Hard TP/SL ghim trên sàn, Reduce-Only, Mark Price Trigger, Reconcile Zero-Orphan")
    print(f"[Nhật ký realtime]: {log_file}")
    print(f"[Trạng thái]: Bắt đầu vòng lặp giám sát thị trường 24/7...")

    prev_amt = 0.0
    prev_equity = equity
    active_symbol = strategy.symbol
    entry_timestamp = time.time()
    exit_manager = DynamicExitManager()
    highest_price_seen = 0.0
    lowest_price_seen = float('inf')

    # Initial check of open position across all symbols
    all_pos = client.get("/fapi/v2/positionRisk")
    active_pos = [p for p in all_pos if abs(float(p.get("positionAmt", 0.0))) > 1e-5] if isinstance(all_pos, list) else []
    if active_pos:
        active_symbol = active_pos[0].get("symbol", strategy.symbol)
        prev_amt = float(active_pos[0].get("positionAmt", 0.0))

    iteration = 0
    while running:
        iteration += 1
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Step A: Query live account equity and position from Binance
            acc_info = client.get("/fapi/v2/account")
            if isinstance(acc_info, dict) and "totalMarginBalance" in acc_info:
                equity = float(acc_info["totalMarginBalance"])

            # Query all active positions (supports multi-asset strategy)
            all_pos = client.get("/fapi/v2/positionRisk")
            active_pos = [p for p in all_pos if abs(float(p.get("positionAmt", 0.0))) > 1e-5] if isinstance(all_pos, list) else []

            if active_pos:
                active_symbol = active_pos[0].get("symbol", strategy.symbol)
                amt = float(active_pos[0].get("positionAmt", 0.0))
                entry = float(active_pos[0].get("entryPrice", 0.0))
                unPnl = float(active_pos[0].get("unRealizedProfit", 0.0))
            else:
                amt = 0.0
                entry = 0.0
                unPnl = 0.0

            reconciler = OrderReconciler(client, symbol=active_symbol)

            # Step B: Position Reconciliation & Trade Settlement
            if abs(prev_amt) > 1e-5 and abs(amt) <= 1e-5:
                # Previous position has just been closed by TP or SL!
                trade_pnl = equity - prev_equity
                risk_mgr.record_trade_outcome(trade_pnl, equity)
                orphans_cancelled = reconciler.reconcile_and_cleanup_orphans(amt)

                close_banner = (
                    f"\n{'='*75}\n"
                    f"🎯 [{now_str}] [{strategy.name.upper()}] VỊ THẾ {active_symbol} ĐÃ HOÀN TẤT CHỐT LỜI / CẮT LỖ:\n"
                    f"   • Lãi/Lỗ thực tế (Net PnL): {trade_pnl:+.4f} USDT\n"
                    f"   • Vốn khả dụng mới: ${equity:,.2f} USDT\n"
                    f"   • Reconciler: Đã hủy {orphans_cancelled} lệnh treo đối ứng còn sót lại (Zero-Orphan guarantee)\n"
                    f"{'='*75}"
                )
                print(close_banner)
                with open(log_file, "a") as f: f.write(close_banner + "\n")
                prev_equity = equity

                # Signal cooldown to strategy
                if hasattr(strategy, 'last_trade_close_time'):
                    strategy.last_trade_close_time = time.time()

                # Reset tracking
                highest_price_seen = 0.0
                lowest_price_seen = float('inf')

            # Step C: Active Position Management
            if abs(amt) > 1e-5:
                # Currently in an active trade
                pos_dir = 1 if amt > 0 else -1
                cur_market_price = float(fetch_recent_candles(active_symbol, limit=1).iloc[-1]["close"])

                # Track extreme prices for trailing stop
                highest_price_seen = max(highest_price_seen, cur_market_price)
                lowest_price_seen = min(lowest_price_seen, cur_market_price)

                # --- DYNAMIC EXIT MANAGER (Score Decay, Sign Flip, Trailing) ---
                # Re-score current position by running strategy analysis
                try:
                    if hasattr(strategy, 'cached_ranking') and strategy.cached_ranking:
                        # Find current rank and score of active symbol
                        current_score = 0.0
                        current_rank = 99
                        for rank_idx, r in enumerate(strategy.cached_ranking):
                            if r["symbol"] == active_symbol:
                                current_score = r["final_score"] * pos_dir  # Align score with position direction
                                current_rank = rank_idx + 1
                                break

                        should_exit, exit_reason = exit_manager.check_dynamic_exit(
                            entry_time=entry_timestamp,
                            entry_price=entry,
                            current_price=cur_market_price,
                            position_direction=pos_dir,
                            sl_distance_pct=strategy.stop_loss_pct,
                            current_score=current_score,
                            current_rank=current_rank,
                        )

                        if should_exit:
                            # Close position via market order
                            close_side = "SELL" if pos_dir == 1 else "BUY"
                            close_res = client.place_market_order(active_symbol, close_side, abs(amt))
                            time.sleep(0.3)
                            orphans_cancelled = reconciler.reconcile_and_cleanup_orphans(0.0)

                            exit_msg = (
                                f"\n{'='*75}\n"
                                f"🧠 [{now_str}] [DYNAMIC EXIT] {exit_reason}\n"
                                f"   • Đóng vị thế {active_symbol} bằng lệnh thị trường\n"
                                f"   • Đã hủy {orphans_cancelled} lệnh treo đối ứng\n"
                                f"{'='*75}"
                            )
                            print(exit_msg)
                            with open(log_file, "a") as f: f.write(exit_msg + "\n")
                            if hasattr(strategy, 'last_trade_close_time'):
                                strategy.last_trade_close_time = time.time()
                            highest_price_seen = 0.0
                            lowest_price_seen = float('inf')
                            prev_amt = amt
                            time.sleep(poll_interval)
                            continue

                        # Check trailing stop update
                        atr_5m_pct = strategy.stop_loss_pct / 1.2  # Reverse ATR estimate
                        new_trailing_sl = exit_manager.calculate_trailing_stop(
                            entry_price=entry,
                            current_price=cur_market_price,
                            position_direction=pos_dir,
                            sl_distance_pct=strategy.stop_loss_pct,
                            atr_5m_pct=atr_5m_pct,
                            current_highest_price=highest_price_seen,
                            current_lowest_price=lowest_price_seen,
                        )

                        if new_trailing_sl is not None:
                            new_sl_quantized = universe_mgr.quantize_price(active_symbol, new_trailing_sl)
                            trail_msg = f"[{now_str}] 📈 [TRAILING STOP] Cập nhật SL mới cho {active_symbol}: ${new_sl_quantized}"
                            print(trail_msg)
                            with open(log_file, "a") as f: f.write(trail_msg + "\n")
                            # Re-place SL order with new trailing price
                            tp_p = universe_mgr.quantize_price(active_symbol, entry * (1.0 + strategy.take_profit_pct) if pos_dir == 1 else entry * (1.0 - strategy.take_profit_pct))
                            reconciler.place_verified_protection_orders(pos_dir, abs(amt), tp_p, new_sl_quantized)

                except Exception as e:
                    exit_err = f"[{now_str}] ⚠️ Dynamic Exit check error: {e}"
                    print(exit_err)
                    with open(log_file, "a") as f: f.write(exit_err + "\n")

                # --- Protection Order Reconciliation ---
                orders = client.get("/fapi/v1/openOrders", {"symbol": active_symbol})
                algos = client.get("/fapi/v1/openAlgoOrders", {"symbol": active_symbol})
                
                # Check if protection orders are missing on Binance
                has_regular = isinstance(orders, list) and len(orders) > 0
                has_algo = isinstance(algos, list) and len(algos) > 0

                if not has_regular or not has_algo:
                    # Place missing protection orders immediately
                    tp_p = universe_mgr.quantize_price(active_symbol, entry * (1.0 + strategy.take_profit_pct) if amt > 0 else entry * (1.0 - strategy.take_profit_pct))
                    sl_p = universe_mgr.quantize_price(active_symbol, entry * (1.0 - strategy.stop_loss_pct) if amt > 0 else entry * (1.0 + strategy.stop_loss_pct))
                    
                    reconciler.place_verified_protection_orders(pos_dir, abs(amt), tp_p, sl_p)
                    prot_msg = f"[{now_str}] 🛡️ [RECONCILER] Đã tự động tái lập Hard TP/SL trên Binance cho {active_symbol}: Qty={abs(amt)} | TP=${tp_p} | SL=${sl_p}"
                    print(prot_msg)
                    with open(log_file, "a") as f: f.write(prot_msg + "\n")

                side_str = "LONG" if amt > 0 else "SHORT"
                status_line = f"[{now_str}] [{strategy.name.upper()}] Vị thế đang chạy: {side_str} {abs(amt)} {active_symbol} @ ${entry:,.2f} | Lãi/Lỗ: {unPnl:+.4f} USDT | Vốn: ${equity:,.2f} USDT"
                print(status_line)
                with open(log_file, "a") as f: f.write(status_line + "\n")

            else:
                # Step D: Flat (No Active Position) — Ready to evaluate new setup
                # Clean up any leftover orphan orders first (Section 1.1)
                orphans = reconciler.reconcile_and_cleanup_orphans(amt)
                if orphans > 0:
                    orphan_msg = f"[{now_str}] 🧹 [RECONCILER] Đã dọn sạch {orphans} lệnh mồ côi {active_symbol} trước khi tìm kiếm cơ hội mới."
                    print(orphan_msg)
                    with open(log_file, "a") as f: f.write(orphan_msg + "\n")

                # Fetch market data for primary baseline (BTC)
                candles = fetch_recent_candles("BTCUSDT", limit=100)
                ob = fetch_orderbook_l2("BTCUSDT", limit=20)
                trades = fetch_recent_trades("BTCUSDT", limit=100)
                cur_price = float(candles.iloc[-1]["close"])

                # Measure spread and data freshness (Section 8)
                best_bid = float(ob["bids"][0][0]) if (ob.get("bids") and len(ob["bids"]) > 0) else cur_price
                best_ask = float(ob["asks"][0][0]) if (ob.get("asks") and len(ob["asks"]) > 0) else cur_price
                spread_pct = (best_ask - best_bid) / cur_price

                freshness_sec = 0.0
                if isinstance(trades, list) and len(trades) > 0:
                    last_trade_t = trades[0].get("time", 0) / 1000.0
                    freshness_sec = max(0.0, time.time() - last_trade_t)

                # Check Account-Level Kill Switch (Section 8)
                can_trade, ks_msg = risk_mgr.check_kill_switch(
                    current_equity=equity,
                    current_spread_pct=spread_pct,
                    data_freshness_seconds=freshness_sec,
                )

                if not can_trade:
                    status_line = f"[{now_str}] [{strategy.name.upper()}] 🚨 BẢO VỆ TÀI KHOẢN: {ks_msg}"
                    print(status_line)
                    with open(log_file, "a") as f: f.write(status_line + "\n")
                else:
                    # Evaluate Strategy Signals (Section 9 & 13)
                    market_data = {
                        "candles": candles,
                        "orderbook": ob,
                        "trades": trades,
                        "current_price": cur_price,
                        "timestamp": now_dt
                    }

                    decision = strategy.analyze(market_data)
                    status_line = f"[{now_str}] [{strategy.name.upper()}] BTC: ${cur_price:,.1f} | Quyết định: {decision.reason}"
                    print(status_line)
                    with open(log_file, "a") as f: f.write(status_line + "\n")

                    # Step E: Trigger New Position if Signal fires (Section 13)
                    if decision.signal != 0:
                        target_sym = decision.extra_metrics.get("selected_symbol", strategy.symbol) if decision.extra_metrics else strategy.symbol
                        active_symbol = target_sym
                        reconciler = OrderReconciler(client, symbol=target_sym)
                        client.init_account_settings(target_sym, leverage=strategy.leverage)

                        # Determine target price and stops
                        cand_entry_p = decision.extra_metrics.get("candidate", {}).get("current_price", cur_price) if decision.extra_metrics else cur_price
                        sl_pct = decision.sl_pct
                        tp_pct = decision.tp_pct
                        sl_price = decision.sl_price or universe_mgr.quantize_price(target_sym, cand_entry_p * (1.0 - sl_pct) if decision.signal == 1 else cand_entry_p * (1.0 + sl_pct))
                        tp_price = decision.tp_price or universe_mgr.quantize_price(target_sym, cand_entry_p * (1.0 + tp_pct) if decision.signal == 1 else cand_entry_p * (1.0 - tp_pct))

                        # 2. Compute Risk-Based Position Sizing (Section 2 & 19)
                        raw_qty, notional, size_info = risk_mgr.calculate_position_size(
                            equity=equity,
                            stop_distance_pct=sl_pct,
                            current_price=cand_entry_p,
                        )
                        qty = universe_mgr.quantize_qty(target_sym, raw_qty)

                        order_side = "BUY" if decision.signal == 1 else "SELL"

                        # 3. Submit Market Entry Order
                        res = client.place_market_order(target_sym, order_side, qty)
                        
                        # 4. Immediately Place Verified Hard Protection Orders on Binance (Sections 1.2 & 5)
                        time.sleep(0.4)
                        r_tp, r_sl = reconciler.place_verified_protection_orders(
                            position_side=decision.signal,
                            qty=qty,
                            tp_price=tp_price,
                            sl_price=sl_price,
                        )

                        order_msg = (
                            f"\n{'='*75}\n"
                            f"🚀 [{now_str}] TỰ ĐỘNG MỞ VỊ THẾ {order_side} {qty} {target_sym} @ ${cand_entry_p:,.2f}\n"
                            f"   • Quản lý vốn: Vốn ${equity:,.2f} USDT | Rủi ro: ${size_info.get('risk_amount_usdt', 0)} USDT ({risk_mgr.risk_fraction*100:.1f}%) | Notional: ${notional:,.1f}\n"
                            f"   • Bảo hiểm Hard TP (+{tp_pct*100:.2f}%): ${tp_price} [LIMIT Reduce-Only]\n"
                            f"   • Bảo hiểm Hard SL (-{sl_pct*100:.2f}%): ${sl_price} [MARK_PRICE Stop-Market Reduce-Only]\n"
                            f"   • Khớp lệnh Binance: Entry={res.get('status', 'OK')} (Order ID: {res.get('orderId', 'N/A')})\n"
                            f"   • Căn cứ tín hiệu: {decision.reason}\n"
                            f"{'='*75}"
                        )
                        print(order_msg)
                        with open(log_file, "a") as f: f.write(order_msg + "\n")

                        prev_amt = qty if decision.signal == 1 else -qty
                        prev_equity = equity
                        entry_timestamp = time.time()

            prev_amt = amt

        except Exception as e:
            err_msg = f"[{now_str}] ⚠️ Lỗi vòng lặp daemon: {e}"
            print(err_msg)
            with open(log_file, "a") as f: f.write(err_msg + "\n")

        # Sleep interval with graceful interrupt
        for _ in range(poll_interval):
            if not running:
                break
            time.sleep(1)

    print(f"\n[DAEMON] Đã dừng vòng lặp an toàn.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universal 24/7 Trading Daemon")
    parser.add_argument("--strategy", type=str, default="chien_thuat_3", help="Tên chiến thuật (VD: chien_thuat_3, chien_thuat_4...)")
    parser.add_argument("--interval", type=int, default=25, help="Chu kỳ quét thị trường tính theo giây (mặc định 25s)")
    args = parser.parse_args()

    run_daemon(strategy_name=args.strategy, poll_interval=args.interval)
