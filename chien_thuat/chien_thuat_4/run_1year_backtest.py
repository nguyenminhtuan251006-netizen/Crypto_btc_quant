"""
FULL 1-YEAR (365 DAYS) Institutional Backtest for CHIẾN THUẬT 4 (AFCX v3)
==========================================================================
Evaluates ~105,000 bars (5-minute resolution) across 12 major assets:
BTC, ETH, SOL, BNB, DOGE, XRP, ADA, AVAX, LINK, NEAR, DOT, ARB

Phần A: Fixed Split 70% In-Sample (~8.5 tháng) vs 30% Out-of-Sample (~3.5 tháng)
Phần B: Walk-Forward Analysis (4 cửa sổ quý - Q1, Q2, Q3, Q4)
Phần C: Phân tích theo từng Mùa thị trường (Uptrend vs Downtrend vs Sideway)
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, base_dir)

from chien_thuat.chien_thuat_4.src.cross_sectional_ranker import CrossSectionalRanker
from chien_thuat.chien_thuat_4.src.regime_engine import MarketRegimeEngine
from chien_thuat.chien_thuat_4.run_backtest import compute_indicators

def load_1year_datasets(data_dir: str):
    """Loads 1-year 5m datasets and aligns by datetime."""
    all_files = sorted([f for f in os.listdir(data_dir) if f.endswith("_5m_1y.csv")])
    if not all_files:
        raise FileNotFoundError(f"Không tìm thấy file *_5m_1y.csv trong {data_dir}")

    print(f"  • Phát hiện {len(all_files)} bộ dữ liệu nến 1 năm (105k bars mỗi coin)...")
    datasets = {}
    for fname in all_files:
        sym = fname.replace("_5m_1y.csv", "")
        fpath = os.path.join(data_dir, fname)
        df = pd.read_csv(fpath)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.sort_values("datetime", inplace=True)
        df.drop_duplicates("datetime", inplace=True)
        datasets[sym] = df
        print(f"    → {sym:<10}: {len(df):,} nến ({str(df['datetime'].min())[:10]} → {str(df['datetime'].max())[:10]})")

    # Common range across all
    start_dt = max(df["datetime"].min() for df in datasets.values())
    end_dt = min(df["datetime"].max() for df in datasets.values())
    print(f"\n  • Khung thời gian đồng bộ chung: {start_dt} → {end_dt}")

    for sym in list(datasets.keys()):
        df = datasets[sym]
        df = df[(df["datetime"] >= start_dt) & (df["datetime"] <= end_dt)].reset_index(drop=True)
        datasets[sym] = df

    symbols = sorted(datasets.keys())
    n_bars = min(len(datasets[s]) for s in symbols)
    for s in symbols:
        datasets[s] = datasets[s].iloc[:n_bars].reset_index(drop=True)

    total_days = (end_dt - start_dt).days
    print(f"  • Tổng coins: {len(symbols)} | Nến/coin: {n_bars:,} | Thời gian: {total_days} ngày (~{total_days/365:.2f} năm)")
    return datasets, symbols, n_bars

def run_simulation(datasets, symbols, start_idx, end_idx, initial_capital=5000.0,
                   leverage=5, risk_pct=0.002, min_abs_score=1.70, min_score_gap=0.40,
                   sl_atr_mult=2.2, min_sl_pct=0.012, tp_mult=2.2, max_hold_bars=72,
                   cooldown_bars=6, period_name="PERIOD"):
    """Runs simulation on designated bar range."""
    ranker = CrossSectionalRanker(
        min_abs_score=min_abs_score,
        min_score_gap=min_score_gap,
        min_consensus=4,
        cost_ratio_threshold=3.0,
    )
    regime_engine = MarketRegimeEngine()

    capital = initial_capital
    active_trade = None
    trades_history = []
    equity_curve = [capital]
    last_exit_bar = -999

    maker_fee = 0.0002
    taker_fee = 0.0005
    slippage = 0.0002

    start_dt = datasets["BTCUSDT"].iloc[start_idx]["datetime"]
    end_dt = datasets["BTCUSDT"].iloc[min(end_idx - 1, len(datasets["BTCUSDT"]) - 1)]["datetime"]

    for idx in range(start_idx, end_idx):
        if idx >= len(datasets["BTCUSDT"]):
            break
        cur_dt = datasets["BTCUSDT"].iloc[idx]["datetime"]
        hour = cur_dt.hour
        is_active_session = 8 <= hour <= 21

        # Manage active trade
        if active_trade is not None:
            sym = active_trade["symbol"]
            if idx >= len(datasets[sym]):
                break
            row = datasets[sym].iloc[idx]
            cur_price = row["close"]
            high_price = row["high"]
            low_price = row["low"]
            direction = active_trade["direction"]

            closed = False
            exit_price = cur_price
            exit_reason = ""

            if direction == 1:
                if low_price <= active_trade["sl"]:
                    closed, exit_price, exit_reason = True, active_trade["sl"], "STOP_LOSS"
                elif high_price >= active_trade["tp"]:
                    closed, exit_price, exit_reason = True, active_trade["tp"], "TAKE_PROFIT"
            elif direction == -1:
                if high_price >= active_trade["sl"]:
                    closed, exit_price, exit_reason = True, active_trade["sl"], "STOP_LOSS"
                elif low_price <= active_trade["tp"]:
                    closed, exit_price, exit_reason = True, active_trade["tp"], "TAKE_PROFIT"

            if not closed and (idx - active_trade["entry_bar"]) >= max_hold_bars:
                closed, exit_price, exit_reason = True, cur_price, "TIME_EXPIRE"

            if closed:
                raw_ret = (exit_price - active_trade["entry_price"]) / active_trade["entry_price"] if direction == 1 else (active_trade["entry_price"] - exit_price) / active_trade["entry_price"]
                fee_cost = active_trade["notional"] * (taker_fee + maker_fee + slippage)
                gross_pnl = active_trade["notional"] * raw_ret
                net_pnl = gross_pnl - fee_cost
                capital += net_pnl

                active_trade["exit_time"] = cur_dt
                active_trade["exit_price"] = exit_price
                active_trade["exit_reason"] = exit_reason
                active_trade["net_pnl"] = net_pnl
                active_trade["ret_pct"] = raw_ret * 100
                active_trade["capital_after"] = capital
                trades_history.append(active_trade)
                active_trade = None
                last_exit_bar = idx

        equity_curve.append(capital)

        if active_trade is not None or not is_active_session or idx % 3 != 0:
            continue
        if idx - last_exit_bar < cooldown_bars:
            continue

        # Regime filter
        btc_sub = datasets["BTCUSDT"].iloc[max(0, idx - 240):idx + 1]
        btc_1h = btc_sub.iloc[::12].copy()
        pos_m = sum(1 for s in symbols if idx < len(datasets[s]) and datasets[s].iloc[idx].get("m_1h", 0) > 0)
        breadth = pos_m / max(len(symbols), 1)

        if len(btc_1h) >= 20:
            regime, _, _ = regime_engine.evaluate_regime(btc_1h, market_breadth=breadth)
        else:
            regime = "TREND"
        if regime in ("STRESS", "FLAT"):
            continue

        # Rank universe
        raw_candidates = []
        for sym in symbols:
            if idx >= len(datasets[sym]):
                continue
            r = datasets[sym].iloc[idx]
            raw_candidates.append({
                "symbol": sym, "current_price": r["close"], "atr_pct": r["atr_pct"],
                "m_1h": r["m_1h"], "m_4h": r["m_4h"], "ofi_15m": r["ofi_15m"],
                "oi_confirmation": r["oi_confirmation"], "book_imbalance": r["book_imbalance"],
                "rel_volume": r["rel_volume"], "funding_z": r["funding_z"],
                "basis_z": r["basis_z"], "funding_raw": r["funding_raw"],
            })

        if len(raw_candidates) < 2:
            continue

        ranked = ranker.rank_universe(raw_candidates)
        if not ranked:
            continue

        qualified, top_cand, reason = ranker.evaluate_top_candidate(ranked)
        if qualified and top_cand is not None:
            direction = top_cand["direction"]
            target_sym = top_cand["symbol"]
            entry_p = float(top_cand["current_price"])
            atr = float(datasets[target_sym].iloc[idx]["atr"])

            risk_usd = capital * risk_pct
            sl_dist = max(atr * sl_atr_mult, entry_p * min_sl_pct)
            notional = min((risk_usd / (sl_dist / entry_p)), capital * leverage * 0.4)

            tp_p = entry_p + tp_mult * sl_dist if direction == 1 else entry_p - tp_mult * sl_dist
            sl_p = entry_p - sl_dist if direction == 1 else entry_p + sl_dist

            active_trade = {
                "period": period_name, "entry_time": cur_dt, "entry_bar": idx,
                "symbol": target_sym, "direction": direction, "entry_price": entry_p,
                "tp": tp_p, "sl": sl_p, "notional": notional,
                "score": top_cand["final_score"], "consensus": top_cand["consensus_count"],
            }

    df_trades = pd.DataFrame(trades_history)
    total_trades = len(df_trades)
    result = {
        "period": period_name, "trades": total_trades, "wins": 0, "losses": 0,
        "win_rate": 0.0, "net_pnl": 0.0, "roi_pct": 0.0,
        "profit_factor": 0.0, "max_dd": 0.0, "sharpe": 0.0,
        "start_time": start_dt, "end_time": end_dt, "final_capital": capital,
        "df_trades": df_trades,
    }

    if total_trades > 0:
        wins = df_trades[df_trades["net_pnl"] > 0]
        losses = df_trades[df_trades["net_pnl"] <= 0]
        win_rate = (len(wins) / total_trades) * 100
        gross_profit = wins["net_pnl"].sum() if len(wins) > 0 else 0.0
        gross_loss = abs(losses["net_pnl"].sum()) if len(losses) > 0 else 1e-9
        profit_factor = gross_profit / gross_loss
        total_net_pnl = capital - initial_capital
        total_roi = (total_net_pnl / initial_capital) * 100

        eq_series = pd.Series(equity_curve)
        peak = eq_series.cummax()
        drawdown = (eq_series - peak) / peak
        max_dd = abs(drawdown.min()) * 100

        returns = df_trades["net_pnl"] / initial_capital
        sharpe = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(365 * 24 / 2) if len(returns) > 1 else 0.0

        result.update({
            "wins": len(wins), "losses": len(losses), "win_rate": win_rate,
            "net_pnl": total_net_pnl, "roi_pct": total_roi, "profit_factor": profit_factor,
            "max_dd": max_dd, "sharpe": sharpe,
        })
    return result

def print_result_row(label, res):
    if res["trades"] == 0:
        print(f"  {label:<30} | {'Không có lệnh':<60}")
        return
    print(f"  {label:<30} | {res['trades']:>4} lệnh | WR {res['win_rate']:5.1f}% ({res['wins']:>3}W/{res['losses']:>3}L) | PF {res['profit_factor']:5.2f} | PnL {res['net_pnl']:+9.2f} ({res['roi_pct']:+5.2f}%) | DD {res['max_dd']:4.2f}% | Sharpe {res['sharpe']:6.2f}")

def main():
    print("=" * 115)
    print("   🔬 FULL 1-YEAR (365 DAYS) INSTITUTIONAL BACKTEST: CHIẾN THUẬT 4 (AFCX v3)")
    print("   Dữ liệu trọn vẹn 1 năm (105,000 nến 5M) | Vũ trụ 12 Top Coins | Multi-Layer Gates")
    print("=" * 115)

    data_dir = os.path.join(base_dir, "data", "1year")
    datasets, symbols, n_bars = load_1year_datasets(data_dir)

    print("\n[1/3] Chuẩn bị đặc trưng dòng tiền & Vi cấu trúc cho toàn bộ 12 tài sản...")
    for sym in symbols:
        datasets[sym] = compute_indicators(datasets[sym], sym)
        print(f"  • {sym:<10}: {len(datasets[sym]):,} nến | Đã tính Momentum, OFI, Book Imbalance, ATR")

    warmup = 100
    usable_bars = n_bars - warmup
    split_idx = warmup + int(usable_bars * 0.70)
    start_all = datasets["BTCUSDT"].iloc[warmup]["datetime"]
    split_dt = datasets["BTCUSDT"].iloc[split_idx]["datetime"]
    end_all = datasets["BTCUSDT"].iloc[n_bars - 1]["datetime"]
    total_days = (end_all - start_all).days

    print(f"\n[2/3] PHÂN TÁCH DỮ LIỆU ĐỊNH LƯỢNG (TOÀN BỘ {total_days} NGÀY = ~{total_days/365:.2f} NĂM)")
    print(f"  • Toàn bộ:                    {n_bars:,} nến ({start_all} → {end_all})")
    print(f"  • IN-SAMPLE  (70% Train/Opt): {split_idx - warmup:,} nến ({start_all} → {split_dt})")
    print(f"  • OUT-OF-SAMPLE (30% Test):   {n_bars - split_idx:,} nến ({split_dt} → {end_all})")

    print("\n" + "-" * 115)
    print(">>> ĐANG CHẠY IN-SAMPLE (70% = ~8.5 THÁNG)...")
    res_is = run_simulation(datasets, symbols, warmup, split_idx, period_name="IN_SAMPLE")
    print(">>> ĐANG CHẠY OUT-OF-SAMPLE (30% = ~3.5 THÁNG)...")
    res_oos = run_simulation(datasets, symbols, split_idx, n_bars - 1, period_name="OUT_OF_SAMPLE")

    print("\n" + "=" * 115)
    print("   📊 PHẦN A: BẢNG SO SÁNH 1 NĂM (70% IN-SAMPLE VS 30% OUT-OF-SAMPLE)")
    print("=" * 115)
    print_result_row(f"IN-SAMPLE  ({str(res_is['start_time'])[:10]}→{str(res_is['end_time'])[:10]})", res_is)
    print_result_row(f"OUT-OF-SAMPLE ({str(res_oos['start_time'])[:10]}→{str(res_oos['end_time'])[:10]})", res_oos)
    print("=" * 115)

    # Walk-Forward 4 quarters
    print(f"\n[3/3] WALK-FORWARD ANALYSIS: Chia 365 ngày thành 4 Quý (Q1, Q2, Q3, Q4)")
    window_size = usable_bars // 4
    wf_results = []
    for i in range(4):
        w_start = warmup + i * window_size
        w_end = warmup + (i + 1) * window_size if i < 3 else n_bars - 1
        w_split = w_start + int((w_end - w_start) * 0.70)
        w_start_dt = datasets["BTCUSDT"].iloc[w_start]["datetime"]
        w_split_dt = datasets["BTCUSDT"].iloc[w_split]["datetime"]
        w_end_dt = datasets["BTCUSDT"].iloc[min(w_end, n_bars - 1)]["datetime"]

        res_train = run_simulation(datasets, symbols, w_start, w_split, period_name=f"WF_Q{i+1}_TRAIN")
        res_test = run_simulation(datasets, symbols, w_split, w_end, period_name=f"WF_Q{i+1}_TEST")
        wf_results.append({"train": res_train, "test": res_test})
        print(f"\n  ── Quý {i+1}/4 ({str(w_start_dt)[:10]} → {str(w_end_dt)[:10]}) ──")
        print_result_row(f"  Train ({str(w_start_dt)[:10]}→{str(w_split_dt)[:10]})", res_train)
        print_result_row(f"  Test  ({str(w_split_dt)[:10]}→{str(w_end_dt)[:10]})", res_test)

    # Combined WF-OOS
    wf_oos_trades = sum(r["test"]["trades"] for r in wf_results)
    wf_oos_wins = sum(r["test"]["wins"] for r in wf_results)
    wf_oos_losses = sum(r["test"]["losses"] for r in wf_results)
    wf_oos_pnl = sum(r["test"]["net_pnl"] for r in wf_results)
    wf_oos_wr = (wf_oos_wins / wf_oos_trades * 100) if wf_oos_trades > 0 else 0.0

    print("\n" + "=" * 115)
    print("   📊 TỔNG HỢP WALK-FORWARD 4 QUÝ BLIND FORWARD TEST")
    print("=" * 115)
    for i, r in enumerate(wf_results):
        print_result_row(f"Quý {i+1} OOS ({str(r['test']['start_time'])[:10]}→{str(r['test']['end_time'])[:10]})", r["test"])
    print("-" * 115)
    print(f"  {'TỔNG HỢP 4 QUÝ WF-OOS':<30} | {wf_oos_trades:>4} lệnh | WR {wf_oos_wr:5.1f}% ({wf_oos_wins}W/{wf_oos_losses}L) | PnL tổng: {wf_oos_pnl:+9.2f} USDT")
    print("=" * 115)

    # Save 1-year trades report
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    all_trades = []
    for label, res in [("IS_1Y", res_is), ("OOS_1Y", res_oos)]:
        if not res["df_trades"].empty:
            res["df_trades"]["split"] = label
            all_trades.append(res["df_trades"])
    for i, r in enumerate(wf_results):
        for phase in ["train", "test"]:
            if not r[phase]["df_trades"].empty:
                r[phase]["df_trades"]["split"] = f"WF_Q{i+1}_{phase.upper()}"
                all_trades.append(r[phase]["df_trades"])
    if all_trades:
        pd.concat(all_trades, ignore_index=True).to_csv(os.path.join(reports_dir, "afcx_1year_all_trades.csv"), index=False)
        print(f"\n  💾 Nhật ký toàn bộ lệnh 1 năm đã lưu tại: {os.path.join(reports_dir, 'afcx_1year_all_trades.csv')}")

if __name__ == "__main__":
    main()
