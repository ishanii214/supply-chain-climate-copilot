import math
from datetime import datetime


class ActionPlanner:
    """
    Turns prediction outputs into concrete logistics actions.
    This is intentionally heuristic-first for hackathon reliability,
    with optional LLM polishing done elsewhere.
    """

    def plan(self, result: dict, business_params: dict | None = None) -> dict:
        business_params = business_params or {}
        cost_per_delay_hour = float(business_params.get("cost_per_delay_hour", 1500))

        disruption = result["disruption"]
        delay = result["delay"]
        route = result["route"]
        damage = result["damage"]

        severity = disruption["severity"]
        disruption_conf = float(disruption.get("confidence", 1.0))
        predicted_delay = delay.get("refined_predicted_delay_hours", delay.get("predicted_delay_hours", 0.0))
        predicted_delay = float(predicted_delay)
        delay_interpretation = delay.get("interpretation", "")

        # Damage triggers separate handling regardless of climate severity.
        damage_flagged = bool(damage.get("flagged", False))
        damage_conf = float(damage.get("confidence", 0.0))

        # Human review conditions.
        low_climate_conf = disruption_conf < 0.6
        no_image_requested = damage.get("action") == "REQUEST_IMAGE"
        requires_human_approval = (
            severity == "CRITICAL"
            or damage_flagged
            or low_climate_conf
            or no_image_requested
        )

        # Dispatch-level decision.
        if no_image_requested:
            dispatch_decision = "HOLD_PENDING_IMAGE"
        elif severity == "CRITICAL":
            dispatch_decision = "HOLD_DISPATCH_STOP"
        elif damage_flagged and damage_conf >= 0.7:
            dispatch_decision = "HOLD_DISPATCH_INSPECTION"
        elif predicted_delay >= 18:
            dispatch_decision = "RESCHEDULE_PRIMARY"
        elif severity == "HIGH":
            dispatch_decision = "REROUTE_AND_BUFFER"
        elif severity == "MEDIUM":
            dispatch_decision = "MONITOR_AND_CHECKPOINT"
        else:
            dispatch_decision = "PROCEED"

        # Build concrete next actions.
        actions = []
        if dispatch_decision.startswith("HOLD"):
            actions.append("Stop dispatch/vehicle movement until verification is complete.")
        if dispatch_decision.startswith("RESCHEDULE"):
            actions.append("Reschedule pickup/drop window and notify customer with new ETA range.")
        if dispatch_decision.startswith("REROUTE"):
            actions.append("Implement rerouted plan immediately (use route recommendation).")
        if dispatch_decision.startswith("MONITOR"):
            actions.append("Proceed, but set a checkpoint check-in (weather update + driver confirmation).")
        if dispatch_decision == "PROCEED":
            actions.append("Proceed with planned route; re-check risk at the next milestone.")

        if damage_flagged:
            actions.append("Flag package for inspection; prioritize moisture/crush risk items.")
        if low_climate_conf:
            actions.append("Request human validation due to low confidence in disruption assessment.")
        if no_image_requested:
            actions.append("Request a parcel image (front + label + corner close-up).")

        # Route-level hazard can upgrade the decision even if origin climate looks benign.
        route_hazard_profile = route.get("route_hazard_profile") or []
        route_hazard_triggered = False
        if isinstance(route_hazard_profile, list) and route_hazard_profile:
            try:
                max_hazard_score = max(float(p.get("hazard_score", 0.0) or 0.0) for p in route_hazard_profile)
                if max_hazard_score >= 0.78 and dispatch_decision in ["PROCEED", "MONITOR_AND_CHECKPOINT"]:
                    dispatch_decision = "REROUTE_AND_BUFFER"
                    requires_human_approval = True
                    route_hazard_triggered = True
                    actions.insert(0, "Route-level hazard detected: reroute via safer corridor and add extra safety buffer.")
            except Exception:
                max_hazard_score = None

        # Operationally specific messages.
        timeline = self._build_timeline(
            severity=severity,
            dispatch_decision=dispatch_decision,
            predicted_delay_hours=predicted_delay,
            damage_flagged=damage_flagged,
            no_image_requested=no_image_requested,
        )

        customer_message = self._customer_message(
            severity=severity,
            predicted_delay_hours=predicted_delay,
            damage_type=damage.get("damage_type", "unclassifiable"),
            route_action=route.get("recommendation", {}).get("action", ""),
        )

        # Simple business impact estimate.
        # This is a rough hackathon metric to show "why it matters".
        delay_hours = max(0.0, predicted_delay)
        estimated_delay_cost = delay_hours * cost_per_delay_hour

        return {
            "agent": "action_planner",
            "delivery_id": result["delivery_id"],
            "timestamp": datetime.utcnow().isoformat(),
            "dispatch_decision": dispatch_decision,
            "predicted_delay_hours": predicted_delay,
            "delay_interpretation": delay_interpretation,
            "requires_human_approval": requires_human_approval,
            "action_steps": actions,
            "timeline_checklist": timeline,
            "customer_message": customer_message,
            "estimated_delay_cost_inr": int(round(estimated_delay_cost)),
            "routing_recommendation": route.get("recommendation"),
            "reason_flags": {
                "severity_critical": severity == "CRITICAL",
                "damage_flagged": damage_flagged,
                "low_disruption_confidence": low_climate_conf,
                "missing_image": no_image_requested,
                "route_hazard_triggered": route_hazard_triggered,
            },
        }

    def _customer_message(self, severity: str, predicted_delay_hours: float, damage_type: str, route_action: str) -> str:
        # Keep it short and non-technical.
        delay_part = "may be delayed" if predicted_delay_hours >= 2 else "is on track"
        severity_part = {
            "CRITICAL": "due to safety checks and severe weather risk",
            "HIGH": "due to heavy weather/road risk",
            "MEDIUM": "due to changing road and weather conditions",
            "LOW": "with normal operating conditions",
        }.get(severity, "with normal operating conditions")

        damage_part = ""
        if damage_type and damage_type not in ["no_visible_damage", "no_damage", "no_image_provided"]:
            damage_part = f". We also noted: {damage_type.replace('_', ' ')}."

        # route_action is often long; use only a hint
        reroute_hint = ""
        if "REROUTE" in (route_action or ""):
            reroute_hint = " We'll take an alternate route to improve safety."

        return f"Your shipment {delay_part} by about {predicted_delay_hours:.1f} hours {severity_part}{reroute_hint}{damage_part}".strip()

    def _build_timeline(
        self,
        severity: str,
        dispatch_decision: str,
        predicted_delay_hours: float,
        damage_flagged: bool,
        no_image_requested: bool,
    ) -> list[dict]:
        """
        Produces a hackathon-friendly operational checklist.
        Times are relative (e.g., "T+0h", "T+2h") so it stays usable in demos.
        """
        base = [
            {"t": "T+0h", "item": "Assign a case owner and open a disruption ticket."},
        ]

        if no_image_requested:
            base.append({"t": "T+0h", "item": "Request parcel image (front + label + corner close-up)."})

        if damage_flagged:
            base.append({"t": "T+0h", "item": "Hold package for inspection; verify moisture/crush risk."})

        if severity == "CRITICAL" or dispatch_decision.startswith("HOLD_DISPATCH_STOP"):
            base += [
                {"t": "T+0h", "item": "Stop dispatch on this route until safety verification is complete."},
                {"t": "T+2h", "item": "Contact customer with safety-first status update."},
                {"t": "T+24h", "item": "Reassess and either re-route via rail/alternate corridors or resume dispatch."},
            ]
        elif dispatch_decision.startswith("REROUTE"):
            base += [
                {"t": "T+0h", "item": "Trigger reroute request using the route recommendation."},
                {"t": "T+2h", "item": "Update ETA range and notify customer."},
                {"t": "T+6h", "item": "Checkpoint: confirm roads remain passable and adjust plan if conditions worsen."},
            ]
        elif dispatch_decision.startswith("RESCHEDULE"):
            base += [
                {"t": "T+0h", "item": "Reschedule pickup/drop window and reserve an alternate slot."},
                {"t": "T+2h", "item": "Share revised ETA range with customer."},
                {"t": "T+24h", "item": "Recovery checkpoint: verify disruption clears before next dispatch batch."},
            ]
        elif dispatch_decision.startswith("MONITOR"):
            base += [
                {"t": "T+0h", "item": "Proceed with caution; keep driver on the current route only if safe."},
                {"t": "T+2h", "item": "Checkpoint: re-check weather signals and confirm vehicle access."},
                {"t": "T+4h", "item": "Update customer if delay trajectory changes."},
            ]
        else:
            # PROCEED
            base += [
                {"t": "T+0h", "item": "Proceed normally and keep standard tracking active."},
                {"t": "T+3h", "item": "Quick verification: confirm no new hazards on the route corridor."},
                {"t": "T+{:.0f}h".format(max(3.0, predicted_delay_hours)), "item": "If delay grows, switch to MONITOR actions and notify customer."},
            ]

        return base

