"""
XGBoost / Gradient Boosting AI Meta Filter for Strategy 2
"""
import os
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

class Strategy2AIFilter:
    def __init__(self, max_iter: int = 150, learning_rate: float = 0.03, max_depth: int = 4):
        self.model = HistGradientBoostingClassifier(
            max_iter=max_iter,
            learning_rate=learning_rate,
            max_depth=max_depth,
            class_weight="balanced",
            random_state=42
        )
        self.is_trained = False
        self.feature_cols = []
        
    def train(self, X_train: np.ndarray, y_train: np.ndarray, feature_cols: list[str] = None):
        self.feature_cols = feature_cols or []
        self.model.fit(X_train, y_train)
        self.is_trained = True
        
    def predict_probability(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained:
            raise ValueError("Model has not been trained yet.")
        if len(X.shape) == 1:
            X = X.reshape(1, -1)
        probs = self.model.predict_proba(X)[:, 1]
        return probs

    def save(self, file_path: str):
        joblib.dump({"model": self.model, "feature_cols": self.feature_cols}, file_path)

    @classmethod
    def load(cls, file_path: str):
        instance = cls()
        data = joblib.load(file_path)
        instance.model = data["model"]
        instance.feature_cols = data["feature_cols"]
        instance.is_trained = True
        return instance
