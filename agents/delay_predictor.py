import sys
sys.path.append(".")

import os
import pickle
from datetime import datetime

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures

class DelayPredictor:
    """
    Uses a machine learning model to predict
    how many hours a delivery will be delayed.
    """
    
    MODEL_FILE = "data/delay_model.pkl"
    
    def __init__(self):
        if os.path.exists(self.MODEL_FILE):
            with open(self.MODEL_FILE, "rb") as f:
                payload = pickle.load(f)
            # Backward compatibility: older versions stored only the estimator.
            if isinstance(payload, dict) and "model" in payload:
                self.model = payload["model"]
                self.feature_stats = payload.get("feature_stats", {}) or {}
                self.train_mae = payload.get("train_mae")
            else:
                self.model = payload
                self.feature_stats = {}
                self.train_mae = None
            print("Loaded existing delay model")
        else:
            self.model = self._train()
            self.feature_stats = self._feature_stats
            self.train_mae = getattr(self, "_train_mae", None)
    
    def _train(self):
        """Train the delay model and cache stats for confidence."""
        print("Training delay prediction model...")

        # Ensure training data exists.
        if not os.path.exists("data/deliveries.csv"):
            from data.generator import make_deliveries

            df = make_deliveries(200)
            os.makedirs("data", exist_ok=True)
            df.to_csv("data/deliveries.csv", index=False)
        else:
            df = pd.read_csv("data/deliveries.csv")

        features = ["weather_score", "traffic_index"]
        X = df[features].astype(float)
        y = df["delay_hours"].astype(float)

        # Feature stats for confidence.
        self._feature_stats = {
            "weather_mean": float(X["weather_score"].mean()),
            "weather_std": float(X["weather_score"].std() or 1.0),
            "traffic_mean": float(X["traffic_index"].mean()),
            "traffic_std": float(X["traffic_index"].std() or 1.0),
        }

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Add non-linearities on top of the tree model.
        # This improves stability on hackathon-scale synthetic datasets.
        model = Pipeline(
            steps=[
                ("poly", PolynomialFeatures(degree=2, include_bias=False)),
                ("rf", RandomForestRegressor(n_estimators=220, random_state=42)),
            ]
        )
        model.fit(X_train, y_train)

        predictions = model.predict(X_test)
        error = mean_absolute_error(y_test, predictions)
        self._train_mae = float(error)
        print(f"Delay model trained! MAE: {error:.2f} hours")

        payload = {"model": model, "feature_stats": self._feature_stats, "train_mae": self._train_mae}
        with open(self.MODEL_FILE, "wb") as f:
            pickle.dump(payload, f)

        return model
    
    def predict(self, weather_score, traffic_index, delivery_id, audit_logger):
        """Predict delay for a delivery"""

        weather_score = float(weather_score)
        traffic_index = float(traffic_index)
        X = [[weather_score, traffic_index]]
        predicted_hours = float(self.model.predict(X)[0])
        predicted_hours = max(0, round(predicted_hours, 1))

        # Heuristic confidence: lower when inputs are far from the training distribution.
        stats = getattr(self, "feature_stats", {}) or {}
        w_mean = stats.get("weather_mean", weather_score)
        w_std = stats.get("weather_std", 1.0) or 1.0
        t_mean = stats.get("traffic_mean", traffic_index)
        t_std = stats.get("traffic_std", 1.0) or 1.0
        z_w = abs((weather_score - w_mean) / w_std)
        z_t = abs((traffic_index - t_mean) / t_std)
        distance = (z_w + z_t) / 2.0
        confidence = max(0.35, min(0.93, round(0.90 - 0.10 * distance, 2)))
        
        decision = {
            "agent": "delay_predictor",
            "delivery_id": delivery_id,
            "timestamp": datetime.utcnow().isoformat(),
            "inputs": {
                "weather_score": weather_score,
                "traffic_index": traffic_index
            },
            "predicted_delay_hours": predicted_hours,
            "confidence": confidence,
            "interpretation": self._interpret(predicted_hours)
        }
        
        audit_logger.log(decision)
        return decision
    
    def _interpret(self, hours):
        if hours < 2:   return "Minor delay — within acceptable range"
        if hours < 6:   return "Moderate delay — notify customer"
        if hours < 24:  return "Significant delay — consider rescheduling"
        return "Severe delay — escalate to manager"


if __name__ == "__main__":
    class FakeLogger:
        def log(self, data): print("LOG:", data)
    
    predictor = DelayPredictor()
    result = predictor.predict(
        weather_score=7.5,
        traffic_index=0.8,
        delivery_id="DEL-99999",
        audit_logger=FakeLogger()
    )
    print("\nPrediction:", result)