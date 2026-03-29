"""Tests for the EventBus pub/sub system."""

import sys
sys.path.append(".")

from core.event_bus import EventBus, Event, EventType


def test_publish_subscribe():
    """Events published to a topic reach subscribers."""
    bus = EventBus()
    received = []

    bus.subscribe(EventType.DISRUPTION_DETECTED, lambda e: received.append(e))
    bus.publish(Event(
        event_type=EventType.DISRUPTION_DETECTED,
        source_agent="test",
        data={"severity": "HIGH"},
        delivery_id="DEL-001",
    ))

    assert len(received) == 1
    assert received[0].data["severity"] == "HIGH"
    print("✓ test_publish_subscribe passed")


def test_history():
    """Event history is maintained and queryable."""
    bus = EventBus()
    bus.publish(Event(event_type=EventType.DATA_READY, source_agent="a", data={}, delivery_id="D1"))
    bus.publish(Event(event_type=EventType.DELAY_PREDICTED, source_agent="b", data={}, delivery_id="D2"))
    bus.publish(Event(event_type=EventType.DATA_READY, source_agent="c", data={}, delivery_id="D1"))

    all_hist = bus.get_history()
    assert len(all_hist) == 3

    d1_hist = bus.get_history("D1")
    assert len(d1_hist) == 2
    print("✓ test_history passed")


def test_get_last_event():
    """get_last_event returns the most recent matching event."""
    bus = EventBus()
    bus.publish(Event(event_type=EventType.ALERT, source_agent="a", data={"n": 1}, delivery_id="D1"))
    bus.publish(Event(event_type=EventType.ALERT, source_agent="b", data={"n": 2}, delivery_id="D1"))

    last = bus.get_last_event(EventType.ALERT, "D1")
    assert last is not None
    assert last.data["n"] == 2
    print("✓ test_get_last_event passed")


def test_subscriber_error_does_not_crash():
    """A failing subscriber must not crash the bus or block others."""
    bus = EventBus()
    ok_received = []

    def bad_handler(e):
        raise RuntimeError("boom")

    bus.subscribe(EventType.DATA_READY, bad_handler)
    bus.subscribe(EventType.DATA_READY, lambda e: ok_received.append(e))

    bus.publish(Event(event_type=EventType.DATA_READY, source_agent="x", data={}, delivery_id="D1"))

    assert len(ok_received) == 1  # second subscriber still got the event
    # Error event should be in history
    errors = [e for e in bus._history if e.event_type == EventType.AGENT_ERROR]
    assert len(errors) == 1
    print("✓ test_subscriber_error_does_not_crash passed")


def test_unsubscribe():
    """Unsubscribed handlers stop receiving events."""
    bus = EventBus()
    received = []
    handler = lambda e: received.append(e)

    bus.subscribe(EventType.ALERT, handler)
    bus.publish(Event(event_type=EventType.ALERT, source_agent="a", data={}, delivery_id="D1"))
    assert len(received) == 1

    bus.unsubscribe(EventType.ALERT, handler)
    bus.publish(Event(event_type=EventType.ALERT, source_agent="b", data={}, delivery_id="D2"))
    assert len(received) == 1  # no new events received
    print("✓ test_unsubscribe passed")


if __name__ == "__main__":
    test_publish_subscribe()
    test_history()
    test_get_last_event()
    test_subscriber_error_does_not_crash()
    test_unsubscribe()
    print("\n✅ All event bus tests passed!")
