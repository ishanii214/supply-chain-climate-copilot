"""
Data Ingestion Agent — consolidates data fetching and validation.

Responsibilities:
  • Load delivery data and enrich with live weather
  • Validate all required fields
  • Normalize inputs for downstream agents
  • Publish DATA_READY event when done
"""

from __future__ import annotations

import sys
sys.path.append(".")

from datetime import datetime
from typing import Any

from core.base_agent import BaseAgent
from core.event_bus import EventType
from data.weather import get_weather


class DataIngestionAgent(BaseAgent):
    agent_name = "data_ingestion_agent"

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        delivery = state.get("delivery", {})
        delivery_id = delivery.get("delivery_id", "unknown")
        weather_override = state.get("weather_override")

        print(f"  [{self.agent_name}] Ingesting data for {delivery_id}...")

        # ── Validate required fields ────────────────────────────────────
        required = ["delivery_id", "origin_lat", "origin_lon", "dest_lat", "dest_lon"]
        missing = [f for f in required if f not in delivery]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        # ── Enrich with weather data ────────────────────────────────────
        if weather_override:
            weather = {
                "temperature_c": weather_override["temperature_c"],
                "rainfall_mm": weather_override["rainfall_mm"],
                "wind_kmh": weather_override["wind_kmh"],
                "source": "scenario_injection",
            }
        else:
            weather = get_weather(delivery["origin_lat"], delivery["origin_lon"])

        # ── Normalize delivery fields ───────────────────────────────────
        normalized = {
            **delivery,
            "traffic_index": float(delivery.get("traffic_index", 0.5)),
            "weather_score": float(delivery.get("weather_score", 0)),
        }

        result = {
            "delivery": normalized,
            "weather": weather,
            "weather_override_used": weather_override is not None,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "ready",
        }

        # ── Publish event ───────────────────────────────────────────────
        self.publish(EventType.DATA_READY, result, delivery_id=delivery_id)
        print(f"  [{self.agent_name}] Data ready. Weather source: {weather.get('source')}")

        return result
