"""Strict commands and complete transport-neutral application event union."""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, TypeAdapter, ValidationError

from backend.domain.models import (
    CancellationPhase,
    DeepWorkCompletion,
    DocumentPatchProposal,
    DocumentResultStatus,
    OpportunityDocument,
    SanitizedError,
    ShortText,
    VoiceStatus,
    WireModel,
)

MAX_WIRE_BYTES = 65_536


class ContractValidationError(ValueError):
    """Sanitized failure for an unknown, mistyped, or oversized wire payload."""


class CommandBase(WireModel):
    """App-owned command identity and correlation."""

    command_id: UUID
    idempotency_key: UUID
    session_id: UUID
    timestamp: AwareDatetime


class TurnSubmitCommand(CommandBase):
    """Submit a typed or final voice transcript as one logical turn."""

    type: Literal["turn.submit"]
    turn_id: UUID
    input_mode: Literal["typed", "voice"]
    transcript: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)
    ]


class TurnCancelCommand(CommandBase):
    """Request cancellation of one accepted deep turn."""

    type: Literal["turn.cancel"]
    turn_id: UUID
    reason: ShortText


class VoiceInterruptCommand(CommandBase):
    """Stop current local playback without implying deep-work cancellation."""

    type: Literal["voice.interrupt"]
    turn_id: UUID
    reason: Literal["barge_in", "user_stop"]


class VoiceStartCommand(CommandBase):
    """Record browser-observed acknowledgment playback for an accepted voice turn."""

    type: Literal["voice.start"]
    turn_id: UUID


class VoiceAcknowledgmentCommand(CommandBase):
    """Record one constrained non-authoritative acknowledgment."""

    type: Literal["voice.acknowledge"]
    turn_id: UUID
    intent_summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
    ]
    next_step: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
    ]


class VoiceCompleteCommand(CommandBase):
    """Record browser-observed completion of acknowledgment playback."""

    type: Literal["voice.complete"]
    turn_id: UUID


class DocumentRevertCommand(CommandBase):
    """Restore an earlier immutable document snapshot as a new version."""

    type: Literal["document.revert"]
    turn_id: UUID
    document_id: UUID
    target_version: Annotated[int, Field(ge=1)]
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]


AppCommand = Annotated[
    TurnSubmitCommand
    | TurnCancelCommand
    | VoiceInterruptCommand
    | VoiceStartCommand
    | VoiceAcknowledgmentCommand
    | VoiceCompleteCommand
    | DocumentRevertCommand,
    Field(discriminator="type"),
]


class EventBase(WireModel):
    """App-owned event identity, correlation, and timestamp."""

    event_id: UUID
    idempotency_key: UUID
    session_id: UUID
    turn_id: UUID
    timestamp: AwareDatetime


class TurnStartedEvent(EventBase):
    type: Literal["turn.started"]
    sequence: Annotated[int, Field(ge=1)]
    input_mode: Literal["typed", "voice"]


class TurnQueuedEvent(EventBase):
    type: Literal["turn.queued"]
    position: Annotated[int, Field(ge=1, le=3)]
    depends_on_turn_id: UUID | None = None


class TurnRejectedEvent(EventBase):
    type: Literal["turn.rejected"]
    reason: ShortText
    queue_depth: Annotated[int, Field(ge=0, le=4)]
    error: SanitizedError


class TurnAnalysisStartedEvent(EventBase):
    type: Literal["turn.analysis.started"]
    base_document_version: Annotated[int, Field(ge=0)]


class TurnAnalysisCancellingEvent(EventBase):
    type: Literal["turn.analysis.cancelling"]


class TurnAnalysisCancelledEvent(EventBase):
    type: Literal["turn.analysis.cancelled"]
    phase: CancellationPhase


class TurnAnalysisCompletedEvent(EventBase, DeepWorkCompletion):
    """Validated provider completion metadata that never replaces the document."""

    type: Literal["turn.analysis.completed"]


class VoiceStartedEvent(EventBase):
    type: Literal["voice.started"]


class VoiceAcknowledgmentEvent(EventBase):
    type: Literal["voice.acknowledgment"]
    intent_summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
    ]
    next_step: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
    ]


class VoiceInterruptedEvent(EventBase):
    type: Literal["voice.interrupted"]
    reason: Literal["barge_in", "user_stop", "playback_error"]


class VoiceCompletedEvent(EventBase):
    type: Literal["voice.completed"]


class DocumentPendingEvent(EventBase):
    type: Literal["document.pending"]
    document_id: UUID
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ]


class DocumentCreatedEvent(EventBase):
    type: Literal["document.created"]
    document_id: UUID
    version: Annotated[int, Field(ge=1)]
    document: OpportunityDocument
    markdown_projection: Annotated[str, StringConstraints(max_length=16_000)]
    source_labels: tuple[Annotated[str, StringConstraints(min_length=1, max_length=120)], ...] = Field(
        default=(), max_length=16
    )

    def model_post_init(self, __context: object) -> None:
        if self.document_id != self.document.document_id or self.version != self.document.version:
            raise ValueError("Document event correlation is invalid.")


class DocumentPatchEvent(EventBase):
    type: Literal["document.patch"]
    document_id: UUID
    base_version: Annotated[int, Field(ge=0)]
    version: Annotated[int, Field(ge=1)]
    patch: DocumentPatchProposal

    def model_post_init(self, __context: object) -> None:
        if (
            self.document_id != self.patch.document_id
            or self.base_version != self.patch.base_version
            or self.turn_id != self.patch.turn_id
            or self.session_id != self.patch.session_id
            or self.version != self.base_version + 1
        ):
            raise ValueError("Patch event correlation is invalid.")


class DocumentCommittedEvent(EventBase):
    type: Literal["document.committed"]
    document_id: UUID
    version: Annotated[int, Field(ge=1)]
    document: OpportunityDocument
    markdown_projection: Annotated[str, StringConstraints(max_length=16_000)]
    source_labels: tuple[Annotated[str, StringConstraints(min_length=1, max_length=120)], ...] = Field(
        default=(), max_length=16
    )
    restored_from_version: Annotated[int, Field(ge=1)] | None = None

    def model_post_init(self, __context: object) -> None:
        if self.document_id != self.document.document_id or self.version != self.document.version:
            raise ValueError("Document event correlation is invalid.")


class DocumentFailedEvent(EventBase):
    type: Literal["document.failed"]
    document_id: UUID
    error: SanitizedError


class TurnTimings(WireModel):
    """Content-free elapsed durations in milliseconds."""

    acknowledgment_ms: Annotated[int, Field(ge=0, le=86_400_000)] | None = None
    document_ms: Annotated[int, Field(ge=0, le=86_400_000)] | None = None
    total_ms: Annotated[int, Field(ge=0, le=86_400_000)]


class TurnCompletedEvent(EventBase):
    type: Literal["turn.completed"]
    audio_status: VoiceStatus
    document_status: DocumentResultStatus
    timings: TurnTimings


AppEvent = Annotated[
    TurnStartedEvent
    | TurnQueuedEvent
    | TurnRejectedEvent
    | TurnAnalysisStartedEvent
    | TurnAnalysisCancellingEvent
    | TurnAnalysisCancelledEvent
    | TurnAnalysisCompletedEvent
    | VoiceStartedEvent
    | VoiceAcknowledgmentEvent
    | VoiceInterruptedEvent
    | VoiceCompletedEvent
    | DocumentPendingEvent
    | DocumentCreatedEvent
    | DocumentPatchEvent
    | DocumentCommittedEvent
    | DocumentFailedEvent
    | TurnCompletedEvent,
    Field(discriminator="type"),
]

_COMMAND_ADAPTER = TypeAdapter(AppCommand)
_EVENT_ADAPTER = TypeAdapter(AppEvent)
_PATCH_ADAPTER = TypeAdapter(DocumentPatchProposal)


def _serialize_bounded(value: object) -> bytes:
    try:
        serialized = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractValidationError("Payload must be valid JSON.") from error
    if len(serialized) > MAX_WIRE_BYTES:
        raise ContractValidationError("Payload exceeds the application limit.")
    return serialized


def validate_command(value: object) -> AppCommand:
    """Validate a bounded command and fail closed on every unknown shape."""

    try:
        return _COMMAND_ADAPTER.validate_json(_serialize_bounded(value))
    except ValidationError as error:
        raise ContractValidationError("Command validation failed.") from error


def validate_event(value: object) -> AppEvent:
    """Validate a bounded event and fail closed on every unknown shape."""

    try:
        return _EVENT_ADAPTER.validate_json(_serialize_bounded(value))
    except ValidationError as error:
        raise ContractValidationError("Event validation failed.") from error


def validate_patch(value: object) -> DocumentPatchProposal:
    """Validate a bounded patch proposal with the same wire-size limit."""

    try:
        return _PATCH_ADAPTER.validate_json(_serialize_bounded(value))
    except ValidationError as error:
        raise ContractValidationError("Patch validation failed.") from error
