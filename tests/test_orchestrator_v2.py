"""
Integration test for OrchestratorV2 — runs the full pipeline
with injected weather and validates all state transitions.
"""

import sys
sys.path.append(".")

from agents.orchestrator_v2 import OrchestratorV2


def test_full_pipeline_flood():
    """Full pipeline with flood scenario produces expected outputs."""
    delivery = {
        "delivery_id": "DEL-TEST-001",
        "origin": "Delhi",
        "destination": "Mumbai",
        "origin_lat": 28.6,
        "origin_lon": 77.2,
        "dest_lat": 19.0,
        "dest_lon": 72.8,
        "traffic_index": 0.7,
        "weather_score": 8.0,
        "climate_event": "flood",
    }

    orch = OrchestratorV2()
    result = orch.run(
        delivery,
        driver_notes="package looks wet",
        weather_override={"rainfall_mm": 120, "wind_kmh": 65, "temperature_c": 28},
    )

    # ── Validate all key sections exist ─────────────────────────────
    assert "disruption" in result, "Missing disruption"
    assert "delay" in result, "Missing delay"
    assert "route" in result, "Missing route"
    assert "damage" in result, "Missing damage"
    assert "action_plan" in result, "Missing action_plan"
    assert "action_execution" in result, "Missing action_execution"
    assert "rationale" in result, "Missing rationale"
    assert "impact" in result, "Missing impact"
    assert "monitoring" in result, "Missing monitoring"
    assert "event_stream" in result, "Missing event_stream"
    assert "pipeline_metadata" in result, "Missing pipeline_metadata"

    # ── Validate severity (rainfall=120mm should be HIGH or CRITICAL) ──
    assert result["disruption"]["severity"] in ("HIGH", "CRITICAL")

    # ── Validate impact has required fields ─────────────────────────
    impact = result["impact"]
    assert "delay_reduction_pct" in impact
    assert "total_cost_saved_inr" in impact
    assert "meets_sla" in impact

    # ── Validate event stream has events ────────────────────────────
    events = result["event_stream"]
    assert len(events) >= 5, f"Expected ≥5 events, got {len(events)}"
    event_types = [e["event_type"] for e in events]
    assert "PIPELINE_STARTED" in event_types
    assert "DISRUPTION_DETECTED" in event_types
    assert "DELAY_PREDICTED" in event_types

    # ── Validate pipeline metadata ──────────────────────────────────
    meta = result["pipeline_metadata"]
    assert meta["version"] == "v2"
    assert len(meta["steps_completed"]) == 10  # all 10 steps

    # ── Validate action execution ran (severity > LOW) ──────────────
    ae = result["action_execution"]
    assert ae.get("skipped") is not True, "Actions should execute for HIGH severity"

    print("✓ test_full_pipeline_flood passed — all assertions OK")


def test_low_severity_skips_execution():
    """LOW severity with no damage should skip action execution."""
    delivery = {
        "delivery_id": "DEL-TEST-002",
        "origin": "Chennai",
        "destination": "Bengaluru",
        "origin_lat": 13.0,
        "origin_lon": 80.2,
        "dest_lat": 12.9,
        "dest_lon": 77.5,
        "traffic_index": 0.3,
    }

    orch = OrchestratorV2()
    result = orch.run(
        delivery,
        driver_notes="package is fine",
        weather_override={"rainfall_mm": 2, "wind_kmh": 5, "temperature_c": 30},
    )

    assert result["disruption"]["severity"] == "LOW"
    ae = result["action_execution"]
    assert ae.get("skipped") is True, "LOW severity should skip execution"
    print("✓ test_low_severity_skips_execution passed")


def test_memory_across_runs():
    """StateManager memory persists across multiple pipeline runs."""
    orch = OrchestratorV2()

    delivery = {
        "delivery_id": "DEL-MEM-001",
        "origin": "Delhi",
        "destination": "Mumbai",
        "origin_lat": 28.6,
        "origin_lon": 77.2,
        "dest_lat": 19.0,
        "dest_lon": 72.8,
        "traffic_index": 0.5,
    }

    # Run twice
    orch.run(delivery, weather_override={"rainfall_mm": 50, "wind_kmh": 30, "temperature_c": 35})
    delivery["delivery_id"] = "DEL-MEM-002"
    orch.run(delivery, weather_override={"rainfall_mm": 100, "wind_kmh": 60, "temperature_c": 28})

    memory = orch.get_memory()
    assert len(memory) == 2, f"Expected 2 runs in memory, got {len(memory)}"
    print("✓ test_memory_across_runs passed")


if __name__ == "__main__":
    test_full_pipeline_flood()
    test_low_severity_skips_execution()
    test_memory_across_runs()
    print("\n✅ All orchestrator v2 tests passed!")
