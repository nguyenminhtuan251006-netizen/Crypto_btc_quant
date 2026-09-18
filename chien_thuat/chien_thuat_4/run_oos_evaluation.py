"""
Institutional In-Sample vs Out-of-Sample (OOS) Evaluator for CHIẾN THUẬT 4 (AFCX v3)
=====================================================================================
Performs quantitative validation against Overfitting & Data Snooping:
- 70% In-Sample (Period 1: 2026-08-05 -> 2026-08-30)
- 30% Out-of-Sample (Period 2: 2026-08-30 -> 2026-09-09)
- Compares Win Rate, Profit Factor, Max Drawdown, Sharpe Ratio, Net PnL
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime

# Setup workspace
current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, workspace_dir)

from chien_thuat.chien_thuat_4.src.cross_sectional_ranker import CrossSectionalRanker
from chien_thuat.chien_thuat_4.src.regime_engine import MarketRegimeEngine
from chien_thuat.chien_thuat_4.run_backtest import load_and_align_datasets, compute_indicators


def run_simulation(datasets, symbols, start_idx, end_idx, initial_capital=5000.0, leverage=5, risk_pct=0.005, period_name="PERIOD"):
    """Runs AFCX simulation on a specific slice of bars."""
    ranker = CrossSectionalRanker(
        min_abs_score=1.25,
        min_score_gap=0.20,
        min_consensus=4,
        cost_ratio_threshold=3.0,
    )
    regime_engine = MarketRegimeEngine()

    capital = initial_capital
    active_trade = None
    trades_history = []
    equity_curve = [capital]

    maker_fee = 0.0002   # 0.02% limit fee
    taker_fee = 0.0005   # 0.05% market fee
    slippage = 0.0002    # 0.02% slippage

    start_dt = datasets["BTCUSDT"].iloc[start_idx]["datetime"]
    end_dt = datasets["BTCUSDT"].iloc[end_idx - 1]["datetime"]

    for idx in range(start_idx, end_idx):
        cur_dt = datasets["BTCUSDT"].iloc[idx]["datetime"]
        hour = cur_dt.hour
        is_active_session = 8 <= hour <= 21

        # 1. Manage Active Trade
        if active_trade is not None:
            sym = active_trade["symbol"]
            row = datasets[sym].iloc[idx]
            cur_price = row["close"]
            high_price = row["high"]
            low_price = row["low"]
            direction = active_trade["direction"]

            closed = False
            exit_price = cur_price
            exit_reason = ""

            if direction == 1:  # LONG
                if low_price <= active_trade["sl"]:
                    closed = True
                    exit_price = active_trade["sl"]
                    exit_reason = "STOP_LOSS"
                elif high_price >= active_trade["tp"]:
                    closed = True
                    exit_price = active_trade["tp"]
                    exit_reason = "TAKE_PROFIT"
            elif direction == -1:  # SHORT
                if high_price >= active_trade["sl"]:
                    closed = True
                    exit_price = active_trade["sl"]
                    exit_reason = "STOP_LOSS"
                elif low_price <= active_trade["tp"]:
                    closed = True
                    exit_price = active_trade["tp"]
                    exit_reason = "TAKE_PROFIT"

            # Max duration 3 hours (36 bars 5m)
            if not closed and (idx - active_trade["entry_bar"]) >= 36:
                closed = True
                exit_price = cur_price
                exit_reason = "TIME_EXPIRE"

            if closed:
                if direction == 1:
                    raw_ret = (exit_price - active_trade["entry_price"]) / active_trade["entry_price"]
                else:
                    raw_ret = (active_trade["entry_price"] - exit_price) / active_trade["entry_price"]

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

        equity_curve.append(capital)

        if active_trade is not None:
            continue

        # Evaluate on 15m intervals
        if idx % 3 != 0 or not is_active_session:
            continue

        # Regime filter
        btc_sub = datasets["BTCUSDT"].iloc[max(0, idx - 240):idx + 1]
        btc_1h = btc_sub.iloc[::12].copy()
        if len(btc_1h) >= 20:
            regime, _, _ = regime_engine.evaluate_regime(btc_1h)
        else:
            regime = "TREND"

        if regime == "STRESS":
            continue

        # Rank candidates
        raw_candidates = []
        for sym in symbols:
            r = datasets[sym].iloc[idx]
            raw_candidates.append({
                "symbol": sym,
                "current_price": r["close"],
                "atr_pct": r["atr_pct"],
                "m_1h": r["m_1h"],
                "m_4h": r["m_4h"],
                "ofi_15m": r["ofi_15m"],
                "oi_confirmation": r["oi_confirmation"],
                "book_imbalance": r["book_imbalance"],
                "rel_volume": r["rel_volume"],
                "funding_z": r["funding_z"],
                "basis_z": r["basis_z"],
                "funding_raw": r["funding_raw"],
            })

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
            sl_dist = max(atr * 1.2, entry_p * 0.005)
            notional = min((risk_usd / (sl_dist / entry_p)), capital * leverage * 0.4)

            if direction == 1:
                tp_p = entry_p + 1.8 * sl_dist
                sl_p = entry_p - sl_dist
            else:
                tp_p = entry_p - 1.8 * sl_dist
                sl_p = entry_p + sl_dist

            active_trade = {
                "period": period_name,
                "entry_time": cur_dt,
                "entry_bar": idx,
                "symbol": target_sym,
                "direction": direction,
                "entry_price": entry_p,
                "tp": tp_p,
                "sl": sl_p,
                "notional": notional,
                "score": top_cand["final_score"],
                "consensus": top_cand["consensus_count"],
            }

    df_trades = pd.DataFrame(trades_history)
    total_trades = len(df_trades)
    if total_trades == 0:
        return {
            "period": period_name,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "roi_pct": 0.0,
            "profit_factor": 0.0,
            "max_dd": 0.0,
            "sharpe": 0.0,
            "start_time": start_dt,
            "end_time": end_dt,
            "df_trades": df_trades
        }

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

    return {
        "period": period_name,
        "trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "net_pnl": total_net_pnl,
        "roi_pct": total_roi,
        "profit_factor": profit_factor,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "start_time": start_dt,
        "end_time": end_dt,
        "df_trades": df_trades
    }


def main():
    print("=" * 100)
    print("   🔬 INSTITUTIONAL QUANT EVALUATION: IN-SAMPLE (70%) VS OUT-OF-SAMPLE (30%)")
    print("   CHIẾN THUẬT 4: AFCX (ADAPTIVE FLOW-CENTRIC CROSS-SECTIONAL)")
    print("=" * 100)

    data_dir = os.path.join(workspace_dir, "data")
    datasets = load_and_align_datasets(data_dir)

    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    for sym in symbols:
        datasets[sym] = compute_indicators(datasets[sym], sym)

    n_bars = min(len(datasets[s]) for s in symbols)
    for s in symbols:
        datasets[s] = datasets[s].iloc[:n_bars].reset_index(drop=True)

    warmup = 50
    usable_bars = n_bars - warmup
    split_idx = warmup + int(usable_bars * 0.70)

    start_all = datasets["BTCUSDT"].iloc[warmup]["datetime"]
    split_dt = datasets["BTCUSDT"].iloc[split_idx]["datetime"]
    end_all = datasets["BTCUSDT"].iloc[n_bars - 1]["datetime"]

    print(f"\n[QUY HOẠCH PHÂN TÁCH DỮ LIỆU ĐỊNH LƯỢNG]")
    print(f"  • Toàn bộ dữ liệu:                {n_bars:,} nến ({start_all} → {end_all})")
    print(f"  • Tập 1: IN-SAMPLE (70% Train):    {warmup} → {split_idx} ({split_idx - warmup:,} nến) | {start_all} → {split_dt}")
    print(f"  • Tập 2: OUT-OF-SAMPLE (30% Test): {split_idx} → {n_bars} ({n_bars - split_idx:,} nến) | {split_dt} → {end_all}")

    print("\n" + "-" * 100)
    print(">>> 1. ĐANG CHẠY KIỂM ĐỊNH TRÊN TẬP IN-SAMPLE (70%)...")
    res_is = run_simulation(datasets, symbols, warmup, split_idx, period_name="IN_SAMPLE")

    print(">>> 2. ĐANG CHẠY KIỂM ĐỊNH TRÊN TẬP OUT-OF-SAMPLE (30%)...")
    res_oos = run_simulation(datasets, symbols, split_idx, n_bars - 1, period_name="OUT_OF_SAMPLE")

    # Display Institutional Summary Table
    print("\n" + "=" * 100)
    print("                  📊 BẢNG SO SÁNH HIỆU SUẤT ĐỊNH LƯỢNG: IN-SAMPLE VS OUT-OF-SAMPLE")
    print("=" * 100)
    print(f"{'Tiêu chí đánh giá':<32} | {'IN-SAMPLE (70% Train)':<30} | {'OUT-OF-SAMPLE (30% Test)':<30}")
    print("-" * 100)
    print(f"{'Khung thời gian':<32} | {str(res_is['start_time'])[:16]} → {str(res_is['end_time'])[:16]:<10} | {str(res_oos['start_time'])[:16]} → {str(res_oos['end_time'])[:16]:<10}")
    print(f"{'Số lượng nến 5M':<32} | {split_idx - warmup:<30,} | {n_bars - split_idx:<30,}")
    print(f"{'Số lệnh thực thi (Trades)':<32} | {res_is['trades']:<30} | {res_oos['trades']:<30}")
    print(f"{'Tỷ lệ thắng (Win Rate)':<32} | {res_is['win_rate']:<6.2f}% ({res_is['wins']}W / {res_is['losses']}L){'':<12} | {res_oos['win_rate']:<6.2f}% ({res_oos['wins']}W / {res_oos['losses']}L)")
    print(f"{'Hệ số lợi nhuận (Profit Factor)':<32} | {res_is['profit_factor']:<30.2f} | {res_oos['profit_factor']:<30.2f}")
    print(f"{'Lợi nhuận ròng (Net PnL)':<32} | {res_is['net_pnl']:+8.2f} USDT ({res_is['roi_pct']:+.2f}%){'':<9} | {res_oos['net_pnl']:+8.2f} USDT ({res_oos['roi_pct']:+.2f}%)")
    print(f"{'Độ sụt giảm tối đa (Max DD)':<32} | {res_is['max_dd']:<6.2f}%{'':<23} | {res_oos['max_dd']:<6.2f}%")
    print(f"{'Tỷ lệ Sharpe (Annualized)':<32} | {res_is['sharpe']:<30.2f} | {res_oos['sharpe']:<30.2f}")
    print("=" * 100)

    # Save reports
    reports_dir = os.path.join(workspace_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    if not res_is["df_trades"].empty:
        res_is["df_trades"].to_csv(os.path.join(reports_dir, "afcx_in_sample_trades.csv"), index=False)
    if not res_oos["df_trades"].empty:
        res_oos["df_trades"].to_csv(os.path.join(reports_dir, "afcx_out_of_sample_trades.csv"), index=False)

    # Overfitting assessment
    print("\n🔍 ĐÁNH GIÁ CHỐNG OVERFITTING THEO CHUẨN QUANTITATIVE HEDGE FUND:")
    if res_oos["profit_factor"] >= 1.2 and res_oos["net_pnl"] > 0 and res_oos["max_dd"] <= 3.0:
        print("  ✅ ĐẠT YÊU CẦU OUT-OF-SAMPLE: Chiến thuật duy trì Profit Factor dương, Drawdown thấp và sinh lời ổn định.")
        print("  -> Chứng minh hệ số Alpha của AFCX là thực chất, không bị Data Snooping / Curve-Fitting.")
    else:
        print(f"  ℹ️ KẾT LUẬN OOS: Out-of-Sample PnL = {res_oos['net_pnl']:+.2f} USDT, Profit Factor = {res_oos['profit_factor']:.2f}")
    print("=" * 100)


if __name__ == "__main__":
    main()
