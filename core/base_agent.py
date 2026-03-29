"""
BaseAgent — abstract class that every agent extends.

Provides:
  • Lifecycle hooks (initialize / process / shutdown)
  • Automatic audit logging per decision
  • Event bus integration (publish / subscribe helpers)
  • Retry-with-backoff on transient failures
"""

from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from core.event_bus import Event, EventBus, EventType
from compliance.audit_logger import AuditLogger


class BaseAgent(ABC):
    """
    All agents in the system must subclass BaseAgent and implement `process`.
    """

    agent_name: str = "base_agent"

    def __init__(
        self,
        event_bus: EventBus | None = None,
        audit_logger: AuditLogger | None = None,
        max_retries: int = 2,
    ) -> None:
        self.event_bus = event_bus or EventBus()
        self.audit = audit_logger or AuditLogger()
        self.max_retries = max_retries
        self._initialized = False

    # ── lifecycle hooks ─────────────────────────────────────────────────────
    def initialize(self) -> None:
        """Called once before the first process(). Override for setup."""
        self._initialized = True

    @abstractmethod
    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Core logic. Receives the shared pipeline state, returns updated data
        that the orchestrator merges back into state.
        """
        ...

    def shutdown(self) -> None:
        """Called once after pipeline completes. Override for cleanup."""
        pass

    # ── safe execution with retry ───────────────────────────────────────────
    def safe_process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run process() with retry and error handling. Used by orchestrator."""
        if not self._initialized:
            self.initialize()

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = self.process(state)
                # Auto-audit the decision
                self.audit.log({
                    "agent": self.agent_name,
                    "delivery_id": state.get("delivery_id", "unknown"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "attempt": attempt,
                    "status": "success",
                })
                return result
            except Exception as exc:
                last_error = exc
                self.audit.log({
                    "agent": self.agent_name,
                    "delivery_id": state.get("delivery_id", "unknown"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "attempt": attempt,
                    "status": "error",
                    "error": str(exc),
                })
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)  # simple backoff

        # All retries exhausted — publish error event and return gracefully
        self._publish_error(state, last_error)
        return {"error": str(last_error), "agent": self.agent_name}

    # ── event helpers ───────────────────────────────────────────────────────
    def publish(self, event_type: str, data: dict, delivery_id: str = "") -> None:
        event = Event(
            event_type=event_type,
            source_agent=self.agent_name,
            data=data,
            delivery_id=delivery_id,
        )
        self.event_bus.publish(event)

    def subscribe(self, event_type: str) -> None:
        """Subscribe this agent's `on_event` method to an event type."""
        self.event_bus.subscribe(event_type, self.on_event)

    def on_event(self, event: Event) -> None:
        """Override to react to subscribed events."""
        pass

    # ── internals ───────────────────────────────────────────────────────────
    def _publish_error(self, state: dict, error: Exception | None) -> None:
        self.publish(
            EventType.AGENT_ERROR,
            {
                "agent": self.agent_name,
                "error": str(error) if error else "unknown",
                "traceback": traceback.format_exc(),
            },
            delivery_id=state.get("delivery_id", ""),
        )
