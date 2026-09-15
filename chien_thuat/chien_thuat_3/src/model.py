"""
Machine Learning Models for 5m BTC Prediction
Includes:
1. Linear Regression (predicts continuous 5m forward return)
2. Gradient Boosting Classifier (predicts probability of TP hit)
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score

class BTC5mPredictor:
    def __init__(self, model_type: str = "gradient_boosting"):
        self.model_type = model_type
        if model_type == "linear":
            self.model = Ridge(alpha=1.0)
        else:
            self.model = HistGradientBoostingClassifier(
                class_weight="balanced",
                max_iter=300,              # more iterations for better learning
                learning_rate=0.02,        # smaller LR + more iters = better generalization
                max_depth=4,
                min_samples_leaf=20,       # regularization: prevent overfitting on noise
                l2_regularization=1.0,     # L2 regularization for stability
                random_state=42,
                early_stopping=True,       # stop if validation loss plateaus
                validation_fraction=0.1,
                n_iter_no_change=15,
            )
            
    def train(self, X_train: np.ndarray, y_train: np.ndarray):
        self.model.fit(X_train, y_train)
        
    def predict_signals(self, X_test: np.ndarray, top_percentile: float = 90.0) -> np.ndarray:
        """
        Generates trading signals (-1, 0, 1) based on high-conviction predictions.
        top_percentile: only takes trades in the top (100 - top_percentile)% highest/lowest probability.
        
        Long signal (1):  P(UP) >= top percentile threshold → strong bullish conviction
        Short signal (-1): P(UP) <= bottom percentile threshold → strong bearish conviction
        """
        n = len(X_test)
        signals = np.zeros(n, dtype=int)
        
        if self.model_type == "linear":
            preds = self.model.predict(X_test)
            th_long = np.percentile(preds, top_percentile)
            th_short = np.percentile(preds, 100.0 - top_percentile)
            signals[preds >= th_long] = 1
            signals[preds <= th_short] = -1
        else:
            probs = self.model.predict_proba(X_test)[:, 1]  # Probability of UP
            th_long = np.percentile(probs, top_percentile)
            th_short = np.percentile(probs, 100.0 - top_percentile)
            signals[probs >= th_long] = 1    # High P(UP) → Long
            signals[probs <= th_short] = -1  # Low P(UP) → Short
            
        return signals

