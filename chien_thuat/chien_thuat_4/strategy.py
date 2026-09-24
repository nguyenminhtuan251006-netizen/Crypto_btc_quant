"""
CHIẾN THUẬT 4: AFCX (Adaptive Flow Cross-Sectional Strategy) — v3 Dual Session
===============================================================================
Adaptive Flow Cross-Sectional Strategy for Binance USDT-M Perpetual Futures.
Conforms to 'AFCX Strategy Specification v3' and 'BaseStrategy' interface.

Core Logic:
1. Universe Selection: Top 20 liquid Binance Perpetual contracts.
2. Market Regime Engine: 1H + 4H Trend & Breadth. Blocks STRESS, raises threshold in RANGE.
3. Feature Engineering: Momentum (1h, 4h), OFI (15m), OI Confirmation, Order Book Imbalance, Relative Volume.
4. Crowding Penalty: Discounts crowded setups via Funding Rate Z-score and Basis Z-score.
5. Cross-Sectional Ranking: Identifies the #1 highest qualified opportunity.
6. Multi-Layer Gates: Session-adaptive thresholds (v3) — LIQUID vs ASIA.
7. Persistence Gate (v3): ASIA session requires Top 1 to persist >= 2 consecutive scans.
8. Risk & Execution: Volatility-aware ATR(14) Stop Loss & 1.8R Take Profit.
"""
import os
import sys
import time
import requests
import pandas as pd
from typing import Dict, Any, List, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
workspace_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, workspace_dir)

from execution.strategy_interface import BaseStrategy, StrategyDecision
from chien_thuat.chien_thuat_4.src.universe import UniverseManager
from chien_thuat.chien_thuat_4.src.regime_engine import MarketRegimeEngine
from chien_thuat.chien_thuat_4.src.flow_engine import FlowFeatureEngine
from chien_thuat.chien_thuat_4.src.cross_sectional_ranker import CrossSectionalRanker
from chien_thuat.chien_thuat_4.src.dynamic_exit import DynamicExitManager
from chien_thuat.chien_thuat_4.src.session_manager import SessionManager


class AFCXStrategy(BaseStrategy):
    """AFCX: Adaptive Flow Cross-Sectional Strategy."""

    def __init__(
        self,
        name: str = "chien_thuat_4",
        symbol: str = "BTCUSDT",
        leverage: int = 5,
        default_qty: float = 0.001,
        take_profit_pct: float = 0.012,  # 1.8R baseline
        stop_loss_pct: float = 0.006,    # 1.2 * ATR baseline
        universe_symbols: Optional[List[str]] = None,
    ):
        super().__init__(
            name=name,
            symbol=symbol,
            leverage=leverage,
            default_qty=default_qty,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
        )
        self.universe_mgr = UniverseManager(symbols=universe_symbols)
        self.regime_engine = MarketRegimeEngine()
        self.flow_engine = FlowFeatureEngine()
        self.ranker = CrossSectionalRanker()
        self.exit_manager = DynamicExitManager()
        self.session_mgr = SessionManager()  # v3 Dual Session Manager

        # Trailing Take Profit: Cơ chế Bậc Thang 2 Tầng (Chống quét râu Altcoin)
        self.enable_trailing = True
        self.tier1_trigger_pct = 0.015          # Tầng 1: Đạt +1.5% (~1.2R)
        self.tier1_lock_pct = 0.012             # Ghim cứng SL tại +1.2% (chống quét râu)
        self.tier2_trigger_pct = 0.022          # Tầng 2: Vượt +2.2% bùng nổ bám đỉnh
        self.trailing_callback_pct = 0.0065     # Lùi 0.65% bám sát theo sau đỉnh
        self.profit_lock_floor_pct = 0.0015     # Khóa tối thiểu hòa vốn
        self.wide_tp_pct = 0.15                 # Trần chốt lời khẩn cấp +15.0%

        self.selected_symbol: str = symbol
        self.last_rank_time = 0.0
        self.cached_ranking: List[Dict[str, Any]] = []
        self.current_regime: str = "TREND"
        self.market_breadth: float = 0.5
        self.prev_oi_cache: Dict[str, float] = {}  # Cache previous OI per symbol
        self.last_trade_close_time: float = 0.0     # Cooldown tracking

    def initialize(self):
        """Preload symbol metadata and precision filters."""
        self.universe_mgr.refresh_exchange_metadata()

    def fetch_btc_1h_candles(self, limit: int = 40) -> Optional[pd.DataFrame]:
        """Fetch 1H candles for BTC to feed into MarketRegimeEngine (Section 6 & 10)."""
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/klines", params={"symbol": "BTCUSDT", "interval": "1h", "limit": limit}, timeout=4)
            if r.status_code == 200:
                rows = [row for row in r.json() if int(row[6]) < int(time.time() * 1000)]
                df = pd.DataFrame(rows).iloc[:, [0, 1, 2, 3, 4, 5]]
                df.columns = ["open_time", "open", "high", "low", "close", "volume"]
                for c in ["open", "high", "low", "close", "volume"]:
                    df[c] = df[c].astype(float)
                return df
        except Exception:
            pass
        return None

    def fetch_symbol_market_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch 15m candles, orderbook, and ticker info for a candidate symbol."""
        try:
            base_url = "https://fapi.binance.com"
            # 1. Candles 15m (limit 30)
            c_res = requests.get(f"{base_url}/fapi/v1/klines", params={"symbol": symbol, "interval": "15m", "limit": 30}, timeout=4)
            if c_res.status_code != 200:
                return None
            raw_c = c_res.json()
            raw_c = [row for row in raw_c if int(row[6]) < int(time.time() * 1000)]
            if not raw_c or time.time() * 1000 - int(raw_c[-1][6]) > 16 * 60 * 1000:
                return None
            candles = pd.DataFrame(raw_c, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "trades",
                "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
            ])
            for col in ["open", "high", "low", "close", "volume", "taker_buy_base_asset_volume"]:
                candles[col] = candles[col].astype(float)

            # 2. Premium Index (Mark Price, Index Price, Funding Rate)
            p_res = requests.get(f"{base_url}/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=4)
            premium = p_res.json() if p_res.status_code == 200 else {}
            funding_rate = float(premium.get("lastFundingRate", 0.0001))
            mark_price = float(premium.get("markPrice", candles["close"].iloc[-1]))
            index_price = float(premium.get("indexPrice", mark_price))

            # 3. Open Interest
            oi_res = requests.get(f"{base_url}/fapi/v1/openInterest", params={"symbol": symbol}, timeout=4)
            oi_data = oi_res.json() if oi_res.status_code == 200 else {}
            open_interest = float(oi_data.get("openInterest", 0.0))

            # 4. Order Book L2
            ob_res = requests.get(f"{base_url}/fapi/v1/depth", params={"symbol": symbol, "limit": 10}, timeout=4)
            orderbook = ob_res.json() if ob_res.status_code == 200 else {}

            # 5. Taker Buy/Sell Ratio (Multi-Agent Analyzer §3 & §7)
            # NOTE: /futures/data/ endpoints only return real data from LIVE API (public, no key needed)
            live_data_url = "https://fapi.binance.com"
            taker_ratio = 1.0
            try:
                tbsr_res = requests.get(
                    f"{live_data_url}/futures/data/takerlongshortRatio",
                    params={"symbol": symbol, "period": "15m", "limit": 1},
                    timeout=3,
                )
                if tbsr_res.status_code == 200:
                    tbsr_data = tbsr_res.json()
                    if isinstance(tbsr_data, list) and len(tbsr_data) > 0:
                        taker_ratio = float(tbsr_data[0].get("buyVol", 1.0)) / max(float(tbsr_data[0].get("sellVol", 1.0)), 1e-9)
            except Exception:
                pass

            # 6. Long/Short Account Ratio (Multi-Agent Analyzer §3)
            ls_ratio = 1.0
            try:
                lsr_res = requests.get(
                    f"{live_data_url}/futures/data/globalLongShortAccountRatio",
                    params={"symbol": symbol, "period": "15m", "limit": 1},
                    timeout=3,
                )
                if lsr_res.status_code == 200:
                    lsr_data = lsr_res.json()
                    if isinstance(lsr_data, list) and len(lsr_data) > 0:
                        ls_ratio = float(lsr_data[0].get("longShortRatio", 1.0))
            except Exception:
                pass

            return {
                "candles": candles,
                "funding_rate": funding_rate,
                "mark_price": mark_price,
                "index_price": index_price,
                "open_interest": open_interest,
                "orderbook": orderbook,
                "taker_buy_sell_ratio": taker_ratio,
                "long_short_ratio": ls_ratio,
            }
        except Exception:
            return None

    def scan_and_rank_universe(self) -> List[Dict[str, Any]]:
        """Scans the liquid universe and ranks all candidate symbols."""
        features_list = []
        for sym in self.universe_mgr.symbols:
            snap = self.fetch_symbol_market_snapshot(sym)
            if snap and "candles" in snap:
                current_oi = snap.get("open_interest", 0.0)
                prev_oi = self.prev_oi_cache.get(sym, current_oi)  # First time = same (no signal)

                feats = self.flow_engine.compute_symbol_features(
                    symbol=sym,
                    candles_15m=snap["candles"],
                    orderbook=snap.get("orderbook"),
                    funding_rate=snap.get("funding_rate", 0.0001),
                    mark_price=snap.get("mark_price", 0.0),
                    index_price=snap.get("index_price", 0.0),
                    open_interest=current_oi,
                    prev_open_interest=prev_oi,
                    taker_buy_sell_ratio=snap.get("taker_buy_sell_ratio", 1.0),
                    long_short_ratio=snap.get("long_short_ratio", 1.0),
                )
                if feats:
                    features_list.append(feats)

                # Update OI cache for next scan cycle
                self.prev_oi_cache[sym] = current_oi

        # Calculate actual market breadth (fraction of coins with positive 1h momentum)
        if features_list:
            pos_m = sum(1 for f in features_list if f.get("m_1h", 0) > 0)
            self.market_breadth = pos_m / len(features_list)

        ranked = self.ranker.rank_universe(features_list)
        self.cached_ranking = ranked
        self.last_rank_time = time.time()
        return ranked

    def analyze(self, market_data: Dict[str, Any]) -> StrategyDecision:
        """
        Main decision engine conforming to BaseStrategy.
        Evaluates market regime, ranks candidate universe, and enforces gates.
        """
        now_ts = time.time()
        from datetime import datetime, timezone

        # v3: Resolve active session profile (LIQUID or ASIA)
        session_profile = self.session_mgr.resolve_session()

        # Cooldown: Wait 10 minutes after last trade closure (Review Issue 4: keep across session boundaries)
        cooldown_seconds = 600  # 10 minutes
        in_cooldown = (now_ts - self.last_trade_close_time) < cooldown_seconds if self.last_trade_close_time > 0 else False

        if in_cooldown:
            remaining = int(cooldown_seconds - (now_ts - self.last_trade_close_time))
            return StrategyDecision(
                signal=0,
                confidence=0.0,
                reason=f"⏳ COOLDOWN [{session_profile.name}]: Chờ {remaining}s sau lệnh trước để thị trường ổn định",
            )

        # Step 1: Scan and Rank Universe if cache expired (> 2 minutes)
        if now_ts - self.last_rank_time > 120 or not self.cached_ranking:
            ranked = self.scan_and_rank_universe()
        else:
            ranked = self.cached_ranking

        # Step 2: Evaluate Market Regime via 1H BTC candles (Section 6 & 10)
        btc_1h = self.fetch_btc_1h_candles(limit=40)
        if btc_1h is None:
            btc_1h = market_data.get("candles")

        regime, regime_reason, reg_metrics = self.regime_engine.evaluate_regime(
            btc_1h,
            market_breadth=self.market_breadth,
        )
        self.current_regime = regime

        # STRESS regime strictly blocks new entries (Section 10 & 26)
        if regime == "STRESS":
            return StrategyDecision(
                signal=0,
                confidence=0.0,
                reason=f"🛑 REGIME STRESS [{session_profile.name}]: {regime_reason} (Khóa mở lệnh mới để bảo vệ vốn)",
            )

        # FLAT regime: prolonged sideway with compressed volatility — block all entries
        if regime == "FLAT":
            return StrategyDecision(
                signal=0,
                confidence=0.0,
                reason=f"🚫 REGIME FLAT [{session_profile.name}]: {regime_reason}",
            )

        if not ranked or len(ranked) < 2:
            return StrategyDecision(
                signal=0,
                confidence=0.0,
                reason=f"[{session_profile.name}] Đang thu thập dữ liệu luân chuyển vốn từ vũ trụ Binance...",
            )

        # v3: Apply session-adaptive thresholds (Spec Section 4)
        active_z = session_profile.trend_z_min if regime == "TREND" else session_profile.range_z_min
        self.ranker.min_abs_score = active_z
        self.ranker.min_score_gap = session_profile.confidence_gap_min
        self.ranker.min_consensus = session_profile.consensus_min
        self.ranker.cost_ratio_threshold = session_profile.cost_multiple_min

        # Step 3: Evaluate Candidate #1 against Gates (Confidence, Consensus, Cost)
        qualified, candidate, gate_reason = self.ranker.evaluate_top_candidate(ranked)

        top_summary = f"[{session_profile.name}] Top 1: {ranked[0]['symbol']} ({ranked[0].get('score_100', '?')}/100) | Top 2: {ranked[1]['symbol']} ({ranked[1].get('score_100', '?')}/100)"

        if not qualified or not candidate:
            return StrategyDecision(
                signal=0,
                confidence=float(ranked[0]["abs_score"] / 3.0),
                reason=f"TẠM DỪNG [{regime}/{session_profile.name}]: {gate_reason} [{top_summary}]",
                extra_metrics={"ranking": ranked[:5], "regime": regime, "session": session_profile.name},
            )

        # Candidate passed all gates!
        self.selected_symbol = candidate["symbol"]
        cur_price = candidate["current_price"]
        dir_sign = candidate["direction"]

        # v3 Persistence Gate: ASIA session requires Top 1 to persist (Spec Section 5)
        passed_persist, persist_msg = self.session_mgr.check_persistence_gate(
            candidate_symbol=self.selected_symbol,
            candidate_direction=dir_sign,
            now_ts=self.last_rank_time,
            profile=session_profile,
        )
        if not passed_persist:
            return StrategyDecision(
                signal=0,
                confidence=min(candidate["abs_score"] / 2.0, 0.95),
                reason=f"[{session_profile.name}] {persist_msg} [{top_summary}]",
                extra_metrics={"ranking": ranked[:5], "regime": regime, "session": session_profile.name},
            )

        # Reset persistence counter once we proceed to entry
        self.session_mgr.reset_persistence()

        # Step 4: Calculate Dynamic ATR(14) Stop Loss and 1.8R Take Profit (Sections 19 & 20)
        atr_pct = candidate.get("atr_pct", 0.006)
        sl_pct = float(max(min(atr_pct * 1.2, 0.0150), 0.0035))
        tp_pct = float(sl_pct * 1.8)

        sl_price = self.universe_mgr.quantize_price(
            self.selected_symbol,
            cur_price * (1.0 - sl_pct) if dir_sign == 1 else cur_price * (1.0 + sl_pct),
        )
        tp_price = self.universe_mgr.quantize_price(
            self.selected_symbol,
            cur_price * (1.0 + tp_pct) if dir_sign == 1 else cur_price * (1.0 - tp_pct),
        )

        return StrategyDecision(
            signal=dir_sign,
            confidence=min(candidate["abs_score"] / 2.0, 0.95),
            reason=f"🚀 TÍN HIỆU AFCX [{regime}/{session_profile.name}]: {gate_reason} | {persist_msg}",
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            tp_price=tp_price,
            sl_price=sl_price,
            extra_metrics={
                "selected_symbol": self.selected_symbol,
                "candidate": candidate,
                "ranking": ranked[:5],
                "regime": regime,
                "session": session_profile.name,
                "score_100": candidate.get("score_100", 80),
            },
        )
