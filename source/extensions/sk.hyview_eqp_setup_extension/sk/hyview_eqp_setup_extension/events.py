from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List

APP_TAB_CREATED = "app.tab.created"
APP_TAB_CHANGED = "app.tab.changed"
APP_TAB_REMOVED = "app.tab.removed"

EventPayload = Dict[str, Any]
EventCallback = Callable[[EventPayload], None]
Unsubscribe = Callable[[], None]


class EventBus:
    """Minimal in-process pub/sub bus for tab lifecycle events."""

    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, List[EventCallback]] = defaultdict(list)

    def subscribe(self, event_name: str, callback: EventCallback) -> Unsubscribe:
        self._subscribers[event_name].append(callback)

        def _unsubscribe() -> None:
            callbacks = self._subscribers.get(event_name, [])
            if callback in callbacks:
                callbacks.remove(callback)

        return _unsubscribe

    def publish(self, event_name: str, payload: EventPayload | None = None) -> None:
        event_payload: EventPayload = payload or {}
        for callback in list(self._subscribers.get(event_name, [])):
            callback(event_payload)

    def clear(self) -> None:
        self._subscribers.clear()


_default_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """Return shared extension-level event bus."""

    return _default_event_bus
