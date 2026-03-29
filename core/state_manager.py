"""
State Manager — shared pipeline state with memory across runs.

The orchestrator creates a PipelineState for each delivery analysis.
Agents read from and write to the state via the orchestrator.
The StateManager also keeps a memory of past runs for trend analysis.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any


class PipelineState:
    """Mutable state that flows through the orchestrator graph."""

    def __init__(self, delivery: dict[str, Any]) -> None:
        self.delivery_id: str = delivery.get("delivery_id", "unknown")
        self.delivery: dict = delivery
        self.created_at: str = datetime.utcnow().isoformat()

        # Each agent writes its output into one of these slots.
        self.ingestion: dict = {}
        self.disruption: dict = {}
        self.delay: dict = {}
        self.route: dict = {}
        self.damage: dict = {}
        self.action_plan: dict = {}
        self.action_execution: dict = {}
        self.explanation: dict = {}
        self.monitoring: dict = {}
        self.impact: dict = {}

        # Orchestrator metadata
        self.current_step: str = "INIT"
        self.steps_completed: list[str] = []
        self.errors: list[dict] = []
        self.completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the API / dashboard / audit."""
        return {
            "delivery_id": self.delivery_id,
            "delivery": self.delivery,
            "created_at": self.created_at,
            "current_step": self.current_step,
            "steps_completed": self.steps_completed,
            "completed_at": self.completed_at,
            "ingestion": self.ingestion,
            "disruption": self.disruption,
            "delay": self.delay,
            "route": self.route,
            "damage": self.damage,
            "action_plan": self.action_plan,
            "action_execution": self.action_execution,
            "explanation": self.explanation,
            "monitoring": self.monitoring,
            "impact": self.impact,
            "errors": self.errors,
        }

    def mark_step(self, step_name: str) -> None:
        self.current_step = step_name
        self.steps_completed.append(step_name)

    def mark_complete(self) -> None:
        self.current_step = "COMPLETED"
        self.completed_at = datetime.utcnow().isoformat()


class StateManager:
    """
    Manages pipeline state and keeps a memory of past runs.
    Memory enables the monitoring agent to detect trends
    (e.g. "3 consecutive HIGH-severity runs on Delhi→Mumbai").
    """

    def __init__(self, max_memory: int = 50) -> None:
        self.max_memory = max_memory
        self._memory: list[dict] = []          # past run summaries
        self._active: dict[str, PipelineState] = {}  # currently running

    def create_state(self, delivery: dict) -> PipelineState:
        state = PipelineState(delivery)
        self._active[state.delivery_id] = state
        return state

    def get_active(self, delivery_id: str) -> PipelineState | None:
        return self._active.get(delivery_id)

    def complete(self, state: PipelineState) -> None:
        """Archive a finished pipeline run into memory."""
        state.mark_complete()
        summary = {
            "delivery_id": state.delivery_id,
            "completed_at": state.completed_at,
            "severity": state.disruption.get("severity", "UNKNOWN"),
            "delay_hours": state.delay.get("predicted_delay_hours", 0),
            "dispatch_decision": state.action_plan.get("dispatch_decision", "N/A"),
            "steps": state.steps_completed,
        }
        self._memory.append(summary)
        if len(self._memory) > self.max_memory:
            self._memory = self._memory[-self.max_memory:]
        self._active.pop(state.delivery_id, None)

    def get_memory(self, last_n: int = 10) -> list[dict]:
        return self._memory[-last_n:]

    def get_route_history(self, origin: str, destination: str) -> list[dict]:
        """Find past runs on the same route (for trend detection)."""
        return [
            m for m in self._memory
            if m.get("origin") == origin and m.get("destination") == destination
        ]
