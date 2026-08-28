"""Foundry adapter tests with deterministic local provider fakes."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agent_framework import FunctionTool
from fastapi.testclient import TestClient

from backend.config import AgentProvider, ConfigurationError, Settings, VoiceProvider
from backend.deep_work.base import (
    CancellationToken,
    DeepWorkCancelled,
    DeepWorkFailure,
)
from backend.deep_work.foundry import (
    EXPECTED_LOCAL_TOOL_NAMES,
    FOUNDRY_INSTRUCTION_MARKERS,
    FoundryCompatibility,
    FoundryConversationLostError,
    FoundryDeepWorker,
    FoundryInvocation,
    _FRAMEWORK_LOGGER,
    _build_request,
    _classify_agent_definition,
    _invoke_with_cancellation,
)
from backend.main import create_app
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService
from backend.tools.project_context import create_project_context_tool
from backend.tools.propose_document_patch import (
    PatchProposalCapture,
    create_patch_proposal_tool,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPTED_TURNS = json.loads(
    (ROOT / "fixtures" / "scripted-turns.json").read_text(encoding="utf-8")
)
SESSION_ID = UUID("10000000-0000-4000-8000-000000000095")


@dataclass
class _FakeSession:
    service_session_id: str | None


class _FakeProvider:
    def __init__(
        self,
        *,
        compatibility: FoundryCompatibility | None = None,
    ) -> None:
        self.compatibility = compatibility or FoundryCompatibility(True, True, True)
        self.session = _FakeSession("opaque-conversation")
        self.create_count = 0
        self.invocation_sessions: list[_FakeSession] = []
        self.tool_identity_sets: list[tuple[int, ...]] = []
        self.requests: list[str] = []

    async def validate_compatibility(self) -> FoundryCompatibility:
        return self.compatibility

    async def create_conversation(self, *, tools: object) -> _FakeSession:
        self.create_count += 1
        assert {tool.__name__ for tool in tools} == EXPECTED_LOCAL_TOOL_NAMES
        return self.session

    async def invoke(
        self,
        request: str,
        *,
        session: _FakeSession,
        tools: object,
    ) -> FoundryInvocation:
        tool_map = {tool.__name__: tool for tool in tools}
        self.invocation_sessions.append(session)
        self.tool_identity_sets.append(tuple(id(tool) for tool in tools))
        self.requests.append(request)
        context = tool_map["project_context"]()
        assert context["displayName"] == "Aster Field Cooperative modernization"
        payload = json.loads(request)
        sequence = len(self.invocation_sessions)
        tool_map["propose_document_patch"](
            payload["baseVersion"],
            f"Synthetic Foundry turn {sequence}.",
            [
                {
                    "operationId": str(uuid4()),
                    "op": "replace_section",
                    "section": "customerGoal",
                    "value": {
                        "text": f"Synthetic Foundry value {sequence}.",
                        "classification": "inference",
                    },
                }
            ],
            None,
        )
        return FoundryInvocation(
            response_id=f"opaque-response-{sequence}",
            completion_summary=json.dumps(
                {
                    "summary": (
                        f"Updated the working document to version {sequence}."
                    ),
                    "document_version": sequence,
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


def _command(sequence: int) -> dict[str, object]:
    return {
        "type": "turn.submit",
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(SESSION_ID),
        "turnId": str(uuid4()),
        "timestamp": "2026-08-26T12:00:00Z",
        "inputMode": "typed",
        "transcript": SCRIPTED_TURNS[sequence - 1]["transcript"],
    }


def test_framework_local_tool_warning_cannot_log_agent_identifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_FRAMEWORK_LOGGER.name)

    _FRAMEWORK_LOGGER.warning(
        "Foundry agent '%s' was provided tools, but declarations were omitted.",
        "private-agent-name",
    )
    _FRAMEWORK_LOGGER.warning("A different framework warning.")

    assert "private-agent-name" not in caplog.text
    assert "A different framework warning." in caplog.text


def test_three_turns_reuse_one_conversation_and_request_scoped_tools() -> None:
    async def scenario() -> None:
        provider = _FakeProvider()
        worker = FoundryDeepWorker(_settings(), provider=provider)
        await worker.validate_compatibility()
        store = ConversationStore()
        store.create_session(SESSION_ID)
        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=worker,
        )

        submissions = [await service.submit(_command(sequence)) for sequence in range(1, 4)]
        outcomes = [
            await service.wait_for_turn(SESSION_ID, item.turn_id)
            for item in submissions
        ]

        assert [item.committed_document_version for item in outcomes] == [1, 2, 3]
        assert provider.create_count == 1
        assert provider.invocation_sessions == [provider.session] * 3
        assert len(set(provider.tool_identity_sets)) == 3
        assert [json.loads(item)["baseVersion"] for item in provider.requests] == [
            0,
            1,
            2,
        ]
        turns = store.turns(SESSION_ID)
        assert {
            turn.provider_metadata.conversation_id
            for turn in turns
            if turn.provider_metadata is not None
        } == {"opaque-conversation"}
        assert [
            turn.provider_metadata.response_id
            for turn in turns
            if turn.provider_metadata is not None
        ] == ["opaque-response-1", "opaque-response-2", "opaque-response-3"]
        public_events = json.dumps(
            [event.model_dump(mode="json", by_alias=True) for event in store.events(SESSION_ID)]
        )
        assert "opaque-conversation" not in public_events
        assert "opaque-response" not in public_events

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "definition",
    [
        {
            "kind": "prompt",
            "instructions": "\n".join(FOUNDRY_INSTRUCTION_MARKERS),
            "tools": [
                {"type": "function", "name": "project_context"},
                {"type": "function", "name": "propose_document_patch"},
            ],
        },
        {
            "kind": "hosted",
            "instructions": "\n".join(FOUNDRY_INSTRUCTION_MARKERS),
            "tools": [
                {"type": "function", "name": "project_context"},
                {"type": "function", "name": "propose_document_patch"},
            ],
        },
        {
            "kind": "prompt",
            "instructions": "Unversioned instructions.",
            "tools": [
                {"type": "function", "name": "project_context"},
                {"type": "function", "name": "propose_document_patch"},
            ],
        },
        {
            "kind": "prompt",
            "instructions": "\n".join(FOUNDRY_INSTRUCTION_MARKERS),
            "tools": [
                {"type": "function", "name": "project_context"},
                {"type": "web_search", "name": "web"},
            ],
        },
        {
            "kind": "prompt",
            "instructions": "\n".join(FOUNDRY_INSTRUCTION_MARKERS),
            "tools": [
                {"type": "function", "name": "project_context"},
                {"type": "function", "name": "project_context"},
                {"type": "function", "name": "propose_document_patch"},
            ],
        },
    ],
)
def test_prompt_agent_compatibility_requires_exact_local_contract(
    definition: dict[str, object],
) -> None:
    compatibility = _classify_agent_definition({"definition": definition})

    assert compatibility.compatible is (definition["kind"] == "prompt" and len(definition["tools"]) == 2 and definition["instructions"] != "Unversioned instructions." and definition["tools"][1]["type"] == "function")


def test_local_tool_schemas_are_generated_from_bounded_typed_functions() -> None:
    from backend.deep_work.base import DeepWorkControls, DeepWorkInput

    store = ConversationStore()
    store.create_session(SESSION_ID)
    work_input = DeepWorkInput(
        session_id=SESSION_ID,
        turn_id=uuid4(),
        sequence=1,
        transcript="Synthetic request.",
        document=store.create_document(SESSION_ID),
        prior_turns=(),
        controls=DeepWorkControls(),
    )
    functions = (
        create_project_context_tool({}),
        create_patch_proposal_tool(work_input, PatchProposalCapture()),
    )
    schemas = {
        function.__name__: FunctionTool(
            name=function.__name__,
            description=function.__doc__ or "",
            func=function,
        ).to_json_schema_spec()["function"]
        for function in functions
    }

    assert set(schemas) == EXPECTED_LOCAL_TOOL_NAMES
    assert schemas["project_context"]["parameters"]["properties"] == {}
    patch_parameters = schemas["propose_document_patch"]["parameters"]
    assert patch_parameters["required"] == [
        "base_version",
        "summary",
        "operations",
        "reason",
    ]
    assert patch_parameters["properties"]["base_version"]["minimum"] == 0
    assert patch_parameters["properties"]["summary"]["maxLength"] == 500
    assert "operationId" not in str(patch_parameters)
    assert "oneOf" not in str(patch_parameters)
    operation_batch = patch_parameters["$defs"]["FoundryOperationBatch"]
    assert operation_batch["required"] == [
        "setFields",
        "replaceSections",
        "appendListItems",
        "updateListItems",
        "removeListItems",
    ]
    assert operation_batch["additionalProperties"] is False
    for field in operation_batch["properties"].values():
        assert field["maxItems"] == 32
    classified_text = patch_parameters["$defs"]["FoundryClassifiedText"]
    assert classified_text["required"] == [
        "text",
        "classification",
        "sourceLabel",
    ]
    assert classified_text["additionalProperties"] is False


def test_oversized_provider_request_fails_with_sanitized_error() -> None:
    from backend.deep_work.base import DeepWorkControls, DeepWorkInput

    store = ConversationStore()
    store.create_session(SESSION_ID)
    work_input = DeepWorkInput(
        session_id=SESSION_ID,
        turn_id=uuid4(),
        sequence=1,
        transcript="private-value-" * 8_000,
        document=store.create_document(SESSION_ID),
        prior_turns=(),
        controls=DeepWorkControls(),
    )

    with pytest.raises(DeepWorkFailure) as captured:
        _build_request(work_input, {})

    assert "private-value" not in str(captured.value)


def test_incompatible_startup_fails_closed_without_configuration_values() -> None:
    provider = _FakeProvider(
        compatibility=FoundryCompatibility(
            prompt_agent=True,
            instructions_compatible=False,
            local_tools_compatible=True,
        )
    )
    app = create_app(
        environ={
            "AGENT_PROVIDER": "foundry",
            "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
            "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid/private",
            "FOUNDRY_AGENT_NAME": "private-agent",
            "FOUNDRY_AGENT_VERSION": "private-version",
        },
        agent_worker_factory=lambda settings: FoundryDeepWorker(
            settings,
            provider=provider,
        ),
    )

    with pytest.raises(ConfigurationError) as captured:
        with TestClient(app):
            pass

    message = str(captured.value)
    assert "contract mismatch" in message
    assert "private" not in message
    assert "https://" not in message


def test_provider_failure_is_sanitized_and_does_not_leak_details() -> None:
    class ExplodingProvider(_FakeProvider):
        async def invoke(
            self,
            request: str,
            *,
            session: _FakeSession,
            tools: object,
        ) -> FoundryInvocation:
            del request, session, tools
            raise RuntimeError(
                "****** https://provider.invalid C:\\Users\\person\\private"
            )

    async def scenario() -> None:
        worker = FoundryDeepWorker(_settings(), provider=ExplodingProvider())
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
        with pytest.raises(DeepWorkFailure) as captured:
            await worker.run(work_input, CancellationToken())

        message = str(captured.value)
        assert message == (
            "Foundry deep work could not complete. "
            "Verify compatible agent access, then retry."
        )
        assert "provider.invalid" not in message
        assert "Users" not in message

    asyncio.run(scenario())


def test_conversation_loss_is_visible_sanitized_and_not_retryable() -> None:
    class LostConversationProvider(_FakeProvider):
        async def invoke(
            self,
            request: str,
            *,
            session: _FakeSession,
            tools: object,
        ) -> FoundryInvocation:
            del request, session, tools
            raise FoundryConversationLostError(
                "private-conversation https://provider.invalid"
            )

    async def scenario() -> None:
        from backend.deep_work.base import DeepWorkControls, DeepWorkInput

        worker = FoundryDeepWorker(_settings(), provider=LostConversationProvider())
        store = ConversationStore()
        store.create_session(SESSION_ID)
        work_input = DeepWorkInput(
            session_id=SESSION_ID,
            turn_id=uuid4(),
            sequence=1,
            transcript="Synthetic request.",
            document=store.create_document(SESSION_ID),
            prior_turns=(),
            controls=DeepWorkControls(),
        )

        with pytest.raises(DeepWorkFailure) as captured:
            await worker.run(work_input, CancellationToken())

        assert captured.value.error.code == "conflict"
        assert captured.value.error.retryable is False
        assert str(captured.value) == (
            "The Foundry conversation is unavailable. "
            "Start a new app session instead of retrying this conversation."
        )
        assert "provider.invalid" not in str(captured.value)

    asyncio.run(scenario())


def test_provider_session_identifier_mutation_is_treated_as_conversation_loss() -> None:
    class MutatingProvider(_FakeProvider):
        async def invoke(
            self,
            request: str,
            *,
            session: _FakeSession,
            tools: object,
        ) -> FoundryInvocation:
            invocation = await super().invoke(
                request,
                session=session,
                tools=tools,
            )
            session.service_session_id = "different-private-conversation"
            return invocation

    async def scenario() -> None:
        from backend.deep_work.base import DeepWorkControls, DeepWorkInput

        worker = FoundryDeepWorker(_settings(), provider=MutatingProvider())
        store = ConversationStore()
        store.create_session(SESSION_ID)
        work_input = DeepWorkInput(
            session_id=SESSION_ID,
            turn_id=uuid4(),
            sequence=1,
            transcript="Synthetic request.",
            document=store.create_document(SESSION_ID),
            prior_turns=(),
            controls=DeepWorkControls(),
        )

        with pytest.raises(DeepWorkFailure) as captured:
            await worker.run(work_input, CancellationToken())

        assert captured.value.error.code == "conflict"
        assert captured.value.error.retryable is False
        assert "different-private" not in str(captured.value)

    asyncio.run(scenario())


def test_cancellation_cancels_local_provider_wait() -> None:
    class BlockingProvider(_FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def invoke(
            self,
            request: str,
            *,
            session: _FakeSession,
            tools: object,
        ) -> FoundryInvocation:
            del request, session, tools
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def scenario() -> None:
        from backend.deep_work.base import DeepWorkControls, DeepWorkInput

        provider = BlockingProvider()
        worker = FoundryDeepWorker(_settings(), provider=provider)
        store = ConversationStore()
        store.create_session(SESSION_ID)
        work_input = DeepWorkInput(
            session_id=SESSION_ID,
            turn_id=uuid4(),
            sequence=1,
            transcript="Synthetic request.",
            document=store.create_document(SESSION_ID),
            prior_turns=(),
            controls=DeepWorkControls(),
        )
        cancellation = CancellationToken()
        task = asyncio.create_task(worker.run(work_input, cancellation))
        await provider.started.wait()
        cancellation.request()

        with pytest.raises(DeepWorkCancelled):
            await task
        assert provider.cancelled is True

    asyncio.run(scenario())


def test_outer_cancellation_gathers_invocation_and_cancellation_waits() -> None:
    class BlockingProvider(_FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.cancelled = False

        async def invoke(
            self,
            request: str,
            *,
            session: _FakeSession,
            tools: object,
        ) -> FoundryInvocation:
            del request, session, tools
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    class ObservedCancellation(CancellationToken):
        def __init__(self) -> None:
            super().__init__()
            self.wait_started = asyncio.Event()
            self.wait_cancelled = False

        async def wait(self) -> None:
            self.wait_started.set()
            try:
                await super().wait()
            finally:
                self.wait_cancelled = True

    async def scenario() -> None:
        provider = BlockingProvider()
        cancellation = ObservedCancellation()
        task = asyncio.create_task(
            _invoke_with_cancellation(
                provider,
                "synthetic-request",
                session=provider.session,
                tools=(),
                cancellation=cancellation,
            )
        )
        await provider.started.wait()
        await cancellation.wait_started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert provider.cancelled is True
        assert cancellation.wait_cancelled is True

    asyncio.run(scenario())


def test_cancellation_before_run_never_creates_provider_conversation() -> None:
    async def scenario() -> None:
        from backend.deep_work.base import DeepWorkControls, DeepWorkInput

        provider = _FakeProvider()
        worker = FoundryDeepWorker(_settings(), provider=provider)
        store = ConversationStore()
        store.create_session(SESSION_ID)
        cancellation = CancellationToken()
        cancellation.request()

        with pytest.raises(DeepWorkCancelled):
            await worker.run(
                DeepWorkInput(
                    session_id=SESSION_ID,
                    turn_id=uuid4(),
                    sequence=1,
                    transcript="Synthetic request.",
                    document=store.create_document(SESSION_ID),
                    prior_turns=(),
                    controls=DeepWorkControls(),
                ),
                cancellation,
            )

        assert provider.create_count == 0
        assert provider.invocation_sessions == []

    asyncio.run(scenario())


def test_cancellation_during_conversation_creation_prevents_provider_invoke() -> None:
    class DelayedConversationProvider(_FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.creation_started = asyncio.Event()
            self.release_creation = asyncio.Event()

        async def create_conversation(self, *, tools: object) -> _FakeSession:
            self.create_count += 1
            assert {tool.__name__ for tool in tools} == EXPECTED_LOCAL_TOOL_NAMES
            self.creation_started.set()
            await self.release_creation.wait()
            return self.session

    async def scenario() -> None:
        from backend.deep_work.base import DeepWorkControls, DeepWorkInput

        provider = DelayedConversationProvider()
        worker = FoundryDeepWorker(_settings(), provider=provider)
        store = ConversationStore()
        store.create_session(SESSION_ID)
        cancellation = CancellationToken()
        task = asyncio.create_task(
            worker.run(
                DeepWorkInput(
                    session_id=SESSION_ID,
                    turn_id=uuid4(),
                    sequence=1,
                    transcript="Synthetic request.",
                    document=store.create_document(SESSION_ID),
                    prior_turns=(),
                    controls=DeepWorkControls(),
                ),
                cancellation,
            )
        )
        await provider.creation_started.wait()
        cancellation.request()
        provider.release_creation.set()

        with pytest.raises(DeepWorkCancelled):
            await task
        assert provider.create_count == 1
        assert provider.invocation_sessions == []

    asyncio.run(scenario())


def test_deterministic_startup_does_not_import_foundry_sdk() -> None:
    code = """
import importlib.abc
import sys
class BlockFoundry(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith(('agent_framework', 'azure.ai.projects', 'backend.deep_work.foundry')):
            raise AssertionError(fullname)
        return None
sys.meta_path.insert(0, BlockFoundry())
from backend.main import create_app
app = create_app(environ={})
assert app.state.settings.agent_provider.value == 'deterministic'
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
