import sys
sys.path.append(".")

from compliance.guardrails import GuardrailEngine
from agents.disruption_detector import DisruptionDetector
from agents.delay_predictor import DelayPredictor
from agents.route_optimizer import RouteOptimizer
from agents.damage_detector import DamageDetector
from compliance.audit_logger import AuditLogger
from agents.action_planner import ActionPlanner
from llm.reasoner import LLMReasoner
from datetime import datetime

class Orchestrator:
    """
    The brain. Runs all agents in order and
    combines their outputs into one final result.
    """
    
    def __init__(self):
        self.guardrails = GuardrailEngine()
        self.audit = AuditLogger()
        self.disruption_agent = DisruptionDetector()
        self.delay_agent = DelayPredictor()
        self.route_agent = RouteOptimizer()
        self.damage_agent = DamageDetector()
        self.action_planner = ActionPlanner()
        self.reasoner = LLMReasoner()
    
    def run(
        self,
        delivery: dict,
        driver_notes: str = "",
        image_bytes: bytes | None = None,
        weather_override: dict | None = None,
        max_iterations: int = 2,
        business_params: dict | None = None,
    ) -> dict:
        """
        Run all agents for one delivery.
        delivery: dict with delivery info
        driver_notes: optional text from driver about package condition
        image_bytes: optional parcel image bytes for multimodal damage checks
        weather_override: optional injected weather scenario (demo)
        max_iterations: decision loop iterations (agentic refinement)
        business_params: optional values like cost_per_delay_hour
        """
        
        print(f"\n--- Running agents for {delivery['delivery_id']} ---")
        
        # Log that we started
        self.audit.log({
            "agent": "orchestrator",
            "event": "started",
            "delivery_id": delivery["delivery_id"],
            "timestamp": datetime.utcnow().isoformat()
        })
        
        delivery = self.guardrails.clean_input(delivery)
        self.guardrails.validate_input(delivery)

        reasoning_trace = []
        agentic_actions = []
        sensitivity = None
        final_action_plan = None
        final_rationale = None

        for it in range(max_iterations):
            reasoning_trace.append(
                {
                    "step": "decision_loop_iteration",
                    "iteration": it,
                    "timestamp": datetime.utcnow().isoformat(),
                    "summary": "Starting sensing/prediction/plan cycle",
                }
            )

            # Agent 1: Disruption detection (live weather or scenario injection)
            print("Running disruption detector...")
            if weather_override:
                disruption = self.disruption_agent.detect_with_override(
                    delivery, self.audit, weather_override
                )
            else:
                disruption = self.disruption_agent.detect(delivery, self.audit)

            reasoning_trace.append(
                {
                    "step": "disruption_assessment",
                    "iteration": it,
                    "severity": disruption["severity"],
                    "confidence": disruption.get("confidence"),
                    "hazard_score": disruption.get("hazard_score"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "summary": "Weather-to-severity risk scored",
                }
            )

            print(f"  Severity: {disruption['severity']} (conf: {disruption['confidence']})")

            # Agent 2: Delay prediction
            print("Running delay predictor...")
            delay = self.delay_agent.predict(
                weather_score=disruption["weather_data"]["rainfall_mm"] / 10,
                traffic_index=delivery.get("traffic_index", 0.5),
                delivery_id=delivery["delivery_id"],
                audit_logger=self.audit,
            )

            # Severity-based caps to avoid runaway outputs in demo.
            delay_caps = {"LOW": 3.0, "MEDIUM": 8.0, "HIGH": 20.0, "CRITICAL": 48.0}
            severity = disruption["severity"]
            if delay["predicted_delay_hours"] > delay_caps[severity]:
                delay["predicted_delay_hours"] = delay_caps[severity]
                delay["capped_by_severity"] = True
                delay["interpretation"] = f"Delay adjusted for {severity} climate severity"

            reasoning_trace.append(
                {
                    "step": "delay_prediction",
                    "iteration": it,
                    "predicted_delay_hours": delay["predicted_delay_hours"],
                    "confidence": delay.get("confidence"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "summary": "Predicted ETA impact",
                }
            )

            print(f"  Predicted delay: {delay['predicted_delay_hours']} hours")

            # Agent 3: Route optimization
            print("Running route optimizer...")
            route = self.route_agent.optimize(delivery, disruption, self.audit)
            reasoning_trace.append(
                {
                    "step": "route_optimization",
                    "iteration": it,
                    "distance_km": route.get("original_route", {}).get("distance_km"),
                    "buffer_hours": route.get("recommendation", {}).get("delay_buffer_hours"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "summary": "Selected climate-aware route",
                }
            )
            print(f"  Distance: {route['original_route']['distance_km']} km")

            # Agent 4: Damage detection (multimodal + fallback)
            print("Running damage detector...")
            if image_bytes:
                damage = self.damage_agent.detect_from_bytes(
                    image_bytes, delivery["delivery_id"], self.audit
                )
            elif driver_notes:
                damage = self.damage_agent.detect_from_description(
                    driver_notes, delivery["delivery_id"], self.audit
                )
            else:
                damage = self.damage_agent._no_image_result(delivery["delivery_id"], self.audit)

            reasoning_trace.append(
                {
                    "step": "package_damage_assessment",
                    "iteration": it,
                    "damage_type": damage.get("damage_type"),
                    "confidence": damage.get("confidence"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "summary": "Checked parcel condition from notes/image",
                }
            )
            print(f"  Damage status: {damage['damage_type']}")

            # Refine delay using routing buffer + inspection buffer.
            # This makes the action plan more operationally grounded.
            route_buffer = float(route.get("recommendation", {}).get("delay_buffer_hours", 0.0) or 0.0)
            inspection_buffer = 2.0 if damage.get("flagged", False) else 0.0
            refined_delay = float(delay.get("predicted_delay_hours", 0.0) or 0.0) + route_buffer + inspection_buffer
            # Apply severity cap again so the demo never outputs huge values.
            delay_caps = {"LOW": 3.0, "MEDIUM": 8.0, "HIGH": 20.0, "CRITICAL": 48.0}
            sev = disruption.get("severity")
            if sev in delay_caps:
                refined_delay = min(refined_delay, delay_caps[sev])
            delay["refined_predicted_delay_hours"] = round(refined_delay, 1)
            delay["predicted_delay_hours"] = delay["refined_predicted_delay_hours"]
            delay["interpretation"] = (
                delay.get("interpretation", "") + " (refined with routing/inspection buffer)"
            )

            # Combine everything needed for planning.
            interim_result = {
                "delivery_id": delivery["delivery_id"],
                "origin": delivery.get("origin", ""),
                "destination": delivery.get("destination", ""),
                "disruption": disruption,
                "delay": delay,
                "route": route,
                "damage": damage,
                "overall_risk": disruption["severity"],
            }

            # Action generation
            action_plan = self.action_planner.plan(
                {**interim_result, "delivery_id": delivery["delivery_id"]},
                business_params=business_params,
            )
            agentic_actions.append(action_plan)
            reasoning_trace.append(
                {
                    "step": "action_planning",
                    "iteration": it,
                    "dispatch_decision": action_plan.get("dispatch_decision"),
                    "requires_human_approval": action_plan.get("requires_human_approval"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "summary": "Converted risk to operational steps",
                }
            )

            # Sensitivity analysis if disruption confidence is low.
            # This creates a second-loop justification without re-calling weather APIs.
            disruption_conf = float(disruption.get("confidence", 1.0))
            if it == 0 and disruption_conf < 0.6:
                print("Running sensitivity analysis (low disruption confidence)...")
                sensitivity = self._run_sensitivity(
                    delivery=delivery,
                    route=route,
                    delay_agent=self.delay_agent,
                    traffic_index=delivery.get("traffic_index", 0.5),
                    audit_logger=self.audit,
                )
                # Re-plan with stronger human-validation posture.
                action_plan["sensitivity"] = sensitivity
                action_plan["requires_human_approval"] = True
                reasoning_trace.append(
                    {
                        "step": "sensitivity_analysis",
                        "iteration": it + 1,
                        "timestamp": datetime.utcnow().isoformat(),
                        "summary": "Computed ETA/risk bands across severities",
                    }
                )

            final_action_plan = action_plan

            # LLM-polished rationale (customer-friendly output)
            final_rationale = self.reasoner.generate_rationale(interim_result, action_plan)
            reasoning_trace.append(
                {
                    "step": "llm_rationale",
                    "iteration": it,
                    "timestamp": datetime.utcnow().isoformat(),
                    "summary": "Generated customer-facing rationale",
                }
            )

            # Decision loop stop conditions.
            needs_image = damage.get("action") == "REQUEST_IMAGE" and not image_bytes and not driver_notes
            requires_human_approval = bool(action_plan.get("requires_human_approval"))
            if (
                it == 0
                and not needs_image
                and not requires_human_approval
                and disruption_conf >= 0.6
            ):
                # No further refinement needed for the demo.
                break
            if needs_image:
                # For a hackathon demo, stop here and ask for the missing multimodal input.
                reasoning_trace.append(
                    {
                        "step": "loop_stop_missing_inputs",
                        "iteration": it,
                        "timestamp": datetime.utcnow().isoformat(),
                        "summary": "Stopping until parcel image/notes are provided",
                    }
                )
                break

            if requires_human_approval:
                reasoning_trace.append(
                    {
                        "step": "loop_stop_human_approval",
                        "iteration": it,
                        "timestamp": datetime.utcnow().isoformat(),
                        "summary": "Safety/human-validation required; stopping refinement.",
                    }
                )
                break

        final_result = {
            **interim_result,
            "action_plan": final_action_plan,
            "rationale": final_rationale,
            "reasoning_trace": reasoning_trace,
            "sensitivity": sensitivity,
            "completed_at": datetime.utcnow().isoformat(),
        }

        final_result = self.guardrails.validate_output(final_result)

        self.audit.log(
            {
                "agent": "orchestrator",
                "event": "completed",
                "delivery_id": delivery["delivery_id"],
                "overall_risk": final_result.get("overall_risk"),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        print("All agents done!")
        return final_result

    def _run_sensitivity(self, delivery, route, delay_agent, traffic_index, audit_logger):
        """
        Sensitivity band across severities without re-fetching live weather.
        This keeps the demo fast and still feels agentic.
        """
        severity_to_weather_score = {"LOW": 2.5, "MEDIUM": 6.0, "HIGH": 9.0, "CRITICAL": 12.0}
        severities = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

        bands = []
        delay_caps = {"LOW": 3.0, "MEDIUM": 8.0, "HIGH": 20.0, "CRITICAL": 48.0}
        for sev in severities:
            # Delay prediction uses weather_score proxy (rainfall_mm/10).
            predicted = delay_agent.predict(
                weather_score=severity_to_weather_score[sev],
                traffic_index=traffic_index,
                delivery_id=delivery["delivery_id"],
                audit_logger=audit_logger,
            )
            if float(predicted.get("predicted_delay_hours", 0.0)) > delay_caps[sev]:
                predicted["predicted_delay_hours"] = delay_caps[sev]
                predicted["capped_by_severity"] = True
            # Routing recommendation and route choice use the precomputed OSRM alternatives.
            rec = self.route_agent._climate_adjust(sev)
            alt_selected, scored = self.route_agent.choose_best_route(route.get("alternatives", []), sev)
            bands.append(
                {
                    "severity": sev,
                    "predicted_delay_hours": predicted.get("predicted_delay_hours"),
                    "delay_confidence": predicted.get("confidence"),
                    "route_action": rec.get("action"),
                    "route_delay_buffer_hours": rec.get("delay_buffer_hours"),
                    "selected_route": alt_selected,
                    "route_scoring": scored,
                }
            )
        return {
            "agent": "sensitivity_analysis",
            "timestamp": datetime.utcnow().isoformat(),
            "bands": bands,
        }


if __name__ == "__main__":
    import pandas as pd
    df = pd.read_csv("data/deliveries.csv")
    delivery = df.iloc[0].to_dict()
    
    orch = Orchestrator()
    result = orch.run(delivery, driver_notes="package looks wet")
    
    import json
    print("\nFinal Result:")
    print(json.dumps(result, indent=2))