"""
Strategy 3 Adapter: HFT Microstructure (Oxford Paper Upgraded)
===============================================================
26 Features (14 Technical Candles + 12 Orderbook L2 / Trades)
High-conviction selective filtering (Top 5% probability threshold).
"""
import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any

from execution.strategy_interface import BaseStrategy, StrategyDecision
from chien_thuat.chien_thuat_3.src.features import build_features
from chien_thuat.chien_thuat_3.paper_trader import compute_realtime_microstructure


class Strategy3Adapter(BaseStrategy):
    def __init__(self):
        super().__init__(
            name="chien_thuat_3",
            symbol="BTCUSDT",
            leverage=5,
            default_qty=0.001,
            take_profit_pct=0.004,
            stop_loss_pct=0.004
        )
        self.model = None
        self.feature_cols = []
        self.th_long = 0.671
        self.th_short = 0.228
        self.accuracy = 73.49
        
    def initialize(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        model_path = os.path.join(base_dir, "chien_thuat", "chien_thuat_3", "models", "hft_xgb_model.joblib")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}. Run train_model.py first.")
            
        pkg = joblib.load(model_path)
        self.model = pkg["model"]
        self.feature_cols = pkg["feature_cols"]
        self.th_long = pkg.get("th_long", 0.671)
        self.th_short = pkg.get("th_short", 0.228)
        self.accuracy = pkg.get("accuracy", 73.49)
        
    def analyze(self, market_data: Dict[str, Any]) -> StrategyDecision:
        candles = market_data["candles"]
        orderbook = market_data["orderbook"]
        trades = market_data["trades"]
        cur_p = market_data["current_price"]
        now_dt = market_data.get("timestamp")
        
        # 1. Technical features
        df_feat, _ = build_features(candles, is_train=False)
        latest_feat = df_feat.iloc[-1].to_dict()
        
        # 2. HFT Microstructure features (including Oxford depth-weighted OBI & CVD)
        micro = compute_realtime_microstructure(orderbook, trades, cur_p)
        
        # 3. Vectorize 26 features
        row_dict = {**latest_feat, **micro}
        X_vec = np.array([[row_dict.get(col, 0.0) for col in self.feature_cols]])
        
        # 4. Model Inference
        prob_up = float(self.model.predict_proba(X_vec)[0, 1])
        
        # 5. Session & Trend Filter
        cur_hour = now_dt.hour if now_dt else 16
        is_active_session = (cur_hour >= 15) or (cur_hour <= 2)
        trend_dist = latest_feat.get("trend_dist", 0.0)
        
        signal = 0
        reason = f"P(UP)={prob_up*100:.1f}%, Trend={trend_dist*100:+.2f}%, OBI_w={micro.get('obi_weighted', 0):+.2f}"
        
        if is_active_session:
            if prob_up >= self.th_long and trend_dist > 0:
                signal = 1
                reason += f" → MUA (LONG) [High Conviction >= {self.th_long*100:.1f}%]"
            elif prob_up <= self.th_short and trend_dist < 0:
                signal = -1
                reason += f" → BÁN (SHORT) [High Conviction <= {self.th_short*100:.1f}%]"
            else:
                reason += " → QUAN SÁT (Chưa đủ ngưỡng tự tin Top 5%)"
        else:
            reason += " → QUAN SÁT (Ngoài phiên London/New York)"
            
        return StrategyDecision(
            signal=signal,
            confidence=prob_up if signal == 1 else (1.0 - prob_up),
            reason=reason,
            tp_pct=self.take_profit_pct,
            sl_pct=self.stop_loss_pct,
            extra_metrics={
                "prob_up": prob_up,
                "obi_l1": micro.get("obi_l1", 0.0),
                "obi_weighted": micro.get("obi_weighted", 0.0),
                "cvd": micro.get("cvd", 0.0),
                "trend_dist": trend_dist
            }
        )
