"""Bounded FIFO, cancellation, idempotency, and lane-isolation tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest

from backend.deep_work import (
    DeepWorkControlEnvironment,
    DeepWorkControls,
    DeepWorkInput,
    DeepWorkOutput,
    DeterministicDeepWorker,
)
from backend.deep_work.base import CancellationToken, DeepWorkCancelled
from backend.domain.models import (
    DocumentResultStatus,
    QueueStatus,
    VoiceStatus,
)
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import (
    DeepWorkConflictError,
    DeepWorkService,
)
from backend.services.patch_service import PatchService

ROOT = Path(__file__).resolve().parents[2]
SCRIPTED_TURN = json.loads(
    (ROOT / "fixtures" / "scripted-turns.json").read_text(encoding="utf-8")
)[0]
SESSION_ID = UUID("10000000-0000-4000-8000-000000000092")


@dataclass
class _GateWorker:
    release: asyncio.Event
    started: asyncio.Event = field(default_factory=asyncio.Event)
    inputs: list[DeepWorkInput] = field(default_factory=list)

    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        self.inputs.append(work_input)
        self.started.set()
        release_wait = asyncio.create_task(self.release.wait())
        cancellation_wait = asyncio.create_task(cancellation.wait())
        done, pending = await asyncio.wait(
            {release_wait, cancellation_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if cancellation_wait in done:
            raise DeepWorkCancelled("Deep work was cancelled.")
        return _proposal(work_input)


@dataclass
class _NonCooperativeGateWorker:
    release: asyncio.Event
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        del cancellation
        self.started.set()
        await self.release.wait()
        return _proposal(work_input)


class _ExplodingWorker:
    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        del cancellation
        raise RuntimeError(work_input.transcript)


class _WrongTurnWorker:
    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        del cancellation
        output = _proposal(work_input)
        proposal = dict(output.proposal)
        proposal["turnId"] = str(uuid4())
        return DeepWorkOutput(proposal=proposal)


def _proposal(work_input: DeepWorkInput) -> DeepWorkOutput:
    payload = {
        "patchId": str(uuid5(work_input.turn_id, "test-patch")),
        "sessionId": str(work_input.session_id),
        "turnId": str(work_input.turn_id),
        "documentId": str(work_input.document.document_id),
        "baseVersion": work_input.document.version,
        "summary": "Apply one synthetic queue test update.",
        "operations": [
            {
                "operationId": str(uuid5(work_input.turn_id, "test-operation")),
                "op": "replace_section",
                "section": "opportunityHypothesis",
                "value": {
                    "text": f"Synthetic queued hypothesis {work_input.sequence}.",
                    "classification": "inference",
                },
            }
        ],
    }
    return DeepWorkOutput(proposal=payload)


def _command(
    *,
    turn_id: UUID | None = None,
    idempotency_key: UUID | None = None,
    transcript: str = "Review the synthetic queue context.",
    input_mode: str = "typed",
) -> dict[str, object]:
    return {
        "type": "turn.submit",
        "commandId": str(uuid4()),
        "idempotencyKey": str(idempotency_key or uuid4()),
        "sessionId": str(SESSION_ID),
        "turnId": str(turn_id or uuid4()),
        "timestamp": "2026-08-26T09:00:00Z",
        "inputMode": input_mode,
        "transcript": transcript,
    }


def _cancel(turn_id: UUID, *, idempotency_key: UUID | None = None) -> dict[str, object]:
    return {
        "type": "turn.cancel",
        "commandId": str(uuid4()),
        "idempotencyKey": str(idempotency_key or uuid4()),
        "sessionId": str(SESSION_ID),
        "turnId": str(turn_id),
        "timestamp": "2026-08-26T09:00:01Z",
        "reason": "Stop this synthetic deep task.",
    }


def _interrupt(turn_id: UUID) -> dict[str, object]:
    return {
        "type": "voice.interrupt",
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(SESSION_ID),
        "turnId": str(turn_id),
        "timestamp": "2026-08-26T09:00:01Z",
        "reason": "barge_in",
    }


def _voice_command(
    command_type: str,
    turn_id: UUID,
    **payload: object,
) -> dict[str, object]:
    return {
        "type": command_type,
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(SESSION_ID),
        "turnId": str(turn_id),
        "timestamp": "2026-08-26T09:00:02Z",
        **payload,
    }


def _service(
    worker: object,
    *,
    event_sink: object | None = None,
) -> tuple[ConversationStore, DeepWorkService]:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=worker,
        control_environment=DeepWorkControlEnvironment.TEST,
        event_sink=event_sink,
    )
    return store, service


async def _wait_until_running(service: DeepWorkService, turn_id: UUID) -> None:
    while True:
        snapshot = await service.snapshot(SESSION_ID, turn_id)
        if snapshot.status in {QueueStatus.RUNNING, QueueStatus.CANCELLING}:
            return
        await asyncio.sleep(0)


def test_capacity_is_one_running_plus_three_pending_then_rejects_without_task() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _GateWorker(release)
        store, service = _service(worker)
        commands = [_command() for _ in range(5)]
        results = [await service.submit(command) for command in commands]

        assert [result.queue_position for result in results[:4]] == [
            None,
            1,
            2,
            3,
        ]
        assert [
            results[index].depends_on_turn_id for index in range(1, 4)
        ] == [results[index].turn_id for index in range(3)]
        assert results[4].accepted is False
        assert results[4].task_created is False
        assert results[4].input_available is True
        assert results[4].error.code == "queue_full"
        assert len(store.turns(SESSION_ID)) == 4
        with pytest.raises(LookupError):
            await service.snapshot(SESSION_ID, results[4].turn_id)

        release.set()
        outcomes = [
            await service.wait_for_turn(SESSION_ID, result.turn_id)
            for result in results[:4]
        ]
        assert [outcome.committed_document_version for outcome in outcomes] == [
            1,
            2,
            3,
            4,
        ]
        rejected = [
            event for event in store.events(SESSION_ID) if event.type == "turn.rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0].queue_depth == 4

    asyncio.run(scenario())


def test_queued_cancellation_is_immediate_and_never_commits() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _GateWorker(release)
        store, service = _service(worker)
        first = await service.submit(_command())
        second = await service.submit(_command())
        cancellation = await service.cancel(_cancel(second.turn_id))

        assert cancellation.final is True
        assert cancellation.status is QueueStatus.CANCELLED
        cancelled = await service.wait_for_turn(SESSION_ID, second.turn_id)
        assert cancelled.document_status is DocumentResultStatus.CANCELLED
        release.set()
        await service.wait_for_turn(SESSION_ID, first.turn_id)
        assert store.document(SESSION_ID).version == 1
        assert second.turn_id not in {
            version.diff.turn_id for version in store.versions(SESSION_ID)
        }
        phases = [
            event.phase
            for event in store.events(SESSION_ID)
            if event.type == "turn.analysis.cancelled"
        ]
        assert phases == ["queued"]

    asyncio.run(scenario())


def test_running_cancellation_signals_worker_and_never_commits() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _GateWorker(release)
        store, service = _service(worker)
        submitted = await service.submit(_command())
        await worker.started.wait()

        cancellation = await service.cancel(_cancel(submitted.turn_id))
        assert cancellation.status is QueueStatus.CANCELLING
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert outcome.status is QueueStatus.CANCELLED
        assert store.document(SESSION_ID).version == 0
        event_types = [event.type for event in store.events(SESSION_ID)]
        assert event_types.index("turn.analysis.cancelling") < event_types.index(
            "turn.analysis.cancelled"
        )
        assert "document.committed" not in event_types

    asyncio.run(scenario())


def test_late_result_after_running_cancellation_is_suppressed() -> None:
    async def scenario() -> None:
        store, service = _service(DeterministicDeepWorker())
        command = {
            **_command(
                turn_id=UUID(SCRIPTED_TURN["turnId"]),
                transcript=SCRIPTED_TURN["transcript"],
            )
        }
        submitted = await service.submit(
            command,
            controls=DeepWorkControls(delay_ms=20, late_result=True),
        )
        await _wait_until_running(service, submitted.turn_id)
        await service.cancel(_cancel(submitted.turn_id))
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert outcome.status is QueueStatus.CANCELLED
        assert store.document(SESSION_ID).version == 0
        assert not any(
            event.type == "document.committed"
            for event in store.events(SESSION_ID)
        )

    asyncio.run(scenario())


def test_noncooperative_result_is_suppressed_before_commit_after_cancellation() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _NonCooperativeGateWorker(release)
        store, service = _service(worker)
        submitted = await service.submit(_command())
        await worker.started.wait()

        cancellation = await service.cancel(_cancel(submitted.turn_id))
        assert cancellation.status is QueueStatus.CANCELLING
        release.set()
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert outcome.status is QueueStatus.CANCELLED
        assert outcome.document_status is DocumentResultStatus.CANCELLED
        assert store.document(SESSION_ID).version == 0
        event_types = [event.type for event in store.events(SESSION_ID)]
        assert event_types.count("turn.analysis.cancelling") == 1
        assert event_types.count("turn.analysis.cancelled") == 1
        assert "document.patch" not in event_types
        assert "document.committed" not in event_types

    asyncio.run(scenario())


def test_voice_interruption_does_not_cancel_delayed_deep_work() -> None:
    async def scenario() -> None:
        store, service = _service(DeterministicDeepWorker())
        command = _command(
            turn_id=UUID(SCRIPTED_TURN["turnId"]),
            transcript=SCRIPTED_TURN["transcript"],
            input_mode="voice",
        )
        submitted = await service.submit(
            command,
            controls=DeepWorkControls(delay_ms=10),
        )
        await _wait_until_running(service, submitted.turn_id)
        assert await service.interrupt_voice(_interrupt(submitted.turn_id)) is True
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert outcome.status is QueueStatus.COMPLETED
        assert outcome.audio_status is VoiceStatus.INTERRUPTED
        assert outcome.document_status is DocumentResultStatus.COMMITTED
        assert store.document(SESSION_ID).version == 1
        assert not any(
            event.type.startswith("turn.analysis.cancel")
            for event in store.events(SESSION_ID)
        )

    asyncio.run(scenario())


def test_audio_failure_and_event_delivery_failure_do_not_corrupt_document_lane() -> None:
    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)

        def flaky_sink(event: object) -> bool:
            if isinstance(event, dict) and event.get("type") == "turn.analysis.started":
                raise RuntimeError("Synthetic delivery failure detail must be discarded.")
            return store.apply_event(event)

        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=DeterministicDeepWorker(),
            control_environment=DeepWorkControlEnvironment.TEST,
            event_sink=flaky_sink,
        )
        command = _command(
            turn_id=UUID(SCRIPTED_TURN["turnId"]),
            transcript=SCRIPTED_TURN["transcript"],
        )
        submitted = await service.submit(
            command,
            controls=DeepWorkControls(audio_lane_failure=True),
        )
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert outcome.audio_status is VoiceStatus.FAILED
        assert outcome.document_status is DocumentResultStatus.COMMITTED
        assert store.document(SESSION_ID).version == 1
        failures = service.delivery_failures()
        assert len(failures) == 1
        assert failures[0].event_type == "turn.analysis.started"
        diagnostics = repr(failures)
        assert SCRIPTED_TURN["transcript"] not in diagnostics
        assert "delivery failure detail" not in diagnostics
        serialized_events = "\n".join(
            event.model_dump_json() for event in store.events(SESSION_ID)
        )
        assert SCRIPTED_TURN["transcript"] not in serialized_events

    asyncio.run(scenario())


def test_unexpected_worker_error_is_content_free_and_does_not_block_input() -> None:
    async def scenario() -> None:
        store, service = _service(_ExplodingWorker())
        command = _command(transcript="Synthetic private failure marker.")
        submitted = await service.submit(command)
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert submitted.input_available is True
        assert outcome.status is QueueStatus.FAILED
        assert outcome.document_status is DocumentResultStatus.FAILED
        assert store.document(SESSION_ID).version == 0
        serialized = "\n".join(
            event.model_dump_json() for event in store.events(SESSION_ID)
        )
        assert "Synthetic private failure marker." not in serialized
        assert "The document lane could not complete." in serialized

    asyncio.run(scenario())


def test_worker_cannot_commit_a_patch_for_a_different_turn() -> None:
    async def scenario() -> None:
        store, service = _service(_WrongTurnWorker())
        submitted = await service.submit(_command())
        outcome = await service.wait_for_turn(SESSION_ID, submitted.turn_id)

        assert outcome.status is QueueStatus.FAILED
        assert outcome.document_status is DocumentResultStatus.FAILED
        assert store.document(SESSION_ID).version == 0
        assert store.versions(SESSION_ID) == ()
        event_types = [event.type for event in store.events(SESSION_ID)]
        assert event_types.count("document.failed") == 1
        assert "document.patch" not in event_types
        assert "document.committed" not in event_types

    asyncio.run(scenario())


def test_submit_and_cancel_idempotency_create_no_duplicate_work_or_events() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _GateWorker(release)
        store, service = _service(worker)
        command = _command()
        first = await service.submit(command)
        duplicate = await service.submit(command)
        assert duplicate == first

        altered = {**command, "transcript": "Different synthetic request."}
        with pytest.raises(DeepWorkConflictError):
            await service.submit(altered)

        cancel_command = _cancel(first.turn_id)
        cancellation = await service.cancel(cancel_command)
        duplicate_cancellation = await service.cancel(cancel_command)
        assert duplicate_cancellation == cancellation
        outcome = await service.wait_for_turn(SESSION_ID, first.turn_id)
        assert outcome.status is QueueStatus.CANCELLED

        event_ids = [event.event_id for event in store.events(SESSION_ID)]
        assert len(event_ids) == len(set(event_ids))
        assert store.versions(SESSION_ID) == ()

    asyncio.run(scenario())


def test_voice_lifecycle_updates_canonical_turn_after_deep_completion() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _GateWorker(release)
        store, service = _service(worker)
        submission = await service.submit(_command(input_mode="voice"))
        await worker.started.wait()

        assert await service.start_voice(
            _voice_command("voice.start", submission.turn_id)
        )
        assert await service.acknowledge_voice(
            _voice_command(
                "voice.acknowledge",
                submission.turn_id,
                intentSummary="I understand the requested review.",
                nextStep="Next, I will assess the synthetic context.",
            )
        )
        release.set()
        deep_outcome = await service.wait_for_turn(
            SESSION_ID,
            submission.turn_id,
        )
        assert deep_outcome.audio_status is VoiceStatus.SPEAKING

        assert await service.complete_voice(
            _voice_command("voice.complete", submission.turn_id)
        )
        canonical_turn = store.turns(SESSION_ID)[0]
        assert canonical_turn.queue_status is QueueStatus.COMPLETED
        assert canonical_turn.document_status is DocumentResultStatus.COMMITTED
        assert canonical_turn.document_version == 1
        assert canonical_turn.voice_status is VoiceStatus.COMPLETED
        assert [event.type for event in store.events(SESSION_ID)][-1] == (
            "voice.completed"
        )

    asyncio.run(scenario())


def test_second_request_receives_completed_prior_turn_and_version() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _GateWorker(release)
        _, service = _service(worker)
        first = await service.submit(_command())
        second = await service.submit(_command())
        await worker.started.wait()
        release.set()

        await service.wait_for_turn(SESSION_ID, first.turn_id)
        await service.wait_for_turn(SESSION_ID, second.turn_id)

        prior = worker.inputs[1].prior_turns[0]
        assert prior.turn_id == first.turn_id
        assert prior.queue_status is QueueStatus.COMPLETED
        assert prior.document_status is DocumentResultStatus.COMMITTED
        assert prior.document_version == 1

    asyncio.run(scenario())


def test_shutdown_cancels_and_awaits_running_and_queued_tasks() -> None:
    async def scenario() -> None:
        release = asyncio.Event()
        worker = _NonCooperativeGateWorker(release)
        _, service = _service(worker)
        first = await service.submit(_command())
        second = await service.submit(_command())
        await worker.started.wait()

        await service.shutdown()

        first_outcome = await service.wait_for_turn(SESSION_ID, first.turn_id)
        second_outcome = await service.wait_for_turn(SESSION_ID, second.turn_id)
        assert first_outcome.status is QueueStatus.CANCELLED
        assert second_outcome.status is QueueStatus.CANCELLED
        assert not any(
            task.get_name().startswith("deep-work-")
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        )
        with pytest.raises(DeepWorkConflictError):
            await service.submit(_command())

    asyncio.run(scenario())
