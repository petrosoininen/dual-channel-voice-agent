"""Immutable document, patch, turn, and status models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
ClaimText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
SummaryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
SourceLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class WireModel(BaseModel):
    """Strict immutable wire model with camel-case serialization."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class ClaimClassification(StrEnum):
    """Allowed provenance classification for every opportunity claim."""

    SYNTHETIC_EVIDENCE = "synthetic_evidence"
    INFERENCE = "inference"
    UNKNOWN = "unknown"


class DocumentStatus(StrEnum):
    """Refinement state for the opportunity document."""

    DRAFT = "draft"
    REFINING = "refining"
    READY_FOR_VALIDATION = "ready_for_validation"


class QueueStatus(StrEnum):
    """Bounded deep-work lifecycle states implemented by the ordered queue."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    RUNNING = "running"
    REJECTED = "rejected"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class CancellationPhase(StrEnum):
    """Point at which cancellation completed."""

    QUEUED = "queued"
    RUNNING = "running"


class VoiceStatus(StrEnum):
    """Independent voice-lane terminal state."""

    NOT_STARTED = "not_started"
    SPEAKING = "speaking"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class DocumentResultStatus(StrEnum):
    """Independent document-lane terminal state."""

    NOT_STARTED = "not_started"
    PENDING = "pending"
    COMMITTED = "committed"
    NO_OP = "no_op"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class SanitizedErrorCode(StrEnum):
    """Public error identities that never include provider details."""

    VALIDATION_ERROR = "validation_error"
    CONFLICT = "conflict"
    QUEUE_FULL = "queue_full"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class SanitizedErrorCategory(StrEnum):
    """Safe client-facing error categories."""

    COMMAND = "command"
    TURN = "turn"
    VOICE = "voice"
    DOCUMENT = "document"


class SanitizedError(WireModel):
    """Bounded client-visible error without exception or provider content."""

    code: SanitizedErrorCode
    category: SanitizedErrorCategory
    message: ShortText
    retryable: bool


class ClassifiedText(WireModel):
    """A claim and its explicit provenance."""

    text: ClaimText
    classification: ClaimClassification
    source_label: SourceLabel | None = None

    @model_validator(mode="after")
    def require_evidence_source(self) -> ClassifiedText:
        """Require a synthetic source label when a claim is marked as evidence."""

        if (
            self.classification is ClaimClassification.SYNTHETIC_EVIDENCE
            and self.source_label is None
        ):
            raise ValueError("Synthetic evidence requires a source label.")
        if (
            self.classification is not ClaimClassification.SYNTHETIC_EVIDENCE
            and self.source_label is not None
        ):
            raise ValueError("Only synthetic evidence may name a source label.")
        return self


class DocumentListItem(ClassifiedText):
    """Classified list item with an app-owned stable identity."""

    item_id: UUID


class OpportunityDocument(WireModel):
    """Canonical, bounded opportunity document projection."""

    document_id: UUID
    version: Annotated[int, Field(ge=0)]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    status: DocumentStatus
    customer_goal: ClassifiedText | None
    current_situation: ClassifiedText | None
    opportunity_hypothesis: ClassifiedText | None
    supporting_signals: tuple[DocumentListItem, ...] = Field(max_length=24)
    expected_value: ClassifiedText | None
    stakeholders: tuple[DocumentListItem, ...] = Field(max_length=16)
    assumptions_and_uncertainties: tuple[DocumentListItem, ...] = Field(max_length=24)
    missing_evidence: tuple[DocumentListItem, ...] = Field(max_length=24)
    recommended_next_actions: tuple[DocumentListItem, ...] = Field(max_length=24)
    confidence_and_rationale: ClassifiedText | None


ScalarField = Literal["title", "status"]
ClaimSection = Literal[
    "customerGoal",
    "currentSituation",
    "opportunityHypothesis",
    "expectedValue",
    "confidenceAndRationale",
]
ListSection = Literal[
    "supportingSignals",
    "stakeholders",
    "assumptionsAndUncertainties",
    "missingEvidence",
    "recommendedNextActions",
]


class OperationBase(WireModel):
    """Identity shared by semantic operations."""

    operation_id: UUID


class SetFieldOperation(OperationBase):
    """Set an allowlisted scalar field with field-specific validation."""

    op: Literal["set_field"]
    field: ScalarField
    value: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ]

    @model_validator(mode="after")
    def validate_field_value(self) -> SetFieldOperation:
        """Enforce the value type and enum for the selected field."""

        if self.field == "status":
            try:
                DocumentStatus(self.value)
            except ValueError as error:
                raise ValueError("Unknown document status.") from error
        return self


class ReplaceSectionOperation(OperationBase):
    """Replace one scalar claim section."""

    op: Literal["replace_section"]
    section: ClaimSection
    value: ClassifiedText


class AppendListItemOperation(OperationBase):
    """Append a classified value; the service creates the stable item ID."""

    op: Literal["append_list_item"]
    section: ListSection
    value: ClassifiedText


class UpdateListItemOperation(OperationBase):
    """Replace a known list item while preserving its stable ID."""

    op: Literal["update_list_item"]
    section: ListSection
    item_id: UUID
    value: ClassifiedText


class RemoveListItemOperation(OperationBase):
    """Remove a known list item by stable ID."""

    op: Literal["remove_list_item"]
    section: ListSection
    item_id: UUID


SemanticOperation = Annotated[
    SetFieldOperation
    | ReplaceSectionOperation
    | AppendListItemOperation
    | UpdateListItemOperation
    | RemoveListItemOperation,
    Field(discriminator="op"),
]


class DocumentPatchProposal(WireModel):
    """Complete atomic semantic patch proposal."""

    patch_id: UUID
    session_id: UUID
    turn_id: UUID
    document_id: UUID
    base_version: Annotated[int, Field(ge=0)]
    summary: SummaryText
    operations: tuple[SemanticOperation, ...] = Field(max_length=32)
    reason: ShortText | None = None

    @model_validator(mode="after")
    def validate_no_op_reason(self) -> DocumentPatchProposal:
        """Require a reason exactly when a proposal has no operations."""

        if not self.operations and self.reason is None:
            raise ValueError("A zero-operation proposal requires a reason.")
        if self.operations and self.reason is not None:
            raise ValueError("A reason is allowed only for a zero-operation proposal.")
        operation_ids = [operation.operation_id for operation in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Operation IDs must be unique within a proposal.")
        return self


class AppliedOperation(WireModel):
    """Immutable record of one applied semantic operation."""

    operation: SemanticOperation
    created_item_id: UUID | None = None


class DocumentDiff(WireModel):
    """Readable immutable change record for one committed version."""

    base_version: Annotated[int, Field(ge=0)]
    version: Annotated[int, Field(ge=1)]
    turn_id: UUID
    summary: SummaryText
    operations: tuple[AppliedOperation, ...] = Field(max_length=32)
    committed_at: AwareDatetime
    restored_from_version: Annotated[int, Field(ge=1)] | None = None


class DocumentVersion(WireModel):
    """Immutable full snapshot plus its diff metadata."""

    document: OpportunityDocument
    diff: DocumentDiff

    @model_validator(mode="after")
    def validate_version_correlation(self) -> DocumentVersion:
        """Require snapshot and diff version metadata to agree."""

        if self.document.version != self.diff.version:
            raise ValueError("Document snapshot version does not match its diff.")
        if self.diff.base_version >= self.diff.version:
            raise ValueError("Document base version must precede its version.")
        if self.diff.restored_from_version is not None and self.diff.operations:
            raise ValueError("A restoring version cannot contain semantic operations.")
        return self


class NoOpRecord(WireModel):
    """Successful deep turn that intentionally created no document version."""

    patch_id: UUID
    session_id: UUID
    turn_id: UUID
    document_id: UUID
    base_version: Annotated[int, Field(ge=0)]
    summary: SummaryText
    reason: ShortText
    status: Literal["succeeded"] = "succeeded"
    document_status: Literal["no_op"] = "no_op"
    recorded_at: AwareDatetime


class DeepWorkCompletion(WireModel):
    """Validated non-authoritative completion metadata for one deep turn."""

    outcome: Literal["committed", "no_op"]
    summary: ShortText
    document_version: Annotated[int, Field(ge=0)]
    no_op_reason: ShortText | None = None

    @model_validator(mode="after")
    def validate_no_op_metadata(self) -> DeepWorkCompletion:
        """Require a no-op reason only for successful no-op completion."""

        if self.outcome == "no_op" and self.no_op_reason is None:
            raise ValueError("A no-op completion requires a reason.")
        if self.outcome == "committed" and self.no_op_reason is not None:
            raise ValueError("A committed completion cannot include a no-op reason.")
        return self


class ProviderMetadata(WireModel):
    """Optional opaque provider correlation retained only in memory."""

    conversation_id: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None = None
    response_id: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None = None


class ConversationTurn(WireModel):
    """Immutable accepted-turn record."""

    turn_id: UUID
    sequence: Annotated[int, Field(ge=1)]
    user_transcript: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
    accepted_at: AwareDatetime
    queue_status: QueueStatus
    voice_status: VoiceStatus
    document_status: DocumentResultStatus
    document_version: Annotated[int, Field(ge=0)] | None = None
    provider_metadata: ProviderMetadata | None = None


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for app-owned records."""

    return datetime.now(UTC)
