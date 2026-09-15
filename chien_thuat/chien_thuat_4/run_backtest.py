"""
Institutional Backtest Runner for CHIẾN THUẬT 4: AFCX (Adaptive Flow Cross-Sectional)
=====================================================================================
Multi-Asset Quantitative Evaluation on Binance USDT-M Perpetual Futures:
1. BTCUSDT (Candles 5M + 11 HFT Microstructure Features from Orderbook & Trades)
2. ETHUSDT (Candles 5M + Volume Flow)
3. SOLUSDT (Candles 5M + Volume Flow)
4. HFT Microstructure (Orderbook Imbalance L20, CVD, Spread, Microprice)

Evaluates:
- Cross-Sectional Divergence & Selection Alpha
- Multi-Layer Gate Efficiency (Confidence Gate, Consensus Gate, Cost Gate)
- Market Regime Filter (Trend vs Range vs Stress)
- Net PnL, Win Rate, Profit Factor, Max Drawdown, Sharpe Ratio
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime

# Setup workspace path
current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, workspace_dir)

from chien_thuat.chien_thuat_4.src.flow_engine import winsorize_z
from chien_thuat.chien_thuat_4.src.cross_sectional_ranker import CrossSectionalRanker
from chien_thuat.chien_thuat_4.src.regime_engine import MarketRegimeEngine


def load_and_align_datasets(data_dir: str):
    """Loads 4 core datasets and aligns them cleanly by datetime."""
    btc_path = os.path.join(data_dir, "BTCUSDT_5m.csv")
    eth_path = os.path.join(data_dir, "ETHUSDT_5m.csv")
    sol_path = os.path.join(data_dir, "SOLUSDT_5m.csv")
    hft_path = os.path.join(data_dir, "hft_features_5m.parquet")

    for p in [btc_path, eth_path, sol_path, hft_path]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Không tìm thấy file dữ liệu: {p}")

    print("  • Đang nạp dữ liệu nến BTC, ETH, SOL...")
    df_btc = pd.read_csv(btc_path)
    df_eth = pd.read_csv(eth_path)
    df_sol = pd.read_csv(sol_path)

    for df in [df_btc, df_eth, df_sol]:
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.sort_values("datetime", inplace=True)
        df.drop_duplicates("datetime", inplace=True)

    print("  • Đang nạp 11 đặc trưng vi cấu trúc HFT (Orderbook L2 + Trades CVD)...")
    df_hft = pd.read_parquet(hft_path)
    df_hft["datetime"] = pd.to_datetime(df_hft["datetime"])
    df_hft.sort_values("datetime", inplace=True)
    df_hft.drop_duplicates("datetime", inplace=True)

    # Find common date range
    start_dt = max(df_btc["datetime"].min(), df_eth["datetime"].min(), df_sol["datetime"].min(), df_hft["datetime"].min())
    end_dt = min(df_btc["datetime"].max(), df_eth["datetime"].max(), df_sol["datetime"].max(), df_hft["datetime"].max())

    print(f"  • Khung thời gian đồng bộ: {start_dt} → {end_dt}")

    df_btc = df_btc[(df_btc["datetime"] >= start_dt) & (df_btc["datetime"] <= end_dt)].reset_index(drop=True)
    df_eth = df_eth[(df_eth["datetime"] >= start_dt) & (df_eth["datetime"] <= end_dt)].reset_index(drop=True)
    df_sol = df_sol[(df_sol["datetime"] >= start_dt) & (df_sol["datetime"] <= end_dt)].reset_index(drop=True)
    df_hft = df_hft[(df_hft["datetime"] >= start_dt) & (df_hft["datetime"] <= end_dt)].reset_index(drop=True)

    # Merge HFT features into BTC
    df_btc = pd.merge(df_btc, df_hft, on="datetime", how="left").ffill().fillna(0)

    print(f"  • Tổng số thanh nến 5M kiểm thử: {len(df_btc):,} nến")
    return {"BTCUSDT": df_btc, "ETHUSDT": df_eth, "SOLUSDT": df_sol}


def compute_indicators(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Precomputes technical indicators, momentum, and ATR."""
    df = df.copy()
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values

    # ATR 14
    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr[0] = tr1[0]
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    df["atr"] = atr
    df["atr_pct"] = atr / (close + 1e-9)

    # Momentum 1h (12 bars 5m) & 4h (48 bars 5m)
    df["m_1h"] = (close - np.roll(close, 12)) / (np.roll(close, 12) + 1e-9)
    df["m_4h"] = (close - np.roll(close, 48)) / (np.roll(close, 48) + 1e-9)

    # Relative Volume (ratio vs 20-period average)
    vol_ma20 = pd.Series(volume).rolling(20, min_periods=1).mean().values
    df["rel_volume"] = volume / (vol_ma20 + 1e-9)

    # Order flow imbalance
    if "obi_l20" in df.columns:
        # High precision HFT Orderbook imbalance
        df["book_imbalance"] = df["obi_l20"]
    else:
        # Proxy from price action and volume
        price_spread = (close - df["open"].values) / (high - low + 1e-9)
        df["book_imbalance"] = np.clip(price_spread, -1.0, 1.0)

    if "cvd" in df.columns:
        # HFT cumulative volume delta slope
        cvd_diff = df["cvd"] - df["cvd"].shift(3).fillna(0)
        df["ofi_15m"] = np.tanh(cvd_diff / (volume + 1e-9))
    else:
        # Candle volume delta proxy
        direction = np.sign(close - df["open"].values)
        df["ofi_15m"] = np.clip(direction * (volume / (vol_ma20 + 1e-9)), -1.0, 1.0)

    # Open interest / momentum confirmation
    df["oi_confirmation"] = np.clip(df["m_1h"] * df["rel_volume"], -2.0, 2.0)

    # Basis & Funding proxies
    if "spread_mean" in df.columns:
        df["basis_z"] = np.clip(df["spread_mean"], -3.0, 3.0)
    else:
        df["basis_z"] = 0.0

    df["funding_z"] = 0.0
    df["funding_raw"] = 0.0001
    return df


def run_afcx_backtest(initial_capital: float = 5000.0, leverage: int = 5, risk_pct: float = 0.005):
    """Executes institutional cross-sectional backtest for AFCX Strategy."""
    print("=" * 95)
    print("      🚀 RESEARCH LAB: CHIẾN THUẬT 4 - AFCX MULTI-ASSET CROSS-SECTIONAL BACKTEST")
    print("=" * 95)

    data_dir = os.path.join(workspace_dir, "data")
    datasets = load_and_align_datasets(data_dir)

    print("\n[1/4] Chuẩn bị đặc trưng dòng tiền & Vi cấu trúc cho từng cặp tài sản...")
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    for sym in symbols:
        datasets[sym] = compute_indicators(datasets[sym], sym)
        print(f"  • {sym:<10}: {len(datasets[sym]):,} nến | Đã tính Momentum, OFI, Book Imbalance, ATR")

    # Sync indices
    n_bars = min(len(datasets[s]) for s in symbols)
    for s in symbols:
        datasets[s] = datasets[s].iloc[:n_bars].reset_index(drop=True)

    ranker = CrossSectionalRanker(
        min_abs_score=1.25,
        min_score_gap=0.20,
        min_consensus=4,
        cost_ratio_threshold=3.0,
    )
    regime_engine = MarketRegimeEngine()

    print("\n[2/4] Chạy mô phỏng giao dịch chéo (Cross-Sectional Trade Engine)...")
    capital = initial_capital
    active_trade = None
    trades_history = []
    equity_curve = [capital]

    maker_fee = 0.0002   # 0.02% limit fee
    taker_fee = 0.0005   # 0.05% market fee
    slippage = 0.0002    # 0.02% slippage

    # Run step-by-step
    warmup = 50
    for idx in range(warmup, n_bars - 1):
        cur_dt = datasets["BTCUSDT"].iloc[idx]["datetime"]

        # Session Filter: Tập trung phiên sôi động London + NY (15:00 - 02:00 giờ VN = 08:00 - 19:00 UTC)
        hour = cur_dt.hour
        # Assuming datetime is in UTC: 08:00 to 21:00 UTC
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

            # Check TP & SL
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

            # Max duration: 36 bars (3 hours)
            if not closed and (idx - active_trade["entry_bar"]) >= 36:
                closed = True
                exit_price = cur_price
                exit_reason = "TIME_EXPIRE"

            if closed:
                # Calculate PnL
                if direction == 1:
                    raw_ret = (exit_price - active_trade["entry_price"]) / active_trade["entry_price"]
                else:
                    raw_ret = (active_trade["entry_price"] - exit_price) / active_trade["entry_price"]

                # Total fee
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

        # Skip scanning if already in trade
        if active_trade is not None:
            continue

        # Evaluate only on 15m intervals (idx % 3 == 0) and active session
        if idx % 3 != 0 or not is_active_session:
            continue

        # 2. Determine Regime from BTC (resample or slice 1h from 5m)
        btc_sub = datasets["BTCUSDT"].iloc[max(0, idx - 240):idx + 1]
        # Resample to 1H (every 12 bars)
        btc_1h = btc_sub.iloc[::12].copy()
        if len(btc_1h) >= 20:
            regime, _, _ = regime_engine.evaluate_regime(btc_1h)
        else:
            regime = "TREND"
            
        if regime == "STRESS":
            continue

        # 3. Cross-Sectional Ranking across BTC, ETH, SOL
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
            # Enter trade
            direction = top_cand["direction"]
            target_sym = top_cand["symbol"]
            entry_p = float(top_cand["current_price"])
            atr = float(datasets[target_sym].iloc[idx]["atr"])

            # Risk-based position sizing
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

    # Summary Metrics
    print("\n[3/4] Đang tổng hợp và tính toán các chỉ số thống kê hiệu suất...")
    df_trades = pd.DataFrame(trades_history)
    reports_dir = os.path.join(workspace_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_file = os.path.join(reports_dir, "afcx_backtest_results.csv")
    if not df_trades.empty:
        df_trades.to_csv(report_file, index=False)

    total_trades = len(df_trades)
    if total_trades == 0:
        print("  ⚠️ Không có lệnh nào được thực thi trong thời gian kiểm thử.")
        return

    wins = df_trades[df_trades["net_pnl"] > 0]
    losses = df_trades[df_trades["net_pnl"] <= 0]
    win_rate = (len(wins) / total_trades) * 100
    gross_profit = wins["net_pnl"].sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses["net_pnl"].sum()) if len(losses) > 0 else 1e-9
    profit_factor = gross_profit / gross_loss
    total_net_pnl = capital - initial_capital
    total_roi = (total_net_pnl / initial_capital) * 100

    # Max Drawdown
    eq_series = pd.Series(equity_curve)
    peak = eq_series.cummax()
    drawdown = (eq_series - peak) / peak
    max_dd = abs(drawdown.min()) * 100

    # Sharpe Ratio
    returns = df_trades["net_pnl"] / initial_capital
    sharpe = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(365 * 24 / 2) if len(returns) > 1 else 0.0

    print("\n" + "=" * 95)
    print("      📊 KẾT QUẢ BACKTEST CHIẾN THUẬT 4 (AFCX - MULTI-ASSET QUANT BACKTEST)")
    print("=" * 95)
    print(f"  • Vốn ban đầu (Initial Capital):       ${initial_capital:,.2f} USDT")
    print(f"  • Vốn kết thúc (Ending Capital):       ${capital:,.2f} USDT")
    print(f"  • Lợi nhuận ròng (Net Profit):         {total_net_pnl:+,.2f} USDT ({total_roi:+.2f}%)")
    print(f"  • Tổng số giao dịch (Total Trades):    {total_trades} lệnh")
    print(f"  • Tỷ lệ thắng (Win Rate):              {win_rate:.2f}% ({len(wins)} thắng / {len(losses)} thua)")
    print(f"  • Hệ số lợi nhuận (Profit Factor):     {profit_factor:.2f}")
    print(f"  • Độ sụt giảm tối đa (Max Drawdown):   {max_dd:.2f}%")
    print(f"  • Tỷ lệ Sharpe (Annualized Sharpe):    {sharpe:.2f}")
    print("-" * 95)

    print("\n[4/4] PHÂN BỔ HIỆU SUẤT THEO TỪNG CẶP ĐỒNG COIN:")
    by_sym = df_trades.groupby("symbol").agg(
        trades=("net_pnl", "count"),
        win_count=("net_pnl", lambda x: (x > 0).sum()),
        total_pnl=("net_pnl", "sum"),
    )
    by_sym["win_rate"] = (by_sym["win_count"] / by_sym["trades"]) * 100
    for s, r in by_sym.iterrows():
        print(f"  • {s:<10}: {int(r['trades']):2d} lệnh | Win Rate: {r['win_rate']:5.1f}% | PnL: {r['total_pnl']:+8.2f} USDT")

    print(f"\n  💾 Nhật ký chi tiết từng lệnh đã lưu tại: {report_file}")
    print("=" * 95)


if __name__ == "__main__":
    run_afcx_backtest()
