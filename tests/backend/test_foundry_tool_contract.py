"""Exact-once Foundry patch-tool and no-mutation contract tests."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from backend.config import AgentProvider, Settings, VoiceProvider
from backend.deep_work.base import CancellationToken, DeepWorkFailure
from backend.deep_work.foundry import (
    FoundryCompatibility,
    FoundryConversationLostError,
    FoundryDeepWorker,
    FoundryInvocation,
)
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService
from backend.tools.propose_document_patch import (
    PatchProposalCapture,
    create_patch_proposal_tool,
)

SESSION_ID = UUID("10000000-0000-4000-8000-000000000096")


@dataclass
class _Session:
    service_session_id: str = "opaque-conversation"


class _Provider:
    def __init__(self, action, *, summary: str | None = None) -> None:
        self.action = action
        self.summary = summary
        self.session = _Session()

    async def validate_compatibility(self) -> FoundryCompatibility:
        return FoundryCompatibility(True, True, True)

    async def create_conversation(self, *, tools: object) -> _Session:
        del tools
        return self.session

    async def invoke(
        self,
        request: str,
        *,
        session: _Session,
        tools: object,
    ) -> FoundryInvocation:
        del session
        payload = json.loads(request)
        tool_map = {tool.__name__: tool for tool in tools}
        self.action(payload, tool_map["propose_document_patch"])
        version = payload["baseVersion"] + 1
        completion = self.summary or json.dumps(
            {
                "summary": f"Updated the working document to version {version}.",
                "document_version": version,
                "claims": [],
            }
        )
        return FoundryInvocation(
            response_id="opaque-response",
            completion_summary=completion,
        )


def _settings() -> Settings:
    return Settings(
        agent_provider=AgentProvider.FOUNDRY,
        voice_provider=VoiceProvider.OFF,
        azure_token_credentials="AzureCliCredential",
        azure_tenant_id="00000000-0000-4000-8000-000000000001",
        foundry_project_endpoint="https://example.invalid",
        foundry_agent_name="synthetic-agent",
        foundry_agent_version="1",
    )


def _operation(value: str = "Supported synthetic claim.") -> list[dict[str, object]]:
    return [
        {
            "operationId": str(uuid4()),
            "op": "replace_section",
            "section": "customerGoal",
            "value": {"text": value, "classification": "inference"},
        }
    ]


def _valid_call(payload: dict[str, object], tool: object) -> object:
    return tool(
        payload["baseVersion"],
        "Apply a supported synthetic update.",
        _operation(),
        None,
    )


async def _run(action, *, summary: str | None = None):
    store = ConversationStore()
    store.create_session(SESSION_ID)
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=FoundryDeepWorker(
            _settings(),
            provider=_Provider(action, summary=summary),
            project_context={},
        ),
    )
    turn_id = uuid4()
    submission = await service.submit(
        {
            "type": "turn.submit",
            "commandId": str(uuid4()),
            "idempotencyKey": str(uuid4()),
            "sessionId": str(SESSION_ID),
            "turnId": str(turn_id),
            "timestamp": "2026-08-27T00:00:00Z",
            "inputMode": "typed",
            "transcript": "Review the synthetic project.",
        }
    )
    assert submission.accepted
    outcome = await service.wait_for_turn(SESSION_ID, turn_id)
    return store, outcome


@pytest.mark.parametrize(
    "action",
    [
        lambda payload, tool: None,
        lambda payload, tool: tool(
            payload["baseVersion"] + 1,
            "Use a stale base.",
            _operation(),
            None,
        ),
        lambda payload, tool: tool(
            payload["baseVersion"],
            "Use an invalid operation.",
            [{"operationId": str(uuid4()), "op": "unknown"}],
            None,
        ),
    ],
    ids=["zero-calls", "stale", "invalid"],
)
def test_rejected_tool_contracts_never_mutate_canonical_document(action) -> None:
    store, outcome = asyncio.run(_run(action))

    assert outcome.status.value == "failed"
    assert outcome.document_status.value == "failed"
    assert store.document(SESSION_ID).version == 0
    assert store.versions(SESSION_ID) == ()
    assert store.no_ops(SESSION_ID) == ()


def test_valid_call_returns_staged_committed_outcome_then_canonical_commit() -> None:
    returned: list[object] = []

    def action(payload, tool) -> None:
        returned.append(_valid_call(payload, tool))

    store, outcome = asyncio.run(_run(action))

    assert returned == [
        {
            "accepted": True,
            "outcome": "committed",
            "documentVersion": 1,
        }
    ]
    assert outcome.committed_document_version == 1
    assert store.document(SESSION_ID).version == 1


def test_repeated_dispatch_returns_the_single_staged_outcome() -> None:
    returned: list[object] = []

    def action(payload, tool) -> None:
        returned.extend((_valid_call(payload, tool), _valid_call(payload, tool)))

    store, outcome = asyncio.run(_run(action))

    assert returned[0] == returned[1]
    assert outcome.committed_document_version == 1
    assert len(store.versions(SESSION_ID)) == 1


def test_reasoned_no_op_returns_outcome_without_version_increment() -> None:
    returned: list[object] = []

    def action(payload, tool) -> None:
        returned.append(
            tool(
                payload["baseVersion"],
                "No supported change is warranted.",
                [],
                "The supplied synthetic evidence already matches the document.",
            )
        )

    summary = json.dumps(
        {
            "summary": "No document changes were needed.",
            "document_version": 0,
            "no_op_reason": (
                "The supplied synthetic evidence already matches the document."
            ),
            "claims": [],
        }
    )
    store, outcome = asyncio.run(_run(action, summary=summary))

    assert returned[0]["outcome"] == "no_op"
    assert outcome.document_status.value == "no_op"
    assert outcome.committed_document_version == 0
    assert store.document(SESSION_ID).version == 0
    assert len(store.no_ops(SESSION_ID)) == 1
    completion = next(
        event
        for event in store.events(SESSION_ID)
        if event.type == "turn.analysis.completed"
    )
    assert completion.outcome == "no_op"
    assert completion.summary == "No document changes were needed."
    assert completion.document_version == 0
    assert completion.no_op_reason == (
        "The supplied synthetic evidence already matches the document."
    )


def test_no_op_summary_must_repeat_the_accepted_reason() -> None:
    def action(payload, tool) -> None:
        tool(
            payload["baseVersion"],
            "No supported change is warranted.",
            [],
            "The supplied synthetic evidence already matches the document.",
        )

    summary = json.dumps(
        {
            "summary": "No document changes were needed.",
            "document_version": 0,
            "no_op_reason": "Unsupported provider-only no-op reason.",
            "claims": [],
        }
    )
    store, outcome = asyncio.run(_run(action, summary=summary))

    assert outcome.status.value == "failed"
    assert store.document(SESSION_ID).version == 0
    assert store.no_ops(SESSION_ID) == ()


def test_empty_operations_without_reason_are_rejected_without_mutation() -> None:
    def action(payload, tool) -> None:
        result = tool(
            payload["baseVersion"],
            "Invalid empty proposal.",
            [],
            None,
        )
        assert result == {
            "accepted": False,
            "outcome": "rejected",
            "reason": "validation_failed",
        }

    store, outcome = asyncio.run(_run(action))

    assert outcome.status.value == "failed"
    assert store.document(SESSION_ID).version == 0
    assert store.no_ops(SESSION_ID) == ()


def test_raw_strict_operation_batch_is_hydrated_before_staging() -> None:
    def action(payload, tool) -> None:
        result = tool(
            payload["baseVersion"],
            "Apply the strict operation batch.",
            {
                "setFields": [],
                "replaceSections": [
                    {
                        "section": "customerGoal",
                        "value": {
                            "text": "Supported synthetic claim.",
                            "classification": "inference",
                            "sourceLabel": None,
                        },
                    }
                ],
                "appendListItems": [],
                "updateListItems": [],
                "removeListItems": [],
            },
            None,
        )
        assert result["accepted"] is True

    store, outcome = asyncio.run(_run(action))

    assert outcome.status.value == "completed"
    assert outcome.committed_document_version == 1
    assert store.document(SESSION_ID).customer_goal.text == "Supported synthetic claim."


def test_post_cancellation_tool_call_is_rejected_without_staging() -> None:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    document = store.create_document(SESSION_ID)
    from backend.deep_work.base import DeepWorkControls, DeepWorkInput

    work_input = DeepWorkInput(
        session_id=SESSION_ID,
        turn_id=uuid4(),
        sequence=1,
        transcript="Synthetic request.",
        document=document,
        prior_turns=(),
        controls=DeepWorkControls(),
    )
    cancellation = CancellationToken()
    cancellation.request()
    capture = PatchProposalCapture()
    tool = create_patch_proposal_tool(work_input, capture, cancellation)

    result = tool(
        0,
        "Attempt after cancellation.",
        _operation(),
        None,
    )

    assert result["accepted"] is False
    assert result["reason"] == "cancelled"
    with pytest.raises(LookupError):
        capture.require_exactly_one()
    assert store.document(SESSION_ID).version == 0


def test_concurrent_repeated_dispatch_is_idempotent() -> None:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    document = store.create_document(SESSION_ID)
    from backend.deep_work.base import DeepWorkControls, DeepWorkInput

    work_input = DeepWorkInput(
        session_id=SESSION_ID,
        turn_id=uuid4(),
        sequence=1,
        transcript="Synthetic request.",
        document=document,
        prior_turns=(),
        controls=DeepWorkControls(),
    )
    capture = PatchProposalCapture()
    tool = create_patch_proposal_tool(work_input, capture)

    def invoke() -> object:
        return tool(
            0,
            "Concurrent synthetic attempt.",
            _operation(),
            None,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: invoke(), range(2)))

    assert all(result["accepted"] is True for result in results)
    assert results[0] == results[1]
    assert capture.attempt_count == 1
    capture.require_exactly_one()
    assert store.document(SESSION_ID).version == 0
    assert store.versions(SESSION_ID) == ()


def test_provider_loss_after_staging_never_commits() -> None:
    class LossAfterStagingProvider(_Provider):
        async def invoke(
            self,
            request: str,
            *,
            session: _Session,
            tools: object,
        ) -> FoundryInvocation:
            await super().invoke(request, session=session, tools=tools)
            raise FoundryConversationLostError("private provider details")

    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)
        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=FoundryDeepWorker(
                _settings(),
                provider=LossAfterStagingProvider(_valid_call),
                project_context={},
            ),
        )
        turn_id = uuid4()
        await service.submit(
            {
                "type": "turn.submit",
                "commandId": str(uuid4()),
                "idempotencyKey": str(uuid4()),
                "sessionId": str(SESSION_ID),
                "turnId": str(turn_id),
                "timestamp": "2026-08-27T00:00:00Z",
                "inputMode": "typed",
                "transcript": "Synthetic provider-loss request.",
            }
        )

        outcome = await service.wait_for_turn(SESSION_ID, turn_id)

        assert outcome.status.value == "failed"
        assert store.document(SESSION_ID).version == 0
        assert store.versions(SESSION_ID) == ()

    asyncio.run(scenario())


def test_late_provider_output_after_cancellation_cannot_commit() -> None:
    class LateProvider(_Provider):
        def __init__(self) -> None:
            super().__init__(lambda payload, tool: None)
            self.staged = asyncio.Event()
            self.cancelled = False

        async def invoke(
            self,
            request: str,
            *,
            session: _Session,
            tools: object,
        ) -> FoundryInvocation:
            del session
            payload = json.loads(request)
            patch_tool = next(
                tool for tool in tools if tool.__name__ == "propose_document_patch"
            )
            _valid_call(payload, patch_tool)
            self.staged.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                return FoundryInvocation(
                    response_id="late-response",
                    completion_summary=json.dumps(
                        {
                            "summary": "Updated the working document to version 1.",
                            "document_version": 1,
                            "claims": [],
                        }
                    ),
                )

    async def scenario() -> None:
        provider = LateProvider()
        store = ConversationStore()
        store.create_session(SESSION_ID)
        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=FoundryDeepWorker(
                _settings(),
                provider=provider,
                project_context={},
            ),
        )
        turn_id = uuid4()
        await service.submit(
            {
                "type": "turn.submit",
                "commandId": str(uuid4()),
                "idempotencyKey": str(uuid4()),
                "sessionId": str(SESSION_ID),
                "turnId": str(turn_id),
                "timestamp": "2026-08-27T00:00:00Z",
                "inputMode": "typed",
                "transcript": "Cancel this synthetic turn.",
            }
        )
        await provider.staged.wait()
        cancellation = await service.cancel(
            {
                "type": "turn.cancel",
                "commandId": str(uuid4()),
                "idempotencyKey": str(uuid4()),
                "sessionId": str(SESSION_ID),
                "turnId": str(turn_id),
                "timestamp": "2026-08-27T00:00:01Z",
                "reason": "user_request",
            }
        )
        outcome = await service.wait_for_turn(SESSION_ID, turn_id)

        assert cancellation.status.value == "cancelling"
        assert provider.cancelled is True
        assert outcome.status.value == "cancelled"
        assert store.document(SESSION_ID).version == 0
        assert store.versions(SESSION_ID) == ()

    asyncio.run(scenario())


def test_worker_surfaces_exact_once_failure_as_sanitized_validation_error() -> None:
    async def scenario() -> None:
        store = ConversationStore()
        store.create_session(SESSION_ID)
        document = store.create_document(SESSION_ID)
        from backend.deep_work.base import DeepWorkControls, DeepWorkInput

        worker = FoundryDeepWorker(
            _settings(),
            provider=_Provider(lambda payload, tool: None),
            project_context={},
        )
        with pytest.raises(DeepWorkFailure) as captured:
            await worker.run(
                DeepWorkInput(
                    session_id=SESSION_ID,
                    turn_id=uuid4(),
                    sequence=1,
                    transcript="Synthetic request.",
                    document=document,
                    prior_turns=(),
                    controls=DeepWorkControls(),
                ),
                CancellationToken(),
            )
        assert captured.value.error.code.value == "validation_error"
        assert "canonical document was not changed" in str(captured.value)

    asyncio.run(scenario())
