"""
CHIẾN THUẬT 4: AFCX (Adaptive Flow Cross-Sectional Strategy)
============================================================
Adaptive Flow Cross-Sectional Strategy for Binance USDT-M Perpetual Futures.
Conforms to 'AFCX Strategy Specification' and 'BaseStrategy' interface.

Core Logic:
1. Universe Selection: Top 20 liquid Binance Perpetual contracts.
2. Market Regime Engine: 1H + 4H Trend & Breadth. Blocks STRESS, raises threshold in RANGE.
3. Feature Engineering: Momentum (1h, 4h), OFI (15m), OI Confirmation, Order Book Imbalance, Relative Volume.
4. Crowding Penalty: Discounts crowded setups via Funding Rate Z-score and Basis Z-score.
5. Cross-Sectional Ranking: Identifies the #1 highest qualified opportunity.
6. Multi-Layer Gates: Confidence Gap (>=0.20), Indicator Consensus (>=4/6), Cost Gate (Edge > 3x Cost).
7. Risk & Execution: Volatility-aware ATR(14) Stop Loss & 1.8R Take Profit.
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
                df = pd.DataFrame(r.json()).iloc[:, [0, 1, 2, 3, 4, 5]]
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
            base_url = "https://demo-fapi.binance.com"
            # 1. Candles 15m (limit 30)
            c_res = requests.get(f"{base_url}/fapi/v1/klines", params={"symbol": symbol, "interval": "15m", "limit": 30}, timeout=4)
            if c_res.status_code != 200:
                return None
            raw_c = c_res.json()
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

            return {
                "candles": candles,
                "funding_rate": funding_rate,
                "mark_price": mark_price,
                "index_price": index_price,
                "open_interest": open_interest,
                "orderbook": orderbook,
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

        # Session Filter: Only trade during high-liquidity London+NY session
        # 08:00–21:00 UTC = 15:00–04:00 VN time
        utc_hour = datetime.now(timezone.utc).hour
        is_active_session = 8 <= utc_hour <= 21

        # Cooldown: Wait 10 minutes after last trade closure
        cooldown_seconds = 600  # 10 minutes
        in_cooldown = (now_ts - self.last_trade_close_time) < cooldown_seconds if self.last_trade_close_time > 0 else False

        if not is_active_session:
            return StrategyDecision(
                signal=0,
                confidence=0.0,
                reason=f"⏸️ NGOÀI PHIÊN GIAO DỊCH: Giờ UTC {utc_hour}:00 nằm ngoài phiên London/NY (08:00–21:00 UTC)",
            )

        if in_cooldown:
            remaining = int(cooldown_seconds - (now_ts - self.last_trade_close_time))
            return StrategyDecision(
                signal=0,
                confidence=0.0,
                reason=f"⏳ COOLDOWN: Chờ {remaining}s sau lệnh trước để thị trường ổn định",
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
                reason=f"🛑 REGIME STRESS: {regime_reason} (Khóa mở lệnh mới để bảo vệ vốn)",
            )

        if not ranked or len(ranked) < 2:
            return StrategyDecision(
                signal=0,
                confidence=0.0,
                reason="Đang thu thập dữ liệu luân chuyển vốn từ vũ trụ Binance...",
            )

        # In RANGE or TRANSITION, raise the entry threshold (Section 10)
        # Normal threshold = 1.25. If RANGE/TRANSITION, require >= 1.35
        active_threshold = 1.25 if regime == "TREND" else 1.35
        self.ranker.min_abs_score = active_threshold

        # Step 3: Evaluate Candidate #1 against Gates (Confidence, Consensus, Cost)
        qualified, candidate, gate_reason = self.ranker.evaluate_top_candidate(ranked)

        top_summary = f"Top 1: {ranked[0]['symbol']} ({ranked[0]['final_score']:+.2f}) | Top 2: {ranked[1]['symbol']} ({ranked[1]['final_score']:+.2f})"

        if not qualified or not candidate:
            return StrategyDecision(
                signal=0,
                confidence=float(ranked[0]["abs_score"] / 3.0),
                reason=f"TẠM DỪNG [{regime}]: {gate_reason} [{top_summary}]",
                extra_metrics={"ranking": ranked[:5], "regime": regime},
            )

        # Candidate passed all gates!
        self.selected_symbol = candidate["symbol"]
        cur_price = candidate["current_price"]
        dir_sign = candidate["direction"]

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
            reason=f"🚀 TÍN HIỆU AFCX [{regime}]: {gate_reason}",
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            tp_price=tp_price,
            sl_price=sl_price,
            extra_metrics={
                "selected_symbol": self.selected_symbol,
                "candidate": candidate,
                "ranking": ranked[:5],
                "regime": regime,
            },
        )
