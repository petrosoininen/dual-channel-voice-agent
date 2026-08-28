"""Request-scoped guard and capture seam for Foundry patch proposals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import Field, JsonValue, ValidationError, model_validator

from backend.deep_work.base import CancellationToken, DeepWorkInput
from backend.domain.models import (
    DocumentPatchProposal,
    DocumentVersion,
    ClaimClassification,
    ClaimText,
    NoOpRecord,
    OpportunityDocument,
    ScalarField,
    SourceLabel,
    WireModel,
)
from backend.services.conversation_store import ConversationStore
from backend.services.patch_service import PatchService, PatchValidationError

PATCH_PROPOSAL_TOOL_NAME = "propose_document_patch"

class FoundryClassifiedText(WireModel):
    """Strict-compatible classified text with an explicit nullable source label."""

    text: ClaimText
    classification: ClaimClassification
    source_label: SourceLabel | None


class FoundrySetFieldInput(WireModel):
    field: ScalarField
    value: str


class FoundryReplaceSectionInput(WireModel):
    section: Literal[
        "customerGoal",
        "currentSituation",
        "opportunityHypothesis",
        "expectedValue",
        "confidenceAndRationale",
    ]
    value: FoundryClassifiedText


class FoundryAppendListItemInput(WireModel):
    section: Literal[
        "supportingSignals",
        "stakeholders",
        "assumptionsAndUncertainties",
        "missingEvidence",
        "recommendedNextActions",
    ]
    value: FoundryClassifiedText


class FoundryUpdateListItemInput(FoundryAppendListItemInput):
    item_id: UUID


class FoundryRemoveListItemInput(WireModel):
    section: Literal[
        "supportingSignals",
        "stakeholders",
        "assumptionsAndUncertainties",
        "missingEvidence",
        "recommendedNextActions",
    ]
    item_id: UUID


class FoundryOperationBatch(WireModel):
    """Strict operation groups that avoid unsupported JSON Schema unions."""

    set_fields: list[FoundrySetFieldInput] = Field(max_length=32)
    replace_sections: list[FoundryReplaceSectionInput] = Field(max_length=32)
    append_list_items: list[FoundryAppendListItemInput] = Field(max_length=32)
    update_list_items: list[FoundryUpdateListItemInput] = Field(max_length=32)
    remove_list_items: list[FoundryRemoveListItemInput] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_total(self) -> FoundryOperationBatch:
        if sum(
            len(group)
            for group in (
                self.set_fields,
                self.replace_sections,
                self.append_list_items,
                self.update_list_items,
                self.remove_list_items,
            )
        ) > 32:
            raise ValueError("Operation batch exceeds its allowed size.")
        return self

    def canonical_operations(self) -> list[dict[str, JsonValue]]:
        grouped = (
            ("set_field", self.set_fields),
            ("replace_section", self.replace_sections),
            ("append_list_item", self.append_list_items),
            ("update_list_item", self.update_list_items),
            ("remove_list_item", self.remove_list_items),
        )
        return [
            {
                "op": operation_name,
                **item.model_dump(mode="json", by_alias=True),
            }
            for operation_name, items in grouped
            for item in items
        ]

PatchProposalTool = Callable[
    [int, str, FoundryOperationBatch, str | None],
    dict[str, JsonValue],
]


@dataclass
class PatchProposalCapture:
    """Capture one request-local staged tool transaction."""

    attempt_count: int = 0
    proposal: DocumentPatchProposal | None = None
    result: DocumentVersion | NoOpRecord | None = None
    staged_document: OpportunityDocument | None = None
    rejection: str | None = None
    rejection_detail: str | None = None
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def require_exactly_one(
        self,
    ) -> tuple[DocumentPatchProposal, DocumentVersion | NoOpRecord]:
        """Return the successful staged transaction or reject the entire turn."""

        if (
            self.attempt_count != 1
            or self.proposal is None
            or self.result is None
            or self.rejection is not None
        ):
            raise LookupError("The Foundry patch-tool contract was not satisfied.")
        return self.proposal, self.result


def create_patch_proposal_tool(
    work_input: DeepWorkInput,
    capture: PatchProposalCapture,
    cancellation: CancellationToken | None = None,
) -> PatchProposalTool:
    """Stage one proposal so an invalid turn cannot mutate canonical state."""

    staging_service = _create_staging_service(work_input)

    def propose_document_patch(
        base_version: Annotated[
            int,
            Field(
                ge=0,
                description="Canonical document version supplied in the request.",
            ),
        ],
        summary: Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Concise description of the proposed document update.",
            ),
        ],
        operations: FoundryOperationBatch,
        reason: Annotated[
            str | None,
            Field(
                max_length=500,
                description="Required when operations are empty.",
            ),
        ],
    ) -> dict[str, JsonValue]:
        """Validate and stage one semantic patch proposal for the current turn."""

        # The hosted tool policy can request the same function again while producing
        # its continuation. Return the already staged outcome without applying twice.
        with capture._lock:
            if (
                capture.attempt_count == 1
                and capture.result is not None
                and capture.rejection is None
            ):
                return _accepted(capture.result)
            capture.attempt_count += 1
            if capture.attempt_count > 1:
                capture.rejection = "multiple_calls"
                return _rejected("multiple_calls")
            if cancellation is not None and cancellation.is_cancelled:
                capture.rejection = "cancelled"
                return _rejected("cancelled")
            try:
                if isinstance(operations, FoundryOperationBatch):
                    authored_operations = operations.canonical_operations()
                elif isinstance(operations, Mapping):
                    authored_operations = FoundryOperationBatch.model_validate(
                        operations
                    ).canonical_operations()
                else:
                    authored_operations = [dict(operation) for operation in operations]
                normalized_operations = []
                for index, serialized in enumerate(authored_operations):
                    serialized.pop("operationId", None)
                    serialized["operationId"] = str(
                        uuid5(work_input.turn_id, f"foundry-operation:{index}")
                    )
                    normalized_operations.append(serialized)
                payload = {
                    "patchId": str(
                        uuid5(
                            work_input.turn_id,
                            "foundry-document-patch:1",
                        )
                    ),
                    "sessionId": str(work_input.session_id),
                    "turnId": str(work_input.turn_id),
                    "documentId": str(work_input.document.document_id),
                    "baseVersion": base_version,
                    "summary": summary,
                    "operations": normalized_operations,
                    "reason": reason,
                }
                proposal = DocumentPatchProposal.model_validate(payload)
                result = staging_service.apply(
                    proposal.model_dump(mode="json", by_alias=True)
                )
            except PatchValidationError:
                capture.rejection_detail = "patch_validation"
                capture.rejection = "validation_failed"
                return _rejected("validation_failed")
            except ValidationError:
                capture.rejection_detail = "proposal_validation"
                capture.rejection = "validation_failed"
                return _rejected("validation_failed")
            except ValueError:
                capture.rejection_detail = "operation_validation"
                capture.rejection = "validation_failed"
                return _rejected("validation_failed")
            if cancellation is not None and cancellation.is_cancelled:
                capture.rejection = "cancelled"
                return _rejected("cancelled")
            capture.proposal = proposal
            capture.result = result
            capture.staged_document = (
                result.document
                if isinstance(result, DocumentVersion)
                else work_input.document
            )
            return _accepted(result)

    setattr(propose_document_patch, "_dcr_patch_capture", capture)
    return propose_document_patch


def _create_staging_service(work_input: DeepWorkInput) -> PatchService:
    """Create an isolated transaction projection for request-local tool feedback."""

    store = ConversationStore()
    store.create_session(work_input.session_id)
    with store.transaction(work_input.session_id) as state:
        state.document = work_input.document
    return PatchService(store)


def _accepted(result: DocumentVersion | NoOpRecord) -> dict[str, JsonValue]:
    if isinstance(result, DocumentVersion):
        outcome = "committed"
        document_version = result.document.version
    else:
        outcome = "no_op"
        document_version = result.base_version
    return {
        "accepted": True,
        "outcome": outcome,
        "documentVersion": document_version,
    }


def _rejected(reason: str) -> dict[str, JsonValue]:
    """Return a bounded result that contains no rejected proposal details."""

    return {
        "accepted": False,
        "outcome": "rejected",
        "reason": reason,
    }
