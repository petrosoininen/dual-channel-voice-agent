"""Process-memory conversation state with immutable records and empty startup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from threading import RLock
from uuid import UUID, uuid4

from backend.domain.events import AppEvent, validate_event
from backend.domain.models import (
    ConversationTurn,
    DocumentResultStatus,
    DocumentVersion,
    NoOpRecord,
    OpportunityDocument,
    ProviderMetadata,
    QueueStatus,
    VoiceStatus,
)


class ConversationNotFoundError(LookupError):
    """Raised when an app-owned session is not present in this process."""


class ConversationConflictError(RuntimeError):
    """Raised when a requested mutation conflicts with canonical state."""


@dataclass
class _ConversationState:
    session_id: UUID
    authorization_token: str = field(repr=False)
    turns: list[ConversationTurn] = field(default_factory=list)
    events: list[AppEvent] = field(default_factory=list)
    event_fingerprints: dict[UUID, str] = field(default_factory=dict)
    command_results: dict[UUID, DocumentVersion | NoOpRecord] = field(
        default_factory=dict
    )
    command_fingerprints: dict[UUID, str] = field(default_factory=dict)
    document: OpportunityDocument | None = None
    versions: list[DocumentVersion] = field(default_factory=list)
    no_ops: list[NoOpRecord] = field(default_factory=list)


class ConversationStore:
    """Own all ephemeral application state for one backend process."""

    def __init__(self) -> None:
        self._states: dict[UUID, _ConversationState] = {}
        self._lock = RLock()

    def create_session(self, session_id: UUID | None = None) -> UUID:
        """Create one empty app-owned conversation."""

        app_session_id = session_id or uuid4()
        with self._lock:
            if app_session_id in self._states:
                raise ConversationConflictError("Session already exists.")
            self._states[app_session_id] = _ConversationState(
                session_id=app_session_id,
                authorization_token=token_urlsafe(32),
            )
        return app_session_id

    def session_authorization_token(self, session_id: UUID) -> str:
        """Return the process-memory handshake token for the session creation response."""

        with self._lock:
            return self._require_state(session_id).authorization_token

    def authorize_session(self, session_id: UUID, authorization_token: str) -> bool:
        """Compare a presented handshake token without exposing the retained value."""

        with self._lock:
            state = self._require_state(session_id)
            return compare_digest(state.authorization_token, authorization_token)

    def session_count(self) -> int:
        """Return the number of process-memory conversations."""

        with self._lock:
            return len(self._states)

    def record_turn(self, session_id: UUID, turn: ConversationTurn) -> None:
        """Append one immutable accepted turn."""

        with self._lock:
            state = self._require_state(session_id)
            if turn.turn_id in {item.turn_id for item in state.turns}:
                raise ConversationConflictError("Turn already exists.")
            if turn.sequence != len(state.turns) + 1:
                raise ConversationConflictError("Turn sequence is not contiguous.")
            state.turns.append(turn)

    def turns(self, session_id: UUID) -> tuple[ConversationTurn, ...]:
        """Return immutable turn history."""

        with self._lock:
            return tuple(self._require_state(session_id).turns)

    def synchronize_turn(
        self,
        session_id: UUID,
        turn_id: UUID,
        *,
        queue_status: QueueStatus,
        voice_status: VoiceStatus,
        document_status: DocumentResultStatus,
        document_version: int | None,
    ) -> None:
        """Replace one immutable turn snapshot with its latest canonical statuses."""

        with self._lock:
            state = self._require_state(session_id)
            for index, turn in enumerate(state.turns):
                if turn.turn_id != turn_id:
                    continue
                state.turns[index] = turn.model_copy(
                    update={
                        "queue_status": queue_status,
                        "voice_status": voice_status,
                        "document_status": document_status,
                        "document_version": document_version,
                    }
                )
                return
            raise ConversationNotFoundError("Turn does not exist.")

    def record_provider_metadata(
        self,
        session_id: UUID,
        turn_id: UUID,
        metadata: ProviderMetadata,
    ) -> None:
        """Attach opaque provider correlation to one accepted in-memory turn."""

        with self._lock:
            state = self._require_state(session_id)
            for index, turn in enumerate(state.turns):
                if turn.turn_id != turn_id:
                    continue
                if turn.provider_metadata not in {None, metadata}:
                    raise ConversationConflictError(
                        "Provider correlation already differs for this turn."
                    )
                state.turns[index] = turn.model_copy(
                    update={"provider_metadata": metadata}
                )
                return
            raise ConversationNotFoundError("Turn does not exist.")

    def apply_event(self, value: object) -> bool:
        """Validate and record an event once by its app-owned event ID."""

        event = validate_event(value)
        fingerprint = sha256(
            event.model_dump_json(by_alias=True).encode("utf-8")
        ).hexdigest()
        with self._lock:
            state = self._require_state(event.session_id)
            prior = state.event_fingerprints.get(event.event_id)
            if prior is not None:
                if prior != fingerprint:
                    raise ConversationConflictError(
                        "Event identity was reused with different content."
                    )
                return False
            state.event_fingerprints[event.event_id] = fingerprint
            state.events.append(event)
            return True

    def events(self, session_id: UUID) -> tuple[AppEvent, ...]:
        """Return immutable event delivery history."""

        with self._lock:
            return tuple(self._require_state(session_id).events)

    def create_document(
        self,
        session_id: UUID,
        *,
        document_id: UUID | None = None,
        title: str = "Opportunity assessment",
    ) -> OpportunityDocument:
        """Create the conversation's sole canonical version-zero document."""

        with self._lock:
            state = self._require_state(session_id)
            if state.document is not None:
                raise ConversationConflictError(
                    "Conversation already has a canonical document."
                )
            state.document = OpportunityDocument(
                document_id=document_id or uuid4(),
                version=0,
                title=title,
                status="draft",
                customer_goal=None,
                current_situation=None,
                opportunity_hypothesis=None,
                supporting_signals=(),
                expected_value=None,
                stakeholders=(),
                assumptions_and_uncertainties=(),
                missing_evidence=(),
                recommended_next_actions=(),
                confidence_and_rationale=None,
            )
            return state.document

    def document(self, session_id: UUID) -> OpportunityDocument | None:
        """Return the canonical document projection, if created."""

        with self._lock:
            return self._require_state(session_id).document

    def versions(self, session_id: UUID) -> tuple[DocumentVersion, ...]:
        """Return immutable document version history."""

        with self._lock:
            return tuple(self._require_state(session_id).versions)

    def no_ops(self, session_id: UUID) -> tuple[NoOpRecord, ...]:
        """Return successful no-op history."""

        with self._lock:
            return tuple(self._require_state(session_id).no_ops)

    @contextmanager
    def transaction(self, session_id: UUID) -> Iterator[_ConversationState]:
        """Hold the process lock across one complete state transition."""

        with self._lock:
            yield self._require_state(session_id)

    def _require_state(self, session_id: UUID) -> _ConversationState:
        try:
            return self._states[session_id]
        except KeyError as error:
            raise ConversationNotFoundError("Conversation does not exist.") from error
