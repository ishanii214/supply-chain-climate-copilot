import base64
import sys
from typing import Any, Optional

sys.path.append(".")

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agents.orchestrator import Orchestrator
from agents.orchestrator_v2 import OrchestratorV2
from compliance.audit_logger import AuditLogger
from llm.explainer import LLMExplainer
from core.impact_model import compute_fleet_impact


app = FastAPI(title="Supply Intelligence Agent", version="0.1.0")

# Reuse a single agent instance to avoid repeated ML model loads.
orch = Orchestrator()
orch_v2 = OrchestratorV2()


class DeliveryPayload(BaseModel):
    delivery_id: str
    origin: str = ""
    destination: str = ""
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    traffic_index: float = 0.5


class AnalyzeRequest(BaseModel):
    delivery: DeliveryPayload
    driver_notes: str = ""
    image_base64: Optional[str] = None
    scenario: str = Field(default="Real weather data")
    include_explanation: bool = False
    business_params: dict[str, Any] = Field(default_factory=dict)


SCENARIO_OVERRIDES = {
    "Simulate flood": {"rainfall_mm": 120, "wind_kmh": 65, "temperature_c": 28},
    "Simulate cyclone": {"rainfall_mm": 85, "wind_kmh": 145, "temperature_c": 26},
    "Simulate heatwave": {"rainfall_mm": 0, "wind_kmh": 20, "temperature_c": 47},
}


def _decode_image_base64(image_base64: Optional[str]) -> Optional[bytes]:
    if not image_base64:
        return None
    try:
        return base64.b64decode(image_base64)
    except Exception:
        return None


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── V1 endpoint (backward compatible) ──────────────────────────────────────
@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    override = SCENARIO_OVERRIDES.get(req.scenario)
    image_bytes = _decode_image_base64(req.image_base64)

    result = orch.run(
        req.delivery.model_dump(),
        driver_notes=req.driver_notes or "",
        image_bytes=image_bytes,
        weather_override=override,
        business_params=req.business_params,
    )

    if req.include_explanation:
        try:
            result["plain_english_report"] = LLMExplainer().explain(result)
        except Exception as e:
            result["plain_english_report"] = f"Explanation unavailable: {e}"

    return result


# ── V2 endpoint (multi-agent pipeline) ─────────────────────────────────────
@app.post("/api/analyze/v2")
def analyze_v2(req: AnalyzeRequest):
    """Run the full multi-agent pipeline with event bus, impact model, and monitoring."""
    override = SCENARIO_OVERRIDES.get(req.scenario)
    image_bytes = _decode_image_base64(req.image_base64)

    result = orch_v2.run(
        req.delivery.model_dump(),
        driver_notes=req.driver_notes or "",
        image_bytes=image_bytes,
        weather_override=override,
        business_params=req.business_params,
    )

    if req.include_explanation:
        try:
            result["plain_english_report"] = LLMExplainer().explain(result)
        except Exception as e:
            result["plain_english_report"] = f"Explanation unavailable: {e}"

    return result


# ── Event stream endpoint ──────────────────────────────────────────────────
@app.get("/api/events/{delivery_id}")
def get_events(delivery_id: str):
    """Get the event stream for a specific delivery (from the V2 pipeline)."""
    events = orch_v2.get_events(delivery_id)
    return {"delivery_id": delivery_id, "events": events, "count": len(events)}


# ── Impact model endpoint ─────────────────────────────────────────────────
@app.get("/api/impact")
def get_impact():
    """Get fleet-wide impact metrics from past pipeline runs."""
    memory = orch_v2.get_memory(last_n=50)
    if not memory:
        return {"message": "No pipeline runs yet. Run /api/analyze/v2 first."}

    # Build impact list from memory
    from core.impact_model import compute_single_delivery_impact
    impacts = []
    for run in memory:
        imp = compute_single_delivery_impact(
            predicted_delay_hours=float(run.get("delay_hours", 3)),
            severity=run.get("severity", "LOW"),
            damage_flagged=False,
            dispatch_decision=run.get("dispatch_decision", "PROCEED"),
        )
        impacts.append(imp)

    fleet = compute_fleet_impact(impacts)
    return {"fleet_impact": fleet, "runs_analyzed": len(impacts)}


# ── Audit endpoint ─────────────────────────────────────────────────────────
@app.get("/api/audit/{delivery_id}")
def audit_for_delivery(delivery_id: str):
    audit = AuditLogger()
    return {"delivery_id": delivery_id, "events": audit.get_for_delivery(delivery_id)}

