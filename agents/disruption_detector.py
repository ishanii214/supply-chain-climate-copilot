import sys
sys.path.append(".")  # so Python can find our other files

from compliance import audit_logger
from data.weather import get_weather
from datetime import datetime

class DisruptionDetector:
    """
    This agent looks at weather data and decides
    how dangerous it is for deliveries.
    """
    
    def detect(self, delivery, audit_logger):
        """
        delivery: a dict with origin_lat, origin_lon etc
        audit_logger: the object that records every decision
        Returns: a dict describing the risk
        """

        # Step 1: Get live weather for origin city
        weather = get_weather(delivery["origin_lat"], delivery["origin_lon"])

        # Step 2: Assess severity from weather
        assessment = self.assess(weather)
        severity = assessment["severity"]
        
        # Step 3: Build our decision record
        decision = {
            "agent": "disruption_detector",
            "delivery_id": delivery["delivery_id"],
            "timestamp": datetime.utcnow().isoformat(),
            "weather_data": weather,
            "severity": severity,
            "confidence": assessment["confidence"],
            "hazard_score": assessment["hazard_score"],
            "severity_probabilities": assessment["severity_probabilities"],
            "action": self._recommend_action(severity)
        }
        
        # Step 4: Log it to audit trail (very important for judges)
        audit_logger.log(decision)
        
        return decision
    def detect_with_override(self, delivery, audit_logger, weather_override):
        """Same as detect() but uses injected weather instead of live API"""
        
        weather = {
            "temperature_c": weather_override["temperature_c"],
            "rainfall_mm":   weather_override["rainfall_mm"],
            "wind_kmh":      weather_override["wind_kmh"],
            "source":        "scenario_injection"
        }
        
        assessment = self.assess(weather)
        severity = assessment["severity"]
        
        decision = {
            "agent": "disruption_detector",
            "delivery_id": delivery["delivery_id"],
            "timestamp": datetime.utcnow().isoformat(),
            "weather_data": weather,
            "severity": severity,
            "confidence": assessment["confidence"],
            "hazard_score": assessment["hazard_score"],
            "severity_probabilities": assessment["severity_probabilities"],
            "action": self._recommend_action(severity),
            "scenario_injected": True
        }
        
        audit_logger.log(decision)
        return decision
    
    def assess(self, weather: dict) -> dict:
        """
        Produces a severity + confidence + probabilities from weather signals.
        This is designed for the agent loop (can be re-run with injected scenarios).
        """
        rain = float(weather.get("rainfall_mm", 0.0))
        wind = float(weather.get("wind_kmh", 0.0))
        temp = float(weather.get("temperature_c", 30.0))

        # Hazard score in [0, 1] using soft saturation.
        # - rainfall dominates flooding risk
        # - wind contributes to cyclone/storm risk
        # - temperature contributes to heatwave risk
        rain_term = min(1.0, rain / 120.0)
        wind_term = min(1.0, wind / 150.0)
        temp_term = min(1.0, max(0.0, temp - 35.0) / 15.0)
        hazard_score = 0.55 * rain_term + 0.30 * wind_term + 0.15 * temp_term
        hazard_score = max(0.0, min(1.0, round(hazard_score, 4)))

        # Map hazard score to severity band.
        if hazard_score >= 0.78:
            severity = "CRITICAL"
        elif hazard_score >= 0.55:
            severity = "HIGH"
        elif hazard_score >= 0.30:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        # Confidence grows as hazard_score is safely inside a band.
        band_centers = {"LOW": 0.15, "MEDIUM": 0.42, "HIGH": 0.66, "CRITICAL": 0.90}
        center = band_centers.get(severity, 0.3)
        # wider bands when confidence is uncertain
        band_width = {"LOW": 0.22, "MEDIUM": 0.20, "HIGH": 0.20, "CRITICAL": 0.14}.get(severity, 0.2)
        dist = abs(hazard_score - center)
        conf = 0.55 + 0.35 * (1.0 - min(1.0, dist / max(1e-6, band_width)))
        conf = round(max(0.50, min(0.97, conf)), 2)

        # Probabilities: softened one-vs-rest around centers.
        def soft_prob(s: str) -> float:
            c = band_centers[s]
            w = {"LOW": 0.18, "MEDIUM": 0.16, "HIGH": 0.16, "CRITICAL": 0.12}[s]
            return math.exp(-((hazard_score - c) ** 2) / (2 * w * w))

        import math

        probs_raw = {s: soft_prob(s) for s in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]}
        total = sum(probs_raw.values()) or 1.0
        severity_probabilities = {k: round(v / total, 3) for k, v in probs_raw.items()}

        return {
            "severity": severity,
            "confidence": conf,
            "hazard_score": hazard_score,
            "severity_probabilities": severity_probabilities,
        }
    
    def _recommend_action(self, severity):
        actions = {
            "CRITICAL": "STOP — halt dispatch, contact customer immediately",
            "HIGH":     "REROUTE — find alternative path before dispatching",
            "MEDIUM":   "MONITOR — proceed with caution, check again in 2 hours",
            "LOW":      "PROCEED — conditions are safe for delivery"
        }
        return actions[severity]


# Quick test — run this file directly to check it works
if __name__ == "__main__":
    # Make a simple fake audit logger for testing
    class FakeLogger:
        def log(self, data):
            print("AUDIT LOG:", data)
    
    fake_delivery = {
        "delivery_id": "DEL-99999",
        "origin_lat": 28.6,
        "origin_lon": 77.2
    }
    
    agent = DisruptionDetector()
    result = agent.detect(fake_delivery, FakeLogger())
    print("\nResult:", result)