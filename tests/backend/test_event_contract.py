"""Coverage for every command and event discriminant."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.domain.events import ContractValidationError, validate_command, validate_event


def _event(event_type: str, **payload: object) -> dict[str, object]:
    return {
        "type": event_type,
        "eventId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(uuid4()),
        "turnId": str(uuid4()),
        "timestamp": "2026-08-26T09:00:00Z",
        **payload,
    }


def _document(document_id: str, version: int) -> dict[str, object]:
    return {
        "documentId": document_id,
        "version": version,
        "title": "Synthetic opportunity",
        "status": "draft",
        "customerGoal": None,
        "currentSituation": None,
        "opportunityHypothesis": None,
        "supportingSignals": [],
        "expectedValue": None,
        "stakeholders": [],
        "assumptionsAndUncertainties": [],
        "missingEvidence": [],
        "recommendedNextActions": [],
        "confidenceAndRationale": None,
    }


def test_complete_event_union_accepts_known_shapes() -> None:
    document_id = str(uuid4())
    base = _event("document.patch")
    patch = {
        "patchId": str(uuid4()),
        "sessionId": base["sessionId"],
        "turnId": base["turnId"],
        "documentId": document_id,
        "baseVersion": 0,
        "summary": "No change is supported.",
        "operations": [],
        "reason": "The synthetic context contains no new evidence.",
    }
    cases = [
        _event("turn.started", sequence=1, inputMode="voice"),
        _event("turn.queued", position=1, dependsOnTurnId=None),
        _event(
            "turn.rejected",
            reason="The bounded queue is full.",
            queueDepth=4,
            error={
                "code": "queue_full",
                "category": "turn",
                "message": "Deep work is at capacity.",
                "retryable": True,
            },
        ),
        _event("turn.analysis.started", baseDocumentVersion=0),
        _event("turn.analysis.cancelling"),
        _event("turn.analysis.cancelled", phase="running"),
        _event(
            "turn.analysis.completed",
            outcome="committed",
            summary="Updated the working document to version 1.",
            documentVersion=1,
            noOpReason=None,
        ),
        _event("voice.started"),
        _event(
            "voice.acknowledgment",
            intentSummary="I will review the synthetic context.",
            nextStep="I will organize the classified evidence.",
        ),
        _event("voice.interrupted", reason="barge_in"),
        _event("voice.completed"),
        _event("document.pending", documentId=document_id, title="Synthetic opportunity"),
        _event(
            "document.created",
            documentId=document_id,
            version=1,
            document=_document(document_id, 1),
            markdownProjection="",
            sourceLabels=[],
        ),
        {
            **base,
            "documentId": document_id,
            "baseVersion": 0,
            "version": 1,
            "patch": patch,
        },
        _event(
            "document.committed",
            documentId=document_id,
            version=1,
            document=_document(document_id, 1),
            markdownProjection="",
            sourceLabels=[],
        ),
        _event(
            "document.failed",
            documentId=document_id,
            error={
                "code": "validation_error",
                "category": "document",
                "message": "The document update was rejected.",
                "retryable": False,
            },
        ),
        _event(
            "turn.completed",
            audioStatus="completed",
            documentStatus="committed",
            timings={"acknowledgmentMs": 10, "documentMs": 20, "totalMs": 20},
        ),
    ]

    assert len(cases) == 17
    assert all(validate_event(case) for case in cases)


def test_complete_command_union_accepts_known_shapes() -> None:
    envelope = {
        "commandId": str(uuid4()),
        "idempotencyKey": str(uuid4()),
        "sessionId": str(uuid4()),
        "timestamp": "2026-08-26T09:00:00Z",
    }
    cases = [
        {**envelope, "type": "turn.submit", "turnId": str(uuid4()), "inputMode": "typed", "transcript": "Review synthetic context."},
        {**envelope, "type": "turn.cancel", "turnId": str(uuid4()), "reason": "Stop deep work."},
        {**envelope, "type": "voice.start", "turnId": str(uuid4())},
        {
            **envelope,
            "type": "voice.acknowledge",
            "turnId": str(uuid4()),
            "intentSummary": "I understand the requested review.",
            "nextStep": "Next, I will assess the synthetic context.",
        },
        {**envelope, "type": "voice.complete", "turnId": str(uuid4())},
        {**envelope, "type": "voice.interrupt", "turnId": str(uuid4()), "reason": "user_stop"},
        {
            **envelope,
            "type": "document.revert",
            "turnId": str(uuid4()),
            "documentId": str(uuid4()),
            "targetVersion": 1,
            "summary": "Restore the earlier synthetic assessment.",
        },
    ]

    assert all(validate_command(case) for case in cases)


def test_acknowledgment_rejects_substantive_extra_fields() -> None:
    event = _event(
        "voice.acknowledgment",
        intentSummary="I will review the synthetic context.",
        nextStep="I will organize the classified evidence.",
        confidence="high",
    )

    with pytest.raises(ContractValidationError):
        validate_event(event)
