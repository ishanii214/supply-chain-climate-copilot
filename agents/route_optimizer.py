import sys
sys.path.append(".")
import requests
from datetime import datetime
from typing import Any

class RouteOptimizer:
    """
    Suggests the best route between two cities,
    taking into account climate risk.
    """
    def __init__(self):
        # Reuse a single disruption assessor for hazard scoring.
        from agents.disruption_detector import DisruptionDetector

        self.disruption_assessor = DisruptionDetector()
        self._weather_cache: dict[str, dict[str, Any]] = {}
    
    def optimize(self, delivery, disruption_result, audit_logger):
        # 1) Get candidate routes once (agent loop can reuse them).
        alternatives = self.get_route_alternatives(
            delivery["origin_lat"],
            delivery["origin_lon"],
            delivery["dest_lat"],
            delivery["dest_lon"],
        )

        severity = disruption_result["severity"]

        # 2) Pick the best route according to severity-specific buffers.
        selected, scored = self.choose_best_route(alternatives, severity)

        # 3) Build climate-adjusted recommendation.
        recommendation = self._climate_adjust(severity)

        # 4) Route-level hazard profile (hackathon-fast approximation).
        # If the disruption detector used scenario injection, we mirror the same hazard
        # score along the route so the "what-if" demo stays consistent and offline-friendly.
        if disruption_result.get("scenario_injected"):
            n_waypoints = 3
            base_weather = disruption_result.get("weather_data", {}) or {}
            base_hazard = float(disruption_result.get("hazard_score", 0.0) or 0.0)
            base_conf = disruption_result.get("confidence", None)
            route_hazard_profile = []
            for i in range(max(2, n_waypoints)):
                t = i / (max(2, n_waypoints) - 1)
                lat = delivery["origin_lat"] + t * (delivery["dest_lat"] - delivery["origin_lat"])
                lon = delivery["origin_lon"] + t * (delivery["dest_lon"] - delivery["origin_lon"])
                route_hazard_profile.append(
                    {
                        "waypoint_index": i,
                        "lat": round(lat, 4),
                        "lon": round(lon, 4),
                        "weather": base_weather,
                        "hazard_score": base_hazard,
                        "severity": disruption_result.get("severity"),
                        "confidence": base_conf,
                    }
                )
        else:
            route_hazard_profile = self.assess_route_hazard(
                olat=delivery["origin_lat"],
                olon=delivery["origin_lon"],
                dlat=delivery["dest_lat"],
                dlon=delivery["dest_lon"],
                n_waypoints=3,
            )
        max_hazard_score = None
        if route_hazard_profile:
            max_hazard_score = max(float(p.get("hazard_score", 0.0) or 0.0) for p in route_hazard_profile)

        decision = {
            "agent": "route_optimizer",
            "delivery_id": delivery["delivery_id"],
            "timestamp": datetime.utcnow().isoformat(),
            "original_route": selected,
            "route_scoring": scored,
            "alternatives": alternatives,
            "climate_severity": severity,
            "recommendation": recommendation,
            "regulatory_note": self._get_regulatory_note(severity),
            "route_hazard_profile": route_hazard_profile,
            "route_max_hazard_score": max_hazard_score,
        }

        audit_logger.log(decision)
        return decision

    def assess_route_hazard(self, olat: float, olon: float, dlat: float, dlon: float, n_waypoints: int = 3):
        """
        Approximates route hazard by sampling weather at evenly spaced points
        between origin and destination.
        """
        try:
            from data.weather import get_weather
        except Exception:
            return []

        n_waypoints = max(2, int(n_waypoints or 3))
        points = []
        for i in range(n_waypoints):
            t = i / (n_waypoints - 1)
            lat = olat + t * (dlat - olat)
            lon = olon + t * (dlon - olon)

            key = f"{round(lat, 2)}:{round(lon, 2)}"
            if key in self._weather_cache:
                weather = self._weather_cache[key]
            else:
                weather = get_weather(lat, lon)
                self._weather_cache[key] = weather

            assessment = self.disruption_assessor.assess(weather)
            points.append(
                {
                    "waypoint_index": i,
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "weather": weather,
                    "hazard_score": assessment.get("hazard_score"),
                    "severity": assessment.get("severity"),
                    "confidence": assessment.get("confidence"),
                }
            )

        return points

    def get_route_alternatives(self, olat, olon, dlat, dlon):
        """
        Get top route alternatives from OSRM (when available).
        Falls back to a single estimated route.
        """
        try:
            url = (
                "http://router.project-osrm.org/route/v1/driving/"
                f"{olon},{olat};{dlon},{dlat}"
            )
            resp = requests.get(
                url,
                params={"overview": "false", "alternatives": "true", "steps": "false"},
                timeout=8,
            )
            data = resp.json()
            
            if data["code"] == "Ok":
                routes = data.get("routes", [])[:3]
                alternatives = []
                for r in routes:
                    alternatives.append(
                        {
                            "distance_km": round(r["distance"] / 1000, 1),
                            "duration_hours": round(r["duration"] / 3600, 1),
                            "source": "OSRM live routing",
                            "osrm_route_index": len(alternatives),
                        }
                    )
                if alternatives:
                    return alternatives
        except Exception as e:
            print(f"OSRM error: {e}")
        
        # Fallback: estimate from coordinates
        import math
        dist = math.sqrt((dlat-olat)**2 + (dlon-olon)**2) * 111
        return [
            {
                "distance_km": round(dist, 1),
                "duration_hours": round(dist / 60, 1),
                "source": "estimated",
                "osrm_route_index": 0,
            }
        ]

    def choose_best_route(self, alternatives, severity):
        """
        Choose the best alternative route by minimizing adjusted ETA.
        """
        rec = self._climate_adjust(severity)
        buffer = float(rec.get("delay_buffer_hours", 0.0))

        scored = []
        best = None
        best_score = None
        for alt in alternatives:
            eta = float(alt["duration_hours"])
            adjusted_eta = eta + buffer
            score = adjusted_eta
            scored.append(
                {
                    "osrm_route_index": alt.get("osrm_route_index"),
                    "base_duration_hours": eta,
                    "adjusted_eta_hours": round(adjusted_eta, 2),
                }
            )
            if best is None or score < best_score:
                best = alt
                best_score = score

        return best, {"buffer_hours": buffer, "scores": scored}

    def _climate_adjust(self, severity):
        adjustments = {
            "CRITICAL": {
                "action": "Do NOT dispatch. Halt all vehicles on this route.",
                "delay_buffer_hours": 24,
                "alternative": "Use rail freight or wait 24h"
            },
            "HIGH": {
                "action": "Reroute via NH-48 avoiding low-lying areas.",
                "delay_buffer_hours": 6,
                "alternative": "Add 6-hour buffer to ETA"
            },
            "MEDIUM": {
                "action": "Proceed with caution. Avoid flooded underpasses.",
                "delay_buffer_hours": 2,
                "alternative": "Monitor and update customer"
            },
            "LOW": {
                "action": "Proceed normally.",
                "delay_buffer_hours": 0,
                "alternative": "No changes needed"
            }
        }
        return adjustments[severity]
    
    def _get_regulatory_note(self, severity):
        if severity in ["CRITICAL", "HIGH"]:
            return ("NDMA Advisory: Do not operate vehicles through active flood zones. "
                    "Verify with State Disaster Management Authority before dispatch.")
        return "No active advisories for this route."


if __name__ == "__main__":
    class FakeLogger:
        def log(self, data): print("LOG:", data)
    
    delivery = {
        "delivery_id": "DEL-99999",
        "origin_lat": 28.6, "origin_lon": 77.2,
        "dest_lat": 19.0,   "dest_lon": 72.8
    }
    disruption = {"severity": "HIGH"}
    
    agent = RouteOptimizer()
    result = agent.optimize(delivery, disruption, FakeLogger())
    print("\nRoute result:", result)