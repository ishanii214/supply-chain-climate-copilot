"""
Action Execution Agent — turns action plans into executed (simulated) actions.

This is the "muscles" of the system.  The ActionPlanner says *what* to do;
this agent *does* it (or simulates doing it for the hackathon demo).

Capabilities:
  1. Auto-rerouting       ->calls route optimizer with updated constraints
  2. Delivery rescheduling -> computes delivery windows
  3. Risk alerts           -> generates structured SMS/email alert payloads
  4. Inventory pre-positioning -> suggests warehouse stock moves
"""

from __future__ import annotations

import sys
sys.path.append(".")

from datetime import datetime, timedelta
from typing import Any

from core.base_agent import BaseAgent
from core.event_bus import EventType


class ActionExecutionAgent(BaseAgent):
    agent_name = "action_execution_agent"

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        delivery_id = state.get("delivery_id", state.get("delivery", {}).get("delivery_id", "unknown"))
        action_plan = state.get("action_plan", {})
        dispatch_decision = action_plan.get("dispatch_decision", "PROCEED")
        delay_hours = float(state.get("delay", {}).get("predicted_delay_hours", 0))
        severity = state.get("disruption", {}).get("severity", "LOW")
        route = state.get("route", {})
        damage = state.get("damage", {})

        print(f"  [{self.agent_name}] Executing actions for {delivery_id} (decision: {dispatch_decision})...")

        executed_actions: list[dict] = []

        # 1. Auto-rerouting 
        if dispatch_decision in ("REROUTE_AND_BUFFER",):
            reroute_result = self._execute_reroute(delivery_id, route, severity)
            executed_actions.append(reroute_result)

        # 2. Delivery rescheduling
        if dispatch_decision in ("RESCHEDULE_PRIMARY", "HOLD_DISPATCH_STOP"):
            reschedule_result = self._execute_reschedule(delivery_id, delay_hours, severity)
            executed_actions.append(reschedule_result)

        # 3. Risk alerts
        if severity in ("HIGH", "CRITICAL") or dispatch_decision.startswith("HOLD"):
            alert_result = self._send_risk_alerts(delivery_id, severity, delay_hours, dispatch_decision)
            executed_actions.append(alert_result)

        # 4. Inventory pre-positioning
        if severity in ("HIGH", "CRITICAL") and delay_hours > 6:
            inventory_result = self._preposition_inventory(
                delivery_id, state.get("delivery", {}), delay_hours
            )
            executed_actions.append(inventory_result)

        # 5. Damage handling
        if damage.get("flagged", False):
            damage_result = self._handle_damage(delivery_id, damage)
            executed_actions.append(damage_result)

        # Default: proceed normally 
        if not executed_actions:
            executed_actions.append({
                "action_type": "PROCEED_NORMAL",
                "status": "executed",
                "message": "No intervention required. Delivery proceeding on schedule.",
                "timestamp": datetime.utcnow().isoformat(),
            })

        result = {
            "agent": self.agent_name,
            "delivery_id": delivery_id,
            "timestamp": datetime.utcnow().isoformat(),
            "dispatch_decision": dispatch_decision,
            "executed_actions": executed_actions,
            "total_actions_executed": len(executed_actions),
        }

        self.publish(EventType.ACTION_EXECUTED, result, delivery_id=delivery_id)
        print(f"  [{self.agent_name}] Executed {len(executed_actions)} action(s)")
        return result

    # 1. Action implementations (simulated for hackathon) 

    def _execute_reroute(self, delivery_id: str, route: dict, severity: str) -> dict:
        """Simulate auto-rerouting via a safer corridor."""
        recommendation = route.get("recommendation", {})
        alternatives = route.get("alternatives", [])

        # Pick the safest alternative (shortest duration)
        best_alt = min(alternatives, key=lambda a: a.get("duration_hours", 999)) if alternatives else {}

        return {
            "action_type": "AUTO_REROUTE",
            "status": "executed",
            "original_action": recommendation.get("action", ""),
            "new_route": {
                "distance_km": best_alt.get("distance_km", "N/A"),
                "duration_hours": best_alt.get("duration_hours", "N/A"),
                "source": best_alt.get("source", "fallback"),
            },
            "buffer_added_hours": recommendation.get("delay_buffer_hours", 0),
            "message": f"Vehicle rerouted via safer corridor. Buffer of {recommendation.get('delay_buffer_hours', 0)}h added.",
            "notification_sent_to": ["fleet_manager", "driver_app"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _execute_reschedule(self, delivery_id: str, delay_hours: float, severity: str) -> dict:
        """Compute and execute a new delivery window."""
        now = datetime.utcnow()
        postpone_hours = max(delay_hours, 24.0) if severity == "CRITICAL" else delay_hours + 4
        new_window_start = now + timedelta(hours=postpone_hours)
        new_window_end = new_window_start + timedelta(hours=4)

        return {
            "action_type": "DELIVERY_RESCHEDULE",
            "status": "executed",
            "original_delay_hours": delay_hours,
            "postpone_hours": round(postpone_hours, 1),
            "new_delivery_window": {
                "start": new_window_start.isoformat(),
                "end": new_window_end.isoformat(),
            },
            "message": f"Delivery rescheduled by {postpone_hours:.1f}h. New window: {new_window_start.strftime('%d-%b %H:%M')} to {new_window_end.strftime('%d-%b %H:%M')}",
            "notification_sent_to": ["customer", "warehouse", "fleet_manager"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _send_risk_alerts(self, delivery_id: str, severity: str, delay_hours: float, decision: str) -> dict:
        """Generate structured alert payloads (SMS/email format)."""
        sms_message = (
            f"[SUPPLY-INTEL ALERT] Delivery {delivery_id}: {severity} risk detected. "
            f"Delay: ~{delay_hours:.0f}h. Decision: {decision.replace('_', ' ')}. "
            f"Check dashboard for details."
        )

        email_payload = {
            "to": ["ops-team@company.com", "fleet-manager@company.com"],
            "subject": f"🚨 {severity} Risk Alert — {delivery_id}",
            "body": (
                f"Delivery {delivery_id} has been flagged as {severity} risk.\n\n"
                f"• Predicted delay: {delay_hours:.1f} hours\n"
                f"• Dispatch decision: {decision}\n"
                f"• Immediate action required.\n\n"
                f"— Supply Intelligence Agent"
            ),
        }

        return {
            "action_type": "RISK_ALERT",
            "status": "executed",
            "channels": ["sms", "email", "dashboard"],
            "sms_payload": {"message": sms_message, "recipients": ["+91-FLEET-MGR"]},
            "email_payload": email_payload,
            "message": f"{severity} risk alert dispatched via SMS + Email + Dashboard",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _preposition_inventory(self, delivery_id: str, delivery: dict, delay_hours: float) -> dict:
        """Suggest warehouse stock moves based on predicted disruption."""
        origin = delivery.get("origin", "unknown")
        destination = delivery.get("destination", "unknown")

        # Heuristic: if the main corridor is disrupted, pre-position at a
        # nearby hub to serve customers from a closer warehouse.
        hub_suggestions = {
            "Delhi": "Jaipur Regional Hub",
            "Mumbai": "Pune Regional Hub",
            "Chennai": "Bengaluru Regional Hub",
            "Kolkata": "Patna Regional Hub",
        }
        nearest_hub = hub_suggestions.get(destination, f"{destination} Nearby Hub")

        return {
            "action_type": "INVENTORY_PREPOSITION",
            "status": "suggested",
            "disrupted_corridor": f"{origin} → {destination}",
            "predicted_disruption_hours": delay_hours,
            "suggestion": {
                "move_stock_to": nearest_hub,
                "reason": f"Pre-position critical SKUs at {nearest_hub} to serve {destination} "
                          f"customers while {origin}→{destination} corridor is disrupted (~{delay_hours:.0f}h)",
                "priority_skus": "high-demand, perishable, SLA-critical",
                "estimated_cost_inr": round(delay_hours * 500),  # ₹500/hr logistics cost
            },
            "notification_sent_to": ["warehouse_manager", "supply_planning"],
            "message": f"Inventory pre-positioning suggested: move stock to {nearest_hub}",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _handle_damage(self, delivery_id: str, damage: dict) -> dict:
        """Initiate damage inspection workflow."""
        return {
            "action_type": "DAMAGE_INSPECTION",
            "status": "executed",
            "damage_type": damage.get("damage_type", "unknown"),
            "confidence": damage.get("confidence", 0),
            "actions_taken": [
                "Package flagged for physical inspection",
                "Quality team notified",
                "Insurance claim pre-filed",
                "Replacement shipment option prepared",
            ],
            "notification_sent_to": ["quality_team", "customer_service", "insurance"],
            "message": f"Damage detected ({damage.get('damage_type')}). Inspection workflow initiated.",
            "timestamp": datetime.utcnow().isoformat(),
        }
