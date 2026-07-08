"""
Monitoring Agent — watches for SLA breaches, risk escalation, and anomalies.

Responsibilities:
  -Post-pipeline health check on every run
  -Detects trends from pipeline memory (consecutive HIGH runs)
  -Generates ALERT events when thresholds are breached
  -Provides system health summary for the dashboard
"""

from __future__ import annotations

import sys
sys.path.append(".")

from datetime import datetime
from typing import Any

from core.base_agent import BaseAgent
from core.event_bus import EventType


class MonitoringAgent(BaseAgent):
    agent_name = "monitoring_agent"

    # Configurable thresholds
    CONSECUTIVE_HIGH_THRESHOLD = 3       # alert after N consecutive HIGH+ runs
    DELAY_ALERT_HOURS = 12.0             # alert if delay > this
    SLA_COMPLIANCE_FLOOR_PCT = 80.0      # alert if SLA drops below this

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        delivery_id = state.get("delivery_id", "unknown")
        print(f"  [{self.agent_name}] Running health checks for {delivery_id}...")

        alerts: list[dict] = []
        health_checks: list[dict] = []

        # 1. Delay threshold check
        delay_hours = float(state.get("delay", {}).get("predicted_delay_hours", 0))
        if delay_hours > self.DELAY_ALERT_HOURS:
            alert = {
                "type": "DELAY_THRESHOLD_BREACH",
                "severity": "HIGH",
                "message": f"Predicted delay ({delay_hours:.1f}h) exceeds threshold ({self.DELAY_ALERT_HOURS}h)",
                "delivery_id": delivery_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
            alerts.append(alert)
        health_checks.append({
            "check": "delay_threshold",
            "passed": delay_hours <= self.DELAY_ALERT_HOURS,
            "value": delay_hours,
            "threshold": self.DELAY_ALERT_HOURS,
        })

        # 2. Severity escalation check
        severity = state.get("disruption", {}).get("severity", "LOW")
        if severity == "CRITICAL":
            alerts.append({
                "type": "CRITICAL_SEVERITY",
                "severity": "CRITICAL",
                "message": "CRITICAL severity detected — all dispatch should be halted",
                "delivery_id": delivery_id,
                "timestamp": datetime.utcnow().isoformat(),
            })
        health_checks.append({
            "check": "severity_level",
            "passed": severity not in ("CRITICAL",),
            "value": severity,
        })

        # 3. Damage flag check
        damage_flagged = state.get("damage", {}).get("flagged", False)
        if damage_flagged:
            alerts.append({
                "type": "DAMAGE_FLAGGED",
                "severity": "MEDIUM",
                "message": f"Package damage detected: {state.get('damage', {}).get('damage_type', 'unknown')}",
                "delivery_id": delivery_id,
                "timestamp": datetime.utcnow().isoformat(),
            })
        health_checks.append({
            "check": "damage_flag",
            "passed": not damage_flagged,
            "value": damage_flagged,
        })

        # 4. Pipeline error check
        errors = state.get("errors", [])
        if errors:
            alerts.append({
                "type": "PIPELINE_ERRORS",
                "severity": "HIGH",
                "message": f"{len(errors)} error(s) occurred during pipeline execution",
                "delivery_id": delivery_id,
                "timestamp": datetime.utcnow().isoformat(),
            })
        health_checks.append({
            "check": "pipeline_errors",
            "passed": len(errors) == 0,
            "value": len(errors),
        })

        # 5. Trend analysis from memory
        memory = state.get("_memory", [])
        if len(memory) >= self.CONSECUTIVE_HIGH_THRESHOLD:
            recent = memory[-self.CONSECUTIVE_HIGH_THRESHOLD:]
            if all(m.get("severity") in ("HIGH", "CRITICAL") for m in recent):
                alerts.append({
                    "type": "CONSECUTIVE_HIGH_SEVERITY",
                    "severity": "HIGH",
                    "message": (
                        f"Last {self.CONSECUTIVE_HIGH_THRESHOLD} runs were HIGH/CRITICAL — "
                        "systemic disruption likely; consider fleet-wide hold"
                    ),
                    "delivery_id": delivery_id,
                    "timestamp": datetime.utcnow().isoformat(),
                })

        # Publish alerts 
        for alert in alerts:
            self.publish(EventType.ALERT, alert, delivery_id=delivery_id)

        system_health = "HEALTHY" if not alerts else (
            "CRITICAL" if any(a["severity"] == "CRITICAL" for a in alerts) else "DEGRADED"
        )

        result = {
            "agent": self.agent_name,
            "delivery_id": delivery_id,
            "timestamp": datetime.utcnow().isoformat(),
            "system_health": system_health,
            "alerts": alerts,
            "health_checks": health_checks,
            "alert_count": len(alerts),
        }

        print(f"  [{self.agent_name}] Health: {system_health} | Alerts: {len(alerts)}")
        return result
