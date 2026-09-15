"""
Strategy 1 Adapter: 14 Technical Candle Features + ML Classifier
=================================================================
Predicts direction based on 14 technical momentum, RSI, EMA, Volatility indicators.
"""
import os
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any

from execution.strategy_interface import BaseStrategy, StrategyDecision
from src.features import build_features


class Strategy1Adapter(BaseStrategy):
    def __init__(self):
        super().__init__(
            name="chien_thuat_1",
            symbol="BTCUSDT",
            leverage=5,
            default_qty=0.001,
            take_profit_pct=0.005,
            stop_loss_pct=0.003
        )
        self.model = None
        
    def initialize(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        model_path = os.path.join(base_dir, "models", "btc_xgb_model.joblib")
        if os.path.exists(model_path):
            self.model = joblib.load(model_path)
            
    def analyze(self, market_data: Dict[str, Any]) -> StrategyDecision:
        candles = market_data["candles"]
        cur_p = market_data["current_price"]
        now_dt = market_data.get("timestamp")
        
        df_feat, feature_cols = build_features(candles, is_train=False)
        latest_feat = df_feat.iloc[-1].to_dict()
        
        # If model is loaded, predict probability
        prob_up = 0.5
        if self.model is not None:
            X_vec = np.array([[latest_feat.get(c, 0.0) for c in feature_cols]])
            try:
                prob_up = float(self.model.predict_proba(X_vec)[0, 1])
            except Exception:
                prob_up = float(self.model.predict(X_vec)[0])
                
        trend_dist = latest_feat.get("trend_dist", 0.0)
        cur_hour = now_dt.hour if now_dt else 16
        is_active = (cur_hour >= 15) or (cur_hour <= 2)
        
        signal = 0
        if is_active:
            if prob_up >= 0.65 and trend_dist > 0:
                signal = 1
            elif prob_up <= 0.35 and trend_dist < 0:
                signal = -1
                
        reason = f"P(UP)={prob_up*100:.1f}%, Trend={trend_dist*100:+.2f}%"
        if signal == 1:
            reason += " → MUA (LONG)"
        elif signal == -1:
            reason += " → BÁN (SHORT)"
        else:
            reason += " → QUAN SÁT"
            
        return StrategyDecision(
            signal=signal,
            confidence=prob_up if signal == 1 else (1.0 - prob_up),
            reason=reason,
            tp_pct=self.take_profit_pct,
            sl_pct=self.stop_loss_pct,
            extra_metrics={"prob_up": prob_up, "trend_dist": trend_dist}
        )
