"""Agent Framework adapter for an existing versioned Prompt Agent."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
)

from backend.azure_identity import create_default_async_credential
from backend.config import ConfigurationError, Settings
from backend.deep_work.base import (
    CancellationToken,
    DeepWorkCancelled,
    DeepWorkFailure,
    DeepWorkInput,
    DeepWorkOutput,
)
from backend.domain.models import (
    DocumentVersion,
    DeepWorkCompletion,
    NoOpRecord,
    OpportunityDocument,
    ProviderMetadata,
    SanitizedError,
)
from backend.tools import (
    PATCH_PROPOSAL_TOOL_NAME,
    PROJECT_CONTEXT_TOOL_NAME,
    PatchProposalCapture,
    create_patch_proposal_tool,
    create_project_context_tool,
    load_synthetic_project_context,
)

FOUNDRY_CONTRACT_VERSION = "1.0.0"
FOUNDRY_INSTRUCTION_MARKERS = (
    f"DCR_DEEP_WORK_CONTRACT_VERSION: {FOUNDRY_CONTRACT_VERSION}",
    "PROJECT_CONTEXT_TOOL: project_context",
    "PATCH_PROPOSAL_TOOL: propose_document_patch",
    "COMPLETION_SUMMARY_CONTRACT: strict-json-v1",
)
EXPECTED_LOCAL_TOOL_NAMES = frozenset(
    {PROJECT_CONTEXT_TOOL_NAME, PATCH_PROPOSAL_TOOL_NAME}
)
MAX_PROVIDER_INPUT_BYTES = 65_536
MAX_COMPLETION_SUMMARY_BYTES = 2_048
_LOCAL_TOOL_SCHEMA_WARNING = "Foundry agent '%s' was provided tools"
_FRAMEWORK_LOGGER = logging.getLogger("agent_framework.foundry")

LocalTool = Callable[..., object]
CompletionClaim = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]


class FoundryCompatibilityError(RuntimeError):
    """Sanitized Prompt Agent access or contract incompatibility."""


class FoundryConversationLostError(FoundryCompatibilityError):
    """Sanitized signal that an existing provider conversation no longer exists."""


class _ProviderIdentifierWarningFilter(logging.Filter):
    """Drop the known SDK warning that interpolates the private agent name."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.name == _FRAMEWORK_LOGGER.name
            and isinstance(record.msg, str)
            and record.msg.startswith(_LOCAL_TOOL_SCHEMA_WARNING)
        )


_FRAMEWORK_LOGGER.addFilter(_ProviderIdentifierWarningFilter())


class ProviderSession(Protocol):
    """Agent Framework session surface retained only in process memory."""

    service_session_id: object


@dataclass(frozen=True)
class FoundryCompatibility:
    """Content-free compatibility result for a configured agent version."""

    prompt_agent: bool
    instructions_compatible: bool
    local_tools_compatible: bool

    @property
    def compatible(self) -> bool:
        """Return whether the deployed definition matches this adapter contract."""

        return (
            self.prompt_agent
            and self.instructions_compatible
            and self.local_tools_compatible
        )


@dataclass(frozen=True)
class FoundryInvocation:
    """Provider response correlation and bounded completion-summary payload."""

    response_id: str | None
    completion_summary: str | None = None
    completion_summary_required: bool = True


class CompletionSummary(BaseModel):
    """Strict non-authoritative summary envelope returned after the patch tool."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
    ]
    document_version: Annotated[int, Field(ge=0)]
    no_op_reason: CompletionClaim | None = None
    claims: tuple[CompletionClaim, ...] = Field(default=(), max_length=8)
    remaining_uncertainties: tuple[CompletionClaim, ...] = Field(
        default=(),
        max_length=8,
    )


@dataclass(frozen=True)
class ResolvedPromptAgent:
    """Private in-memory selection of one existing Prompt Agent version."""

    name: str
    version: str
    details: object
    source: str


class FoundryProvider(Protocol):
    """Injectable provider boundary used by deterministic local fakes."""

    async def validate_compatibility(self) -> FoundryCompatibility:
        """Read the configured Prompt Agent definition without mutating it."""

    async def create_conversation(
        self,
        *,
        tools: Sequence[LocalTool],
    ) -> ProviderSession:
        """Create one service conversation for a new app-owned session."""

    async def invoke(
        self,
        request: str,
        *,
        session: ProviderSession,
        tools: Sequence[LocalTool],
    ) -> FoundryInvocation:
        """Invoke the configured agent in the existing service conversation."""


class AgentFrameworkFoundryProvider:
    """Own async Azure clients for one compatibility check or invocation."""

    def __init__(
        self,
        settings: Settings,
        *,
        credential_factory: Callable[[], object] | None = None,
    ) -> None:
        self._endpoint = _require_setting(settings.foundry_project_endpoint)
        self._agent_name = settings.foundry_agent_name
        self._agent_version = settings.foundry_agent_version
        tenant_id = _require_setting(settings.azure_tenant_id)
        self._credential_factory = credential_factory or (
            lambda: create_default_async_credential(tenant_id)
        )

    async def validate_compatibility(self) -> FoundryCompatibility:
        """Resolve, read, and classify one exact version without exposing it."""

        try:
            async with self._project_client() as client:
                selected = await resolve_prompt_agent(
                    client,
                    agent_name=self._agent_name,
                    agent_version=self._agent_version,
                )
        except Exception:
            raise FoundryCompatibilityError(
                "Foundry Prompt Agent access could not be verified."
            ) from None
        if selected is None:
            raise FoundryCompatibilityError(
                "No compatible existing Foundry Prompt Agent version was found."
            )
        self._agent_name = selected.name
        self._agent_version = selected.version
        return _classify_agent_definition(selected.details)

    async def create_conversation(
        self,
        *,
        tools: Sequence[LocalTool],
    ) -> ProviderSession:
        """Create one explicit Foundry conversation through FoundryAgent."""

        del tools
        try:
            async with self._agent(()) as agent:
                return await agent.create_conversation()
        except Exception:
            raise FoundryCompatibilityError(
                "Foundry conversation creation failed."
            ) from None

    async def invoke(
        self,
        request: str,
        *,
        session: ProviderSession,
        tools: Sequence[LocalTool],
    ) -> FoundryInvocation:
        """Run one turn and return correlation only, never provider prose."""

        try:
            async with self._agent(tools) as agent:
                run_session = agent.get_session(
                    service_session_id=session.service_session_id
                )
                result = await agent.run(request, session=run_session)
                if not _patch_tool_attempted(tools):
                    result = await agent.run(
                        _required_patch_retry(request),
                        session=run_session,
                    )
            if not _patch_tool_attempted(tools):
                raise ValueError("The hosted agent omitted the required patch call.")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if _is_conversation_missing(error):
                raise FoundryConversationLostError(
                    "The Foundry conversation is unavailable."
                ) from None
            raise FoundryCompatibilityError(
                "Foundry invocation failed."
            ) from None
        response_id = getattr(result, "response_id", None)
        return FoundryInvocation(
            response_id=response_id if isinstance(response_id, str) else None,
            completion_summary=None,
            completion_summary_required=False,
        )

    @asynccontextmanager
    async def _project_client(self) -> AsyncIterator[object]:
        from azure.ai.projects.aio import AIProjectClient

        credential = self._credential_factory()
        async with credential:
            async with AIProjectClient(
                endpoint=self._endpoint,
                credential=credential,
            ) as project_client:
                yield project_client

    @asynccontextmanager
    async def _agent(
        self,
        tools: Sequence[LocalTool],
    ) -> AsyncIterator[object]:
        from agent_framework.foundry import FoundryAgent
        from azure.ai.projects.aio import AIProjectClient

        agent_name, agent_version = self._resolved_agent()
        credential = self._credential_factory()
        async with credential:
            async with AIProjectClient(
                endpoint=self._endpoint,
                credential=credential,
            ) as project_client:
                agent = FoundryAgent(
                    project_client=project_client,
                    agent_name=agent_name,
                    agent_version=agent_version,
                    tools=tuple(tools),
                    function_invocation_configuration={
                        "max_iterations": 3,
                        "max_function_calls": 2,
                        "max_consecutive_errors_per_request": 1,
                        "terminate_on_unknown_calls": True,
                    },
                    timeout=120.0,
                )
                async with agent:
                    yield agent

    def _resolved_agent(self) -> tuple[str, str]:
        if self._agent_name is None or self._agent_version is None:
            raise FoundryCompatibilityError(
                "Foundry Prompt Agent compatibility was not verified."
            )
        return self._agent_name, self._agent_version


class FoundryDeepWorker:
    """Adapt one app-owned deep turn to one stable Foundry conversation."""

    def __init__(
        self,
        settings: Settings,
        *,
        provider: FoundryProvider | None = None,
        project_context: Mapping[str, JsonValue] | None = None,
    ) -> None:
        self._provider = provider or AgentFrameworkFoundryProvider(settings)
        self._project_context = dict(
            project_context
            if project_context is not None
            else load_synthetic_project_context()
        )
        self._sessions: dict[UUID, ProviderSession] = {}
        self._lost_sessions: set[UUID] = set()
        self._session_lock = asyncio.Lock()

    async def validate_compatibility(self) -> None:
        """Fail startup when the configured Prompt Agent contract is incompatible."""

        try:
            compatibility = await self._provider.validate_compatibility()
        except Exception:
            raise ConfigurationError(
                compatibility_errors=(
                    "Foundry Prompt Agent access could not be verified",
                )
            ) from None
        if not compatibility.compatible:
            raise ConfigurationError(
                compatibility_errors=(
                    "Foundry Prompt Agent contract mismatch",
                )
            )

    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        """Run a bounded request using request-scoped local tool implementations."""

        cancellation.raise_if_cancelled()
        capture = PatchProposalCapture()
        tools: tuple[LocalTool, ...] = (
            create_project_context_tool(self._project_context),
            create_patch_proposal_tool(work_input, capture, cancellation),
        )
        session = await self._session_for(work_input.session_id, tools)
        cancellation.raise_if_cancelled()
        conversation_id = _conversation_id(session)
        if conversation_id is None:
            self._lost_sessions.add(work_input.session_id)
            raise _conversation_lost()

        request = _build_request(work_input, self._project_context)
        try:
            invocation = await _invoke_with_cancellation(
                self._provider,
                request,
                session=session,
                tools=tools,
                cancellation=cancellation,
            )
            cancellation.raise_if_cancelled()
            if _conversation_id(session) != conversation_id:
                self._lost_sessions.add(work_input.session_id)
                raise _conversation_lost()
            proposal, staged_result = capture.require_exactly_one()
            completion = (
                _validate_completion_summary(
                    invocation.completion_summary,
                    staged_result,
                    capture.staged_document,
                )
                if invocation.completion_summary_required
                else _app_owned_completion(staged_result)
            )
            cancellation.raise_if_cancelled()
            metadata = ProviderMetadata(
                conversation_id=conversation_id,
                response_id=invocation.response_id,
            )
        except DeepWorkCancelled:
            raise
        except DeepWorkFailure:
            raise
        except FoundryConversationLostError:
            self._lost_sessions.add(work_input.session_id)
            raise _conversation_lost() from None
        except (LookupError, ValidationError, ValueError):
            raise _tool_contract_failure() from None
        except Exception:
            raise _provider_failure() from None

        return DeepWorkOutput(
            proposal=proposal.model_dump(mode="json", by_alias=True),
            provider_metadata=metadata,
            completion=completion,
        )

    async def _session_for(
        self,
        session_id: UUID,
        tools: Sequence[LocalTool],
    ) -> ProviderSession:
        async with self._session_lock:
            if session_id in self._lost_sessions:
                raise _conversation_lost()
            session = self._sessions.get(session_id)
            if session is not None:
                if _conversation_id(session) is None:
                    self._lost_sessions.add(session_id)
                    raise _conversation_lost()
                return session
            try:
                session = await self._provider.create_conversation(tools=tools)
            except Exception:
                # Creation may have succeeded remotely before the response failed.
                # Tombstone the app session rather than risk creating a second
                # business conversation on a later turn.
                self._lost_sessions.add(session_id)
                raise _provider_failure() from None
            if _conversation_id(session) is None:
                self._lost_sessions.add(session_id)
                raise _conversation_lost()
            self._sessions[session_id] = session
            return session


async def _invoke_with_cancellation(
    provider: FoundryProvider,
    request: str,
    *,
    session: ProviderSession,
    tools: Sequence[LocalTool],
    cancellation: CancellationToken,
) -> FoundryInvocation:
    invocation_task = asyncio.create_task(
        provider.invoke(request, session=session, tools=tools)
    )
    cancellation_task = asyncio.create_task(cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            {invocation_task, cancellation_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation_task in done or cancellation.is_cancelled:
            invocation_task.cancel()
            await asyncio.gather(invocation_task, return_exceptions=True)
            raise DeepWorkCancelled("Deep work was cancelled.")
        return await invocation_task
    finally:
        for task in (invocation_task, cancellation_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            invocation_task,
            cancellation_task,
            return_exceptions=True,
        )


def _build_request(
    work_input: DeepWorkInput,
    project_context: Mapping[str, JsonValue],
) -> str:
    payload = {
        "contractVersion": FOUNDRY_CONTRACT_VERSION,
        "appCorrelation": {
            "sessionId": str(work_input.session_id),
            "turnId": str(work_input.turn_id),
            "documentId": str(work_input.document.document_id),
        },
        "baseVersion": work_input.document.version,
        "requiredAction": {
            "tool": "propose_document_patch",
            "exactCallCount": 1,
            "directAnswerAllowed": False,
        },
        "userRequest": work_input.transcript,
        "syntheticProjectContext": dict(project_context),
        "latestCanonicalDocument": work_input.document.model_dump(
            mode="json",
            by_alias=True,
        ),
        "priorTurns": [
            {
                "turnId": str(turn.turn_id),
                "sequence": turn.sequence,
                "userTranscript": turn.user_transcript,
                "documentStatus": turn.document_status,
                "documentVersion": turn.document_version,
            }
            for turn in work_input.prior_turns[-3:]
        ],
    }
    request = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(request.encode("utf-8")) > MAX_PROVIDER_INPUT_BYTES:
        raise _provider_failure()
    return request


def _patch_tool_attempted(tools: Sequence[LocalTool]) -> bool:
    return any(
        getattr(
            getattr(tool, "_dcr_patch_capture", None),
            "attempt_count",
            0,
        )
        > 0
        for tool in tools
    )


def _required_patch_retry(request: str) -> str:
    payload = json.loads(request)
    payload["retryReason"] = (
        "The prior response omitted the required patch call. "
        "Call propose_document_patch exactly once now; do not answer directly."
    )
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _validate_completion_summary(
    raw: str | None,
    result: DocumentVersion | NoOpRecord,
    staged_document: OpportunityDocument | None,
) -> DeepWorkCompletion:
    """Reject malformed or unsupported provider claims before canonical commit."""

    if raw is None or len(raw.encode("utf-8")) > MAX_COMPLETION_SUMMARY_BYTES:
        raise ValueError("The completion summary is missing or oversized.")
    summary = CompletionSummary.model_validate_json(raw)

    if isinstance(result, DocumentVersion):
        expected_version = result.document.version
        expected_summary = f"Updated the working document to version {expected_version}."
        document = result.document
        expected_no_op_reason = None
    else:
        expected_version = result.base_version
        expected_summary = "No document changes were needed."
        document = staged_document
        expected_no_op_reason = result.reason

    if (
        summary.document_version != expected_version
        or summary.summary != expected_summary
        or summary.no_op_reason != expected_no_op_reason
        or document is None
    ):
        raise ValueError("The completion summary is unsupported.")

    supported_claims = _canonical_claims(document)
    if any(_normalize_claim(claim) not in supported_claims for claim in summary.claims):
        raise ValueError("The completion summary contains an unsupported claim.")
    supported_uncertainties = _canonical_uncertainties(document)
    if (
        (
            supported_uncertainties
            and not summary.remaining_uncertainties
        )
        or any(
            _normalize_claim(claim) not in supported_uncertainties
            for claim in summary.remaining_uncertainties
        )
    ):
        raise ValueError(
            "The completion summary contains unsupported remaining uncertainty."
        )
    return DeepWorkCompletion(
        outcome="committed" if isinstance(result, DocumentVersion) else "no_op",
        summary=summary.summary,
        document_version=summary.document_version,
        no_op_reason=summary.no_op_reason,
    )


def _app_owned_completion(
    result: DocumentVersion | NoOpRecord,
) -> DeepWorkCompletion:
    """Build the authoritative completion after one manually dispatched tool call."""

    if isinstance(result, DocumentVersion):
        version = result.document.version
        return DeepWorkCompletion(
            outcome="committed",
            summary=f"Updated the working document to version {version}.",
            document_version=version,
        )
    return DeepWorkCompletion(
        outcome="no_op",
        summary="No document changes were needed.",
        document_version=result.base_version,
        no_op_reason=result.reason,
    )


def _canonical_claims(document: OpportunityDocument) -> frozenset[str]:
    """Return exact normalized canonical claim text allowed in a summary envelope."""

    scalar_claims = (
        document.customer_goal,
        document.current_situation,
        document.opportunity_hypothesis,
        document.expected_value,
        document.confidence_and_rationale,
    )
    list_claims = (
        *document.supporting_signals,
        *document.stakeholders,
        *document.assumptions_and_uncertainties,
        *document.missing_evidence,
        *document.recommended_next_actions,
    )
    return frozenset(
        _normalize_claim(item.text)
        for item in (*scalar_claims, *list_claims)
        if item is not None
    )


def _canonical_uncertainties(document: OpportunityDocument) -> frozenset[str]:
    """Return exact normalized unresolved items that provider summaries may cite."""

    return frozenset(
        _normalize_claim(item.text)
        for item in (
            *document.assumptions_and_uncertainties,
            *document.missing_evidence,
        )
    )


def _normalize_claim(value: str) -> str:
    return " ".join(value.split()).casefold()


def _classify_agent_definition(details: object) -> FoundryCompatibility:
    definition = _value(details, "definition")
    kind = _value(definition, "kind")
    instructions = _value(definition, "instructions")
    tools = _value(definition, "tools")
    tool_contract = _declared_local_tools(tools)
    return FoundryCompatibility(
        prompt_agent=str(kind).lower() == "prompt",
        instructions_compatible=(
            isinstance(instructions, str)
            and all(marker in instructions for marker in FOUNDRY_INSTRUCTION_MARKERS)
        ),
        local_tools_compatible=tool_contract == EXPECTED_LOCAL_TOOL_NAMES,
    )


async def resolve_prompt_agent(
    client: object,
    *,
    agent_name: str | None,
    agent_version: str | None,
) -> ResolvedPromptAgent | None:
    """Resolve only an existing compatible version through read-only project APIs."""

    agents = getattr(client, "agents")
    if agent_name is not None and agent_version is not None:
        details = await agents.get_version(
            agent_name=agent_name,
            agent_version=agent_version,
        )
        return ResolvedPromptAgent(
            name=agent_name,
            version=agent_version,
            details=details,
            source="configured",
        )

    inspected_versions = 0
    candidates = agents.list(kind="prompt", limit=100, order="desc")
    async for candidate in candidates:
        name = _bounded_identifier(_value(candidate, "name"))
        if name is None:
            continue
        versions = agents.list_versions(
            name,
            limit=100,
            order="desc",
            include_drafts=False,
        )
        async for candidate_version in versions:
            if inspected_versions >= 100:
                return None
            inspected_versions += 1
            version = _bounded_identifier(_value(candidate_version, "version"))
            if version is None:
                continue
            try:
                details = await agents.get_version(
                    agent_name=name,
                    agent_version=version,
                )
            except Exception:
                # A listed version can disappear or be unreadable during enumeration.
                # Continue without surfacing its identifier or provider error.
                continue
            if _classify_agent_definition(details).compatible:
                return ResolvedPromptAgent(
                    name=name,
                    version=version,
                    details=details,
                    source="discovered",
                )
    return None


def _declared_local_tools(value: object) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return frozenset()
    names: set[str] = set()
    for item in value:
        tool_type = _value(item, "type")
        name = _value(item, "name")
        if str(tool_type).lower() != "function" or not isinstance(name, str):
            return frozenset()
        if name in names:
            return frozenset()
        names.add(name)
    return frozenset(names)


def _value(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _bounded_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if 0 < len(value) <= 256 and value.isprintable() else None


def _conversation_id(session: ProviderSession) -> str | None:
    value = getattr(session, "service_session_id", None)
    if isinstance(value, str):
        return value if 0 < len(value) <= 256 else None
    nested = getattr(value, "id", None)
    return nested if isinstance(nested, str) and 0 < len(nested) <= 256 else None


def _is_conversation_missing(error: Exception) -> bool:
    return getattr(error, "status_code", None) in {404, 410}


def _require_setting(value: str | None) -> str:
    if value is None:
        raise ConfigurationError(
            compatibility_errors=("Foundry settings were not retained",)
        )
    return value


def _provider_failure() -> DeepWorkFailure:
    return DeepWorkFailure(
        SanitizedError(
            code="internal_error",
            category="document",
            message=(
                "Foundry deep work could not complete. "
                "Verify compatible agent access, then retry."
            ),
            retryable=True,
        )
    )


def _tool_contract_failure() -> DeepWorkFailure:
    return DeepWorkFailure(
        SanitizedError(
            code="validation_error",
            category="document",
            message=(
                "Foundry output did not satisfy the patch and completion-summary "
                "contract. The canonical document was not changed."
            ),
            retryable=False,
        )
    )


def _conversation_lost() -> DeepWorkFailure:
    return DeepWorkFailure(
        SanitizedError(
            code="conflict",
            category="document",
            message=(
                "The Foundry conversation is unavailable. "
                "Start a new app session instead of retrying this conversation."
            ),
            retryable=False,
        )
    )
