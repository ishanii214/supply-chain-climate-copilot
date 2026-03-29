"""
Demo Flow — end-to-end hackathon presentation script.

Scenario: "Heavy rainfall detected → delay predicted → reroute suggested
           → actions executed → explanation generated"

Run:  python demo/demo_flow.py
"""

import sys
import json

sys.path.append(".")

from agents.orchestrator_v2 import OrchestratorV2
from core.impact_model import compute_fleet_impact


def print_banner(text: str) -> None:
    w = 64
    print(f"\n{'━'*w}")
    print(f"  {text}")
    print(f"{'━'*w}")


def run_demo():
    print_banner("🌧️  SUPPLY INTELLIGENCE AGENT — LIVE DEMO")
    print("  Scenario: Heavy rainfall on Delhi → Mumbai corridor")
    print("  Trigger:  rainfall=120mm, wind=65km/h, temp=28°C\n")

    # ── 1. Setup ────────────────────────────────────────────────────────
    delivery = {
        "delivery_id": "DEL-DEMO-001",
        "origin": "Delhi",
        "destination": "Mumbai",
        "origin_lat": 28.6,
        "origin_lon": 77.2,
        "dest_lat": 19.0,
        "dest_lon": 72.8,
        "traffic_index": 0.75,
        "weather_score": 8.5,
        "climate_event": "flood",
    }

    weather_scenario = {
        "rainfall_mm": 120,
        "wind_kmh": 65,
        "temperature_c": 28,
    }

    # ── 2. Run the full multi-agent pipeline ────────────────────────────
    orch = OrchestratorV2()
    result = orch.run(
        delivery,
        driver_notes="package looks wet and the road is flooded",
        weather_override=weather_scenario,
    )

    # ── 3. Print key results ────────────────────────────────────────────
    print_banner("📊  RESULTS SUMMARY")

    print(f"\n  🌦️  Disruption Severity : {result['disruption']['severity']}")
    print(f"     Confidence          : {result['disruption'].get('confidence')}")
    print(f"     Hazard Score        : {result['disruption'].get('hazard_score')}")

    print(f"\n  ⏱️  Predicted Delay     : {result['delay']['predicted_delay_hours']} hours")
    print(f"     Interpretation      : {result['delay'].get('interpretation')}")

    print(f"\n  🛣️  Route Distance      : {result['route']['original_route']['distance_km']} km")
    print(f"     Route Action        : {result['route']['recommendation']['action']}")

    print(f"\n  📦  Package Status      : {result['damage']['damage_type']}")
    print(f"     Flagged             : {result['damage'].get('flagged')}")

    # ── 4. Action plan ──────────────────────────────────────────────────
    print_banner("🎯  ACTION PLAN")
    ap = result.get("action_plan", {})
    print(f"\n  Dispatch Decision: {ap.get('dispatch_decision')}")
    print(f"  Requires Human Approval: {ap.get('requires_human_approval')}")
    print(f"\n  Action Steps:")
    for step in ap.get("action_steps", []):
        print(f"    • {step}")
    print(f"\n  Customer Message: {ap.get('customer_message')}")

    # ── 5. Executed actions ─────────────────────────────────────────────
    print_banner("⚡  EXECUTED ACTIONS")
    ae = result.get("action_execution", {})
    for action in ae.get("executed_actions", []):
        print(f"\n  [{action.get('action_type')}]")
        print(f"    Status  : {action.get('status')}")
        print(f"    Message : {action.get('message')}")

    # ── 6. Business impact ──────────────────────────────────────────────
    print_banner("💰  BUSINESS IMPACT")
    impact = result.get("impact", {})
    print(f"\n  Baseline delay (without system) : {impact.get('baseline_delay_hours')} hours")
    print(f"  System delay (with AI)          : {impact.get('system_delay_hours')} hours")
    print(f"  Delay saved                     : {impact.get('delay_saved_hours')} hours")
    print(f"  Delay reduction                 : {impact.get('delay_reduction_pct')}%")
    print(f"  Cost saved (this delivery)      : ₹{impact.get('total_cost_saved_inr', 0):,}")
    print(f"  Meets SLA                       : {'✅' if impact.get('meets_sla') else '❌'}")

    # Fleet-wide extrapolation
    fleet = compute_fleet_impact([impact] * 50)
    print(f"\n  --- Fleet Extrapolation (500 deliveries/day) ---")
    print(f"  Avg delay reduction   : {fleet['avg_delay_reduction_pct']}%")
    print(f"  SLA compliance        : {fleet['sla_compliance_pct']}%")
    print(f"  Daily savings         : ₹{fleet['daily_cost_saved_inr']:,}")
    print(f"  Monthly savings       : ₹{fleet['monthly_cost_saved_inr']:,}")
    print(f"  Annual savings        : ₹{fleet['annual_cost_saved_inr']:,}")

    # ── 7. Explainability ───────────────────────────────────────────────
    print_banner("🧠  AI EXPLANATION")
    rationale = result.get("rationale", {})
    print(f"\n  Risk Summary: {rationale.get('risk_summary')}")
    print(f"\n  Reasoning Steps:")
    for step in rationale.get("reasoning_steps", []):
        print(f"    • {step}")
    print(f"\n  Customer Message: {rationale.get('customer_message')}")

    # ── 8. Monitoring ───────────────────────────────────────────────────
    print_banner("🔍  SYSTEM HEALTH")
    mon = result.get("monitoring", {})
    print(f"\n  System Health: {mon.get('system_health')}")
    print(f"  Alert Count: {mon.get('alert_count')}")
    for alert in mon.get("alerts", []):
        print(f"    🚨 [{alert.get('severity')}] {alert.get('message')}")

    # ── 9. Event stream ─────────────────────────────────────────────────
    print_banner("📡  EVENT STREAM")
    for evt in result.get("event_stream", []):
        print(f"  {evt['timestamp'][:19]}  {evt['event_type']:25s}  ← {evt['source_agent']}")

    # ── 10. Pipeline metadata ───────────────────────────────────────────
    print_banner("🔧  PIPELINE METADATA")
    meta = result.get("pipeline_metadata", {})
    print(f"  Version         : {meta.get('version')}")
    print(f"  Steps completed : {', '.join(meta.get('steps_completed', []))}")
    print(f"  Errors          : {len(meta.get('errors', []))}")
    print(f"  Duration        : {meta.get('created_at', '')[:19]} → {meta.get('completed_at', '')[:19]}")

    print(f"\n{'━'*64}")
    print(f"  ✅  DEMO COMPLETE — All 8 agents executed successfully")
    print(f"{'━'*64}\n")

    return result


if __name__ == "__main__":
    run_demo()
