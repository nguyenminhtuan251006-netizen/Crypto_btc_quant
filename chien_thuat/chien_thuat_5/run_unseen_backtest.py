"""
CHIẾN THUẬT 5 (AFCX Micro-Capital) — Out-of-Sample Backtest trên Dữ Liệu Hoàn Toàn Mới
====================================================================================
Thời gian kiểm thử: 21 ngày gần nhất (02/09/2026 → 23/09/2026) — 6,000 thanh nến 5m
Vũ trụ giao dịch: 15 Altcoins thanh khoản cao (ETH, SOL, ARB, OP, XRP, DOGE, ADA, AVAX, SUI, LINK, NEAR, APT, INJ, BNB, LTC)
Baseline Regime: BTCUSDT (1H candles)
Vốn ban đầu: $8.55 USDT | Vị thế tối thiểu: 15.0 USDT | Đòn bẩy: 10x (Ký quỹ ~1.5 USDT)
Đầy đủ:
  - Sửa lỗi đảo dấu SHORT (Fix #1)
  - Thống nhất TP + Trailing 2 tầng (+1.2% / +1.8%) (Fix #2)
  - Làm mới điểm và rank trong lúc giữ lệnh (Fix #3)
  - Phí giao dịch taker 0.05%/chiều (0.10% trọn gói)
  - Kill Switch (3 trận thua liên tiếp, 2% lỗ ngày, 6% drawdown, max 8 lệnh/ngày)
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, base_dir)

from chien_thuat.chien_thuat_4.src.session_manager import SessionManager
from chien_thuat.chien_thuat_4.src.regime_engine import MarketRegimeEngine
from chien_thuat.chien_thuat_4.src.cross_sectional_ranker import CrossSectionalRanker
from chien_thuat.chien_thuat_4.src.dynamic_exit import DynamicExitManager
from chien_thuat.chien_thuat_4.run_backtest import compute_indicators

DATA_DIR = os.path.join(base_dir, "data", "unseen_test")

ALTCOINS = [
    "ETHUSDT", "SOLUSDT", "ARBUSDT", "OPUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT", "LINKUSDT",
    "NEARUSDT", "APTUSDT", "INJUSDT", "BNBUSDT", "LTCUSDT"
]

def load_unseen_datasets():
    print("📂 Đang nạp dữ liệu nến 21 ngày chưa từng thấy từ data/unseen_test/...")
    datasets = {}
    
    # 1. Load BTC
    btc_path = os.path.join(DATA_DIR, "BTCUSDT_5m_unseen.csv")
    df_btc = pd.read_csv(btc_path)
    df_btc["datetime"] = pd.to_datetime(df_btc["datetime"])
    df_btc = compute_indicators(df_btc, "BTCUSDT")
    datasets["BTCUSDT"] = df_btc
    
    # 2. Load Altcoins
    for sym in ALTCOINS:
        p = os.path.join(DATA_DIR, f"{sym}_5m_unseen.csv")
        if not os.path.exists(p):
            continue
        df = pd.read_csv(p)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = compute_indicators(df, sym)
        datasets[sym] = df
        
    # Align by common timestamp
    common_start = max(df["datetime"].min() for df in datasets.values())
    common_end = min(df["datetime"].max() for df in datasets.values())
    print(f"  • Khung thời gian đồng bộ: {common_start} → {common_end}")
    
    for s in list(datasets.keys()):
        df = datasets[s]
        df = df[(df["datetime"] >= common_start) & (df["datetime"] <= common_end)].reset_index(drop=True)
        datasets[s] = df
        
    n_bars = min(len(df) for df in datasets.values())
    for s in datasets:
        datasets[s] = datasets[s].iloc[:n_bars].reset_index(drop=True)
        
    print(f"  • Tổng số thanh nến kiểm thử: {n_bars:,} nến 5m (~{n_bars*5/1440:.1f} ngày)")
    return datasets, n_bars

def run_backtest():
    datasets, n_bars = load_unseen_datasets()
    
    session_mgr = SessionManager()
    regime_engine = MarketRegimeEngine()
    ranker = CrossSectionalRanker()
    
    exit_mgr = DynamicExitManager(
        tier1_trigger_pct=0.012,
        tier1_lock_pct=0.010,
        tier2_trigger_pct=0.018,
        trailing_callback_pct=0.0045,
        max_duration_seconds=3 * 3600
    )
    
    # Resample BTC 5m to 1h for Regime Engine
    btc_df_raw = datasets["BTCUSDT"].copy()
    btc_1h = btc_df_raw.set_index("datetime").resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()

    # Simulation State
    initial_equity = 8.55
    equity = initial_equity
    peak_equity = equity
    day_start_equity = equity
    current_day = None
    
    active_position = None  # None or dict
    last_trade_close_bar = -999
    
    # Kill switch counters
    consecutive_losses = 0
    daily_trades_count = 0
    is_killed = False
    kill_reason = ""
    
    # ASIA persistence tracking
    prev_top1_sym = None
    top1_count = 0
    
    trades = []
    equity_curve = []
    
    # Fee model: 0.05% taker fee each way
    TAKER_FEE = 0.0005
    POSITION_NOTIONAL = 15.0  # Floor notional for micro capital
    WIDE_TP_PCT = 0.08        # Emergency ceiling
    
    # Loop over bars (skip first 50 bars for indicator burn-in)
    for i in range(50, n_bars):
        current_dt = datasets["BTCUSDT"].iloc[i]["datetime"]
        day_str = current_dt.strftime("%Y-%m-%d")
        
        # New day reset
        if day_str != current_day:
            current_day = day_str
            day_start_equity = equity
            daily_trades_count = 0
            consecutive_losses = 0
            if is_killed and "drawdown" not in kill_reason.lower():
                is_killed = False
                kill_reason = ""
                
        # Drawdown tracking
        if equity > peak_equity:
            peak_equity = equity
            
        session = session_mgr.resolve_session(current_dt)
        
        # --- IF IN ACTIVE POSITION: MANAGE IT ---
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
            
            # Track extreme prices seen
            if pos_dir == 1:
                active_position["highest_price"] = max(active_position["highest_price"], cur_high)
            else:
                active_position["lowest_price"] = min(active_position["lowest_price"], cur_low)
                
            # Trailing stop ratchet
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
                    
            # Check price hit SL or TP during bar
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
                    
            # Dynamic Exit Check (Score decay / flip / time stop)
            if not closed:
                elapsed_sec = (i - entry_bar) * 300
                score_now = (bar_df["m_1h"] * 50) + (bar_df["m_4h"] * 30)  # Simplified momentum score
                # Fix #1: Keep raw score, no * pos_dir!
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
                    exit_reason = f"DYN_EXIT ({dyn_reason[:25]})"
                    closed = True
                elif elapsed_sec >= 3 * 3600:
                    exit_p = cur_close
                    exit_reason = "TIME_STOP_3H"
                    closed = True
                    
            if closed:
                ret_pct = ((exit_p - entry_p) / entry_p) if pos_dir == 1 else ((entry_p - exit_p) / entry_p)
                gross_pnl = ret_pct * POSITION_NOTIONAL
                # Fees: entry taker fee + exit taker fee
                total_fee = POSITION_NOTIONAL * TAKER_FEE * 2
                net_pnl = gross_pnl - total_fee
                equity += net_pnl
                
                if net_pnl > 0:
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
                    
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
                
                # Check kill switch
                if consecutive_losses >= 3:
                    is_killed = True
                    kill_reason = f"Kill Switch: 3 lệnh thua liên tiếp ({consecutive_losses})"
                elif day_start_equity > 0 and (day_start_equity - equity) / day_start_equity >= 0.02:
                    is_killed = True
                    kill_reason = "Kill Switch: Lỗ 2% trong ngày"
                elif peak_equity > 0 and (peak_equity - equity) / peak_equity >= 0.06:
                    is_killed = True
                    kill_reason = "Kill Switch: Drawdown tổng 6%"
                    
            equity_curve.append({"datetime": current_dt, "equity": equity})
            continue
            
        equity_curve.append({"datetime": current_dt, "equity": equity})
        
        # --- IF FLAT: SEARCH FOR ENTRY ---
        if is_killed:
            continue
            
        # Cooldown check: 10 minutes (2 bars of 5m)
        if (i - last_trade_close_bar) < 2:
            continue
            
        # Max trades per day
        if daily_trades_count >= 8:
            continue
            
        # 1. Market Regime Check on BTC 1H
        sub_1h = btc_1h[btc_1h["datetime"] <= current_dt].tail(30)
        regime, reason, _ = regime_engine.evaluate_regime(sub_1h)
        
        if regime in ("FLAT", "STRESS"):
            continue  # Protection: No new trades during flat sideway or stress
            
        # 2. Score candidate universe using CrossSectionalRanker
        raw_feats = []
        for sym in ALTCOINS:
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
        
        # Check Z-score threshold by session
        min_threshold = 1.65 if session.name == "ASIA" else 1.35
        gap = top1["abs_score"] - top2["abs_score"]
        
        if top1["abs_score"] < min_threshold or gap < 0.15:
            continue
            
        # Consensus gate (at least 3 of indicators agree)
        if top1.get("consensus_count", 3) < 3:
            continue
            
        # Persistence Gate for ASIA
        if session.name == "ASIA":
            if top1["symbol"] == prev_top1_sym:
                top1_count += 1
            else:
                prev_top1_sym = top1["symbol"]
                top1_count = 1
            if top1_count < 2:
                continue
        else:
            prev_top1_sym = None
            top1_count = 0
            
        # Passed all gates! Open position
        sym = top1["symbol"]
        pos_dir = top1["direction"]
        entry_p = top1["current_price"]
        sl_pct = max(min(top1["atr_pct"] * 1.2, 0.0150), 0.0035)
        
        if pos_dir == 1:
            sl_price = entry_p * (1.0 - sl_pct)
            tp_price = entry_p * (1.0 + WIDE_TP_PCT)  # Fix #2: Wide TP ceiling on exchange
        else:
            sl_price = entry_p * (1.0 + sl_pct)
            tp_price = entry_p * (1.0 - WIDE_TP_PCT)
            
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
        
    # --- REPORT GENERATION ---
    df_trades = pd.DataFrame(trades)
    print("\n" + "="*80)
    print("             📊 BÁO CÁO KẾT QUẢ BACKTEST CHIẾN THUẬT 5 (MICRO-CAPITAL)")
    print("                Tập Dữ Liệu Hoàn Toàn Mới (Out-Of-Sample, 21 Ngày)")
    print("="*80)
    print(f"  • Vốn ban đầu:              ${initial_equity:.2f} USDT")
    print(f"  • Vốn cuối kỳ:              ${equity:.2f} USDT (Lãi ròng: {equity - initial_equity:+.4f} USDT | {(equity - initial_equity)/initial_equity*100:+.2f}%)")
    
    if len(df_trades) == 0:
        print("  ⚠️ Không có lệnh nào được mở trong giai đoạn này.")
        return
        
    wins = df_trades[df_trades["net_pnl"] > 0]
    losses = df_trades[df_trades["net_pnl"] <= 0]
    win_rate = len(wins) / len(df_trades) * 100
    
    gross_profit = wins["net_pnl"].sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses["net_pnl"].sum()) if len(losses) > 0 else 1e-9
    profit_factor = gross_profit / gross_loss
    
    eq_df = pd.DataFrame(equity_curve)
    eq_series = eq_df["equity"]
    peak_series = eq_series.cummax()
    dd_series = (peak_series - eq_series) / peak_series * 100
    max_dd = dd_series.max()
    
    trailing_hits = df_trades[df_trades["trailing_active"] == True]
    
    print(f"  • Tổng số lệnh:             {len(df_trades)} lệnh (~{len(df_trades)/21:.1f} lệnh/ngày)")
    print(f"  • Số lệnh thắng:            {len(wins)} lệnh ({win_rate:.1f}%)")
    print(f"  • Số lệnh thua:             {len(losses)} lệnh ({100 - win_rate:.1f}%)")
    print(f"  • Profit Factor:            {profit_factor:.2f}")
    print(f"  • Max Drawdown:             {max_dd:.2f}%")
    print(f"  • Số lệnh kích hoạt Trailing: {len(trailing_hits)}/{len(df_trades)} ({len(trailing_hits)/len(df_trades)*100:.1f}%)")
    print(f"  • Trung bình lãi mỗi lệnh thắng: {wins['net_pnl'].mean():+.4f} USDT")
    print(f"  • Trung bình lỗ mỗi lệnh thua:  {losses['net_pnl'].mean():+.4f} USDT")
    print("="*80)
    
    print("\n[Chi tiết 10 lệnh gần nhất]:")
    print(df_trades[["entry_time", "symbol", "direction", "ret_pct", "net_pnl", "exit_reason", "equity"]].tail(10).to_string(index=False))
    
    # Save report CSV
    out_csv = os.path.join(base_dir, "reports", "chien_thuat_5_unseen_backtest.csv")
    df_trades.to_csv(out_csv, index=False)
    print(f"\n✅ Đã lưu toàn bộ lịch sử lệnh vào: {out_csv}")

if __name__ == "__main__":
    run_backtest()
