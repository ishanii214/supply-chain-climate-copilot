"""
Event Bus — pub/sub backbone for inter-agent communication.

Agents publish typed events; other agents subscribe to the event types they
care about.  The bus keeps a full event history so the orchestrator (and the
audit trail / dashboard) can replay what happened.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


# Event types 
class EventType:
    """Named constants for every event in the system."""
    DATA_READY           = "DATA_READY"
    DISRUPTION_DETECTED  = "DISRUPTION_DETECTED"
    DELAY_PREDICTED      = "DELAY_PREDICTED"
    ROUTE_OPTIMIZED      = "ROUTE_OPTIMIZED"
    DAMAGE_ASSESSED      = "DAMAGE_ASSESSED"
    ACTION_PLANNED       = "ACTION_PLANNED"
    ACTION_EXECUTED      = "ACTION_EXECUTED"
    EXPLANATION_READY    = "EXPLANATION_READY"
    ALERT                = "ALERT"
    PIPELINE_STARTED     = "PIPELINE_STARTED"
    PIPELINE_COMPLETED   = "PIPELINE_COMPLETED"
    AGENT_ERROR          = "AGENT_ERROR"


# Event payload 
@dataclass
class Event:
    event_type: str
    source_agent: str
    data: dict[str, Any]
    delivery_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# The bus itself 
class EventBus:
    """In-process pub/sub event bus with full history."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._history: list[Event] = []

    # subscribe / unsubscribe     
    def subscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb is not callback
            ]

    # publish 
    def publish(self, event: Event) -> None:
        """Publish an event: store it, then notify every subscriber."""
        self._history.append(event)
        for callback in self._subscribers.get(event.event_type, []):
            try:
                callback(event)
            except Exception as exc:
                # Never let a subscriber crash the bus.
                error_event = Event(
                    event_type=EventType.AGENT_ERROR,
                    source_agent="event_bus",
                    delivery_id=event.delivery_id,
                    data={
                        "original_event": event.event_type,
                        "error": str(exc),
                    },
                )
                self._history.append(error_event)

    # query helpers 
    def get_history(self, delivery_id: str | None = None) -> list[dict]:
        """Return history as plain dicts (JSON-friendly)."""
        events = self._history
        if delivery_id:
            events = [e for e in events if e.delivery_id == delivery_id]
        return [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "source_agent": e.source_agent,
                "delivery_id": e.delivery_id,
                "timestamp": e.timestamp,
                "data_keys": list(e.data.keys()),
            }
            for e in events
        ]

    def get_last_event(self, event_type: str, delivery_id: str | None = None) -> Event | None:
        for event in reversed(self._history):
            if event.event_type == event_type:
                if delivery_id is None or event.delivery_id == delivery_id:
                    return event
        return None

    def clear(self) -> None:
        self._history.clear()
