"""
Comparative Backtest: Current Baseline vs Proposed Relaxed Thresholds
=====================================================================
Evaluates the exact user proposal:
- LIQUID + RANGE: 1.65 -> 1.55
- ASIA + RANGE:   1.75 -> 1.65
- All other parameters identical (LIQUID+TREND=1.50, ASIA+TREND=1.60,
  Consensus 4/6 & 5/6, Persistence=2, Gap=0.30/0.35, FLAT/STRESS blocked).

Runs on:
1. Out-Of-Sample Recent 21 Days (04/09/2026 -> 25/09/2026, 6,000 bars, 15 altcoins)
2. Full 1-Year Multi-Season (105,000 bars, 12 altcoins)
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta, time
from typing import Dict, List, Any, Tuple

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir.endswith("scratch"):
    base_dir = os.path.dirname(base_dir)
# Workspace root
workspace_dir = "/home/tuannm/crypto_btc_quant_lab"
sys.path.insert(0, workspace_dir)

from chien_thuat.chien_thuat_4.src.regime_engine import MarketRegimeEngine
from chien_thuat.chien_thuat_4.src.cross_sectional_ranker import CrossSectionalRanker
from chien_thuat.chien_thuat_4.src.dynamic_exit import DynamicExitManager
from chien_thuat.chien_thuat_4.run_backtest import compute_indicators

def get_vn_time(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # data in unseen is already in Vietnam time or needs conversion
        return dt
    vn_tz = timezone(timedelta(hours=7))
    return dt.astimezone(vn_tz)

def resolve_session_name(cur_dt: datetime) -> str:
    # 04:00 <= VN Time < 15:00 is ASIA, else LIQUID
    hour = cur_dt.hour
    minute = cur_dt.minute
    t = time(hour, minute)
    if time(4, 0) <= t < time(15, 0):
        return "ASIA"
    return "LIQUID"

def run_simulation_engine(
    datasets: Dict[str, pd.DataFrame],
    symbols: List[str],
    n_bars: int,
    config: Dict[str, Any],
    initial_equity: float = 10.0,
    position_notional: float = 15.0,
    taker_fee: float = 0.0005,
    slippage: float = 0.0002,
) -> Dict[str, Any]:
    """
    Simulates AFCX trading logic with specified config.
    """
    regime_engine = MarketRegimeEngine()
    ranker = CrossSectionalRanker()
    exit_mgr = DynamicExitManager(
        tier1_trigger_pct=0.012,
        tier1_lock_pct=0.010,
        tier2_trigger_pct=0.018,
        trailing_callback_pct=0.0045,
        max_duration_seconds=3 * 3600
    )

    # Resample BTC to 1H
    btc_df_raw = datasets["BTCUSDT"].copy()
    btc_1h = btc_df_raw.set_index("datetime").resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()

    equity = initial_equity
    peak_equity = equity
    day_start_equity = equity
    current_day = None

    active_position = None
    last_trade_close_bar = -999

    consecutive_losses = 0
    max_consecutive_losses = 0
    daily_trades_count = 0
    is_killed = False
    kill_reason = ""

    # ASIA persistence tracking: candidate symbol, direction, count
    prev_asia_sym = None
    prev_asia_dir = None
    asia_hit_count = 0

    trades = []
    equity_curve = []
    
    # Gate rejection counters
    blocked_by_regime = 0
    blocked_by_score = 0
    blocked_by_gap = 0
    blocked_by_consensus = 0
    blocked_by_cost = 0
    blocked_by_persistence = 0

    wide_tp_pct = 0.08
    roundtrip_cost = (taker_fee + slippage) * 2

    for i in range(50, n_bars):
        current_dt = datasets["BTCUSDT"].iloc[i]["datetime"]
        day_str = current_dt.strftime("%Y-%m-%d")

        if day_str != current_day:
            current_day = day_str
            day_start_equity = equity
            daily_trades_count = 0
            if is_killed and "drawdown" not in kill_reason.lower():
                is_killed = False
                kill_reason = ""

        if equity > peak_equity:
            peak_equity = equity

        sess_name = resolve_session_name(current_dt)

        # --- MANAGE POSITION ---
        if active_position is not None:
            sym = active_position["symbol"]
            pos_dir = active_position["direction"]
            entry_p = active_position["entry_price"]
            entry_bar = active_position["entry_bar"]
            sl_p = active_position["sl_price"]
            tp_p = active_position["tp_price"]

            bar_df = datasets[sym].iloc[i]
            cur_open = bar_df["open"]
            cur_high = bar_df["high"]
            cur_low = bar_df["low"]
            cur_close = bar_df["close"]

            if pos_dir == 1:
                active_position["highest_price"] = max(active_position["highest_price"], cur_high)
            else:
                active_position["lowest_price"] = min(active_position["lowest_price"], cur_low)

            new_sl = exit_mgr.calculate_trailing_stop(
                entry_price=entry_p,
                current_price=cur_close,
                position_direction=pos_dir,
                sl_distance_pct=active_position["sl_pct"],
                atr_5m_pct=bar_df["atr_pct"],
                current_highest_price=active_position["highest_price"],
                current_lowest_price=active_position["lowest_price"]
            )
            if new_sl is not None:
                if pos_dir == 1 and new_sl > active_position["sl_price"]:
                    active_position["sl_price"] = new_sl
                    active_position["trailing_active"] = True
                elif pos_dir == -1 and new_sl < active_position["sl_price"]:
                    active_position["sl_price"] = new_sl
                    active_position["trailing_active"] = True

            closed = False
            exit_p = 0.0
            exit_reason = ""

            if pos_dir == 1:
                if cur_low <= active_position["sl_price"]:
                    exit_p = active_position["sl_price"]
                    exit_reason = "STOP_LOSS (Locked)" if active_position.get("trailing_active") else "STOP_LOSS"
                    closed = True
                elif cur_high >= tp_p:
                    exit_p = tp_p
                    exit_reason = "WIDE_TAKE_PROFIT"
                    closed = True
            else:
                if cur_high >= active_position["sl_price"]:
                    exit_p = active_position["sl_price"]
                    exit_reason = "STOP_LOSS (Locked)" if active_position.get("trailing_active") else "STOP_LOSS"
                    closed = True
                elif cur_low <= tp_p:
                    exit_p = tp_p
                    exit_reason = "WIDE_TAKE_PROFIT"
                    closed = True

            if not closed:
                elapsed_sec = (i - entry_bar) * 300
                score_now = (bar_df["m_1h"] * 50) + (bar_df["m_4h"] * 30)
                should_dyn_exit, dyn_reason = exit_mgr.check_dynamic_exit(
                    entry_time=0,
                    entry_price=entry_p,
                    current_price=cur_close,
                    position_direction=pos_dir,
                    sl_distance_pct=active_position["sl_pct"],
                    current_score=score_now,
                    current_rank=1
                )
                if should_dyn_exit and elapsed_sec >= 15 * 60:
                    exit_p = cur_close
                    exit_reason = f"DYN_EXIT ({dyn_reason[:20]})"
                    closed = True
                elif elapsed_sec >= 3 * 3600:
                    exit_p = cur_close
                    exit_reason = "TIME_STOP_3H"
                    closed = True

            if closed:
                ret_pct = ((exit_p - entry_p) / entry_p) if pos_dir == 1 else ((entry_p - exit_p) / entry_p)
                gross_pnl = ret_pct * position_notional
                total_fee = position_notional * roundtrip_cost
                net_pnl = gross_pnl - total_fee
                equity += net_pnl

                if net_pnl > 0:
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)

                trades.append({
                    "entry_time": active_position["entry_time"],
                    "exit_time": current_dt,
                    "symbol": sym,
                    "direction": "LONG" if pos_dir == 1 else "SHORT",
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "exit_reason": exit_reason,
                    "ret_pct": ret_pct * 100,
                    "net_pnl": net_pnl,
                    "equity": equity,
                    "trailing_active": active_position.get("trailing_active", False)
                })

                active_position = None
                last_trade_close_bar = i

                if consecutive_losses >= 3:
                    is_killed = True
                    kill_reason = "Kill Switch: 3 consecutive losses"
                elif day_start_equity > 0 and (day_start_equity - equity) / day_start_equity >= 0.02:
                    is_killed = True
                    kill_reason = "Kill Switch: 2% daily loss"
                elif peak_equity > 0 and (peak_equity - equity) / peak_equity >= 0.06:
                    is_killed = True
                    kill_reason = "Kill Switch: 6% total drawdown"

            equity_curve.append({"datetime": current_dt, "equity": equity})
            continue

        equity_curve.append({"datetime": current_dt, "equity": equity})

        # --- ENTRY SCAN ---
        if is_killed:
            continue
        if (i - last_trade_close_bar) < 2:
            continue
        if daily_trades_count >= 8:
            continue

        # 1. Regime
        sub_1h = btc_1h[btc_1h["datetime"] <= current_dt].tail(30)
        regime, _, _ = regime_engine.evaluate_regime(sub_1h)
        if regime in ("FLAT", "STRESS"):
            blocked_by_regime += 1
            continue

        # 2. Ranking
        raw_feats = []
        for sym in symbols:
            if sym == "BTCUSDT":
                continue
            sub = datasets[sym].iloc[i]
            raw_feats.append({
                "symbol": sym,
                "m_1h": sub.get("m_1h", 0.0),
                "m_4h": sub.get("m_4h", 0.0),
                "ofi_15m": sub.get("ofi_15m", 0.0),
                "oi_confirmation": 0.0,
                "book_imbalance": sub.get("book_imbalance", 0.0),
                "rel_volume": sub.get("rel_volume", 1.0),
                "funding_z": 0.0,
                "basis_z": 0.0,
                "atr_pct": sub.get("atr_pct", 0.005),
                "current_price": sub["close"],
            })

        ranked = ranker.rank_universe(raw_feats)
        if not ranked or len(ranked) < 2:
            continue

        top1 = ranked[0]
        top2 = ranked[1]

        # Determine thresholds based on session and regime
        if sess_name == "LIQUID":
            min_z = config["LIQUID_TREND"] if regime == "TREND" else config["LIQUID_RANGE"]
            min_gap = config["LIQUID_GAP"]
            min_consensus = config["LIQUID_CONSENSUS"]
            min_cost_mult = config["LIQUID_COST_MULT"]
            req_persist = config["LIQUID_PERSIST"]
        else: # ASIA
            min_z = config["ASIA_TREND"] if regime == "TREND" else config["ASIA_RANGE"]
            min_gap = config["ASIA_GAP"]
            min_consensus = config["ASIA_CONSENSUS"]
            min_cost_mult = config["ASIA_COST_MULT"]
            req_persist = config["ASIA_PERSIST"]

        # Check Absolute Direction agreement
        if top1.get("momentum_raw", 0.0) * top1["direction"] <= 0:
            continue

        # Confidence Gate (Score)
        if top1["abs_score"] < min_z:
            blocked_by_score += 1
            continue

        # Confidence Gap
        gap = top1["abs_score"] - top2["abs_score"]
        if gap < min_gap:
            blocked_by_gap += 1
            continue

        # Consensus Gate
        if top1.get("consensus_count", 0) < min_consensus:
            blocked_by_consensus += 1
            continue

        # Cost Gate
        atr_pct = max(top1["atr_pct"] * 1.2, 0.0035)
        expected_move = 1.8 * atr_pct
        expected_cost = 0.0010 + 0.0004 + abs(top1.get("funding_raw", 0.0001))
        if expected_cost > 0 and (expected_move / expected_cost) < min_cost_mult:
            blocked_by_cost += 1
            continue

        # Persistence Gate for ASIA
        if sess_name == "ASIA" and req_persist > 1:
            if top1["symbol"] == prev_asia_sym and top1["direction"] == prev_asia_dir:
                asia_hit_count += 1
            else:
                prev_asia_sym = top1["symbol"]
                prev_asia_dir = top1["direction"]
                asia_hit_count = 1

            if asia_hit_count < req_persist:
                blocked_by_persistence += 1
                continue
        else:
            prev_asia_sym = None
            prev_asia_dir = None
            asia_hit_count = 0

        # PASS! Open position
        sym = top1["symbol"]
        pos_dir = top1["direction"]
        entry_p = top1["current_price"]
        sl_pct = max(min(top1["atr_pct"] * 1.2, 0.0150), 0.0035)

        if pos_dir == 1:
            sl_price = entry_p * (1.0 - sl_pct)
            tp_price = entry_p * (1.0 + wide_tp_pct)
        else:
            sl_price = entry_p * (1.0 + sl_pct)
            tp_price = entry_p * (1.0 - wide_tp_pct)

        active_position = {
            "symbol": sym,
            "direction": pos_dir,
            "entry_time": current_dt,
            "entry_bar": i,
            "entry_price": entry_p,
            "sl_pct": sl_pct,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "highest_price": entry_p,
            "lowest_price": entry_p,
            "trailing_active": False
        }
        daily_trades_count += 1

    df_trades = pd.DataFrame(trades)
    eq_df = pd.DataFrame(equity_curve)
    
    # Calculate stats
    total_trades = len(df_trades)
    if total_trades > 0:
        wins = df_trades[df_trades["net_pnl"] > 0]
        losses = df_trades[df_trades["net_pnl"] <= 0]
        win_rate = len(wins) / total_trades * 100.0
        gross_profit = wins["net_pnl"].sum() if len(wins) > 0 else 0.0
        gross_loss = abs(losses["net_pnl"].sum()) if len(losses) > 0 else 1e-9
        profit_factor = gross_profit / gross_loss
        net_profit = equity - initial_equity
        ret_pct = net_profit / initial_equity * 100.0
        
        eq_series = eq_df["equity"]
        peak_series = eq_series.cummax()
        dd_series = (peak_series - eq_series) / peak_series * 100
        max_dd = dd_series.max()
        trailing_rate = len(df_trades[df_trades["trailing_active"] == True]) / total_trades * 100.0
    else:
        win_rate = 0.0
        profit_factor = 0.0
        net_profit = 0.0
        ret_pct = 0.0
        max_dd = 0.0
        trailing_rate = 0.0

    return {
        "trades": df_trades,
        "equity_curve": eq_df,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "net_profit": net_profit,
        "ret_pct": ret_pct,
        "max_dd": max_dd,
        "max_consecutive_losses": max_consecutive_losses,
        "final_equity": equity,
        "trailing_rate": trailing_rate,
        "blocked_stats": {
            "score": blocked_by_score,
            "gap": blocked_by_gap,
            "consensus": blocked_by_consensus,
            "cost": blocked_by_cost,
            "persistence": blocked_by_persistence,
        }
    }

def main():
    # Define Configurations
    config_baseline = {
        "name": "Hiện tại (Strict)",
        "LIQUID_TREND": 1.50,
        "LIQUID_RANGE": 1.65,
        "LIQUID_GAP": 0.30,
        "LIQUID_CONSENSUS": 4,
        "LIQUID_COST_MULT": 2.5,
        "LIQUID_PERSIST": 1,
        "ASIA_TREND": 1.60,
        "ASIA_RANGE": 1.75,
        "ASIA_GAP": 0.35,
        "ASIA_CONSENSUS": 5,
        "ASIA_COST_MULT": 3.0,
        "ASIA_PERSIST": 2,
    }

    config_proposed = {
        "name": "Đề xuất thử (Relaxed 1.55/1.65)",
        "LIQUID_TREND": 1.50,
        "LIQUID_RANGE": 1.55,       # Relaxed from 1.65
        "LIQUID_GAP": 0.30,
        "LIQUID_CONSENSUS": 4,
        "LIQUID_COST_MULT": 2.5,
        "LIQUID_PERSIST": 1,
        "ASIA_TREND": 1.60,
        "ASIA_RANGE": 1.65,         # Relaxed from 1.75
        "ASIA_GAP": 0.35,
        "ASIA_CONSENSUS": 5,
        "ASIA_COST_MULT": 3.0,
        "ASIA_PERSIST": 2,
    }

    # =========================================================================
    # PART 1: UNSEEN RECENT DATASET (21 Days up to TODAY 25/09/2026)
    # =========================================================================
    print("=" * 80)
    print("🔍 PHẦN 1: BACKTEST SO SÁNH TRÊN TẬP DỮ LIỆU MỚI (OUT-OF-SAMPLE 21 NGÀY)")
    print("   Bao gồm dữ liệu thời gian thực cập nhật đến ngày 25/09/2026")
    print("=" * 80)

    unseen_dir = os.path.join(workspace_dir, "data", "unseen_test")
    symbols_unseen = [
        "ETHUSDT", "SOLUSDT", "ARBUSDT", "OPUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT", "LINKUSDT",
        "NEARUSDT", "APTUSDT", "INJUSDT", "BNBUSDT", "LTCUSDT"
    ]
    
    datasets_unseen = {}
    df_btc = pd.read_csv(os.path.join(unseen_dir, "BTCUSDT_5m_unseen.csv"))
    df_btc["datetime"] = pd.to_datetime(df_btc["datetime"])
    df_btc = compute_indicators(df_btc, "BTCUSDT")
    datasets_unseen["BTCUSDT"] = df_btc

    for sym in symbols_unseen:
        p = os.path.join(unseen_dir, f"{sym}_5m_unseen.csv")
        if os.path.exists(p):
            df = pd.read_csv(p)
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = compute_indicators(df, sym)
            datasets_unseen[sym] = df

    c_start = max(df["datetime"].min() for df in datasets_unseen.values())
    c_end = min(df["datetime"].max() for df in datasets_unseen.values())
    for s in list(datasets_unseen.keys()):
        df = datasets_unseen[s]
        df = df[(df["datetime"] >= c_start) & (df["datetime"] <= c_end)].reset_index(drop=True)
        datasets_unseen[s] = df
    n_bars_unseen = min(len(df) for df in datasets_unseen.values())
    for s in datasets_unseen:
        datasets_unseen[s] = datasets_unseen[s].iloc[:n_bars_unseen].reset_index(drop=True)

    print(f"• Thời gian: {c_start} → {c_end} ({n_bars_unseen:,} nến 5m)")

    res_base_unseen = run_simulation_engine(datasets_unseen, symbols_unseen, n_bars_unseen, config_baseline)
    res_prop_unseen = run_simulation_engine(datasets_unseen, symbols_unseen, n_bars_unseen, config_proposed)

    print("\n--- BẢNG SO SÁNH TRÊN TẬP UNSEEN 21 NGÀY ---")
    headers = ["Chỉ số", "Hiện tại (Strict)", "Đề xuất thử (Relaxed)", "Chênh lệch"]
    row_fmt = "{:<25} | {:<20} | {:<22} | {:<15}"
    print(row_fmt.format(*headers))
    print("-" * 90)
    
    t_diff = res_prop_unseen['total_trades'] - res_base_unseen['total_trades']
    p_diff = res_prop_unseen['net_profit'] - res_base_unseen['net_profit']
    wr_diff = res_prop_unseen['win_rate'] - res_base_unseen['win_rate']
    dd_diff = res_prop_unseen['max_dd'] - res_base_unseen['max_dd']
    pf_diff = res_prop_unseen['profit_factor'] - res_base_unseen['profit_factor']

    print(row_fmt.format("Số lệnh mở", f"{res_base_unseen['total_trades']} lệnh", f"{res_prop_unseen['total_trades']} lệnh", f"{t_diff:+d} lệnh"))
    print(row_fmt.format("Tần suất (lệnh/ngày)", f"{res_base_unseen['total_trades']/21:.2f}", f"{res_prop_unseen['total_trades']/21:.2f}", f"{t_diff/21:+.2f}"))
    print(row_fmt.format("Tỷ lệ thắng (Win Rate)", f"{res_base_unseen['win_rate']:.1f}%", f"{res_prop_unseen['win_rate']:.1f}%", f"{wr_diff:+.1f}%"))
    print(row_fmt.format("Lãi ròng (Net PnL)", f"{res_base_unseen['net_profit']:+.4f} USDT", f"{res_prop_unseen['net_profit']:+.4f} USDT", f"{p_diff:+.4f} USDT"))
    print(row_fmt.format("Tỷ suất lợi nhuận", f"{res_base_unseen['ret_pct']:+.2f}%", f"{res_prop_unseen['ret_pct']:+.2f}%", f"{res_prop_unseen['ret_pct'] - res_base_unseen['ret_pct']:+.2f}%"))
    print(row_fmt.format("Profit Factor", f"{res_base_unseen['profit_factor']:.2f}", f"{res_prop_unseen['profit_factor']:.2f}", f"{pf_diff:+.2f}"))
    print(row_fmt.format("Max Drawdown", f"{res_base_unseen['max_dd']:.2f}%", f"{res_prop_unseen['max_dd']:.2f}%", f"{dd_diff:+.2f}%"))
    print(row_fmt.format("Chuỗi thua tối đa", f"{res_base_unseen['max_consecutive_losses']} lệnh", f"{res_prop_unseen['max_consecutive_losses']} lệnh", f"{res_prop_unseen['max_consecutive_losses'] - res_base_unseen['max_consecutive_losses']:+d}"))
    print(row_fmt.format("Trailing SL kích hoạt", f"{res_base_unseen['trailing_rate']:.1f}%", f"{res_prop_unseen['trailing_rate']:.1f}%", f"{res_prop_unseen['trailing_rate'] - res_base_unseen['trailing_rate']:+.1f}%"))
    
    # Analyze trade diffs
    tb = res_base_unseen["trades"]
    tp = res_prop_unseen["trades"]
    print("\n🔍 Phân tích các lệnh mới phát sinh từ cấu hình nới:")
    if len(tp) > len(tb):
        base_times = set(tb["entry_time"].astype(str)) if len(tb) > 0 else set()
        new_trades = tp[~tp["entry_time"].astype(str).isin(base_times)]
        print(f"  • Có {len(new_trades)} lệnh mới:")
        for _, r in new_trades.iterrows():
            print(f"    - [{r['entry_time']}] {r['direction']} {r['symbol']} | Lãi: {r['ret_pct']:+.2f}% ({r['net_pnl']:+.4f} USDT) | Lý do đóng: {r['exit_reason']}")
    else:
        print("  • Không có lệnh mới nào phát sinh thêm (các rào cản khác như Gap, Consensus, Cost vẫn bảo vệ chặt chẽ).")

    print("\nThống kê số lần bị chặn bởi các lớp bảo vệ:")
    print(f"  • Bị chặn bởi Điểm (Score):      Hiện tại: {res_base_unseen['blocked_stats']['score']} | Đề xuất: {res_prop_unseen['blocked_stats']['score']}")
    print(f"  • Bị chặn bởi Gap (Top1 - Top2): Hiện tại: {res_base_unseen['blocked_stats']['gap']} | Đề xuất: {res_prop_unseen['blocked_stats']['gap']}")
    print(f"  • Bị chặn bởi Đồng thuận:        Hiện tại: {res_base_unseen['blocked_stats']['consensus']} | Đề xuất: {res_prop_unseen['blocked_stats']['consensus']}")
    print(f"  • Bị chặn bởi Chi phí (Cost):    Hiện tại: {res_base_unseen['blocked_stats']['cost']} | Đề xuất: {res_prop_unseen['blocked_stats']['cost']}")
    print(f"  • Bị chặn bởi Persistence ASIA: Hiện tại: {res_base_unseen['blocked_stats']['persistence']} | Đề xuất: {res_prop_unseen['blocked_stats']['persistence']}")

    # =========================================================================
    # PART 2: 1-YEAR (365 DAYS) MULTI-SEASON BACKTEST
    # =========================================================================
    year_dir = os.path.join(workspace_dir, "data", "1year")
    if os.path.exists(year_dir):
        print("\n" + "=" * 80)
        print("🔍 PHẦN 2: BACKTEST SO SÁNH TRÊN TẬP DỮ LIỆU 1 NĂM (105,000 NẾN 5M)")
        print("   Kiểm chứng tính bền bỉ qua các mùa Bull, Bear, Sideway")
        print("=" * 80)
        
        symbols_1y = ["ADAUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT", "DOGEUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "NEARUSDT", "SOLUSDT", "XRPUSDT"]
        datasets_1y = {}
        df_btc_1y = pd.read_csv(os.path.join(year_dir, "BTCUSDT_5m_1y.csv"))
        df_btc_1y["datetime"] = pd.to_datetime(df_btc_1y["datetime"])
        df_btc_1y = compute_indicators(df_btc_1y, "BTCUSDT")
        datasets_1y["BTCUSDT"] = df_btc_1y

        for sym in symbols_1y:
            p = os.path.join(year_dir, f"{sym}_5m_1y.csv")
            if os.path.exists(p):
                df = pd.read_csv(p)
                df["datetime"] = pd.to_datetime(df["datetime"])
                df = compute_indicators(df, sym)
                datasets_1y[sym] = df

        c_start_1y = max(df["datetime"].min() for df in datasets_1y.values())
        c_end_1y = min(df["datetime"].max() for df in datasets_1y.values())
        for s in list(datasets_1y.keys()):
            df = datasets_1y[s]
            df = df[(df["datetime"] >= c_start_1y) & (df["datetime"] <= c_end_1y)].reset_index(drop=True)
            datasets_1y[s] = df
        n_bars_1y = min(len(df) for df in datasets_1y.values())
        for s in datasets_1y:
            datasets_1y[s] = datasets_1y[s].iloc[:n_bars_1y].reset_index(drop=True)

        print(f"• Thời gian: {c_start_1y} → {c_end_1y} ({n_bars_1y:,} nến 5m ~ 365 ngày)")

        res_base_1y = run_simulation_engine(datasets_1y, symbols_1y, n_bars_1y, config_baseline, initial_equity=100.0, position_notional=100.0)
        res_prop_1y = run_simulation_engine(datasets_1y, symbols_1y, n_bars_1y, config_proposed, initial_equity=100.0, position_notional=100.0)

        print("\n--- BẢNG SO SÁNH TRÊN TẬP 1 NĂM (365 NGÀY) ---")
        print(row_fmt.format(*headers))
        print("-" * 90)
        
        t_diff_1y = res_prop_1y['total_trades'] - res_base_1y['total_trades']
        p_diff_1y = res_prop_1y['net_profit'] - res_base_1y['net_profit']
        wr_diff_1y = res_prop_1y['win_rate'] - res_base_1y['win_rate']
        dd_diff_1y = res_prop_1y['max_dd'] - res_base_1y['max_dd']
        pf_diff_1y = res_prop_1y['profit_factor'] - res_base_1y['profit_factor']

        print(row_fmt.format("Số lệnh mở", f"{res_base_1y['total_trades']} lệnh", f"{res_prop_1y['total_trades']} lệnh", f"{t_diff_1y:+d} lệnh"))
        print(row_fmt.format("Tần suất (lệnh/tuần)", f"{res_base_1y['total_trades']/52:.2f}", f"{res_prop_1y['total_trades']/52:.2f}", f"{t_diff_1y/52:+.2f}"))
        print(row_fmt.format("Tỷ lệ thắng (Win Rate)", f"{res_base_1y['win_rate']:.1f}%", f"{res_prop_1y['win_rate']:.1f}%", f"{wr_diff_1y:+.1f}%"))
        print(row_fmt.format("Lãi ròng (Net PnL)", f"{res_base_1y['net_profit']:+.2f} USDT", f"{res_prop_1y['net_profit']:+.2f} USDT", f"{p_diff_1y:+.2f} USDT"))
        print(row_fmt.format("Tỷ suất lợi nhuận", f"{res_base_1y['ret_pct']:+.2f}%", f"{res_prop_1y['ret_pct']:+.2f}%", f"{res_prop_1y['ret_pct'] - res_base_1y['ret_pct']:+.2f}%"))
        print(row_fmt.format("Profit Factor", f"{res_base_1y['profit_factor']:.2f}", f"{res_prop_1y['profit_factor']:.2f}", f"{pf_diff_1y:+.2f}"))
        print(row_fmt.format("Max Drawdown", f"{res_base_1y['max_dd']:.2f}%", f"{res_prop_1y['max_dd']:.2f}%", f"{dd_diff_1y:+.2f}%"))
        print(row_fmt.format("Chuỗi thua tối đa", f"{res_base_1y['max_consecutive_losses']} lệnh", f"{res_prop_1y['max_consecutive_losses']} lệnh", f"{res_prop_1y['max_consecutive_losses'] - res_base_1y['max_consecutive_losses']:+d}"))
        print(row_fmt.format("Trailing SL kích hoạt", f"{res_base_1y['trailing_rate']:.1f}%", f"{res_prop_1y['trailing_rate']:.1f}%", f"{res_prop_1y['trailing_rate'] - res_base_1y['trailing_rate']:+.1f}%"))

    print("\n✅ Hoàn thành toàn bộ backtest kiểm chứng.")

if __name__ == "__main__":
    main()
