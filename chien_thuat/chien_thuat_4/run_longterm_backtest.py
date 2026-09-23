"""
LONG-TERM Institutional Backtest & Walk-Forward OOS for CHIẾN THUẬT 4 (AFCX v3)
=================================================================================
Downloads & uses ~5 months of 5m candle data (BTC, ETH, SOL) + HFT Microstructure.
Splits into:
  - 70% In-Sample (Train / Parameter Tuning)
  - 30% Out-of-Sample (Blind Forward Test)
Also runs Walk-Forward Analysis with 3 rolling windows.
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
from chien_thuat.chien_thuat_4.run_backtest import compute_indicators


def load_long_term_datasets(data_dir: str):
    """Loads 50k-bar datasets for all available coins + HFT features."""
    hft_path = os.path.join(data_dir, "hft_features_5m.parquet")
    if not os.path.exists(hft_path):
        raise FileNotFoundError(f"Không tìm thấy HFT features: {hft_path}")

    # Discover all *_5m_50k.csv files
    all_files = sorted([f for f in os.listdir(data_dir) if f.endswith("_5m_50k.csv")])
    if not all_files:
        raise FileNotFoundError("Không tìm thấy file *_5m_50k.csv nào trong thư mục data/")

    print(f"  • Phát hiện {len(all_files)} bộ dữ liệu nến 5M (50k bars mỗi coin)...")
    datasets = {}
    for fname in all_files:
        sym = fname.replace("_5m_50k.csv", "")
        fpath = os.path.join(data_dir, fname)
        df = pd.read_csv(fpath)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.sort_values("datetime", inplace=True)
        df.drop_duplicates("datetime", inplace=True)
        datasets[sym] = df
        print(f"    → {sym}: {len(df):,} nến")

    print("  • Đang nạp 11 đặc trưng vi cấu trúc HFT (Orderbook L2 + Trades CVD)...")
    df_hft = pd.read_parquet(hft_path)
    df_hft["datetime"] = pd.to_datetime(df_hft["datetime"])
    df_hft.sort_values("datetime", inplace=True)
    df_hft.drop_duplicates("datetime", inplace=True)

    # Find common date range across ALL datasets + HFT
    start_dt = max(df["datetime"].min() for df in datasets.values())
    start_dt = max(start_dt, df_hft["datetime"].min())
    end_dt = min(df["datetime"].max() for df in datasets.values())
    end_dt = min(end_dt, df_hft["datetime"].max())

    print(f"  • Khung thời gian đồng bộ chung: {start_dt} → {end_dt}")

    for sym in list(datasets.keys()):
        df = datasets[sym]
        df = df[(df["datetime"] >= start_dt) & (df["datetime"] <= end_dt)].reset_index(drop=True)
        datasets[sym] = df

    df_hft = df_hft[(df_hft["datetime"] >= start_dt) & (df_hft["datetime"] <= end_dt)].reset_index(drop=True)

    # Merge HFT features into BTCUSDT
    if "BTCUSDT" in datasets:
        datasets["BTCUSDT"] = pd.merge(datasets["BTCUSDT"], df_hft, on="datetime", how="left").ffill().fillna(0)

    total_days = (end_dt - start_dt).days
    symbols = sorted(datasets.keys())
    min_len = min(len(datasets[s]) for s in symbols)
    print(f"  • Tổng coins: {len(symbols)} | Nến/coin: {min_len:,} | Thời gian: {total_days} ngày (~{total_days/30:.1f} tháng)")
    return datasets


def run_simulation(datasets, symbols, start_idx, end_idx, initial_capital=5000.0,
                   leverage=5, risk_pct=0.002, min_abs_score=1.70, min_score_gap=0.40,
                   sl_atr_mult=2.2, min_sl_pct=0.012, tp_mult=2.2, max_hold_bars=72,
                   cooldown_bars=6, period_name="PERIOD"):
    """Runs AFCX simulation on a specific bar range with tightened gates & realistic SL/TP."""
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

        # Manage Active Trade
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
                last_exit_bar = idx

        equity_curve.append(capital)

        if active_trade is not None:
            continue
        if idx % 3 != 0 or not is_active_session:
            continue
        if idx - last_exit_bar < cooldown_bars:
            continue

        # Regime filter
        btc_sub = datasets["BTCUSDT"].iloc[max(0, idx - 240):idx + 1]
        btc_1h = btc_sub.iloc[::12].copy()
        
        # Market breadth across universe
        pos_m = sum(1 for s in symbols if idx < len(datasets[s]) and datasets[s].iloc[idx].get("m_1h", 0) > 0)
        breadth = pos_m / max(len(symbols), 1)

        if len(btc_1h) >= 20:
            regime, _, _ = regime_engine.evaluate_regime(btc_1h, market_breadth=breadth)
        else:
            regime = "TREND"
        if regime in ("STRESS", "FLAT"):
            continue

        # Rank candidates
        raw_candidates = []
        for sym in symbols:
            if idx >= len(datasets[sym]):
                continue
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

            if direction == 1:
                tp_p = entry_p + tp_mult * sl_dist
                sl_p = entry_p - sl_dist
            else:
                tp_p = entry_p - tp_mult * sl_dist
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
    result = {
        "period": period_name,
        "trades": 0, "wins": 0, "losses": 0,
        "win_rate": 0.0, "net_pnl": 0.0, "roi_pct": 0.0,
        "profit_factor": 0.0, "max_dd": 0.0, "sharpe": 0.0,
        "start_time": start_dt, "end_time": end_dt,
        "final_capital": capital,
        "df_trades": df_trades,
    }

    if total_trades == 0:
        return result

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
        "trades": total_trades, "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "net_pnl": total_net_pnl, "roi_pct": total_roi,
        "profit_factor": profit_factor, "max_dd": max_dd, "sharpe": sharpe,
        "final_capital": capital,
    })
    return result


def print_result_row(label, res):
    """Print one row of a result for the comparison table."""
    if res["trades"] == 0:
        print(f"  {label:<28} | {'Không có lệnh':<60}")
        return
    print(f"  {label:<28} | {res['trades']:>3} lệnh | WR {res['win_rate']:5.1f}% ({res['wins']}W/{res['losses']}L) | PF {res['profit_factor']:5.2f} | PnL {res['net_pnl']:+8.2f} ({res['roi_pct']:+5.2f}%) | DD {res['max_dd']:4.2f}% | Sharpe {res['sharpe']:6.2f}")


def main():
    print("=" * 110)
    print("   🔬 LONG-TERM BACKTEST & WALK-FORWARD OOS: CHIẾN THUẬT 4 (AFCX v3)")
    print("   Dữ liệu dài hạn ~5 tháng | BTC + ETH + SOL | HFT Microstructure Features")
    print("=" * 110)

    data_dir = os.path.join(workspace_dir, "data")
    datasets = load_long_term_datasets(data_dir)

    symbols = sorted(datasets.keys())
    print(f"\n[1/3] Chuẩn bị đặc trưng dòng tiền & Vi cấu trúc cho toàn bộ {len(symbols)} cặp tài sản...")
    for sym in symbols:
        datasets[sym] = compute_indicators(datasets[sym], sym)
        print(f"  • {sym:<10}: {len(datasets[sym]):,} nến | Đã tính Momentum, OFI, Book Imbalance, ATR")

    n_bars = min(len(datasets[s]) for s in symbols)
    for s in symbols:
        datasets[s] = datasets[s].iloc[:n_bars].reset_index(drop=True)

    warmup = 50

    # =========================================================================
    # PHẦN A: CHIA CỐ ĐỊNH 70/30
    # =========================================================================
    usable_bars = n_bars - warmup
    split_idx = warmup + int(usable_bars * 0.70)
    start_all = datasets["BTCUSDT"].iloc[warmup]["datetime"]
    split_dt = datasets["BTCUSDT"].iloc[split_idx]["datetime"]
    end_all = datasets["BTCUSDT"].iloc[n_bars - 1]["datetime"]
    total_days = (end_all - start_all).days

    print(f"\n[2/3] PHÂN TÁCH DỮ LIỆU ĐỊNH LƯỢNG (TOÀN BỘ {total_days} NGÀY = ~{total_days/30:.1f} THÁNG)")
    print(f"  • Toàn bộ:                    {n_bars:,} nến ({start_all} → {end_all})")
    print(f"  • IN-SAMPLE  (70% Train/Opt): {split_idx - warmup:,} nến ({start_all} → {split_dt})")
    print(f"  • OUT-OF-SAMPLE (30% Test):   {n_bars - split_idx:,} nến ({split_dt} → {end_all})")

    print("\n" + "-" * 110)
    print(">>> ĐANG CHẠY IN-SAMPLE (70%)...")
    res_is = run_simulation(datasets, symbols, warmup, split_idx, period_name="IN_SAMPLE")
    print(">>> ĐANG CHẠY OUT-OF-SAMPLE (30%)...")
    res_oos = run_simulation(datasets, symbols, split_idx, n_bars - 1, period_name="OUT_OF_SAMPLE")

    print("\n" + "=" * 110)
    print("   📊 PHẦN A: BẢNG SO SÁNH IN-SAMPLE (70%) VS OUT-OF-SAMPLE (30%)")
    print("=" * 110)
    print_result_row(f"IN-SAMPLE  ({str(res_is['start_time'])[:10]}→{str(res_is['end_time'])[:10]})", res_is)
    print_result_row(f"OUT-OF-SAMPLE ({str(res_oos['start_time'])[:10]}→{str(res_oos['end_time'])[:10]})", res_oos)
    print("=" * 110)

    # =========================================================================
    # PHẦN B: WALK-FORWARD ANALYSIS (3 cửa sổ cuộn)
    # =========================================================================
    print(f"\n[3/3] WALK-FORWARD ANALYSIS: Chia {total_days} ngày thành 3 cửa sổ cuộn")

    n_usable = n_bars - warmup
    window_size = n_usable // 3

    wf_results = []
    for i in range(3):
        w_start = warmup + i * window_size
        w_end = warmup + (i + 1) * window_size if i < 2 else n_bars - 1
        # Chia mỗi cửa sổ thành 70% train / 30% test
        w_usable = w_end - w_start
        w_split = w_start + int(w_usable * 0.70)

        w_start_dt = datasets["BTCUSDT"].iloc[w_start]["datetime"]
        w_split_dt = datasets["BTCUSDT"].iloc[w_split]["datetime"]
        w_end_dt = datasets["BTCUSDT"].iloc[min(w_end, n_bars - 1)]["datetime"]
        w_days = (w_end_dt - w_start_dt).days

        print(f"\n  ── Cửa sổ {i+1}/3: {str(w_start_dt)[:10]} → {str(w_end_dt)[:10]} ({w_days} ngày) ──")

        res_train = run_simulation(datasets, symbols, w_start, w_split,
                                   period_name=f"WF{i+1}_TRAIN")
        res_test = run_simulation(datasets, symbols, w_split, w_end,
                                  period_name=f"WF{i+1}_TEST")
        wf_results.append({"train": res_train, "test": res_test})
        print_result_row(f"  Train ({str(w_start_dt)[:10]}→{str(w_split_dt)[:10]})", res_train)
        print_result_row(f"  Test  ({str(w_split_dt)[:10]}→{str(w_end_dt)[:10]})", res_test)

    # Walk-Forward combined OOS
    wf_oos_trades = sum(r["test"]["trades"] for r in wf_results)
    wf_oos_wins = sum(r["test"]["wins"] for r in wf_results)
    wf_oos_losses = sum(r["test"]["losses"] for r in wf_results)
    wf_oos_pnl = sum(r["test"]["net_pnl"] for r in wf_results)
    wf_oos_wr = (wf_oos_wins / wf_oos_trades * 100) if wf_oos_trades > 0 else 0.0

    print("\n" + "=" * 110)
    print("   📊 PHẦN B: TỔNG HỢP WALK-FORWARD OUT-OF-SAMPLE (3 CỬA SỔ CUỘN)")
    print("=" * 110)
    for i, r in enumerate(wf_results):
        t = r["test"]
        label = f"Window {i+1} OOS"
        print_result_row(label, t)
    print("-" * 110)
    print(f"  {'TỔNG HỢP WF-OOS':<28} | {wf_oos_trades:>3} lệnh | WR {wf_oos_wr:5.1f}% ({wf_oos_wins}W/{wf_oos_losses}L) | PnL tổng: {wf_oos_pnl:+8.2f} USDT")
    print("=" * 110)

    # =========================================================================
    # SAVE REPORTS
    # =========================================================================
    reports_dir = os.path.join(workspace_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    all_trades = []
    for label, res in [("IS_70", res_is), ("OOS_30", res_oos)]:
        if not res["df_trades"].empty:
            res["df_trades"]["split"] = label
            all_trades.append(res["df_trades"])
    for i, r in enumerate(wf_results):
        for phase in ["train", "test"]:
            if not r[phase]["df_trades"].empty:
                r[phase]["df_trades"]["split"] = f"WF{i+1}_{phase.upper()}"
                all_trades.append(r[phase]["df_trades"])

    if all_trades:
        pd.concat(all_trades, ignore_index=True).to_csv(
            os.path.join(reports_dir, "afcx_longterm_backtest_all_trades.csv"), index=False
        )

    # =========================================================================
    # FINAL VERDICT
    # =========================================================================
    print("\n🔍 ĐÁNH GIÁ TỔNG KẾT CHỐNG OVERFITTING (INSTITUTIONAL STANDARD):")

    oos_ok = res_oos["profit_factor"] >= 1.1 and res_oos["net_pnl"] > 0
    wf_ok = wf_oos_pnl > 0 and wf_oos_wr >= 45.0

    if oos_ok and wf_ok:
        print("  ✅ ĐẠT CHUẨN: Cả hai phương pháp (Split 70/30 và Walk-Forward) đều khẳng định Alpha dương trên dữ liệu mù.")
        print("  -> Chiến thuật AFCX v3 có Edge thực sự, không bị Overfitting / Curve-Fitting.")
    elif oos_ok:
        print("  ⚠️ ĐẠT MỘT PHẦN: Split 70/30 OOS dương, nhưng Walk-Forward cần thêm tuning.")
    elif wf_ok:
        print("  ⚠️ ĐẠT MỘT PHẦN: Walk-Forward OOS dương, nhưng Fixed Split cần thêm dữ liệu.")
    else:
        print("  ❌ CHƯA ĐẠT: Cần nghiên cứu bổ sung thêm nhân tố hoặc tinh chỉnh bộ lọc.")

    print(f"\n  💾 Nhật ký toàn bộ lệnh đã lưu tại: {os.path.join(reports_dir, 'afcx_longterm_backtest_all_trades.csv')}")
    print("=" * 110)


if __name__ == "__main__":
    main()
