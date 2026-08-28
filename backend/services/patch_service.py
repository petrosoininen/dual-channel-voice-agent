"""Atomic allowlisted semantic patch and history-preserving revert service."""

from __future__ import annotations

from hashlib import sha256
from typing import TypeAlias
from uuid import UUID, uuid5

from pydantic import ValidationError

from backend.domain.events import ContractValidationError, validate_patch
from backend.domain.models import (
    AppendListItemOperation,
    AppliedOperation,
    DocumentDiff,
    DocumentListItem,
    DocumentPatchProposal,
    DocumentStatus,
    DocumentVersion,
    NoOpRecord,
    OpportunityDocument,
    RemoveListItemOperation,
    ReplaceSectionOperation,
    SemanticOperation,
    SetFieldOperation,
    UpdateListItemOperation,
    utc_now,
)
from backend.services.conversation_store import (
    ConversationConflictError,
    ConversationStore,
)

PatchResult: TypeAlias = DocumentVersion | NoOpRecord
_CLAIM_ATTRIBUTES = {
    "customerGoal": "customer_goal",
    "currentSituation": "current_situation",
    "opportunityHypothesis": "opportunity_hypothesis",
    "expectedValue": "expected_value",
    "confidenceAndRationale": "confidence_and_rationale",
}
_LIST_ATTRIBUTES = {
    "supportingSignals": "supporting_signals",
    "stakeholders": "stakeholders",
    "assumptionsAndUncertainties": "assumptions_and_uncertainties",
    "missingEvidence": "missing_evidence",
    "recommendedNextActions": "recommended_next_actions",
}


class PatchValidationError(ValueError):
    """Sanitized semantic patch validation failure."""


class StaleDocumentVersionError(ConversationConflictError):
    """Patch base version does not match the canonical projection."""


class PatchService:
    """Validate and commit patches atomically to a process-memory store."""

    def __init__(self, store: ConversationStore) -> None:
        self._store = store

    def apply(self, value: object) -> PatchResult:
        """Apply one proposal or return the prior idempotent result."""

        try:
            proposal = validate_patch(value)
        except ContractValidationError as error:
            raise PatchValidationError("Patch validation failed.") from error
        fingerprint = sha256(
            proposal.model_dump_json(by_alias=True).encode("utf-8")
        ).hexdigest()

        with self._store.transaction(proposal.session_id) as state:
            prior = state.command_results.get(proposal.patch_id)
            if prior is not None:
                if state.command_fingerprints[proposal.patch_id] != fingerprint:
                    raise PatchValidationError(
                        "Patch identity was reused with different content."
                    )
                return prior
            document = state.document
            if document is None or document.document_id != proposal.document_id:
                raise PatchValidationError("Document identity is invalid.")
            if document.version != proposal.base_version:
                raise StaleDocumentVersionError(
                    "Patch base version is stale."
                )

            if not proposal.operations:
                no_op = NoOpRecord(
                    patch_id=proposal.patch_id,
                    session_id=proposal.session_id,
                    turn_id=proposal.turn_id,
                    document_id=proposal.document_id,
                    base_version=proposal.base_version,
                    summary=proposal.summary,
                    reason=proposal.reason,
                    recorded_at=utc_now(),
                )
                state.no_ops.append(no_op)
                state.command_results[proposal.patch_id] = no_op
                state.command_fingerprints[proposal.patch_id] = fingerprint
                return no_op

            candidate, applied = self._apply_operations(document, proposal)
            version_number = document.version + 1
            candidate = candidate.model_copy(
                update={"version": version_number}, deep=True
            )
            version = DocumentVersion(
                document=candidate,
                diff=DocumentDiff(
                    base_version=document.version,
                    version=version_number,
                    turn_id=proposal.turn_id,
                    summary=proposal.summary,
                    operations=tuple(applied),
                    committed_at=utc_now(),
                ),
            )
            state.document = candidate
            state.versions.append(version)
            state.command_results[proposal.patch_id] = version
            state.command_fingerprints[proposal.patch_id] = fingerprint
            return version

    def revert(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        document_id: UUID,
        target_version: int,
        summary: str,
        idempotency_key: UUID,
    ) -> DocumentVersion:
        """Restore an earlier snapshot as a new immutable version."""

        fingerprint = sha256(
            (
                f"{session_id}:{turn_id}:{document_id}:{target_version}:"
                f"{summary}:{idempotency_key}"
            ).encode("utf-8")
        ).hexdigest()
        with self._store.transaction(session_id) as state:
            prior = state.command_results.get(idempotency_key)
            if isinstance(prior, DocumentVersion):
                if state.command_fingerprints[idempotency_key] != fingerprint:
                    raise PatchValidationError(
                        "Restore identity was reused with different content."
                    )
                return prior
            document = state.document
            if document is None or document.document_id != document_id:
                raise PatchValidationError("Document identity is invalid.")
            target = next(
                (
                    item
                    for item in state.versions
                    if item.document.version == target_version
                ),
                None,
            )
            if target is None:
                raise PatchValidationError("Restore version does not exist.")
            restored_content = target.document.model_copy(
                update={"version": document.version + 1}, deep=True
            )
            if _content_without_version(restored_content) == _content_without_version(
                document
            ):
                raise PatchValidationError(
                    "Restore target does not change document content."
                )
            version = DocumentVersion(
                document=restored_content,
                diff=DocumentDiff(
                    base_version=document.version,
                    version=restored_content.version,
                    turn_id=turn_id,
                    summary=summary,
                    operations=(),
                    committed_at=utc_now(),
                    restored_from_version=target_version,
                ),
            )
            state.document = restored_content
            state.versions.append(version)
            state.command_results[idempotency_key] = version
            state.command_fingerprints[idempotency_key] = fingerprint
            return version

    def _apply_operations(
        self,
        document: OpportunityDocument,
        proposal: DocumentPatchProposal,
    ) -> tuple[OpportunityDocument, list[AppliedOperation]]:
        candidate = document
        applied: list[AppliedOperation] = []
        try:
            for operation in proposal.operations:
                candidate, created_item_id = _apply_operation(
                    candidate, proposal.patch_id, operation
                )
                applied.append(
                    AppliedOperation(
                        operation=operation,
                        created_item_id=created_item_id,
                    )
                )
            return OpportunityDocument.model_validate(
                candidate.model_dump(mode="python")
            ), applied
        except (ValidationError, ValueError) as error:
            raise PatchValidationError("Patch operation validation failed.") from error


def _apply_operation(
    document: OpportunityDocument,
    patch_id: UUID,
    operation: SemanticOperation,
) -> tuple[OpportunityDocument, UUID | None]:
    if isinstance(operation, SetFieldOperation):
        value: object = (
            DocumentStatus(operation.value)
            if operation.field == "status"
            else operation.value
        )
        return document.model_copy(update={operation.field: value}, deep=True), None

    if isinstance(operation, ReplaceSectionOperation):
        attribute = _CLAIM_ATTRIBUTES[operation.section]
        return document.model_copy(update={attribute: operation.value}, deep=True), None

    if isinstance(operation, AppendListItemOperation):
        attribute = _LIST_ATTRIBUTES[operation.section]
        values = list(getattr(document, attribute))
        if len(values) >= _max_items(operation.section):
            raise ValueError("List section is at capacity.")
        item_id = uuid5(patch_id, str(operation.operation_id))
        values.append(
            DocumentListItem(item_id=item_id, **operation.value.model_dump())
        )
        return document.model_copy(update={attribute: tuple(values)}, deep=True), item_id

    attribute = _LIST_ATTRIBUTES[operation.section]
    values = list(getattr(document, attribute))
    index = next(
        (position for position, item in enumerate(values) if item.item_id == operation.item_id),
        None,
    )
    if index is None:
        raise ValueError("List item does not exist.")
    if isinstance(operation, UpdateListItemOperation):
        values[index] = DocumentListItem(
            item_id=operation.item_id, **operation.value.model_dump()
        )
    elif isinstance(operation, RemoveListItemOperation):
        values.pop(index)
    else:
        raise ValueError("Unknown operation.")
    return document.model_copy(update={attribute: tuple(values)}, deep=True), None


def _max_items(section: str) -> int:
    return 16 if section == "stakeholders" else 24


def _content_without_version(document: OpportunityDocument) -> dict[str, object]:
    content = document.model_dump(mode="python")
    content.pop("version")
    return content
