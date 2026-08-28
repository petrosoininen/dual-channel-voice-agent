"""Ephemeral store, immutable turn, and event-idempotency tests."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.domain.models import ConversationTurn, utc_now
from backend.main import create_app
from backend.services.conversation_store import ConversationStore
from backend.services.conversation_store import ConversationConflictError

ROOT = Path(__file__).resolve().parents[2]
EVENT = json.loads(
    (ROOT / "contracts" / "fixtures" / "valid-events.json").read_text(
        encoding="utf-8"
    )
)[0]["input"]
SESSION_ID = UUID(EVENT["sessionId"])


def test_new_store_and_new_app_start_empty() -> None:
    assert ConversationStore().session_count() == 0
    assert create_app(environ={}).state.conversations.session_count() == 0
    assert create_app(environ={}).state.conversations.session_count() == 0


def test_event_delivery_is_idempotent() -> None:
    store = ConversationStore()
    store.create_session(SESSION_ID)

    assert store.apply_event(EVENT) is True
    assert store.apply_event(EVENT) is False
    assert len(store.events(SESSION_ID)) == 1

    with pytest.raises(ConversationConflictError):
        store.apply_event({**EVENT, "sequence": 2})


def test_turn_records_are_frozen_and_sequence_is_contiguous() -> None:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    turn = ConversationTurn(
        turn_id=UUID(EVENT["turnId"]),
        sequence=1,
        user_transcript="Synthetic transcript.",
        accepted_at=utc_now(),
        queue_status="accepted",
        voice_status="not_started",
        document_status="not_started",
    )
    store.record_turn(SESSION_ID, turn)

    with pytest.raises(ValidationError):
        turn.sequence = 2
    assert store.turns(SESSION_ID) == (turn,)
