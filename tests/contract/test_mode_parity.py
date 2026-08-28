"""Shared app-level behavior is mode-independent."""

from __future__ import annotations

import asyncio
import json
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import AgentProvider, Settings, VoiceProvider
from backend.deep_work.base import DeepWorkControlEnvironment, DeepWorkControls
from backend.deep_work.deterministic import DeterministicDeepWorker
from backend.deep_work.foundry import (
    FoundryCompatibility,
    FoundryDeepWorker,
    FoundryInvocation,
)
from backend.main import create_app
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService

ROOT = Path(__file__).resolve().parents[2]
SCRIPTED_TURNS = json.loads(
    (ROOT / "fixtures" / "scripted-turns.json").read_text(encoding="utf-8")
)


@dataclass
class _Session:
    service_session_id: str = "opaque-conversation"


class _FoundryProvider:
    def __init__(self) -> None:
        self.session = _Session()
        self.create_count = 0

    async def validate_compatibility(self) -> FoundryCompatibility:
        return FoundryCompatibility(True, True, True)

    async def create_conversation(self, *, tools: object) -> _Session:
        del tools
        self.create_count += 1
        return self.session

    async def invoke(
        self,
        request: str,
        *,
        session: _Session,
        tools: object,
    ) -> FoundryInvocation:
        assert session is self.session
        payload = json.loads(request)
        version = payload["baseVersion"] + 1
        patch_tool = next(
            tool for tool in tools if tool.__name__ == "propose_document_patch"
        )
        patch_tool(
            payload["baseVersion"],
            f"Apply synthetic mode-parity turn {version}.",
            [
                {
                    "operationId": str(uuid4()),
                    "op": "replace_section",
                    "section": "customerGoal",
                    "value": {
                        "text": f"Synthetic parity value {version}.",
                        "classification": "inference",
                    },
                }
            ],
            None,
        )
        return FoundryInvocation(
            response_id=f"opaque-response-{version}",
            completion_summary=json.dumps(
                {
                    "summary": (
                        f"Updated the working document to version {version}."
                    ),
                    "document_version": version,
                    "claims": [],
                }
            ),
        )


class _BlockingFoundryProvider(_FoundryProvider):
    def __init__(self) -> None:
        super().__init__()
        self.invoke_count = 0
        self.cancelled = False

    async def invoke(
        self,
        request: str,
        *,
        session: _Session,
        tools: object,
    ) -> FoundryInvocation:
        del request, session, tools
        self.invoke_count += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _FailingFoundryProvider(_FoundryProvider):
    def __init__(self) -> None:
        super().__init__()
        self.invoke_count = 0

    async def invoke(
        self,
        request: str,
        *,
        session: _Session,
        tools: object,
    ) -> FoundryInvocation:
        del request, session, tools
        self.invoke_count += 1
        raise RuntimeError("private provider failure details")


def _foundry_worker(provider: _FoundryProvider) -> FoundryDeepWorker:
    settings = Settings(
        agent_provider=AgentProvider.FOUNDRY,
        voice_provider=VoiceProvider.OFF,
        azure_token_credentials="AzureCliCredential",
        azure_tenant_id="00000000-0000-4000-8000-000000000001",
        foundry_project_endpoint="https://example.invalid",
        foundry_agent_name="synthetic-agent",
        foundry_agent_version="1",
    )
    return FoundryDeepWorker(settings, provider=provider, project_context={})


def _command(
    session_id: UUID,
    *,
    transcript: str,
) -> dict[str, object]:
    return {
        "type": "turn.submit",
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(session_id),
        "turnId": str(uuid4()),
        "timestamp": "2026-08-27T00:00:00Z",
        "inputMode": "typed",
        "transcript": transcript,
    }


def _cancel(session_id: UUID, turn_id: UUID) -> dict[str, object]:
    return {
        "type": "turn.cancel",
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(session_id),
        "turnId": str(turn_id),
        "timestamp": "2026-08-27T00:00:01Z",
        "reason": "user_request",
    }


async def _wait_until_running(
    service: DeepWorkService,
    session_id: UUID,
    turn_id: UUID,
) -> None:
    while (await service.snapshot(session_id, turn_id)).status.value != "running":
        await asyncio.sleep(0)


async def _run_mode(mode: AgentProvider) -> dict[str, object]:
    session_id = UUID(
        "10000000-0000-4000-8000-000000000099"
        if mode is AgentProvider.DETERMINISTIC
        else "10000000-0000-4000-8000-000000000100"
    )
    store = ConversationStore()
    store.create_session(session_id)
    provider = _FoundryProvider()
    worker = (
        DeterministicDeepWorker()
        if mode is AgentProvider.DETERMINISTIC
        else _foundry_worker(provider)
    )
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=worker,
    )
    submissions = []
    turn_ids = []
    for scripted in SCRIPTED_TURNS:
        turn_id = uuid4()
        turn_ids.append(turn_id)
        submissions.append(
            await service.submit(
                {
                    "type": "turn.submit",
                    "commandId": str(uuid4()),
                    "idempotencyKey": str(uuid4()),
                    "sessionId": str(session_id),
                    "turnId": str(turn_id),
                    "timestamp": "2026-08-27T00:00:00Z",
                    "inputMode": "typed",
                    "transcript": scripted["transcript"],
                }
            )
        )
    outcomes = [
        await service.wait_for_turn(session_id, turn_id) for turn_id in turn_ids
    ]
    current = store.document(session_id)
    assert current is not None
    restored = await service.revert(
        {
            "type": "document.revert",
            "commandId": str(uuid4()),
            "idempotencyKey": str(uuid4()),
            "sessionId": str(session_id),
            "turnId": str(uuid4()),
            "timestamp": "2026-08-27T00:01:00Z",
            "documentId": str(current.document_id),
            "targetVersion": 1,
            "summary": "Restore the first synthetic version.",
        }
    )
    events = [
        event.model_dump(mode="json", by_alias=True)
        for event in store.events(session_id)
    ]
    event_shapes: dict[str, set[str]] = {}
    for event in events:
        event_shapes.setdefault(event["type"], set()).update(event)
    return {
        "accepted": [item.accepted for item in submissions],
        "queue_positions": [item.queue_position for item in submissions],
        "statuses": [
            (item.status.value, item.document_status.value) for item in outcomes
        ],
        "versions": [item.committed_document_version for item in outcomes],
        "event_types": [event["type"] for event in events],
        "event_shapes": event_shapes,
        "document_shape": set(restored.document.model_dump(by_alias=True)),
        "history_versions": [
            item.document.version for item in store.versions(session_id)
        ],
        "restored_from": restored.diff.restored_from_version,
        "provider_conversations": provider.create_count,
    }


async def _run_capacity_and_cancellation(mode: AgentProvider) -> dict[str, object]:
    session_id = UUID(
        "10000000-0000-4000-8000-000000000102"
        if mode is AgentProvider.DETERMINISTIC
        else "10000000-0000-4000-8000-000000000103"
    )
    store = ConversationStore()
    store.create_session(session_id)
    provider = _BlockingFoundryProvider()
    worker = (
        DeterministicDeepWorker()
        if mode is AgentProvider.DETERMINISTIC
        else _foundry_worker(provider)
    )
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=worker,
        control_environment=DeepWorkControlEnvironment.TEST,
    )
    first = await service.submit(
        _command(session_id, transcript=SCRIPTED_TURNS[0]["transcript"]),
        controls=(
            DeepWorkControls(delay_ms=60_000)
            if mode is AgentProvider.DETERMINISTIC
            else None
        ),
    )
    await _wait_until_running(service, session_id, first.turn_id)
    submissions = [first]
    for index in range(4):
        submissions.append(
            await service.submit(
                _command(
                    session_id,
                    transcript=SCRIPTED_TURNS[min(index + 1, 2)]["transcript"],
                )
            )
        )

    queued_cancellations = [
        await service.cancel(_cancel(session_id, item.turn_id))
        for item in submissions[1:4]
    ]
    running_cancellation = await service.cancel(
        _cancel(session_id, submissions[0].turn_id)
    )
    outcomes = [
        await service.wait_for_turn(session_id, item.turn_id)
        for item in submissions[:4]
    ]
    events = [
        event.model_dump(mode="json", by_alias=True)
        for event in store.events(session_id)
    ]
    event_shapes: dict[str, set[str]] = {}
    for event in events:
        event_shapes.setdefault(event["type"], set()).update(event)
    return {
        "accepted": [item.accepted for item in submissions],
        "task_created": [item.task_created for item in submissions],
        "queue_positions": [item.queue_position for item in submissions],
        "rejection_code": submissions[4].error.code if submissions[4].error else None,
        "queued_cancellations": [
            (item.final, item.status.value if item.status else None)
            for item in queued_cancellations
        ],
        "running_cancellation": (
            running_cancellation.final,
            (
                running_cancellation.status.value
                if running_cancellation.status
                else None
            ),
        ),
        "outcomes": [
            (item.status.value, item.document_status.value) for item in outcomes
        ],
        "event_types": [event["type"] for event in events],
        "event_shapes": event_shapes,
        "document_version": store.document(session_id).version,
        "provider_invocations": provider.invoke_count,
        "provider_cancelled": provider.cancelled,
    }


async def _run_failure(mode: AgentProvider) -> dict[str, object]:
    session_id = UUID(
        "10000000-0000-4000-8000-000000000104"
        if mode is AgentProvider.DETERMINISTIC
        else "10000000-0000-4000-8000-000000000105"
    )
    store = ConversationStore()
    store.create_session(session_id)
    provider = _FailingFoundryProvider()
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=(
            DeterministicDeepWorker()
            if mode is AgentProvider.DETERMINISTIC
            else _foundry_worker(provider)
        ),
        control_environment=DeepWorkControlEnvironment.TEST,
    )
    submission = await service.submit(
        _command(session_id, transcript=SCRIPTED_TURNS[0]["transcript"]),
        controls=(
            DeepWorkControls(producer_failure=True)
            if mode is AgentProvider.DETERMINISTIC
            else None
        ),
    )
    outcome = await service.wait_for_turn(session_id, submission.turn_id)
    failure = next(
        event
        for event in store.events(session_id)
        if event.type == "document.failed"
    )
    return {
        "status": (outcome.status.value, outcome.document_status.value),
        "error_class": (
            failure.error.code.value,
            failure.error.category.value,
            failure.error.retryable,
        ),
        "event_shape": set(failure.model_dump(mode="json", by_alias=True)),
        "document_version": store.document(session_id).version,
        "provider_invocations": provider.invoke_count,
        "serialized_events": "\n".join(
            event.model_dump_json() for event in store.events(session_id)
        ),
    }


def test_deterministic_and_foundry_modes_have_app_contract_parity() -> None:
    deterministic = asyncio.run(_run_mode(AgentProvider.DETERMINISTIC))
    foundry = asyncio.run(_run_mode(AgentProvider.FOUNDRY))

    for key in (
        "accepted",
        "queue_positions",
        "statuses",
        "versions",
        "event_types",
        "event_shapes",
        "document_shape",
        "history_versions",
        "restored_from",
    ):
        assert foundry[key] == deterministic[key]
    assert foundry["provider_conversations"] == 1
    assert deterministic["provider_conversations"] == 0


def test_fifo_capacity_and_cancellation_have_cross_mode_parity() -> None:
    deterministic = asyncio.run(
        _run_capacity_and_cancellation(AgentProvider.DETERMINISTIC)
    )
    foundry = asyncio.run(_run_capacity_and_cancellation(AgentProvider.FOUNDRY))

    for key in (
        "accepted",
        "task_created",
        "queue_positions",
        "rejection_code",
        "queued_cancellations",
        "running_cancellation",
        "outcomes",
        "event_types",
        "event_shapes",
        "document_version",
    ):
        assert foundry[key] == deterministic[key]
    assert foundry["provider_invocations"] == 1
    assert foundry["provider_cancelled"] is True
    assert deterministic["provider_invocations"] == 0
    assert deterministic["provider_cancelled"] is False


def test_sanitized_failure_classes_have_cross_mode_parity_without_fallback() -> None:
    deterministic = asyncio.run(_run_failure(AgentProvider.DETERMINISTIC))
    foundry = asyncio.run(_run_failure(AgentProvider.FOUNDRY))

    for key in ("status", "error_class", "event_shape", "document_version"):
        assert foundry[key] == deterministic[key]
    assert foundry["provider_invocations"] == 1
    assert deterministic["provider_invocations"] == 0
    assert "private provider failure" not in foundry["serialized_events"]
    assert "deterministic producer" not in foundry["serialized_events"].lower()


def test_mode_and_content_free_telemetry_are_process_owned_and_restart_empty() -> None:
    capability_shapes = []
    for mode in AgentProvider:
        provider = _FoundryProvider()
        environ = (
            {}
            if mode is AgentProvider.DETERMINISTIC
            else {
                "AGENT_PROVIDER": "foundry",
                "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
                "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
                "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid",
            }
        )
        application = create_app(
            environ=environ,
            agent_worker_factory=lambda settings: FoundryDeepWorker(
                settings,
                provider=provider,
                project_context={},
            ),
        )
        with TestClient(application) as client:
            session_id = UUID(client.post("/api/sessions").json()["sessionId"])
            environ["AGENT_PROVIDER"] = (
                "foundry"
                if mode is AgentProvider.DETERMINISTIC
                else "deterministic"
            )
            capabilities = client.get("/api/capabilities").json()
            assert capabilities["agentProvider"] == mode.value
            assert capabilities["voiceProvider"] == "off"
            with pytest.raises(FrozenInstanceError):
                setattr(
                    application.state.settings,
                    "agent_provider",
                    AgentProvider.FOUNDRY,
                )
            application.state.telemetry.record(
                "document_pending",
                session_id=session_id,
                outcome="pending",
            )
            telemetry = application.state.telemetry.snapshot()
            assert len(telemetry) == 1
            assert telemetry[0].name == "document_pending"
            assert telemetry[0].session_id == session_id
            assert telemetry[0].outcome == "pending"
            capability_shapes.append(set(capabilities) - {"agentProvider"})

        restarted = create_app(
            environ=(
                {}
                if mode is AgentProvider.DETERMINISTIC
                else {
                    "AGENT_PROVIDER": "foundry",
                    "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
                    "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
                    "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid",
                }
            ),
            agent_worker_factory=lambda settings: FoundryDeepWorker(
                settings,
                provider=_FoundryProvider(),
                project_context={},
            ),
        )
        assert restarted.state.conversations.session_count() == 0
        assert restarted.state.telemetry.snapshot() == ()

    assert capability_shapes[0] == capability_shapes[1]


def test_backend_restart_deletes_state_in_both_modes() -> None:
    for mode in AgentProvider:
        result = asyncio.run(_run_mode(mode))
        assert result["history_versions"] == [1, 2, 3, 4]
        restarted = ConversationStore()
        assert restarted.session_count() == 0
