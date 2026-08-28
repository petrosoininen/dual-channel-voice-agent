"""FIFO deep-work orchestration with bounded capacity and safe cancellation."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from time import monotonic
from uuid import UUID, uuid5

from pydantic import ValidationError

from backend.deep_work.base import (
    CancellationToken,
    DeepWorkCancelled,
    DeepWorkControlEnvironment,
    DeepWorkControls,
    DeepWorkFailure,
    DeepWorkInput,
    DeepWorkOutput,
    DeepWorker,
    validate_controls,
)
from backend.domain.events import (
    ContractValidationError,
    DocumentRevertCommand,
    TurnCancelCommand,
    TurnSubmitCommand,
    VoiceAcknowledgmentCommand,
    VoiceCompleteCommand,
    VoiceInterruptCommand,
    VoiceStartCommand,
    validate_command,
    validate_event,
    validate_patch,
)
from backend.domain.models import (
    ConversationTurn,
    DeepWorkCompletion,
    DocumentPatchProposal,
    DocumentResultStatus,
    DocumentVersion,
    NoOpRecord,
    OpportunityDocument,
    QueueStatus,
    SanitizedError,
    VoiceStatus,
    utc_now,
)
from backend.services.conversation_store import ConversationStore
from backend.services.patch_service import (
    PatchService,
    PatchValidationError,
    StaleDocumentVersionError,
)

MAX_PENDING_TASKS = 3
MAX_ACTIVE_TASKS = MAX_PENDING_TASKS + 1
EventSink = Callable[[object], bool]


class DeepWorkConflictError(RuntimeError):
    """Sanitized conflict for reused command or turn identities."""


@dataclass(frozen=True)
class SubmissionResult:
    """Immediate result of accepting, queueing, or rejecting a deep turn."""

    accepted: bool
    task_created: bool
    turn_id: UUID
    queue_position: int | None
    depends_on_turn_id: UUID | None
    input_available: bool
    error: SanitizedError | None = None


@dataclass(frozen=True)
class CancellationResult:
    """Immediate result of a queued or running cancellation request."""

    found: bool
    final: bool
    turn_id: UUID
    status: QueueStatus | None


@dataclass(frozen=True)
class TaskSnapshot:
    """Content-free observable state for one deep task."""

    turn_id: UUID
    status: QueueStatus
    document_status: DocumentResultStatus
    audio_status: VoiceStatus
    queue_position: int | None
    depends_on_turn_id: UUID | None
    base_document_version: int | None
    committed_document_version: int | None


@dataclass(frozen=True)
class EventDeliveryFailure:
    """Sanitized event-delivery diagnostic without payload or exception text."""

    turn_id: UUID
    event_type: str
    code: str = "event_delivery_failed"


@dataclass
class _TaskRecord:
    command: TurnSubmitCommand
    sequence: int
    controls: DeepWorkControls
    accepted_monotonic: float
    completion: asyncio.Future[TaskSnapshot]
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    status: QueueStatus = QueueStatus.ACCEPTED
    document_status: DocumentResultStatus = DocumentResultStatus.NOT_STARTED
    audio_status: VoiceStatus = VoiceStatus.NOT_STARTED
    depends_on_turn_id: UUID | None = None
    base_document_version: int | None = None
    committed_document_version: int | None = None
    document_started_monotonic: float | None = None


@dataclass
class _QueueState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: deque[_TaskRecord] = field(default_factory=deque)
    running: _TaskRecord | None = None
    runner: asyncio.Task[None] | None = None
    records: dict[UUID, _TaskRecord] = field(default_factory=dict)
    submit_results: dict[UUID, SubmissionResult] = field(default_factory=dict)
    submit_fingerprints: dict[UUID, str] = field(default_factory=dict)
    seen_turns: set[UUID] = field(default_factory=set)
    cancel_results: dict[UUID, CancellationResult] = field(default_factory=dict)
    cancel_fingerprints: dict[UUID, str] = field(default_factory=dict)
    voice_fingerprints: dict[UUID, str] = field(default_factory=dict)
    command_fingerprints: dict[UUID, str] = field(default_factory=dict)
    idempotency_fingerprints: dict[UUID, str] = field(default_factory=dict)


class DeepWorkService:
    """Serialize dependent deep work independently for every conversation."""

    def __init__(
        self,
        *,
        store: ConversationStore,
        patch_service: PatchService,
        worker: DeepWorker,
        control_environment: DeepWorkControlEnvironment = (
            DeepWorkControlEnvironment.PRODUCTION
        ),
        event_sink: EventSink | None = None,
    ) -> None:
        self._store = store
        self._patch_service = patch_service
        self._worker = worker
        self._control_environment = control_environment
        self._event_sink = event_sink or store.apply_event
        self._queues: dict[UUID, _QueueState] = {}
        self._delivery_failures: list[EventDeliveryFailure] = []
        self._closed = False

    async def submit(
        self,
        value: object,
        *,
        controls: DeepWorkControls | None = None,
    ) -> SubmissionResult:
        """Accept at most one running and three pending tasks per conversation."""

        if self._closed:
            raise DeepWorkConflictError("Deep work is shutting down.")
        command = _require_submit(value)
        selected_controls = controls or DeepWorkControls()
        validate_controls(
            selected_controls,
            environment=self._control_environment,
        )
        state = self._queues.setdefault(command.session_id, _QueueState())
        fingerprint = _fingerprint(command)
        async with state.lock:
            if self._closed:
                raise DeepWorkConflictError("Deep work is shutting down.")
            _guard_command_identity(state, command, fingerprint)
            prior = state.submit_results.get(command.idempotency_key)
            if prior is not None:
                if state.submit_fingerprints[command.idempotency_key] != fingerprint:
                    raise DeepWorkConflictError(
                        "Submit identity was reused with different content."
                    )
                return prior
            if command.turn_id in state.seen_turns:
                raise DeepWorkConflictError("Turn identity was already used.")

            active_count = len(state.pending) + int(state.running is not None)
            if state.running is None and state.pending:
                active_count = len(state.pending)
            if active_count >= MAX_ACTIVE_TASKS:
                result = self._reject_submission(
                    command,
                    sequence=len(self._store.turns(command.session_id)) + 1,
                    queue_depth=active_count,
                )
                self._remember_submission(state, command, fingerprint, result)
                return result

            if self._store.document(command.session_id) is None:
                self._store.create_document(command.session_id)
            document = self._store.document(command.session_id)

            queue_position = _new_queue_position(state)
            depends_on_turn_id = _tail_turn_id(state)
            completion: asyncio.Future[TaskSnapshot] = (
                asyncio.get_running_loop().create_future()
            )
            record = _TaskRecord(
                command=command,
                sequence=len(self._store.turns(command.session_id)) + 1,
                controls=selected_controls,
                accepted_monotonic=monotonic(),
                completion=completion,
                status=(
                    QueueStatus.QUEUED
                    if queue_position is not None
                    else QueueStatus.ACCEPTED
                ),
                audio_status=(
                    VoiceStatus.FAILED
                    if selected_controls.audio_lane_failure
                    else VoiceStatus.NOT_STARTED
                ),
                depends_on_turn_id=depends_on_turn_id,
            )
            self._store.record_turn(
                command.session_id,
                ConversationTurn(
                    turn_id=command.turn_id,
                    sequence=record.sequence,
                    user_transcript=command.transcript,
                    accepted_at=utc_now(),
                    queue_status=record.status,
                    voice_status=record.audio_status,
                    document_status=record.document_status,
                    document_version=document.version if document is not None else None,
                ),
            )
            state.pending.append(record)
            state.records[command.turn_id] = record
            result = SubmissionResult(
                accepted=True,
                task_created=True,
                turn_id=command.turn_id,
                queue_position=queue_position,
                depends_on_turn_id=depends_on_turn_id,
                input_available=True,
            )
            self._remember_submission(state, command, fingerprint, result)
            self._emit(
                command.session_id,
                command.turn_id,
                "turn.started",
                sequence=record.sequence,
                inputMode=command.input_mode,
            )
            if queue_position is not None:
                self._emit(
                    command.session_id,
                    command.turn_id,
                    "turn.queued",
                    position=queue_position,
                    dependsOnTurnId=(
                        str(depends_on_turn_id)
                        if depends_on_turn_id is not None
                        else None
                    ),
                )
            if state.runner is None or state.runner.done():
                state.runner = asyncio.create_task(
                    self._drain(command.session_id, state),
                    name=f"deep-work-{command.session_id}",
                )
            return result

    async def cancel(self, value: object) -> CancellationResult:
        """Cancel queued work immediately or signal the running producer."""

        command = _require_cancel(value)
        state = self._queues.setdefault(command.session_id, _QueueState())
        fingerprint = _fingerprint(command)
        async with state.lock:
            _guard_command_identity(state, command, fingerprint)
            prior = state.cancel_results.get(command.idempotency_key)
            if prior is not None:
                if state.cancel_fingerprints[command.idempotency_key] != fingerprint:
                    raise DeepWorkConflictError(
                        "Cancellation identity was reused with different content."
                    )
                return prior

            record = state.records.get(command.turn_id)
            if record is None:
                result = CancellationResult(
                    found=False,
                    final=True,
                    turn_id=command.turn_id,
                    status=None,
                )
            elif record in state.pending:
                state.pending.remove(record)
                record.cancellation.request()
                self._finalize_cancelled(
                    command.session_id,
                    record,
                    phase="queued",
                )
                result = CancellationResult(
                    found=True,
                    final=True,
                    turn_id=command.turn_id,
                    status=QueueStatus.CANCELLED,
                )
            elif state.running is record and record.status is QueueStatus.RUNNING:
                record.status = QueueStatus.CANCELLING
                record.cancellation.request()
                self._synchronize_turn(command.session_id, record)
                self._emit(
                    command.session_id,
                    command.turn_id,
                    "turn.analysis.cancelling",
                )
                result = CancellationResult(
                    found=True,
                    final=False,
                    turn_id=command.turn_id,
                    status=QueueStatus.CANCELLING,
                )
            else:
                result = CancellationResult(
                    found=True,
                    final=record.status is not QueueStatus.CANCELLING,
                    turn_id=command.turn_id,
                    status=record.status,
                )
            state.cancel_fingerprints[command.idempotency_key] = fingerprint
            state.cancel_results[command.idempotency_key] = result
            _remember_command_identity(state, command, fingerprint)
            return result

    async def start_voice(self, value: object) -> bool:
        """Record browser-observed acknowledgment playback start."""

        command = _require_voice_start(value)
        return await self._apply_voice_transition(
            command,
            status=VoiceStatus.SPEAKING,
            event_type="voice.started",
        )

    async def acknowledge_voice(self, value: object) -> bool:
        """Record a constrained acknowledgment correlated to its accepted turn."""

        command = _require_voice_acknowledgment(value)
        return await self._apply_voice_transition(
            command,
            status=VoiceStatus.SPEAKING,
            event_type="voice.acknowledgment",
            intentSummary=command.intent_summary,
            nextStep=command.next_step,
        )

    async def complete_voice(self, value: object) -> bool:
        """Record browser-observed terminal acknowledgment completion."""

        command = _require_voice_complete(value)
        return await self._apply_voice_transition(
            command,
            status=VoiceStatus.COMPLETED,
            event_type="voice.completed",
        )

    async def interrupt_voice(self, value: object) -> bool:
        """Record voice interruption without signalling deep-work cancellation."""

        command = _require_interrupt(value)
        return await self._apply_voice_transition(
            command,
            status=VoiceStatus.INTERRUPTED,
            event_type="voice.interrupted",
            reason=command.reason,
        )

    async def _apply_voice_transition(
        self,
        command: (
            VoiceStartCommand
            | VoiceAcknowledgmentCommand
            | VoiceCompleteCommand
            | VoiceInterruptCommand
        ),
        *,
        status: VoiceStatus,
        event_type: str,
        **payload: object,
    ) -> bool:
        state = self._queues.get(command.session_id)
        if state is None:
            raise DeepWorkConflictError("Voice turn does not exist.")
        fingerprint = _fingerprint(command)
        async with state.lock:
            _guard_command_identity(state, command, fingerprint)
            prior = state.voice_fingerprints.get(command.idempotency_key)
            if prior is not None:
                if prior != fingerprint:
                    raise DeepWorkConflictError(
                        "Voice lifecycle identity was reused with different content."
                    )
                return False
            record = state.records.get(command.turn_id)
            if record is None or record.command.input_mode != "voice":
                raise DeepWorkConflictError("Voice turn does not exist.")
            if (
                isinstance(command, VoiceAcknowledgmentCommand)
                and record.audio_status is not VoiceStatus.SPEAKING
            ):
                raise DeepWorkConflictError(
                    "Voice acknowledgment arrived before playback started."
                )
            if (
                isinstance(command, VoiceCompleteCommand)
                and record.audio_status is not VoiceStatus.SPEAKING
            ):
                raise DeepWorkConflictError(
                    "Voice completion arrived before playback started."
                )
            if (
                isinstance(command, VoiceStartCommand)
                and record.audio_status is VoiceStatus.COMPLETED
            ):
                raise DeepWorkConflictError("Completed voice playback cannot restart.")

            state.voice_fingerprints[command.idempotency_key] = fingerprint
            _remember_command_identity(state, command, fingerprint)
            record.audio_status = status
            self._synchronize_turn(command.session_id, record)
            self._emit(
                command.session_id,
                command.turn_id,
                event_type,
                event_key=f"{event_type}:{command.idempotency_key}",
                **payload,
            )
            return True

    async def revert(self, value: object) -> DocumentVersion:
        """Create a restoring version and publish it through the app event lane."""

        command = _require_revert(value)
        state = self._queues.setdefault(command.session_id, _QueueState())
        fingerprint = _fingerprint(command)
        async with state.lock:
            _guard_command_identity(state, command, fingerprint)
            result = self._patch_service.revert(
                session_id=command.session_id,
                turn_id=command.turn_id,
                document_id=command.document_id,
                target_version=command.target_version,
                summary=command.summary,
                idempotency_key=command.idempotency_key,
            )
            _remember_command_identity(state, command, fingerprint)
            document = result.document
            self._emit(
                command.session_id,
                command.turn_id,
                "document.committed",
                event_key=f"document.committed:revert:{command.idempotency_key}",
                documentId=str(document.document_id),
                version=document.version,
                document=document.model_dump(mode="json", by_alias=True),
                markdownProjection=_markdown_projection(document),
                sourceLabels=_source_labels(document),
                restoredFromVersion=result.diff.restored_from_version,
            )
            return result

    async def wait_for_turn(
        self,
        session_id: UUID,
        turn_id: UUID,
    ) -> TaskSnapshot:
        """Wait without imposing a completion deadline."""

        state = self._queues.get(session_id)
        if state is None or turn_id not in state.records:
            raise LookupError("Deep task does not exist.")
        return await asyncio.shield(state.records[turn_id].completion)

    async def snapshot(self, session_id: UUID, turn_id: UUID) -> TaskSnapshot:
        """Return current content-free task state."""

        state = self._queues.get(session_id)
        if state is None:
            raise LookupError("Deep task does not exist.")
        async with state.lock:
            record = state.records.get(turn_id)
            if record is None:
                raise LookupError("Deep task does not exist.")
            return _snapshot(record, queue_position=_queue_position(state, record))

    def delivery_failures(self) -> tuple[EventDeliveryFailure, ...]:
        """Return sanitized event delivery failures."""

        return tuple(self._delivery_failures)

    async def shutdown(self) -> None:
        """Cancel and await every conversation runner without leaving live tasks."""

        if self._closed:
            return
        self._closed = True
        active_records: list[tuple[UUID, _QueueState, _TaskRecord]] = []
        runners: list[asyncio.Task[None]] = []
        for session_id, state in tuple(self._queues.items()):
            async with state.lock:
                records = list(state.pending)
                if state.running is not None:
                    records.insert(0, state.running)
                for record in records:
                    if record.status not in {
                        QueueStatus.CANCELLED,
                        QueueStatus.COMPLETED,
                        QueueStatus.FAILED,
                        QueueStatus.REJECTED,
                    }:
                        record.cancellation.request()
                        active_records.append((session_id, state, record))
                if state.runner is not None and not state.runner.done():
                    runners.append(state.runner)

        for runner in runners:
            runner.cancel()
        await asyncio.gather(*runners, return_exceptions=True)

        for session_id, state, record in active_records:
            async with state.lock:
                self._finalize_cancelled(
                    session_id,
                    record,
                    phase=(
                        "running"
                        if record.document_started_monotonic is not None
                        else "queued"
                    ),
                )
                if state.running is record:
                    state.running = None
                try:
                    state.pending.remove(record)
                except ValueError:
                    pass
                state.runner = None

    async def _drain(self, session_id: UUID, state: _QueueState) -> None:
        while True:
            async with state.lock:
                if not state.pending:
                    state.runner = None
                    return
                record = state.pending.popleft()
                state.running = record
                record.status = QueueStatus.RUNNING
                record.document_status = DocumentResultStatus.PENDING
                record.document_started_monotonic = monotonic()
                document = self._store.document(session_id)
                if document is None:
                    self._fail_locked(
                        session_id,
                        record,
                        _document_error(
                            code="conflict",
                            message="The canonical document is unavailable.",
                            retryable=False,
                        ),
                    )
                    state.running = None
                    continue
                record.base_document_version = document.version
                self._synchronize_turn(session_id, record)
                prior_turns = tuple(
                    turn
                    for turn in self._store.turns(session_id)
                    if turn.sequence < record.sequence
                )
                self._emit(
                    session_id,
                    record.command.turn_id,
                    "turn.analysis.started",
                    baseDocumentVersion=document.version,
                )
                self._emit(
                    session_id,
                    record.command.turn_id,
                    "document.pending",
                    documentId=str(document.document_id),
                    title=document.title,
                )
                work_input = DeepWorkInput(
                    session_id=session_id,
                    turn_id=record.command.turn_id,
                    sequence=record.sequence,
                    transcript=record.command.transcript,
                    document=document,
                    prior_turns=prior_turns,
                    controls=record.controls,
                )

            try:
                raw_output = await self._worker.run(
                    work_input,
                    record.cancellation,
                )
                output = DeepWorkOutput.model_validate(raw_output)
                await self._commit_output(session_id, state, record, output)
            except DeepWorkCancelled:
                await self._finish_running_cancellation(session_id, state, record)
            except DeepWorkFailure as error:
                await self._finish_failure(session_id, state, record, error.error)
            except (
                ContractValidationError,
                PatchValidationError,
                ValidationError,
            ) as error:
                del error
                await self._finish_failure(
                    session_id,
                    state,
                    record,
                    _document_error(
                        code="validation_error",
                        message="The document update was rejected.",
                        retryable=False,
                    ),
                )
            except Exception as error:
                del error
                await self._finish_failure(
                    session_id,
                    state,
                    record,
                    _document_error(
                        code="internal_error",
                        message="The document lane could not complete.",
                        retryable=True,
                    ),
                )
            finally:
                async with state.lock:
                    if state.running is record:
                        state.running = None

    async def _commit_output(
        self,
        session_id: UUID,
        state: _QueueState,
        record: _TaskRecord,
        output: DeepWorkOutput,
    ) -> None:
        async with state.lock:
            if record.cancellation.is_cancelled:
                self._finalize_cancelled(session_id, record, phase="running")
                return
            if record.controls.document_failure:
                self._fail_locked(
                    session_id,
                    record,
                    _document_error(
                        code="internal_error",
                        message="The document channel could not complete.",
                        retryable=True,
                    ),
                )
                return

            try:
                proposal = validate_patch(output.proposal)
                document = self._store.document(session_id)
                if (
                    document is None
                    or proposal.session_id != session_id
                    or proposal.turn_id != record.command.turn_id
                    or proposal.document_id != document.document_id
                    or proposal.base_version != record.base_document_version
                ):
                    raise PatchValidationError(
                        "The worker proposal correlation is invalid."
                    )
                expected_completion = _proposal_completion(proposal)
                if (
                    output.completion is not None
                    and output.completion != expected_completion
                ):
                    raise PatchValidationError(
                        "The worker completion does not match its proposal."
                    )
                result = self._patch_service.apply(output.proposal)
            except StaleDocumentVersionError as error:
                raise PatchValidationError(
                    "The start-time document base is no longer canonical."
                ) from error

            if isinstance(result, NoOpRecord):
                if output.provider_metadata is not None:
                    self._store.record_provider_metadata(
                        session_id,
                        record.command.turn_id,
                        output.provider_metadata,
                    )
                record.status = QueueStatus.COMPLETED
                record.document_status = DocumentResultStatus.NO_OP
                record.committed_document_version = result.base_version
                self._synchronize_turn(session_id, record)
                self._emit_analysis_completion(
                    session_id,
                    record,
                    output,
                    result,
                )
                self._finalize_completion(session_id, record)
                return

            if output.provider_metadata is not None:
                self._store.record_provider_metadata(
                    session_id,
                    record.command.turn_id,
                    output.provider_metadata,
                )
            self._emit_document_events(session_id, record, output, result)
            record.status = QueueStatus.COMPLETED
            record.document_status = DocumentResultStatus.COMMITTED
            record.committed_document_version = result.document.version
            self._synchronize_turn(session_id, record)
            self._emit_analysis_completion(
                session_id,
                record,
                output,
                result,
            )
            self._finalize_completion(session_id, record)

    async def _finish_running_cancellation(
        self,
        session_id: UUID,
        state: _QueueState,
        record: _TaskRecord,
    ) -> None:
        async with state.lock:
            self._finalize_cancelled(session_id, record, phase="running")

    async def _finish_failure(
        self,
        session_id: UUID,
        state: _QueueState,
        record: _TaskRecord,
        error: SanitizedError,
    ) -> None:
        async with state.lock:
            if record.cancellation.is_cancelled:
                self._finalize_cancelled(session_id, record, phase="running")
                return
            self._fail_locked(session_id, record, error)

    def _fail_locked(
        self,
        session_id: UUID,
        record: _TaskRecord,
        error: SanitizedError,
    ) -> None:
        document = self._store.document(session_id)
        if document is not None:
            self._emit(
                session_id,
                record.command.turn_id,
                "document.failed",
                documentId=str(document.document_id),
                error=error.model_dump(mode="json", by_alias=True),
            )
        record.status = QueueStatus.FAILED
        record.document_status = DocumentResultStatus.FAILED
        self._synchronize_turn(session_id, record)
        self._finalize_completion(session_id, record)

    def _finalize_cancelled(
        self,
        session_id: UUID,
        record: _TaskRecord,
        *,
        phase: str,
    ) -> None:
        if record.status is QueueStatus.CANCELLED:
            return
        record.status = QueueStatus.CANCELLED
        record.document_status = DocumentResultStatus.CANCELLED
        self._synchronize_turn(session_id, record)
        self._emit(
            session_id,
            record.command.turn_id,
            "turn.analysis.cancelled",
            phase=phase,
        )
        self._finalize_completion(session_id, record)

    def _finalize_completion(
        self,
        session_id: UUID,
        record: _TaskRecord,
    ) -> None:
        document_ms = (
            _elapsed_ms(record.document_started_monotonic)
            if record.document_started_monotonic is not None
            else None
        )
        self._emit(
            session_id,
            record.command.turn_id,
            "turn.completed",
            audioStatus=record.audio_status,
            documentStatus=record.document_status,
            timings={
                "acknowledgmentMs": None,
                "documentMs": document_ms,
                "totalMs": _elapsed_ms(record.accepted_monotonic),
            },
        )
        if not record.completion.done():
            record.completion.set_result(_snapshot(record, queue_position=None))

    def _emit_analysis_completion(
        self,
        session_id: UUID,
        record: _TaskRecord,
        output: DeepWorkOutput,
        result: DocumentVersion | NoOpRecord,
    ) -> None:
        expected = _canonical_completion(result)
        completion = output.completion or expected
        self._emit(
            session_id,
            record.command.turn_id,
            "turn.analysis.completed",
            outcome=completion.outcome,
            summary=completion.summary,
            documentVersion=completion.document_version,
            noOpReason=completion.no_op_reason,
        )

    def _synchronize_turn(
        self,
        session_id: UUID,
        record: _TaskRecord,
    ) -> None:
        document = self._store.document(session_id)
        self._store.synchronize_turn(
            session_id,
            record.command.turn_id,
            queue_status=record.status,
            voice_status=record.audio_status,
            document_status=record.document_status,
            document_version=(
                record.committed_document_version
                if record.committed_document_version is not None
                else document.version if document is not None else None
            ),
        )

    def _emit_document_events(
        self,
        session_id: UUID,
        record: _TaskRecord,
        output: DeepWorkOutput,
        result: DocumentVersion,
    ) -> None:
        document = result.document
        projection = _markdown_projection(document)
        source_labels = _source_labels(document)
        # Publish the validated patch before either document snapshot so browser
        # history can correlate the immutable diff with the committed version.
        self._emit(
            session_id,
            record.command.turn_id,
            "document.patch",
            documentId=str(document.document_id),
            baseVersion=result.diff.base_version,
            version=document.version,
            patch=output.proposal,
        )
        if document.version == 1:
            self._emit(
                session_id,
                record.command.turn_id,
                "document.created",
                documentId=str(document.document_id),
                version=document.version,
                document=document.model_dump(mode="json", by_alias=True),
                markdownProjection=projection,
                sourceLabels=source_labels,
            )
        self._emit(
            session_id,
            record.command.turn_id,
            "document.committed",
            documentId=str(document.document_id),
            version=document.version,
            document=document.model_dump(mode="json", by_alias=True),
            markdownProjection=projection,
            sourceLabels=source_labels,
        )

    def _reject_submission(
        self,
        command: TurnSubmitCommand,
        *,
        sequence: int,
        queue_depth: int,
    ) -> SubmissionResult:
        error = SanitizedError(
            code="queue_full",
            category="turn",
            message="Deep work is at capacity; retry after a queued turn finishes.",
            retryable=True,
        )
        self._emit(
            command.session_id,
            command.turn_id,
            "turn.started",
            sequence=sequence,
            inputMode=command.input_mode,
        )
        self._emit(
            command.session_id,
            command.turn_id,
            "turn.rejected",
            reason="The bounded deep-work queue is full.",
            queueDepth=queue_depth,
            error=error.model_dump(mode="json", by_alias=True),
        )
        self._emit(
            command.session_id,
            command.turn_id,
            "turn.completed",
            audioStatus=VoiceStatus.NOT_STARTED,
            documentStatus=DocumentResultStatus.REJECTED,
            timings={
                "acknowledgmentMs": None,
                "documentMs": None,
                "totalMs": 0,
            },
        )
        return SubmissionResult(
            accepted=False,
            task_created=False,
            turn_id=command.turn_id,
            queue_position=None,
            depends_on_turn_id=None,
            input_available=True,
            error=error,
        )

    @staticmethod
    def _remember_submission(
        state: _QueueState,
        command: TurnSubmitCommand,
        fingerprint: str,
        result: SubmissionResult,
    ) -> None:
        state.submit_fingerprints[command.idempotency_key] = fingerprint
        state.submit_results[command.idempotency_key] = result
        state.seen_turns.add(command.turn_id)
        _remember_command_identity(state, command, fingerprint)

    def _emit(
        self,
        session_id: UUID,
        turn_id: UUID,
        event_type: str,
        *,
        event_key: str | None = None,
        **payload: object,
    ) -> None:
        key = event_key or event_type
        event = {
            "type": event_type,
            "eventId": str(uuid5(turn_id, f"event:{key}")),
            "idempotencyKey": str(uuid5(turn_id, f"idempotency:{key}")),
            "sessionId": str(session_id),
            "turnId": str(turn_id),
            "timestamp": utc_now().isoformat(),
            **payload,
        }
        try:
            validated = validate_event(event)
            self._event_sink(
                validated.model_dump(mode="json", by_alias=True)
            )
        except Exception as error:
            del error
            self._delivery_failures.append(
                EventDeliveryFailure(
                    turn_id=turn_id,
                    event_type=event_type,
                )
            )


def _require_submit(value: object) -> TurnSubmitCommand:
    command = value if isinstance(value, TurnSubmitCommand) else validate_command(value)
    if not isinstance(command, TurnSubmitCommand):
        raise ContractValidationError("Expected a turn.submit command.")
    return command


def _require_cancel(value: object) -> TurnCancelCommand:
    command = value if isinstance(value, TurnCancelCommand) else validate_command(value)
    if not isinstance(command, TurnCancelCommand):
        raise ContractValidationError("Expected a turn.cancel command.")
    return command


def _require_interrupt(value: object) -> VoiceInterruptCommand:
    command = (
        value if isinstance(value, VoiceInterruptCommand) else validate_command(value)
    )
    if not isinstance(command, VoiceInterruptCommand):
        raise ContractValidationError("Expected a voice.interrupt command.")
    return command


def _require_voice_start(value: object) -> VoiceStartCommand:
    command = value if isinstance(value, VoiceStartCommand) else validate_command(value)
    if not isinstance(command, VoiceStartCommand):
        raise ContractValidationError("Expected a voice.start command.")
    return command


def _require_voice_acknowledgment(value: object) -> VoiceAcknowledgmentCommand:
    command = (
        value
        if isinstance(value, VoiceAcknowledgmentCommand)
        else validate_command(value)
    )
    if not isinstance(command, VoiceAcknowledgmentCommand):
        raise ContractValidationError("Expected a voice.acknowledge command.")
    return command


def _require_voice_complete(value: object) -> VoiceCompleteCommand:
    command = (
        value if isinstance(value, VoiceCompleteCommand) else validate_command(value)
    )
    if not isinstance(command, VoiceCompleteCommand):
        raise ContractValidationError("Expected a voice.complete command.")
    return command


def _require_revert(value: object) -> DocumentRevertCommand:
    command = value if isinstance(value, DocumentRevertCommand) else validate_command(value)
    if not isinstance(command, DocumentRevertCommand):
        raise ContractValidationError("Expected a document.revert command.")
    return command


def _fingerprint(
    command: (
        TurnSubmitCommand
        | TurnCancelCommand
        | VoiceStartCommand
        | VoiceAcknowledgmentCommand
        | VoiceCompleteCommand
        | VoiceInterruptCommand
        | DocumentRevertCommand
    ),
) -> str:
    return sha256(command.model_dump_json(by_alias=True).encode("utf-8")).hexdigest()


def _guard_command_identity(
    state: _QueueState,
    command: (
        TurnSubmitCommand
        | TurnCancelCommand
        | VoiceStartCommand
        | VoiceAcknowledgmentCommand
        | VoiceCompleteCommand
        | VoiceInterruptCommand
        | DocumentRevertCommand
    ),
    fingerprint: str,
) -> None:
    command_fingerprint = state.command_fingerprints.get(command.command_id)
    if command_fingerprint is not None and command_fingerprint != fingerprint:
        raise DeepWorkConflictError(
            "Command identity was reused with different content."
        )
    idempotency_fingerprint = state.idempotency_fingerprints.get(
        command.idempotency_key
    )
    if (
        idempotency_fingerprint is not None
        and idempotency_fingerprint != fingerprint
    ):
        raise DeepWorkConflictError(
            "Idempotency identity was reused with different content."
        )


def _remember_command_identity(
    state: _QueueState,
    command: (
        TurnSubmitCommand
        | TurnCancelCommand
        | VoiceStartCommand
        | VoiceAcknowledgmentCommand
        | VoiceCompleteCommand
        | VoiceInterruptCommand
        | DocumentRevertCommand
    ),
    fingerprint: str,
) -> None:
    state.command_fingerprints[command.command_id] = fingerprint
    state.idempotency_fingerprints[command.idempotency_key] = fingerprint


def _new_queue_position(state: _QueueState) -> int | None:
    if state.running is None and not state.pending:
        return None
    if state.running is None:
        return len(state.pending)
    return len(state.pending) + 1


def _tail_turn_id(state: _QueueState) -> UUID | None:
    if state.pending:
        return state.pending[-1].command.turn_id
    if state.running is not None:
        return state.running.command.turn_id
    return None


def _queue_position(state: _QueueState, record: _TaskRecord) -> int | None:
    try:
        return tuple(state.pending).index(record) + 1
    except ValueError:
        return None


def _snapshot(
    record: _TaskRecord,
    *,
    queue_position: int | None,
) -> TaskSnapshot:
    return TaskSnapshot(
        turn_id=record.command.turn_id,
        status=record.status,
        document_status=record.document_status,
        audio_status=record.audio_status,
        queue_position=queue_position,
        depends_on_turn_id=record.depends_on_turn_id,
        base_document_version=record.base_document_version,
        committed_document_version=record.committed_document_version,
    )


def _document_error(
    *,
    code: str,
    message: str,
    retryable: bool,
) -> SanitizedError:
    return SanitizedError(
        code=code,
        category="document",
        message=message,
        retryable=retryable,
    )


def _elapsed_ms(started: float | None) -> int:
    if started is None:
        return 0
    return min(round((monotonic() - started) * 1_000), 86_400_000)


def _proposal_completion(proposal: DocumentPatchProposal) -> DeepWorkCompletion:
    if proposal.operations:
        return DeepWorkCompletion(
            outcome="committed",
            summary=(
                f"Updated the working document to version {proposal.base_version + 1}."
            ),
            document_version=proposal.base_version + 1,
        )
    return DeepWorkCompletion(
        outcome="no_op",
        summary="No document changes were needed.",
        document_version=proposal.base_version,
        no_op_reason=proposal.reason,
    )


def _canonical_completion(
    result: DocumentVersion | NoOpRecord,
) -> DeepWorkCompletion:
    if isinstance(result, DocumentVersion):
        return DeepWorkCompletion(
            outcome="committed",
            summary=f"Updated the working document to version {result.document.version}.",
            document_version=result.document.version,
        )
    return DeepWorkCompletion(
        outcome="no_op",
        summary="No document changes were needed.",
        document_version=result.base_version,
        no_op_reason=result.reason,
    )


def _source_labels(document: OpportunityDocument) -> list[str]:
    claims = [
        document.customer_goal,
        document.current_situation,
        document.opportunity_hypothesis,
        document.expected_value,
        document.confidence_and_rationale,
        *document.supporting_signals,
        *document.stakeholders,
        *document.assumptions_and_uncertainties,
        *document.missing_evidence,
        *document.recommended_next_actions,
    ]
    labels: list[str] = []
    for claim in claims:
        if claim is not None and claim.source_label and claim.source_label not in labels:
            labels.append(claim.source_label)
    return labels


def _markdown_projection(document: OpportunityDocument) -> str:
    lines = [f"# {document.title}", "", f"Status: {document.status.value}"]
    sections = (
        ("Customer goal", document.customer_goal),
        ("Current situation", document.current_situation),
        ("Opportunity hypothesis", document.opportunity_hypothesis),
        ("Expected value", document.expected_value),
        ("Confidence and rationale", document.confidence_and_rationale),
    )
    for heading, claim in sections:
        if claim is not None:
            lines.extend(["", f"## {heading}", claim.text])
    list_sections = (
        ("Supporting signals", document.supporting_signals),
        ("Stakeholders", document.stakeholders),
        ("Assumptions and uncertainties", document.assumptions_and_uncertainties),
        ("Missing evidence", document.missing_evidence),
        ("Recommended next actions", document.recommended_next_actions),
    )
    for heading, items in list_sections:
        if items:
            lines.extend(["", f"## {heading}"])
            lines.extend(f"- {item.text}" for item in items)
    return "\n".join(lines)
