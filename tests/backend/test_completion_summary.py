"""Foundry completion summaries cannot outrank the canonical document."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from backend.config import AgentProvider, Settings, VoiceProvider
from backend.deep_work.foundry import (
    FoundryCompatibility,
    FoundryDeepWorker,
    FoundryInvocation,
)
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService

SESSION_ID = UUID("10000000-0000-4000-8000-000000000097")
CLAIM = "Synthetic operations teams need a bounded review workflow."


@dataclass
class _Session:
    service_session_id: str = "opaque-conversation"


class _Provider:
    def __init__(
        self,
        completion_summary: str | None,
        *,
        operations: list[dict[str, object]] | None = None,
    ) -> None:
        self.completion_summary = completion_summary
        self.operations = operations

    async def validate_compatibility(self) -> FoundryCompatibility:
        return FoundryCompatibility(True, True, True)

    async def create_conversation(self, *, tools: object) -> _Session:
        del tools
        return _Session()

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
        result = patch_tool(
            payload["baseVersion"],
            "Apply one supported claim.",
            self.operations
            or [
                {
                    "operationId": str(uuid4()),
                    "op": "replace_section",
                    "section": "customerGoal",
                    "value": {"text": CLAIM, "classification": "inference"},
                }
            ],
            None,
        )
        assert result["outcome"] == "committed"
        return FoundryInvocation(
            response_id="opaque-response",
            completion_summary=self.completion_summary,
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


async def _run(summary: str | None):
    store = ConversationStore()
    store.create_session(SESSION_ID)
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=FoundryDeepWorker(
            _settings(),
            provider=_Provider(summary),
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
            "transcript": "Review the bounded synthetic context.",
        }
    )
    return store, await service.wait_for_turn(SESSION_ID, turn_id)


async def _run_with_operations(
    summary: str | None,
    operations: list[dict[str, object]],
):
    store = ConversationStore()
    store.create_session(SESSION_ID)
    service = DeepWorkService(
        store=store,
        patch_service=PatchService(store),
        worker=FoundryDeepWorker(
            _settings(),
            provider=_Provider(summary, operations=operations),
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
            "transcript": "Review the bounded synthetic context.",
        }
    )
    return store, await service.wait_for_turn(SESSION_ID, turn_id)


def _summary(
    *,
    text: str,
    version: int = 1,
    no_op_reason: str | None = None,
    claims: list[str] | None = None,
    remaining_uncertainties: list[str] | None = None,
) -> str:
    payload = {
        "summary": text,
        "document_version": version,
        "claims": claims or [],
        "remaining_uncertainties": remaining_uncertainties or [],
    }
    if no_op_reason is not None:
        payload["no_op_reason"] = no_op_reason
    return json.dumps(payload)


def test_supported_short_summary_is_accepted_after_tool_completion() -> None:
    store, outcome = asyncio.run(
        _run(
            _summary(
                text="Updated the working document to version 1.",
                claims=[CLAIM],
            )
        )
    )

    assert outcome.committed_document_version == 1
    assert store.document(SESSION_ID).customer_goal.text == CLAIM
    completion = next(
        event
        for event in store.events(SESSION_ID)
        if event.type == "turn.analysis.completed"
    )
    assert completion.outcome == "committed"
    assert completion.summary == "Updated the working document to version 1."
    assert completion.document_version == 1
    assert completion.no_op_reason is None


def test_summary_cites_canonical_remaining_uncertainty() -> None:
    uncertainty = "Synthetic approval criteria remain unverified."
    operations = [
        {
            "operationId": str(uuid4()),
            "op": "append_list_item",
            "section": "missingEvidence",
            "value": {
                "text": uncertainty,
                "classification": "unknown",
            },
        }
    ]
    store, outcome = asyncio.run(
        _run_with_operations(
            _summary(
                text="Updated the working document to version 1.",
                remaining_uncertainties=[uncertainty],
            ),
            operations,
        )
    )

    assert outcome.committed_document_version == 1
    assert store.document(SESSION_ID).missing_evidence[0].text == uncertainty


def test_summary_must_reference_remaining_uncertainty_when_one_exists() -> None:
    operations = [
        {
            "operationId": str(uuid4()),
            "op": "append_list_item",
            "section": "assumptionsAndUncertainties",
            "value": {
                "text": "Synthetic adoption remains uncertain.",
                "classification": "unknown",
            },
        }
    ]
    store, outcome = asyncio.run(
        _run_with_operations(
            _summary(text="Updated the working document to version 1."),
            operations,
        )
    )

    assert outcome.status.value == "failed"
    assert store.document(SESSION_ID).version == 0
    assert store.versions(SESSION_ID) == ()


@pytest.mark.parametrize(
    "summary",
    [
        None,
        "not-json",
        _summary(text="The opportunity will save forty percent."),
        _summary(
            text="Updated the working document to version 1.",
            version=2,
        ),
        _summary(
            text="Updated the working document to version 1.",
            claims=["Unsupported provider-only claim."],
        ),
        _summary(
            text="Updated the working document to version 1.",
            remaining_uncertainties=["Unsupported provider-only uncertainty."],
        ),
        _summary(
            text="Updated the working document to version 1.",
            no_op_reason="No-op metadata cannot accompany a committed patch.",
        ),
    ],
    ids=[
        "missing",
        "malformed",
        "unsupported-prose",
        "wrong-version",
        "unsupported-claim",
        "unsupported-uncertainty",
        "unexpected-no-op-reason",
    ],
)
def test_invalid_or_unsupported_summary_blocks_canonical_mutation(
    summary: str | None,
) -> None:
    store, outcome = asyncio.run(_run(summary))

    assert outcome.status.value == "failed"
    assert outcome.document_status.value == "failed"
    assert store.document(SESSION_ID).version == 0
    assert store.document(SESSION_ID).customer_goal is None
    assert store.versions(SESSION_ID) == ()
    failures = [
        event for event in store.events(SESSION_ID) if event.type == "document.failed"
    ]
    assert len(failures) == 1
    assert failures[0].error.code.value == "validation_error"
