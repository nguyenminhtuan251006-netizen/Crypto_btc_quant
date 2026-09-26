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
import fcntl
import json
from datetime import datetime
from decimal import Decimal, ROUND_UP
import pandas as pd

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(current_dir)
sys.path.insert(0, workspace_dir)

from execution.registry import get_strategy
from execution.afcx_risk_manager import RiskManager
from execution.afcx_order_reconciler import OrderReconciler
from execution.afcx_order_registry import OrderRegistry
from execution.afcx_client import AFCXClient
from chien_thuat.chien_thuat_3.live_trader_demo import load_credentials, BinanceDemoClient
from chien_thuat.chien_thuat_3.paper_trader import (
    fetch_recent_candles,
    fetch_orderbook_l2,
    fetch_recent_trades,
)
from chien_thuat.chien_thuat_4.src.execution_universe import UniverseManager
from chien_thuat.chien_thuat_4.src.dynamic_exit import DynamicExitManager

running = True

def handle_sigterm(signum, frame):
    global running
    print(f"\n[DAEMON] Nhận tín hiệu dừng (Signal {signum}), đang thoát an toàn...")
    running = False

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)


def entry_size_skip_reason(universe_mgr, symbol, qty, price, equity, risk_fraction, stop_pct):
    """Explain exchange-minimum rejection without turning it into a daemon error."""
    metadata = universe_mgr.get_symbol_metadata(symbol)
    min_qty = float(metadata.get("market_min_qty", metadata.get("min_qty", 0.0)))
    min_notional = float(metadata.get("min_notional", 0.0))
    actual_notional = float(qty) * float(price)

    if qty >= min_qty and actual_notional >= min_notional:
        return None

    required_notional = max(min_notional, min_qty * float(price))
    estimated_equity = (
        required_notional * (float(stop_pct) + 0.0014) / float(risk_fraction)
        if risk_fraction > 0 else 0.0
    )
    return (
        f"Vị thế theo ngân sách rủi ro chỉ đạt {actual_notional:.2f} USDT sau làm tròn; "
        f"{symbol} yêu cầu tối thiểu {required_notional:.2f} USDT. "
        f"Với SL {stop_pct*100:.2f}% và risk {risk_fraction*100:.2f}%, "
        f"vốn hiện tại {equity:.2f} USDT; ước tính cần khoảng {estimated_equity:.2f} USDT"
    )


def run_daemon(strategy_name: str = "chien_thuat_5", poll_interval: int = 25, mode: str = None):
    resolved_mode = (mode or os.getenv("BINANCE_MODE", "demo")).lower()
    os.makedirs(os.path.join(workspace_dir, "logs"), exist_ok=True)
    # Both AFCX strategies share an account-level process lock within each mode.
    with open(os.path.join(workspace_dir, "logs", f"afcx_{resolved_mode}.lock"), "a") as account_lock:
        try:
            fcntl.flock(account_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another AFCX daemon owns this account mode") from None
        return _run_daemon(strategy_name, poll_interval, resolved_mode)


def _run_daemon(strategy_name, poll_interval, resolved_mode):
    global running
    print("=" * 95)
    print("      🛡️ UNIVERSAL 24/7 QUANT TRADING DAEMON — SAFETY & RISK ENFORCED")
    print(f"      Chiến thuật hoạt động: {strategy_name.upper()} | Môi trường: {resolved_mode.upper()}")
    print("      Tiêu chuẩn: Institutional Risk & Safety Specification (Binance Futures)")
    print("      Cơ chế: Chạy ngầm độc lập trên Linux Server (Tắt máy tính cá nhân vẫn chạy 24/7)")
    print("=" * 95)

    # 1. Credentials
    api_key, api_secret = load_credentials(mode=resolved_mode)
    if not api_key or not api_secret:
        print(f"[LỖI] Không tìm thấy API Key cho chế độ '{resolved_mode}' trong file .env!")
        return

    # 2. Strategy instantiation
    try:
        strategy = get_strategy(strategy_name)
    except Exception as e:
        print(f"[LỖI KHỞI TẠO CHIẾN THUẬT] {e}")
        return

    # 3. Binance Client, Risk Manager, and Universe Manager
    base_url = "https://fapi.binance.com" if resolved_mode == "live" else "https://demo-fapi.binance.com"
    client = AFCXClient(api_key, api_secret, base_url=base_url)
    risk_state_file = os.path.join(workspace_dir, "logs", f"kill_switch_{strategy.name}_{resolved_mode}.json")
    registry_file = os.path.join(workspace_dir, "logs", f"trade_registry_{strategy.name}_{resolved_mode}.json")
    risk_mgr = RiskManager(max_leverage=strategy.leverage, state_file=risk_state_file,
                           risk_fraction=getattr(strategy, 'risk_fraction', 0.005))
    universe_mgr = UniverseManager()
    universe_mgr.refresh_exchange_metadata(base_url=base_url)
    order_registry = OrderRegistry(registry_file=registry_file)

    log_dir = os.path.join(workspace_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"live_{strategy.name}_{resolved_mode}.log")

    # Initial equity fetch
    acc_info = client.get("/fapi/v2/account")
    equity = float(acc_info.get("totalMarginBalance", 0.0)) if isinstance(acc_info, dict) else 0.0

    # Startup reconciliation with Binance exchange (v3 Review Issue 5)
    startup_sync_msg = "Registry loaded; positions and pending entries reconciled in loop"

    print(f"[Khởi tạo thành công] Chiến thuật: {strategy.name} | Đòn bẩy tối đa: {strategy.leverage}x")
    print(f"[Vốn tài khoản hiện tại]: ${equity:,.2f} USDT")
    print(f"[Cơ chế quản trị rủi ro]: Risk {risk_mgr.risk_fraction*100:.1f}% vốn/lệnh | Dynamic ATR Stops")
    print(f"[Kill Switch Circuit Breaker]: Max {risk_mgr.max_consecutive_losses} lệnh thua | Max {risk_mgr.max_daily_loss_pct*100:.1f}% lỗ/ngày | Max Drawdown {risk_mgr.max_account_drawdown_pct*100:.1f}% | Max {risk_mgr.max_trades_per_day} lệnh/ngày")
    print(f"[Bảo hiểm Binance]: Hard TP/SL ghim trên sàn, Reduce-Only, Mark Price Trigger, Targeted Reconcile")
    print(f"[Order Registry]: {startup_sync_msg}")
    print(f"[Nhật ký realtime]: {log_file}")
    print(f"[Trạng thái]: Bắt đầu vòng lặp giám sát thị trường 24/7...")

    # Write startup banner to log file (stdout is redirected to /dev/null by quant_bot.sh)
    startup_banner = (
        f"\n{'='*95}\n"
        f"      🛡️ UNIVERSAL 24/7 QUANT TRADING DAEMON — SAFETY & RISK ENFORCED\n"
        f"      Chiến thuật hoạt động: {strategy_name.upper()} | Môi trường: {resolved_mode.upper()}\n"
        f"      Khởi tạo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"      Vốn: ${equity:,.2f} USDT | Đòn bẩy: {strategy.leverage}x | Risk: {risk_mgr.risk_fraction*100:.1f}%/lệnh\n"
        f"      Kill Switch: {risk_mgr.max_consecutive_losses} thua liên tiếp | {risk_mgr.max_daily_loss_pct*100:.1f}% lỗ/ngày | {risk_mgr.max_account_drawdown_pct*100:.1f}% drawdown | {risk_mgr.max_trades_per_day} lệnh/ngày\n"
        f"{'='*95}"
    )
    with open(log_file, "a") as f: f.write(startup_banner + "\n")

    prev_amt = 0.0
    prev_equity = equity
    active_symbol = strategy.symbol
    entry_timestamp = time.time()
    all_pos = []  # Fix #2: Initialize to prevent NameError in Step E when no active_trade exists
    consecutive_errors = 0  # Fix #1: Track consecutive API errors for exponential backoff

    # Trailing Take Profit Configuration from Strategy (Two-Tier Ratchet)
    enable_trailing = getattr(strategy, 'enable_trailing', True)
    trailing_activation_pct = getattr(strategy, 'trailing_activation_pct', None)
    trailing_callback_pct = getattr(strategy, 'trailing_callback_pct', None)
    profit_lock_floor_pct = getattr(strategy, 'profit_lock_floor_pct', 0.0010)
    wide_tp_pct = getattr(strategy, 'wide_tp_pct', 0.10)
    tier1_trigger_pct = getattr(strategy, 'tier1_trigger_pct', None)
    tier1_lock_pct = getattr(strategy, 'tier1_lock_pct', None)
    tier2_trigger_pct = getattr(strategy, 'tier2_trigger_pct', None)

    exit_manager = DynamicExitManager(
        trailing_activation_pct=trailing_activation_pct,
        trailing_callback_pct=trailing_callback_pct,
        profit_lock_floor_pct=profit_lock_floor_pct,
        tier1_trigger_pct=tier1_trigger_pct,
        tier1_lock_pct=tier1_lock_pct,
        tier2_trigger_pct=tier2_trigger_pct,
    )
    trailing_active = False
    highest_price_seen = 0.0
    lowest_price_seen = float('inf')

    # Initial check of open position for bot's registered trade ONLY
    active_trade = order_registry.get_active_trade()
    if active_trade:
        active_symbol = active_trade.get("symbol", strategy.symbol)
        all_pos = client.get("/fapi/v2/positionRisk")
        matched = [p for p in all_pos if p.get("symbol") == active_symbol and abs(float(p.get("positionAmt", 0.0))) > 1e-5] if isinstance(all_pos, list) else []
        if matched:
            prev_amt = float(matched[0].get("positionAmt", 0.0))
            entry_timestamp = active_trade["entry_time"]
            highest_price_seen = active_trade.get("highest_price", active_trade["entry_price"])
            lowest_price_seen = active_trade.get("lowest_price", active_trade["entry_price"])
            trailing_active = active_trade.get("trailing_active", False)

    iteration = 0
    while running:
        iteration += 1
        now_dt = datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Step A0: Session boundary detection & session profile resolution (v3 Section 2 & Review Issue 1)
            current_session_name = "DEFAULT"
            session_max_spread = None
            if hasattr(strategy, 'session_mgr'):
                active_profile = strategy.session_mgr.resolve_session()
                current_session_name = active_profile.name
                session_max_spread = active_profile.max_spread_pct

                if strategy.session_mgr.detect_session_boundary_crossed():
                    boundary_msg = (
                        f"\n{'='*75}\n"
                        f"🔄 [{now_str}] CHUYỂN PHIÊN GIAO DỊCH: Bắt đầu phiên {current_session_name}\n"
                        f"   • Reset bộ đếm chuỗi thua liên tiếp (consecutive_losses = 0)\n"
                        f"   • Giữ nguyên tổng lỗ trong ngày (daily_loss_amount) để bảo toàn vốn\n"
                        f"   • Áp dụng ngưỡng: Trend Z={active_profile.trend_z_min} | Gap={active_profile.confidence_gap_min} | Spread={active_profile.max_spread_pct*100:.2f}%\n"
                        f"{'='*75}"
                    )
                    print(boundary_msg)
                    with open(log_file, "a") as f: f.write(boundary_msg + "\n")
                    risk_mgr.session_boundary_reset(current_session_name)

            # Step A: Query live account equity and position from Binance
            acc_info = client.get("/fapi/v2/account")
            if isinstance(acc_info, dict) and "totalMarginBalance" in acc_info:
                equity = float(acc_info["totalMarginBalance"])
            else:
                raise RuntimeError("Account balance unavailable")

            # Query positions, but manage ONLY bot-registered active trade
            all_pos = client.get("/fapi/v2/positionRisk")
            if not isinstance(all_pos, list):
                raise RuntimeError("Position state unavailable; refusing to infer flat")
            active_trade = order_registry.get_active_trade()
            if active_trade:
                active_symbol = active_trade.get("symbol", strategy.symbol)
                matched = [p for p in all_pos if p.get("symbol") == active_symbol and abs(float(p.get("positionAmt", 0.0))) > 1e-5] if isinstance(all_pos, list) else []
                if matched:
                    amt = float(matched[0].get("positionAmt", 0.0))
                    entry = float(matched[0].get("entryPrice", 0.0))
                    unPnl = float(matched[0].get("unRealizedProfit", 0.0))
                else:
                    amt = 0.0
                    entry = 0.0
                    unPnl = 0.0
            else:
                # Bot does NOT own any active trade.
                # Any positions on Binance belong to manual trades or vouchers — DO NOT TOUCH!
                amt = 0.0
                entry = 0.0
                unPnl = 0.0
                active_symbol = strategy.symbol

            reconciler = OrderReconciler(client, symbol=active_symbol)

            # Step B: Position Reconciliation & Trade Settlement (Only for bot's registered trade)
            if abs(amt) <= 1e-5 and active_trade:
                if active_trade.get("entry_pending"):
                    # An uncertain entry must never be retried blindly.
                    entry_order = client.get("/fapi/v1/order", {
                        "symbol": active_symbol,
                        "origClientOrderId": active_trade["client_order_ids"]["entry_cid"],
                    })
                    if entry_order.get("status") not in {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
                        raise RuntimeError("Entry outcome unresolved; entry remains locked")
                    if float(entry_order.get("executedQty", 0)) == 0:
                        order_registry.mark_trade_closed(close_reason="Entry not filled")
                        continue
                # Previous bot position has just been closed by TP or SL!
                # Query Realized PnL, Commission, and Funding from Binance API for True Net PnL (Fix #5)
                income_res = client.get("/fapi/v1/income", {
                    "symbol": active_symbol, "startTime": int(active_trade["entry_time"] * 1000),
                    "limit": 1000,
                })
                if not isinstance(income_res, list) or len(income_res) >= 1000:
                    raise RuntimeError("Settlement incomplete; keep position registry locked")
                if not any(item.get("incomeType") == "REALIZED_PNL" for item in income_res):
                    raise RuntimeError("Waiting for realized PnL before settlement")
                trade_pnl = sum(float(item["income"]) for item in income_res
                                if item.get("incomeType") in {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"})
                risk_mgr.record_trade_outcome(trade_pnl, equity, trade_id=active_trade["trade_id"])

                # v3 Normal Reconcile: Cancel by registered order IDs (Spec Section 12 & 13)
                orphans_cancelled = reconciler.reconcile_trade_closure(active_trade)
                order_registry.mark_trade_closed(
                    exit_price=0.0,
                    net_pnl=trade_pnl,
                    close_reason="TP/SL Hit on Binance",
                )

                close_banner = (
                    f"\n{'='*75}\n"
                    f"🎯 [{now_str}] [{strategy.name.upper()}] VỊ THẾ {active_symbol} ĐÃ HOÀN TẤT CHỐT LỜI / CẮT LỖ:\n"
                    f"   • Phiên sở hữu: {active_trade.get('owner', current_session_name) if active_trade else current_session_name}\n"
                    f"   • Lãi/Lỗ thực tế (Net PnL): {trade_pnl:+.4f} USDT\n"
                    f"   • Vốn khả dụng mới: ${equity:,.2f} USDT\n"
                    f"   • Reconciler: Đã hủy {orphans_cancelled} lệnh treo đối ứng (Targeted cancel + Zero-Orphan guarantee)\n"
                    f"{'='*75}"
                )
                print(close_banner)
                with open(log_file, "a") as f: f.write(close_banner + "\n")
                prev_equity = equity

                # Signal cooldown to strategy (Review Issue 4: persists across session boundary)
                if hasattr(strategy, 'last_trade_close_time'):
                    strategy.last_trade_close_time = time.time()

                # Reset tracking
                highest_price_seen = 0.0
                lowest_price_seen = float('inf')
                trailing_active = False

            # Step C: Active Position Management
            if abs(amt) > 1e-5:
                # Currently in an active trade
                pos_dir = 1 if amt > 0 else -1
                cur_market_price = float(fetch_recent_candles(active_symbol, limit=1).iloc[-1]["close"])

                # Track extreme prices for trailing stop
                highest_price_seen = max(highest_price_seen, cur_market_price)
                lowest_price_seen = min(lowest_price_seen, cur_market_price)
                actual_sl_pct = active_trade.get("initial_sl_pct", abs(entry - active_trade["sl_price"]) / entry)
                entry_timestamp = active_trade["entry_time"]
                order_registry.update_active_state(highest_price=highest_price_seen, lowest_price=lowest_price_seen,
                                                   entry_pending=False)

                # --- Protection Order Reconciliation ---
                orders = client.get("/fapi/v1/openOrders", {"symbol": active_symbol})
                algos = client.get("/fapi/v1/openAlgoOrders", {"symbol": active_symbol})

                # Check if protection orders are missing on Binance
                if not isinstance(orders, list) or not isinstance(algos, list):
                    raise RuntimeError("Protection order state unavailable")
                active_trade = order_registry.get_active_trade()
                has_regular = any(str(o.get("orderId")) == str(active_trade.get("tp_order_id")) for o in orders)
                has_algo = any(str(o.get("algoId")) == str(active_trade.get("sl_order_id")) for o in algos)

                if not has_algo:
                    sl_p = active_trade["sl_price"]
                    if (pos_dir == 1 and sl_p >= cur_market_price) or (pos_dir == -1 and sl_p <= cur_market_price):
                        client.place_market_order(active_symbol, "SELL" if pos_dir == 1 else "BUY", abs(amt), reduce_only=True)
                        continue
                    result = reconciler.update_stop_loss(pos_dir, abs(amt), sl_p)
                    order_registry.update_active_state(sl_order_id=result["algoId"])
                    prot_msg = f"[{now_str}] 🛡️ [RECONCILER] Đã tự động tái lập Hard SL trên Binance cho {active_symbol}: Qty={abs(amt)} | SL=${sl_p}"
                    print(prot_msg)
                    with open(log_file, "a") as f: f.write(prot_msg + "\n")


                if not has_regular:
                    tp_p = active_trade["tp_price"]
                    if (amt > 0 and tp_p <= cur_market_price) or (amt < 0 and tp_p >= cur_market_price):
                        tp_p = universe_mgr.quantize_price(active_symbol, cur_market_price * 1.025 if amt > 0 else cur_market_price * 0.975)
                    result = reconciler.place_take_profit_order(pos_dir, abs(amt), tp_p)
                    if not result.get("orderId"):
                        raise RuntimeError("Take-profit not confirmed")
                    order_registry.update_active_state(tp_order_id=result["orderId"], tp_price=tp_p)
                    prot_msg = f"[{now_str}] 🛡️ [RECONCILER] Đã tự động tái lập TP trên Binance cho {active_symbol}: Qty={abs(amt)} | TP=${tp_p} (Trailing={trailing_active})"
                    print(prot_msg)
                    with open(log_file, "a") as f: f.write(prot_msg + "\n")


                # --- DYNAMIC EXIT MANAGER (Score Decay, Sign Flip, Trailing) ---
                active_trade = order_registry.get_active_trade()
                # Re-score current position by refreshing ranking periodically (every 120s)
                try:
                    now_ts = time.time()
                    last_refresh = getattr(strategy, '_last_hold_refresh_ts', 0.0)
                    if (now_ts - last_refresh > 120.0):
                        if hasattr(strategy, 'refresh_ranking'):
                            strategy.refresh_ranking()
                        elif hasattr(strategy, 'strat') and hasattr(strategy.strat, 'scan_and_rank_universe'):
                            strategy.strat.scan_and_rank_universe()
                        strategy._last_hold_refresh_ts = now_ts

                    ranking_list = getattr(strategy, 'cached_ranking', [])
                    if ranking_list:
                        # Find current rank and score of active symbol
                        current_score = 0.0
                        current_rank = 99
                        for rank_idx, r in enumerate(ranking_list):
                            if r["symbol"] == active_symbol:
                                # Fix #1: Keep raw score. dynamic_exit.py already checks
                                # (pos_dir == 1 and score < -0.20) or (pos_dir == -1 and score > 0.20).
                                # Multiplying by pos_dir was inverting SHORT scores and causing instant false exits!
                                current_score = float(r["final_score"])
                                current_rank = rank_idx + 1
                                break

                        if current_rank == 99:
                            raise RuntimeError("Held symbol absent from fresh ranking; retain protection")

                        should_exit, exit_reason = exit_manager.check_dynamic_exit(
                            entry_time=entry_timestamp,
                            entry_price=entry,
                            current_price=cur_market_price,
                            position_direction=pos_dir,
                            sl_distance_pct=actual_sl_pct,
                            current_score=current_score,
                            current_rank=current_rank,
                        )

                        if should_exit:
                            # Close position via market order
                            close_side = "SELL" if pos_dir == 1 else "BUY"
                            close_res = client.place_market_order(active_symbol, close_side, abs(amt), reduce_only=True)
                            # Step B confirms flat, settles PnL and cancels protection.
                            orphans_cancelled = 0

                            exit_msg = (
                                f"\n{'='*75}\n"
                                f"🧠 [{now_str}] [DYNAMIC EXIT] {exit_reason}\n"
                                f"   • Đóng vị thế {active_symbol} bằng lệnh thị trường\n"
                                f"   • Đã hủy {orphans_cancelled} lệnh treo đối ứng (Targeted)\n"
                                f"{'='*75}"
                            )
                            print(exit_msg)
                            with open(log_file, "a") as f: f.write(exit_msg + "\n")
                            prev_amt = amt
                            time.sleep(poll_interval)
                            continue

                        # Check trailing stop update
                        atr_5m_pct = actual_sl_pct / 1.2
                        new_trailing_sl = exit_manager.calculate_trailing_stop(
                            entry_price=entry,
                            current_price=cur_market_price,
                            position_direction=pos_dir,
                            sl_distance_pct=actual_sl_pct,
                            atr_5m_pct=atr_5m_pct,
                            current_highest_price=highest_price_seen,
                            current_lowest_price=lowest_price_seen,
                        )

                        if new_trailing_sl is not None and enable_trailing:
                            new_sl = universe_mgr.quantize_price(active_symbol, new_trailing_sl)
                            previous_sl = active_trade["sl_price"]
                            improves = new_sl > previous_sl if pos_dir == 1 else new_sl < previous_sl
                            valid = new_sl < cur_market_price if pos_dir == 1 else new_sl > cur_market_price
                            if improves and valid:
                                # Save the new ID before attempting cancellation of the old stop.
                                result = reconciler.update_stop_loss(pos_dir, abs(amt), new_sl)
                                old_id = active_trade.get("sl_order_id")
                                order_registry.update_active_state(sl_order_id=result["algoId"],
                                                                   sl_price=new_sl, trailing_active=True)
                                trailing_active = True
                                if old_id:
                                    client.delete("/fapi/v1/algoOrder", {"algoId": old_id})
                                print(f"[{now_str}] TRAILING {active_symbol}: SL={new_sl}")
                except Exception as e:
                    exit_err = f"[{now_str}] ⚠️ Dynamic Exit check error: {e}"
                    print(exit_err)
                    with open(log_file, "a") as f: f.write(exit_err + "\n")

                owner_info = f" [{order_registry.get_owner()}]" if order_registry.get_owner() else ""
                side_str = "LONG" if amt > 0 else "SHORT"
                status_line = f"[{now_str}] [{strategy.name.upper()}{owner_info}] Vị thế đang chạy: {side_str} {abs(amt)} {active_symbol} @ ${entry:,.2f} | Lãi/Lỗ: {unPnl:+.4f} USDT | Vốn: ${equity:,.2f} USDT"
                print(status_line)
                with open(log_file, "a") as f: f.write(status_line + "\n")

            else:
                # Step D: Flat (No Active Position) — Ready to evaluate new setup
                # Clean up any leftover orphan orders for bot's registered trade ONLY
                active_trade = order_registry.get_active_trade()
                if active_trade:
                    orphans = reconciler.reconcile_trade_closure(active_trade)
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
                    last_trade_t = max(t.get("time", 0) for t in trades) / 1000.0
                    freshness_sec = max(0.0, time.time() - last_trade_t)

                # Check Account-Level Kill Switch (Section 8 + v3 Session-Adaptive Spread Filter)
                can_trade, ks_msg = risk_mgr.check_kill_switch(
                    current_equity=equity,
                    current_spread_pct=spread_pct,
                    data_freshness_seconds=freshness_sec,
                    session_max_spread_pct=session_max_spread,
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
                    with open(os.path.join(log_dir, f"decisions_{strategy.name}_{resolved_mode}.jsonl"), "a") as journal:
                        journal.write(json.dumps({"time": now_str, "signal": decision.signal,
                            "reason": decision.reason, "metrics": decision.extra_metrics}, default=str) + "\n")
                    status_line = f"[{now_str}] [{strategy.name.upper()}] BTC: ${cur_price:,.1f} | Quyết định: {decision.reason}"
                    print(status_line)
                    with open(log_file, "a") as f: f.write(status_line + "\n")

                    # Step E: Trigger New Position if Signal fires (Section 13)
                    if decision.signal != 0:
                        # Global Position Lock Check (Spec Section 7 & 8)
                        if order_registry.is_locked():
                            lock_msg = f"[{now_str}] 🔒 POSITION LOCK: Đang có vị thế đang chạy ({order_registry.get_owner()}), không mở vị thế mới (MAX_OPEN_POSITIONS = 1)"
                            print(lock_msg)
                            with open(log_file, "a") as f: f.write(lock_msg + "\n")
                            time.sleep(poll_interval)
                            continue

                        target_sym = decision.extra_metrics.get("selected_symbol", strategy.symbol) if decision.extra_metrics else strategy.symbol

                        # Safety: Do not open if user has a manual/voucher position in this exact symbol
                        if isinstance(all_pos, list):
                            manual_same_sym = [p for p in all_pos if p.get("symbol") == target_sym and abs(float(p.get("positionAmt", 0.0))) > 1e-5]
                            if manual_same_sym:
                                skip_msg = f"[{now_str}] ℹ️ BỎ QUA {target_sym}: Tài khoản đang có sẵn vị thế thủ công/voucher trên cặp này, bot không mở đè."
                                print(skip_msg)
                                with open(log_file, "a") as f: f.write(skip_msg + "\n")
                                time.sleep(poll_interval)
                                continue
                        active_symbol = target_sym
                        reconciler = OrderReconciler(client, symbol=target_sym)

                        # Fix #4: Check actual spread on target altcoin itself to prevent slippage
                        target_ob = fetch_orderbook_l2(target_sym, limit=5)
                        cand_entry_p = decision.extra_metrics.get("candidate", {}).get("current_price", cur_price) if decision.extra_metrics else cur_price
                        if target_ob and target_ob.get("bids") and target_ob.get("asks"):
                            t_bid = float(target_ob["bids"][0][0])
                            t_ask = float(target_ob["asks"][0][0])
                            cand_entry_p = (t_bid + t_ask) / 2.0
                            alt_spread = (t_ask - t_bid) / cand_entry_p
                            effective_spread_limit = session_max_spread or risk_mgr.max_spread_pct
                            if alt_spread > effective_spread_limit:
                                sp_skip_msg = f"[{now_str}] ⚠️ BỎ QUA {target_sym}: Spread thực tế ({alt_spread*100:.3f}%) vượt ngưỡng tối đa ({effective_spread_limit*100:.3f}%), dừng vào lệnh."
                                print(sp_skip_msg)
                                with open(log_file, "a") as f: f.write(sp_skip_msg + "\n")
                                time.sleep(poll_interval)
                                continue

                        client.init_account_settings(target_sym, leverage=strategy.leverage)

                        # Generate client order IDs with session prefix (Spec Section 10)
                        cids = order_registry.generate_client_order_ids(owner=current_session_name)

                        # Determine target price and stops
                        sl_pct = decision.sl_pct

                        # Fix #2: Unify TP and Trailing Ratchet.
                        # When enable_trailing is True, place Wide TP ceiling on Binance (+8%) so the exchange
                        # does not execute prematurely before the 2-tier trailing ratchet (+1.2%/+1.8%) can operate!
                        if enable_trailing:
                            effective_tp_pct = wide_tp_pct
                        else:
                            effective_tp_pct = decision.tp_pct or (sl_pct * 1.8)

                        sl_price = decision.sl_price or universe_mgr.quantize_price(target_sym, cand_entry_p * (1.0 - sl_pct) if decision.signal == 1 else cand_entry_p * (1.0 + sl_pct))
                        tp_price = universe_mgr.quantize_price(target_sym, cand_entry_p * (1.0 + effective_tp_pct) if decision.signal == 1 else cand_entry_p * (1.0 - effective_tp_pct))

                        # 2. Compute Risk-Based Position Sizing (Section 2 & 19 + Micro-Capital support)
                        min_notional_param = getattr(strategy, 'min_notional_target', 0.0)
                        raw_qty, notional, size_info = risk_mgr.calculate_position_size(
                            equity=equity,
                            stop_distance_pct=sl_pct,
                            current_price=cand_entry_p,
                            min_notional=min_notional_param,
                        )

                        # 2b. Dynamic Position Multiplier (Multi-Agent Analyzer §9)
                        # Scale position size based on conviction score: stronger signal = bigger size
                        score_100 = decision.extra_metrics.get("score_100", 85) if decision.extra_metrics else 85
                        if score_100 >= 85:
                            position_multiplier = 1.0
                        elif score_100 >= 75:
                            position_multiplier = 0.7
                        else:
                            position_multiplier = 0.5  # Safety fallback for edge cases
                        # Skip multiplier for micro-capital mode (already at floor notional)
                        if min_notional_param <= 0:
                            raw_qty = raw_qty * position_multiplier
                            size_info["position_multiplier"] = position_multiplier
                            size_info["score_100"] = score_100

                        universe_mgr.refresh_exchange_metadata(base_url=base_url)
                        qty = universe_mgr.quantize_qty(target_sym, raw_qty)

                        # Micro-Capital smart clamp to exchange minimums if within safe max risk
                        is_micro = getattr(strategy, 'micro_capital_mode', False)
                        if is_micro:
                            metadata = universe_mgr.get_symbol_metadata(target_sym)
                            min_sym_qty = float(metadata.get("market_min_qty", metadata.get("min_qty", 0.0)))
                            min_sym_notional = float(metadata.get("min_notional", 0.0))
                            step_size = float(metadata.get("market_step_size", metadata.get("step_size", 0.001)))
                            actual_notional = qty * cand_entry_p

                            if qty < min_sym_qty or actual_notional < min_sym_notional:
                                target_notional_min = max(min_sym_notional, min_sym_qty * cand_entry_p)
                                needed_raw = target_notional_min / cand_entry_p
                                step_dec = Decimal(str(step_size))
                                candidate_qty = float((Decimal(str(needed_raw)) / step_dec).to_integral_value(rounding=ROUND_UP) * step_dec)
                                candidate_qty = max(candidate_qty, min_sym_qty)
                                candidate_notional = candidate_qty * cand_entry_p

                                max_micro_risk = getattr(strategy, 'max_micro_risk_fraction', 0.018)
                                potential_risk_usdt = candidate_notional * (sl_pct + 0.0014)
                                risk_ratio = potential_risk_usdt / equity if equity > 0 else 1.0

                                if risk_ratio <= max_micro_risk:
                                    clamp_msg = (
                                        f"[{now_str}] ℹ️ [MICRO-CAPITAL] Tự động nâng vị thế lên sàn tối thiểu của {target_sym}: "
                                        f"{candidate_qty} (~{candidate_notional:.2f} USDT). Rủi ro SL: {risk_ratio*100:.2f}% vốn "
                                        f"(<= ngưỡng an toàn {max_micro_risk*100:.1f}%)."
                                    )
                                    print(clamp_msg)
                                    with open(log_file, "a") as f:
                                        f.write(clamp_msg + "\n")
                                    qty = candidate_qty

                        size_skip = entry_size_skip_reason(
                            universe_mgr=universe_mgr,
                            symbol=target_sym,
                            qty=qty,
                            price=cand_entry_p,
                            equity=equity,
                            risk_fraction=risk_mgr.risk_fraction,
                            stop_pct=sl_pct,
                        )
                        if size_skip:
                            skip_msg = (
                                f"[{now_str}] ℹ️ BỎ QUA {target_sym}: {size_skip}. "
                                "Bot không tự nâng vị thế vượt ngân sách rủi ro."
                            )
                            print(skip_msg)
                            with open(log_file, "a") as f:
                                f.write(skip_msg + "\n")
                            time.sleep(poll_interval)
                            continue

                        universe_mgr.validate_entry(target_sym, qty, cand_entry_p)
                        required_margin = qty * cand_entry_p / strategy.leverage
                        if required_margin + qty * cand_entry_p * 0.0014 > float(acc_info.get("availableBalance", 0)):
                            raise ValueError("Insufficient available margin including fee buffer")

                        order_side = "BUY" if decision.signal == 1 else "SELL"

                        # Persist ownership BEFORE submission so timeout/restart cannot duplicate entry.
                        order_registry.register_new_trade(
                            owner=current_session_name, symbol=target_sym, side=order_side,
                            qty=qty, entry_price=cand_entry_p, tp_price=tp_price, sl_price=sl_price,
                            client_order_ids=cids, entry_pending=True,
                        )
                        order_registry.update_active_state(entry_pending=True, initial_sl_pct=sl_pct,
                                                           highest_price=cand_entry_p, lowest_price=cand_entry_p)
                        risk_mgr.record_trade_opened()
                        res = client.place_market_order(target_sym, order_side, qty,
                                                        client_order_id=cids["entry_cid"])
                        if res.get("status") != "FILLED" or float(res.get("executedQty", 0)) <= 0:
                            raise RuntimeError("Entry not confirmed FILLED; ownership retained")
                        qty = float(res["executedQty"])
                        cand_entry_p = float(res.get("avgPrice") or cand_entry_p)
                        sl_price = universe_mgr.quantize_price(target_sym, cand_entry_p * (1 - decision.signal * sl_pct))
                        tp_price = universe_mgr.quantize_price(target_sym, cand_entry_p * (1 + decision.signal * effective_tp_pct))
                        order_registry.update_active_state(entry_pending=False, entry_order_id=res["orderId"],
                            entry_price=cand_entry_p, qty=qty, sl_price=sl_price, tp_price=tp_price)
                        # Stop first. Any failure leaves the owned position available for recovery.
                        r_sl = reconciler.update_stop_loss(decision.signal, qty, sl_price, sl_cid=cids["sl_cid"])
                        order_registry.update_active_state(sl_order_id=r_sl["algoId"])
                        r_tp = reconciler.place_take_profit_order(decision.signal, qty, tp_price, tp_cid=cids["tp_cid"])
                        if not r_tp.get("orderId"):
                            raise RuntimeError("Take-profit not confirmed")
                        order_registry.update_active_state(tp_order_id=r_tp["orderId"])

                        order_msg = (
                            f"\n{'='*75}\n"
                            f"🚀 [{now_str}] [{current_session_name}] TỰ ĐỘNG MỞ VỊ THẾ {order_side} {qty} {target_sym} @ ${cand_entry_p:,.2f}\n"
                            f"   • Client Order IDs: Entry={cids['entry_cid']} | TP={cids['tp_cid']} | SL={cids['sl_cid']}\n"
                            f"   • Quản lý vốn: Vốn ${equity:,.2f} USDT | Rủi ro: ${size_info.get('risk_amount_usdt', 0)} USDT ({risk_mgr.risk_fraction*100:.1f}%) | Notional: ${notional:,.1f}\n"
                            f"   • Bảo hiểm Hard TP (+{effective_tp_pct*100:.2f}%): ${tp_price} [LIMIT Reduce-Only]\n"
                            f"   • Bảo hiểm Hard SL (-{sl_pct*100:.2f}%): ${sl_price} [MARK_PRICE Stop-Market Reduce-Only]\n"
                            f"   • Khớp lệnh Binance: Entry={res.get('status', 'OK')} (Order ID: {res.get('orderId', 'N/A')})\n"
                            f"   • Căn cứ tín hiệu: {decision.reason}\n"
                            f"{'='*75}"
                        )
                        print(order_msg)
                        with open(log_file, "a") as f: f.write(order_msg + "\n")

                        # Track daily trade count (Fix #5: prevent fee accumulation)

                        prev_amt = qty if decision.signal == 1 else -qty
                        prev_equity = equity
                        entry_timestamp = time.time()
                        trailing_active = False
                        highest_price_seen = cand_entry_p
                        lowest_price_seen = cand_entry_p
                        amt = prev_amt

            prev_amt = amt
            consecutive_errors = 0  # Reset error count on successful iteration

        except Exception as e:
            consecutive_errors += 1
            # Exponential backoff: 25s -> 50s -> 100s -> 200s -> max 300s
            backoff_secs = min(poll_interval * (2 ** (consecutive_errors - 1)), 300)
            err_msg = f"[{now_str}] ⚠️ Lỗi vòng lặp daemon (#{consecutive_errors}): {e} — Tạm nghỉ {backoff_secs}s trước khi thử lại..."
            print(err_msg)
            with open(log_file, "a") as f: f.write(err_msg + "\n")

            for _ in range(backoff_secs):
                if not running:
                    break
                time.sleep(1)
            continue

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
    parser.add_argument("--mode", type=str, default=None, choices=["demo", "live"], help="Chế độ giao dịch (demo hoặc live)")
    args = parser.parse_args()

    run_daemon(strategy_name=args.strategy, poll_interval=args.interval, mode=args.mode)
