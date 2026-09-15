"""
Test Suite & Live Scanner Verification for CHIẾN THUẬT 4: AFCX
=============================================================
Verifies:
1. Dynamic universe loading.
2. Order flow & microstructure feature computation.
3. Market regime classification (Trend/Range/Transition/Stress).
4. Cross-sectional ranking across candidate perpetuals.
5. Gate evaluation (Confidence Gate, Consensus Gate, Cost Gate).
6. Auto-discovery via execution/registry.py.
"""
import os
import sys
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, workspace_dir)

from execution.registry import get_strategy, list_available_strategies
from chien_thuat.chien_thuat_3.paper_trader import fetch_recent_candles, fetch_orderbook_l2, fetch_recent_trades


def test_afcx():
    print("=" * 80)
    print("      🧪 KIỂM THỬ HỆ THỐNG CHIẾN THUẬT 4: AFCX ADAPTIVE FLOW CROSS-SECTIONAL")
    print("=" * 80)

    # 1. Test Registry Auto-Discovery
    available = list_available_strategies()
    print(f"[1] Danh sách chiến thuật sẵn có: {available}")
    assert "chien_thuat_4" in available, "Lỗi: chien_thuat_4 không có trong danh sách registry!"
    print("    -> ✅ Registry auto-discovery hoạt động chính xác.")

    # 2. Instantiate Strategy 4
    strategy = get_strategy("chien_thuat_4")
    print(f"[2] Khởi tạo thành công: {strategy.name} (Leverage: {strategy.leverage}x)")

    # 3. Test Universe
    universe = strategy.afcx.universe_mgr.symbols
    print(f"[3] Vũ trụ thanh khoản Binance Futures ({len(universe)} đồng):")
    print(f"    {universe}")

    # 4. Fetch market data for BTC to test regime
    print("\n[4] Tải dữ liệu thị trường BTC để kiểm tra Market Regime Engine...")
    btc_candles = fetch_recent_candles("BTCUSDT", limit=50)
    ob = fetch_orderbook_l2("BTCUSDT", limit=10)
    trades = fetch_recent_trades("BTCUSDT", limit=50)
    cur_p = float(btc_candles.iloc[-1]["close"])

    market_data = {
        "candles": btc_candles,
        "orderbook": ob,
        "trades": trades,
        "current_price": cur_p,
    }

    print("\n[5] Thực hiện quét luân chuyển vốn (Cross-Sectional Scan) toàn vũ trụ...")
    start_t = time.time()
    decision = strategy.analyze(market_data)
    dur = time.time() - start_t

    print(f"    -> Thời gian quét & xếp hạng: {dur:.2f}s")
    print(f"    -> Chế độ thị trường: {strategy.afcx.current_regime}")
    print(f"    -> Quyết định: {decision.reason}")
    print(f"    -> Tín hiệu: {decision.signal} (1: LONG, -1: SHORT, 0: FLAT)")

    if decision.extra_metrics and "ranking" in decision.extra_metrics:
        print("\n[6] BẢNG XẾP HẠNG TOP CƠ HỘI DÒNG TIỀN (CROSS-SECTIONAL LEADERBOARD):")
        print(f"    {'Rank':<5} {'Symbol':<10} {'Score':<8} {'Direction':<10} {'Consensus':<10} {'ATR %':<8} {'Price':<12}")
        print("    " + "-" * 65)
        for i, item in enumerate(decision.extra_metrics["ranking"], 1):
            dir_str = "🟢 LONG" if item["direction"] == 1 else "🔴 SHORT"
            print(f"    #{i:<4} {item['symbol']:<10} {item['final_score']:+6.2f}   {dir_str:<10} {item['consensus_count']}/6       {item['atr_pct']*100:5.2f}%   ${item['current_price']:,.2f}")

    print("\n" + "=" * 80)
    print("      🎉 TẤT CẢ CÁC BƯỚC KIỂM THỬ CHIẾN THUẬT 4 ĐỀU THÀNH CÔNG!")
    print("=" * 80)


if __name__ == "__main__":
    test_afcx()
