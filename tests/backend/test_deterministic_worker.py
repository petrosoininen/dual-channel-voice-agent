"""Deterministic three-turn producer and start-time context integration tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from backend.deep_work import (
    DeepWorkControlEnvironment,
    DeepWorkControls,
    DeterministicDeepWorker,
)
from backend.deep_work.base import DeepWorkControlError
from backend.domain.models import ClaimClassification, QueueStatus
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService

ROOT = Path(__file__).resolve().parents[2]
SCRIPTED_TURNS = json.loads(
    (ROOT / "fixtures" / "scripted-turns.json").read_text(encoding="utf-8")
)
SESSION_ID = UUID("10000000-0000-4000-8000-000000000091")


def _submit_command(turn: dict[str, object]) -> dict[str, object]:
    return {
        "type": "turn.submit",
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(SESSION_ID),
        "turnId": turn["turnId"],
        "timestamp": "2026-08-26T09:00:00Z",
        "inputMode": "typed",
        "transcript": turn["transcript"],
    }


def _service() -> tuple[ConversationStore, DeepWorkService]:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=DeterministicDeepWorker(),
        control_environment=DeepWorkControlEnvironment.TEST,
    )
    return store, service


def test_three_rapid_scripted_turns_commit_ordered_versions_from_start_time_bases() -> None:
    async def scenario() -> None:
        store, service = _service()
        submissions = []
        for index, turn in enumerate(SCRIPTED_TURNS):
            submissions.append(
                await service.submit(
                    _submit_command(turn),
                    controls=DeepWorkControls(delay_ms=20 if index == 0 else 0),
                )
            )

        assert [item.queue_position for item in submissions] == [None, 1, 2]
        assert submissions[1].depends_on_turn_id == submissions[0].turn_id
        assert submissions[2].depends_on_turn_id == submissions[1].turn_id

        outcomes = [
            await service.wait_for_turn(SESSION_ID, UUID(turn["turnId"]))
            for turn in SCRIPTED_TURNS
        ]
        assert [item.status for item in outcomes] == [QueueStatus.COMPLETED] * 3
        assert [item.base_document_version for item in outcomes] == [0, 1, 2]
        assert [item.committed_document_version for item in outcomes] == [1, 2, 3]
        assert [item.document.version for item in store.versions(SESSION_ID)] == [
            1,
            2,
            3,
        ]

        document = store.document(SESSION_ID)
        assert document is not None
        assert document.version == 3
        assert (
            document.opportunity_hypothesis.classification
            is ClaimClassification.INFERENCE
        )
        assert document.current_situation is not None
        assert (
            document.current_situation.classification
            is ClaimClassification.SYNTHETIC_EVIDENCE
        )
        assert document.missing_evidence
        assert (
            document.missing_evidence[0].classification
            is ClaimClassification.UNKNOWN
        )
        assert document.recommended_next_actions
        assert (
            document.recommended_next_actions[0].classification
            is ClaimClassification.INFERENCE
        )

        events = store.events(SESSION_ID)
        starts = [
            event
            for event in events
            if event.type == "turn.analysis.started"
        ]
        commits = [
            event
            for event in events
            if event.type == "document.committed"
        ]
        assert [event.base_document_version for event in starts] == [0, 1, 2]
        assert [event.version for event in commits] == [1, 2, 3]
        assert sum(event.type == "document.created" for event in events) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "controls",
    [
        DeepWorkControls(delay_ms=1),
        DeepWorkControls(audio_lane_failure=True),
        DeepWorkControls(producer_failure=True),
        DeepWorkControls(document_failure=True),
        DeepWorkControls(malformed_patch=True),
        DeepWorkControls(late_result=True),
    ],
    ids=[
        "delay",
        "audio-failure",
        "producer-failure",
        "document-failure",
        "malformed-patch",
        "late-result",
    ],
)
def test_deterministic_controls_fail_closed_without_explicit_nonproduction_configuration(
    controls: DeepWorkControls,
) -> None:
    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)
        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=DeterministicDeepWorker(),
        )
        with pytest.raises(DeepWorkControlError):
            await service.submit(
                _submit_command(SCRIPTED_TURNS[0]),
                controls=controls,
            )
        assert store.turns(SESSION_ID) == ()
        assert store.document(SESSION_ID) is None

    asyncio.run(scenario())


def test_deterministic_controls_reject_unvalidated_environment_strings() -> None:
    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)
        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=DeterministicDeepWorker(),
            control_environment=cast(
                DeepWorkControlEnvironment,
                "development",
            ),
        )

        with pytest.raises(DeepWorkControlError):
            await service.submit(
                _submit_command(SCRIPTED_TURNS[0]),
                controls=DeepWorkControls(delay_ms=1),
            )

        assert store.turns(SESSION_ID) == ()
        assert store.document(SESSION_ID) is None

    asyncio.run(scenario())


def test_deterministic_controls_run_in_explicit_development_configuration() -> None:
    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)
        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=DeterministicDeepWorker(),
            control_environment=DeepWorkControlEnvironment.DEVELOPMENT,
        )
        turn = SCRIPTED_TURNS[0]
        submitted = await service.submit(
            _submit_command(turn),
            controls=DeepWorkControls(delay_ms=1),
        )
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert outcome.status is QueueStatus.COMPLETED
        assert outcome.committed_document_version == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "controls",
    [
        DeepWorkControls(producer_failure=True),
        DeepWorkControls(document_failure=True),
        DeepWorkControls(malformed_patch=True),
    ],
    ids=["producer-failure", "document-failure", "malformed-patch"],
)
def test_controlled_document_failures_are_sanitized_and_do_not_commit(
    controls: DeepWorkControls,
) -> None:
    async def scenario() -> None:
        store, service = _service()
        turn = SCRIPTED_TURNS[0]
        await service.submit(_submit_command(turn), controls=controls)
        outcome = await service.wait_for_turn(SESSION_ID, UUID(turn["turnId"]))

        assert outcome.status is QueueStatus.FAILED
        assert outcome.committed_document_version is None
        assert store.document(SESSION_ID).version == 0
        failed = [
            event for event in store.events(SESSION_ID) if event.type == "document.failed"
        ]
        assert len(failed) == 1
        assert failed[0].error.message in {
            "The deterministic producer could not complete.",
            "The document channel could not complete.",
            "The document update was rejected.",
        }
        assert turn["transcript"] not in failed[0].model_dump_json()

    asyncio.run(scenario())
