"""Same-process fan-out for validated app events."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import AsyncIterator
from uuid import UUID

from backend.domain.events import validate_event
from backend.services.conversation_store import ConversationStore

MAX_SUBSCRIBER_EVENTS = 64


@dataclass(eq=False)
class AppEventSubscription:
    """Atomic replay snapshot plus bounded live-event delivery state."""

    replay: tuple[dict[str, object], ...]
    queue: asyncio.Queue[dict[str, object]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_SUBSCRIBER_EVENTS)
    )
    overflowed: asyncio.Event = field(default_factory=asyncio.Event)


class AppEventHub:
    """Record validated events and deliver replay plus ordered live events."""

    def __init__(self, store: ConversationStore) -> None:
        self._store = store
        self._subscribers: dict[UUID, set[AppEventSubscription]] = {}
        self._lock = RLock()

    def publish(self, value: object) -> bool:
        """Persist one validated event and fan it out without silent loss."""

        event = validate_event(value)
        payload = event.model_dump(mode="json", by_alias=True)
        with self._lock:
            recorded = self._store.apply_event(payload)
            if not recorded:
                return False
            for subscription in tuple(
                self._subscribers.get(event.session_id, ())
            ):
                if subscription.overflowed.is_set():
                    continue
                try:
                    subscription.queue.put_nowait(payload)
                except asyncio.QueueFull:
                    subscription.overflowed.set()
            return True

    @asynccontextmanager
    async def subscribe(
        self,
        session_id: UUID,
    ) -> AsyncIterator[AppEventSubscription]:
        """Atomically snapshot recorded events and subscribe to later events."""

        with self._lock:
            replay = tuple(
                event.model_dump(mode="json", by_alias=True)
                for event in self._store.events(session_id)
            )
            subscription = AppEventSubscription(replay=replay)
            subscribers = self._subscribers.setdefault(session_id, set())
            subscribers.add(subscription)
        try:
            yield subscription
        finally:
            with self._lock:
                subscribers.discard(subscription)
                if not subscribers:
                    self._subscribers.pop(session_id, None)
