"""Replay ordering and overflow recovery for the app-event hub."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from backend.api.app_events import _send_events
from backend.services.conversation_store import ConversationStore
from backend.services.event_hub import (
    MAX_SUBSCRIBER_EVENTS,
    AppEventHub,
    AppEventSubscription,
)

SESSION_ID = UUID("10000000-0000-4000-8000-000000000108")
TURN_ID = UUID("20000000-0000-4000-8000-000000000108")


def _event(sequence: int) -> dict[str, object]:
    return {
        "type": "voice.started",
        "eventId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(SESSION_ID),
        "turnId": str(TURN_ID),
        "timestamp": f"2026-08-27T09:00:{sequence % 60:02d}Z",
    }


def test_subscribe_atomically_replays_then_queues_live_events() -> None:
    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)
        hub = AppEventHub(store)
        first = _event(1)
        second = _event(2)
        third = _event(3)
        hub.publish(first)
        hub.publish(second)

        async with hub.subscribe(SESSION_ID) as subscription:
            assert [item["eventId"] for item in subscription.replay] == [
                first["eventId"],
                second["eventId"],
            ]
            hub.publish(third)
            assert (await subscription.queue.get())["eventId"] == third["eventId"]

    asyncio.run(scenario())


def test_subscriber_overflow_is_explicit_and_all_events_remain_replayable() -> None:
    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)
        hub = AppEventHub(store)

        async with hub.subscribe(SESSION_ID) as subscription:
            for sequence in range(MAX_SUBSCRIBER_EVENTS + 1):
                hub.publish(_event(sequence))

            assert subscription.overflowed.is_set()
            assert subscription.queue.qsize() == MAX_SUBSCRIBER_EVENTS
            assert len(store.events(SESSION_ID)) == MAX_SUBSCRIBER_EVENTS + 1

    asyncio.run(scenario())


def test_overflow_sender_forces_reconnect_with_replay_close_code() -> None:
    class _WebSocket:
        def __init__(self) -> None:
            self.closed: tuple[int, str] | None = None

        async def send_json(self, value: object) -> None:
            del value

        async def close(self, *, code: int, reason: str) -> None:
            self.closed = (code, reason)

    async def scenario() -> None:
        websocket = _WebSocket()
        subscription = AppEventSubscription(replay=())
        subscription.overflowed.set()

        await _send_events(websocket, subscription)  # type: ignore[arg-type]

        assert websocket.closed == (4409, "Event replay is required.")

    asyncio.run(scenario())
