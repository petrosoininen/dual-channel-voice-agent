"""Deterministic integration, restart, and privacy acceptance tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.deep_work import (
    DeepWorkControlEnvironment,
    DeepWorkControls,
    DeterministicDeepWorker,
)
from backend.main import create_app
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService

ROOT = Path(__file__).resolve().parents[2]
SCRIPTED_TURNS = json.loads(
    (ROOT / "fixtures" / "scripted-turns.json").read_text(encoding="utf-8")
)
SESSION_ID = UUID("10000000-0000-4000-8000-000000000094")


def _command(sequence: int, *, session_id: UUID = SESSION_ID) -> dict[str, object]:
    turn = SCRIPTED_TURNS[sequence - 1]
    return {
        "type": "turn.submit",
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(session_id),
        "turnId": str(uuid4()),
        "timestamp": "2026-08-26T12:00:00Z",
        "inputMode": "typed",
        "transcript": turn["transcript"],
    }


def _service(
    session_id: UUID = SESSION_ID,
) -> tuple[ConversationStore, DeepWorkService]:
    store = ConversationStore()
    store.create_session(session_id)
    return store, DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=DeterministicDeepWorker(),
        control_environment=DeepWorkControlEnvironment.TEST,
    )


def test_rapid_three_turn_scenario_commits_versions_in_fifo_order() -> None:
    async def scenario() -> None:
        store, service = _service()
        submissions = [
            await service.submit(
                _command(sequence),
                controls=(
                    DeepWorkControls(delay_ms=40)
                    if sequence == 1
                    else DeepWorkControls()
                ),
            )
            for sequence in range(1, 4)
        ]

        assert [submission.queue_position for submission in submissions] == [
            None,
            1,
            2,
        ]
        assert [submission.depends_on_turn_id for submission in submissions] == [
            None,
            submissions[0].turn_id,
            submissions[1].turn_id,
        ]

        outcomes = [
            await service.wait_for_turn(SESSION_ID, submission.turn_id)
            for submission in submissions
        ]
        assert [outcome.base_document_version for outcome in outcomes] == [0, 1, 2]
        assert [outcome.committed_document_version for outcome in outcomes] == [
            1,
            2,
            3,
        ]
        document = store.document(SESSION_ID)
        assert document is not None
        assert document.version == 3
        versions = store.versions(SESSION_ID)
        assert [version.document.version for version in versions] == [1, 2, 3]
        assert [version.diff.base_version for version in versions] == [0, 1, 2]
        assert len({version.document.document_id for version in versions}) == 1
        assert [
            version.diff.turn_id for version in versions
        ] == [submission.turn_id for submission in submissions]

        events = store.events(SESSION_ID)
        committed = [event for event in events if event.type == "document.committed"]
        assert [event.version for event in committed] == [1, 2, 3]
        queued = [event for event in events if event.type == "turn.queued"]
        assert [event.position for event in queued] == [1, 2]
        first_types = [
            event.type
            for event in events
            if event.turn_id == submissions[0].turn_id
        ]
        assert first_types.index("document.patch") < first_types.index(
            "document.created"
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("controls", "expected_audio", "expected_document", "expected_version"),
    [
        (DeepWorkControls(audio_lane_failure=True), "failed", "committed", 1),
        (DeepWorkControls(document_failure=True), "not_started", "failed", 0),
        (DeepWorkControls(malformed_patch=True), "not_started", "failed", 0),
    ],
)
def test_independent_failures_are_sanitized_and_atomic(
    controls: DeepWorkControls,
    expected_audio: str,
    expected_document: str,
    expected_version: int,
) -> None:
    async def scenario() -> None:
        session_id = uuid4()
        store, service = _service(session_id)
        submission = await service.submit(
            _command(1, session_id=session_id),
            controls=controls,
        )
        outcome = await service.wait_for_turn(session_id, submission.turn_id)

        assert outcome.audio_status == expected_audio
        assert outcome.document_status == expected_document
        document = store.document(session_id)
        assert document is not None
        assert document.version == expected_version
        serialized_events = "\n".join(
            event.model_dump_json() for event in store.events(session_id)
        )
        assert SCRIPTED_TURNS[0]["transcript"] not in serialized_events
        assert "traceback" not in serialized_events.lower()

    asyncio.run(scenario())


def test_new_process_has_no_prior_session_or_provider_state() -> None:
    first_app = create_app(environ={})
    with TestClient(first_app) as first_client:
        old_session_id = first_client.post("/api/sessions").json()["sessionId"]
        assert first_app.state.conversations.session_count() == 1

    restarted_app = create_app(environ={})
    assert restarted_app.state.conversations.session_count() == 0
    assert restarted_app.state.telemetry.snapshot() == ()
    with TestClient(restarted_app) as restarted_client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with restarted_client.websocket_connect(
                f"/api/app-events/{old_session_id}",
                headers={"origin": "http://testserver"},
            ):
                pass
        assert closed.value.code == 4404
