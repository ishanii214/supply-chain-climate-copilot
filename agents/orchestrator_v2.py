"""
Orchestrator V2 - runs the multi-agent supply chain pipeline as a
sequence of steps (INGEST -> DETECT_DISRUPTION -> ... -> MONITOR).
"""

from __future__ import annotations

import sys
sys.path.append(".")

from datetime import datetime
from typing import Any

from core.event_bus import EventBus, EventType, Event
from core.state_manager import StateManager, PipelineState
from core.impact_model import compute_single_delivery_impact
from compliance.audit_logger import AuditLogger
from compliance.guardrails import GuardrailEngine


class OrchestratorV2:
    """
    State-machine orchestrator with named steps and conditional edges.
    """

    # Ordered list of pipeline steps
    STEPS = [
        "INGEST",
        "DETECT_DISRUPTION",
        "PREDICT_DELAY",
        "OPTIMIZE_ROUTE",
        "DETECT_DAMAGE",
        "PLAN_ACTIONS",
        "EXECUTE_ACTIONS",
        "EXPLAIN",
        "COMPUTE_IMPACT",
        "MONITOR",
    ]

    def __init__(self) -> None:
        self.event_bus = EventBus()
        self.state_manager = StateManager()
        self.audit = AuditLogger()
        self.guardrails = GuardrailEngine()

        # Lazy-loaded agents (initialized on first run)
        self._agents: dict[str, Any] = {}
        self._agents_loaded = False

    def _load_agents(self) -> None:
        """Lazy-load all agents to avoid import-time overhead."""
        from agents.data_ingestion_agent import DataIngestionAgent
        from agents.disruption_detector import DisruptionDetector
        from agents.delay_predictor import DelayPredictor
        from agents.route_optimizer import RouteOptimizer
        from agents.damage_detector import DamageDetector
        from agents.action_planner import ActionPlanner
        from agents.action_execution_agent import ActionExecutionAgent
        from agents.monitoring_agent import MonitoringAgent
        from llm.reasoner import LLMReasoner
        
        self._agents = {
            "ingestion": DataIngestionAgent(event_bus=self.event_bus, audit_logger=self.audit),
            "disruption": DisruptionDetector(),
            "delay": DelayPredictor(),
            "route": RouteOptimizer(),
            "damage": DamageDetector(),
            "action_planner": ActionPlanner(),
            "action_executor": ActionExecutionAgent(event_bus=self.event_bus, audit_logger=self.audit),
            "monitoring": MonitoringAgent(event_bus=self.event_bus, audit_logger=self.audit),
            "reasoner": LLMReasoner(),
        }
        self._agents_loaded = True

    #  MAIN ENTRY POINT
    
    def run(
        self,
        delivery: dict,
        driver_notes: str = "",
        image_bytes: bytes | None = None,
        weather_override: dict | None = None,
        business_params: dict | None = None,
    ) -> dict:
        """
        Run the full multi-agent pipeline for one delivery.
        Returns the complete result as a dict.
        """
        if not self._agents_loaded:
            self._load_agents()

        delivery_id = delivery.get("delivery_id", "unknown")
        print(f"\n{'='*60}")
        print(f"  SUPPLY INTELLIGENCE AGENT — Pipeline V2")
        print(f"  Delivery: {delivery_id}")
        print(f"{'='*60}")

        # Create pipeline state
        pipeline = self.state_manager.create_state(delivery)

        # Publish pipeline start event
        self.event_bus.publish(Event(
            event_type=EventType.PIPELINE_STARTED,
            source_agent="orchestrator_v2",
            delivery_id=delivery_id,
            data={"delivery_id": delivery_id, "steps": self.STEPS},
        ))

        # Clean and validate input 
        delivery = self.guardrails.clean_input(delivery)
        self.guardrails.validate_input(delivery)

        # Shared context for all steps
        ctx = {
            "delivery": delivery,
            "delivery_id": delivery_id,
            "driver_notes": driver_notes,
            "image_bytes": image_bytes,
            "weather_override": weather_override,
            "business_params": business_params or {},
        }

        # Execute each step 
        for step in self.STEPS:
            pipeline.mark_step(step)
            print(f"\n  Step: {step}")
            try:
                ctx = self._execute_step(step, ctx, pipeline)
            except Exception as exc:
                pipeline.errors.append({
                    "step": step,
                    "error": str(exc),
                    "timestamp": datetime.utcnow().isoformat(),
                })
                print(f"    Error in {step}: {exc}")
                # Continue to next step — graceful degradation

        # Finalize 
        self.state_manager.complete(pipeline)

        # Build the final result
        result = self._build_result(pipeline, ctx)
        result = self.guardrails.validate_output(result)

        self.event_bus.publish(Event(
            event_type=EventType.PIPELINE_COMPLETED,
            source_agent="orchestrator_v2",
            delivery_id=delivery_id,
            data={"delivery_id": delivery_id, "overall_risk": result.get("overall_risk")},
        ))

        self.audit.log({
            "agent": "orchestrator_v2",
            "event": "pipeline_completed",
            "delivery_id": delivery_id,
            "overall_risk": result.get("overall_risk"),
            "steps_completed": pipeline.steps_completed,
            "timestamp": datetime.utcnow().isoformat(),
        })

        print(f"\n{'='*60}")
        print(f"  Pipeline complete | Risk: {result.get('overall_risk')}")
        print(f"  Events: {len(self.event_bus.get_history(delivery_id))}")
        print(f"{'='*60}\n")

        return result

    #  STEP DISPATCH — each step runs one agent and updates context

    def _execute_step(self, step: str, ctx: dict, pipeline: PipelineState) -> dict:

        if step == "INGEST":
            result = self._agents["ingestion"].safe_process(ctx)
            pipeline.ingestion = result
            ctx["weather"] = result.get("weather", {})
            ctx["delivery"] = result.get("delivery", ctx["delivery"])

        elif step == "DETECT_DISRUPTION":
            delivery = ctx["delivery"]
            if ctx.get("weather_override"):
                disruption = self._agents["disruption"].detect_with_override(
                    delivery, self.audit, ctx["weather_override"]
                )
            else:
                disruption = self._agents["disruption"].detect(delivery, self.audit)
            pipeline.disruption = disruption
            ctx["disruption"] = disruption
            self.event_bus.publish(Event(
                event_type=EventType.DISRUPTION_DETECTED,
                source_agent="disruption_detector",
                delivery_id=ctx["delivery_id"],
                data={"severity": disruption["severity"], "confidence": disruption.get("confidence")},
            ))

        elif step == "PREDICT_DELAY":
            disruption = ctx["disruption"]
            delivery = ctx["delivery"]
            delay = self._agents["delay"].predict(
                weather_score=disruption["weather_data"]["rainfall_mm"] / 10,
                traffic_index=delivery.get("traffic_index", 0.5),
                delivery_id=ctx["delivery_id"],
                audit_logger=self.audit,
            )
            # Severity-based caps
            delay_caps = {"LOW": 3.0, "MEDIUM": 8.0, "HIGH": 20.0, "CRITICAL": 48.0}
            severity = disruption["severity"]
            if delay["predicted_delay_hours"] > delay_caps.get(severity, 48):
                delay["predicted_delay_hours"] = delay_caps[severity]
                delay["capped_by_severity"] = True
            pipeline.delay = delay
            ctx["delay"] = delay
            self.event_bus.publish(Event(
                event_type=EventType.DELAY_PREDICTED,
                source_agent="delay_predictor",
                delivery_id=ctx["delivery_id"],
                data={"predicted_delay_hours": delay["predicted_delay_hours"]},
            ))

        elif step == "OPTIMIZE_ROUTE":
            route = self._agents["route"].optimize(
                ctx["delivery"], ctx["disruption"], self.audit
            )
            pipeline.route = route
            ctx["route"] = route
            self.event_bus.publish(Event(
                event_type=EventType.ROUTE_OPTIMIZED,
                source_agent="route_optimizer",
                delivery_id=ctx["delivery_id"],
                data={"distance_km": route.get("original_route", {}).get("distance_km")},
            ))

        elif step == "DETECT_DAMAGE":
            image_bytes = ctx.get("image_bytes")
            driver_notes = ctx.get("driver_notes", "")
            if image_bytes:
                damage = self._agents["damage"].detect_from_bytes(
                    image_bytes, ctx["delivery_id"], self.audit
                )
            elif driver_notes:
                damage = self._agents["damage"].detect_from_description(
                    driver_notes, ctx["delivery_id"], self.audit
                )
            else:
                damage = self._agents["damage"]._no_image_result(ctx["delivery_id"], self.audit)
            pipeline.damage = damage
            ctx["damage"] = damage
            self.event_bus.publish(Event(
                event_type=EventType.DAMAGE_ASSESSED,
                source_agent="damage_detector",
                delivery_id=ctx["delivery_id"],
                data={"damage_type": damage.get("damage_type"), "flagged": damage.get("flagged")},
            ))

        elif step == "PLAN_ACTIONS":
            # Refine delay with routing buffer
            route_buffer = float(ctx["route"].get("recommendation", {}).get("delay_buffer_hours", 0) or 0)
            inspection_buffer = 2.0 if ctx["damage"].get("flagged", False) else 0.0
            raw_delay = float(ctx["delay"].get("predicted_delay_hours", 0) or 0)
            refined = raw_delay + route_buffer + inspection_buffer
            delay_caps = {"LOW": 3.0, "MEDIUM": 8.0, "HIGH": 20.0, "CRITICAL": 48.0}
            sev = ctx["disruption"].get("severity")
            if sev in delay_caps:
                refined = min(refined, delay_caps[sev])
            ctx["delay"]["predicted_delay_hours"] = round(refined, 1)

            interim = {
                "delivery_id": ctx["delivery_id"],
                "origin": ctx["delivery"].get("origin", ""),
                "destination": ctx["delivery"].get("destination", ""),
                "disruption": ctx["disruption"],
                "delay": ctx["delay"],
                "route": ctx["route"],
                "damage": ctx["damage"],
                "overall_risk": ctx["disruption"]["severity"],
            }
            action_plan = self._agents["action_planner"].plan(
                interim, business_params=ctx.get("business_params")
            )
            pipeline.action_plan = action_plan
            ctx["action_plan"] = action_plan
            self.event_bus.publish(Event(
                event_type=EventType.ACTION_PLANNED,
                source_agent="action_planner",
                delivery_id=ctx["delivery_id"],
                data={"dispatch_decision": action_plan.get("dispatch_decision")},
            ))

        elif step == "EXECUTE_ACTIONS":
            # Conditional: skip execution if LOW severity and no damage
            severity = ctx["disruption"].get("severity", "LOW")
            damage_flagged = ctx["damage"].get("flagged", False)
            if severity == "LOW" and not damage_flagged:
                pipeline.action_execution = {
                    "skipped": True,
                    "reason": "LOW severity, no damage — no intervention needed",
                }
                ctx["action_execution"] = pipeline.action_execution
                print("    ↳ Skipped (LOW severity, no damage)")
            else:
                exec_result = self._agents["action_executor"].safe_process(ctx)
                pipeline.action_execution = exec_result
                ctx["action_execution"] = exec_result

        elif step == "EXPLAIN":
            interim = {
                "delivery_id": ctx["delivery_id"],
                "origin": ctx["delivery"].get("origin", ""),
                "destination": ctx["delivery"].get("destination", ""),
                "disruption": ctx["disruption"],
                "delay": ctx["delay"],
                "route": ctx["route"],
                "damage": ctx["damage"],
            }
            rationale = self._agents["reasoner"].generate_rationale(
                interim, ctx.get("action_plan", {})
            )
            pipeline.explanation = rationale
            ctx["explanation"] = rationale
            self.event_bus.publish(Event(
                event_type=EventType.EXPLANATION_READY,
                source_agent="llm_reasoner",
                delivery_id=ctx["delivery_id"],
                data={"has_rationale": bool(rationale)},
            ))

        elif step == "COMPUTE_IMPACT":
            impact = compute_single_delivery_impact(
                predicted_delay_hours=float(ctx["delay"].get("predicted_delay_hours", 0)),
                severity=ctx["disruption"].get("severity", "LOW"),
                damage_flagged=ctx["damage"].get("flagged", False),
                dispatch_decision=ctx.get("action_plan", {}).get("dispatch_decision", "PROCEED"),
            )
            pipeline.impact = impact
            ctx["impact"] = impact

        elif step == "MONITOR":
            # Inject memory for trend analysis
            monitor_ctx = {**ctx, "_memory": self.state_manager.get_memory()}
            result = self._agents["monitoring"].safe_process(monitor_ctx)
            pipeline.monitoring = result
            ctx["monitoring"] = result

        return ctx

    #  BUILD FINAL RESULT — backward-compatible with v1

    def _build_result(self, pipeline: PipelineState, ctx: dict) -> dict:
        return {
            "delivery_id": pipeline.delivery_id,
            "origin": ctx["delivery"].get("origin", ""),
            "destination": ctx["delivery"].get("destination", ""),
            "disruption": pipeline.disruption,
            "delay": pipeline.delay,
            "route": pipeline.route,
            "damage": pipeline.damage,
            "overall_risk": pipeline.disruption.get("severity", "UNKNOWN"),
            "action_plan": pipeline.action_plan,
            "action_execution": pipeline.action_execution,
            "rationale": pipeline.explanation,
            "impact": pipeline.impact,
            "monitoring": pipeline.monitoring,
            "reasoning_trace": [
                {"step": s, "timestamp": datetime.utcnow().isoformat()}
                for s in pipeline.steps_completed
            ],
            "event_stream": self.event_bus.get_history(pipeline.delivery_id),
            "pipeline_metadata": {
                "version": "v2",
                "steps_completed": pipeline.steps_completed,
                "errors": pipeline.errors,
                "created_at": pipeline.created_at,
                "completed_at": pipeline.completed_at,
            },
            "completed_at": pipeline.completed_at,
        }

    #  ACCESSORS for API / dashboard
  
    def get_events(self, delivery_id: str) -> list[dict]:
        return self.event_bus.get_history(delivery_id)

    def get_memory(self, last_n: int = 10) -> list[dict]:
        return self.state_manager.get_memory(last_n)


# Quick self-test
if __name__ == "__main__":
    import pandas as pd

    df = pd.read_csv("data/deliveries.csv")
    delivery = df.iloc[0].to_dict()

    orch = OrchestratorV2()
    result = orch.run(
        delivery,
        driver_notes="package looks wet",
        weather_override={"rainfall_mm": 120, "wind_kmh": 65, "temperature_c": 28},
    )

    import json
    print("\n--- FINAL RESULT ---")
    print(json.dumps(result, indent=2, default=str))
