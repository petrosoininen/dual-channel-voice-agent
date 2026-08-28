"""Stable Foundry conversation continuity and visible-loss tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from backend.config import AgentProvider, Settings, VoiceProvider
from backend.deep_work.foundry import (
    FoundryCompatibility,
    FoundryConversationLostError,
    FoundryDeepWorker,
    FoundryInvocation,
)
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService

SESSION_ID = UUID("10000000-0000-4000-8000-000000000098")


@dataclass
class _Session:
    service_session_id: str = "opaque-conversation"


class _Provider:
    def __init__(self, *, lose: bool = False) -> None:
        self.lose = lose
        self.session = _Session()
        self.create_count = 0
        self.invoke_count = 0

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
        self.invoke_count += 1
        if self.lose:
            raise FoundryConversationLostError("provider details")
        payload = json.loads(request)
        patch_tool = next(
            tool for tool in tools if tool.__name__ == "propose_document_patch"
        )
        version = payload["baseVersion"] + 1
        patch_tool(
            payload["baseVersion"],
            "Apply the next ordered update.",
            [
                {
                    "operationId": str(uuid4()),
                    "op": "replace_section",
                    "section": "customerGoal",
                    "value": {
                        "text": f"Synthetic turn {version}.",
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


async def _submit(service: DeepWorkService, sequence: int):
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
            "transcript": f"Synthetic follow-up {sequence}.",
        }
    )
    return await service.wait_for_turn(SESSION_ID, turn_id)


def test_three_turns_share_one_service_conversation() -> None:
    async def scenario() -> None:
        provider = _Provider()
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

        outcomes = [await _submit(service, sequence) for sequence in range(1, 4)]

        assert [item.committed_document_version for item in outcomes] == [1, 2, 3]
        assert provider.create_count == 1
        assert provider.invoke_count == 3

    asyncio.run(scenario())


def test_conversation_loss_fails_visibly_without_silent_replacement() -> None:
    async def scenario() -> None:
        provider = _Provider(lose=True)
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

        first = await _submit(service, 1)
        second = await _submit(service, 2)

        assert first.status.value == "failed"
        assert second.status.value == "failed"
        assert provider.create_count == 1
        assert provider.invoke_count == 1
        assert store.document(SESSION_ID).version == 0
        failures = [
            event
            for event in store.events(SESSION_ID)
            if event.type == "document.failed"
        ]
        assert len(failures) == 2
        assert all(event.error.code.value == "conflict" for event in failures)
        assert all(event.error.retryable is False for event in failures)

    asyncio.run(scenario())


def test_uncertain_creation_failure_never_retries_with_a_replacement() -> None:
    class CreationFailureProvider(_Provider):
        async def create_conversation(self, *, tools: object) -> _Session:
            del tools
            self.create_count += 1
            raise RuntimeError("provider creation outcome is unknown")

    async def scenario() -> None:
        provider = CreationFailureProvider()
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

        first = await _submit(service, 1)
        second = await _submit(service, 2)

        assert first.status.value == "failed"
        assert second.status.value == "failed"
        assert provider.create_count == 1
        assert provider.invoke_count == 0
        assert store.document(SESSION_ID).version == 0

    asyncio.run(scenario())
