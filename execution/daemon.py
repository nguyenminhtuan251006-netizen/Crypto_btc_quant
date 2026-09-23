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
from execution.order_registry import OrderRegistry
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


def run_daemon(strategy_name: str = "chien_thuat_3", poll_interval: int = 25, mode: str = None):
    global running
    resolved_mode = (mode or os.getenv("BINANCE_MODE", "demo")).lower()
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
    client = BinanceDemoClient(api_key, api_secret, base_url=base_url)
    risk_state_file = os.path.join(workspace_dir, "logs", f"kill_switch_{strategy.name}_{resolved_mode}.json")
    registry_file = os.path.join(workspace_dir, "logs", f"trade_registry_{strategy.name}_{resolved_mode}.json")
    risk_mgr = RiskManager(max_leverage=strategy.leverage, state_file=risk_state_file)
    universe_mgr = UniverseManager()
    order_registry = OrderRegistry(registry_file=registry_file)

    log_dir = os.path.join(workspace_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"live_{strategy.name}_{resolved_mode}.log")

    # Initial equity fetch
    acc_info = client.get("/fapi/v2/account")
    equity = float(acc_info.get("totalMarginBalance", 0.0)) if isinstance(acc_info, dict) else 0.0

    # Startup reconciliation with Binance exchange (v3 Review Issue 5)
    startup_sync_msg = order_registry.startup_reconciliation(client)

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

            # Query positions, but manage ONLY bot-registered active trade
            all_pos = client.get("/fapi/v2/positionRisk")
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
            if abs(prev_amt) > 1e-5 and abs(amt) <= 1e-5 and active_trade:
                # Previous bot position has just been closed by TP or SL!
                # Query Realized PnL, Commission, and Funding from Binance API for True Net PnL (Fix #5)
                trade_pnl = equity - prev_equity
                try:
                    income_res = client.get("/fapi/v1/income", {
                        "symbol": active_symbol,
                        "limit": 10
                    })
                    if isinstance(income_res, list) and len(income_res) > 0:
                        cutoff_ms = int((time.time() - 300) * 1000)
                        recent_income = [
                            item for item in income_res
                            if int(item.get("time", 0)) >= cutoff_ms
                            and item.get("incomeType") in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE")
                        ]
                        if recent_income and any(item.get("incomeType") == "REALIZED_PNL" for item in recent_income):
                            net_income = sum(float(item.get("income", 0.0)) for item in recent_income)
                            trade_pnl = net_income
                except Exception:
                    pass

                risk_mgr.record_trade_outcome(trade_pnl, equity)

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

                # --- DYNAMIC EXIT MANAGER (Score Decay, Sign Flip, Trailing) ---
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
                            if active_trade:
                                orphans_cancelled = reconciler.reconcile_trade_closure(active_trade)
                                order_registry.mark_trade_closed(
                                    exit_price=cur_market_price,
                                    net_pnl=unPnl,
                                    close_reason=f"Dynamic Exit: {exit_reason}",
                                )
                            else:
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
                            if hasattr(strategy, 'last_trade_close_time'):
                                strategy.last_trade_close_time = time.time()
                            highest_price_seen = 0.0
                            lowest_price_seen = float('inf')
                            trailing_active = False
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

                        if new_trailing_sl is not None and enable_trailing:
                            new_sl_quantized = universe_mgr.quantize_price(active_symbol, new_trailing_sl)
                            active_tier = getattr(exit_manager, 'last_active_tier', 1)
                            if not trailing_active:
                                trailing_active = True
                                # 1. Hủy TP chốt non cũ để thả cho giá chạy bám trend
                                reconciler.cancel_take_profit(active_trade)
                                # 2. Thiết lập trần bảo hiểm khẩn cấp Wide TP
                                wide_tp_price = universe_mgr.quantize_price(
                                    active_symbol,
                                    entry * (1.0 + wide_tp_pct) if pos_dir == 1 else entry * (1.0 - wide_tp_pct)
                                )
                                reconciler.place_take_profit_order(pos_dir, abs(amt), wide_tp_price)
                                # 3. Cập nhật SL lên khóa lãi
                                reconciler.update_stop_loss(pos_dir, abs(amt), new_sl_quantized)
                                trail_msg = (
                                    f"\n{'*'*75}\n"
                                    f"🚀 [{now_str}] [{strategy.name.upper()}] KÍCH HOẠT TRAILING BẬC THANG TẦNG 1 CHO {active_symbol}:\n"
                                    f"   • Giá hiện tại: ${cur_market_price:,.4f} | Entry: ${entry:,.4f}\n"
                                    f"   • Hủy TP chốt non, đặt trần khẩn cấp (+{wide_tp_pct*100:.1f}%): ${wide_tp_price}\n"
                                    f"   • Khóa cứng SL bảo hộ râu nến (+{tier1_lock_pct*100 if tier1_lock_pct else 1.0:.1f}%): ${new_sl_quantized}\n"
                                    f"{'*'*75}"
                                )
                            else:
                                if active_tier == 2:
                                    trail_msg = f"[{now_str}] 🔥 [TẦNG 2: BÙNG NỔ BÁM ĐỈNH] {active_symbol}: Đỉnh ${highest_price_seen if pos_dir==1 else lowest_price_seen:,.4f} | Dời SL bám theo: ${new_sl_quantized}"
                                else:
                                    trail_msg = f"[{now_str}] 🛡️ [TẦNG 1: BẢO HỘ RÂU NẾN] {active_symbol}: Duy trì SL khóa lãi an toàn: ${new_sl_quantized}"
                                reconciler.update_stop_loss(pos_dir, abs(amt), new_sl_quantized)

                            print(trail_msg)
                            with open(log_file, "a") as f: f.write(trail_msg + "\n")

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

                if not has_regular:
                    target_tp_pct = wide_tp_pct if trailing_active else strategy.take_profit_pct
                    tp_p = universe_mgr.quantize_price(active_symbol, entry * (1.0 + target_tp_pct) if amt > 0 else entry * (1.0 - target_tp_pct))
                    if (amt > 0 and tp_p <= cur_market_price) or (amt < 0 and tp_p >= cur_market_price):
                        tp_p = universe_mgr.quantize_price(active_symbol, cur_market_price * 1.025 if amt > 0 else cur_market_price * 0.975)
                    reconciler.place_take_profit_order(pos_dir, abs(amt), tp_p)
                    prot_msg = f"[{now_str}] 🛡️ [RECONCILER] Đã tự động tái lập TP trên Binance cho {active_symbol}: Qty={abs(amt)} | TP=${tp_p} (Trailing={trailing_active})"
                    print(prot_msg)
                    with open(log_file, "a") as f: f.write(prot_msg + "\n")

                if not has_algo:
                    sl_p = universe_mgr.quantize_price(active_symbol, entry * (1.0 - strategy.stop_loss_pct) if amt > 0 else entry * (1.0 + strategy.stop_loss_pct))
                    reconciler.update_stop_loss(pos_dir, abs(amt), sl_p)
                    prot_msg = f"[{now_str}] 🛡️ [RECONCILER] Đã tự động tái lập Hard SL trên Binance cho {active_symbol}: Qty={abs(amt)} | SL=${sl_p}"
                    print(prot_msg)
                    with open(log_file, "a") as f: f.write(prot_msg + "\n")

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
                    last_trade_t = trades[0].get("time", 0) / 1000.0
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
                        target_ob = fetch_orderbook(target_sym, limit=5)
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

                        qty = universe_mgr.quantize_qty(target_sym, raw_qty)

                        order_side = "BUY" if decision.signal == 1 else "SELL"

                        # 3. Submit Market Entry Order
                        res = client.place_market_order(target_sym, order_side, qty)
                        
                        # 4. Immediately Place Verified Hard Protection Orders on Binance (Sections 1.2 & 5 & 10)
                        time.sleep(0.4)
                        r_tp, r_sl = reconciler.place_verified_protection_orders(
                            position_side=decision.signal,
                            qty=qty,
                            tp_price=tp_price,
                            sl_price=sl_price,
                            client_order_ids=cids,
                        )

                        # 5. Register in OrderRegistry (Spec Section 11)
                        order_registry.register_new_trade(
                            owner=current_session_name,
                            symbol=target_sym,
                            side=order_side,
                            qty=qty,
                            entry_price=cand_entry_p,
                            tp_price=tp_price,
                            sl_price=sl_price,
                            entry_order_id=res.get("orderId"),
                            sl_order_id=r_sl.get("algoId") if r_sl else None,
                            tp_order_id=r_tp.get("orderId") if r_tp else None,
                            client_order_ids=cids,
                        )

                        order_msg = (
                            f"\n{'='*75}\n"
                            f"🚀 [{now_str}] [{current_session_name}] TỰ ĐỘNG MỞ VỊ THẾ {order_side} {qty} {target_sym} @ ${cand_entry_p:,.2f}\n"
                            f"   • Client Order IDs: Entry={cids['entry_cid']} | TP={cids['tp_cid']} | SL={cids['sl_cid']}\n"
                            f"   • Quản lý vốn: Vốn ${equity:,.2f} USDT | Rủi ro: ${size_info.get('risk_amount_usdt', 0)} USDT ({risk_mgr.risk_fraction*100:.1f}%) | Notional: ${notional:,.1f}\n"
                            f"   • Bảo hiểm Hard TP (+{tp_pct*100:.2f}%): ${tp_price} [LIMIT Reduce-Only]\n"
                            f"   • Bảo hiểm Hard SL (-{sl_pct*100:.2f}%): ${sl_price} [MARK_PRICE Stop-Market Reduce-Only]\n"
                            f"   • Khớp lệnh Binance: Entry={res.get('status', 'OK')} (Order ID: {res.get('orderId', 'N/A')})\n"
                            f"   • Căn cứ tín hiệu: {decision.reason}\n"
                            f"{'='*75}"
                        )
                        print(order_msg)
                        with open(log_file, "a") as f: f.write(order_msg + "\n")

                        # Track daily trade count (Fix #5: prevent fee accumulation)
                        risk_mgr.record_trade_opened()

                        prev_amt = qty if decision.signal == 1 else -qty
                        prev_equity = equity
                        entry_timestamp = time.time()
                        trailing_active = False
                        highest_price_seen = cur_price
                        lowest_price_seen = cur_price

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
