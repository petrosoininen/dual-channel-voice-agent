"""Atomic semantic patch, stale, duplicate, and partial-invalid tests."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.domain.models import DocumentVersion
from backend.services.conversation_store import ConversationStore
from backend.services.patch_service import (
    PatchService,
    PatchValidationError,
    StaleDocumentVersionError,
)

ROOT = Path(__file__).resolve().parents[2]
VALID_PATCH = json.loads(
    (ROOT / "contracts" / "fixtures" / "valid-patches.json").read_text(
        encoding="utf-8"
    )
)[0]["input"]
SESSION_ID = UUID(VALID_PATCH["sessionId"])
DOCUMENT_ID = UUID(VALID_PATCH["documentId"])


def _service() -> tuple[ConversationStore, PatchService]:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    store.create_document(SESSION_ID, document_id=DOCUMENT_ID)
    return store, PatchService(store)


def test_patch_commits_one_complete_version_and_is_idempotent() -> None:
    store, service = _service()

    first = service.apply(VALID_PATCH)
    duplicate = service.apply(VALID_PATCH)

    assert isinstance(first, DocumentVersion)
    assert duplicate == first
    assert store.document(SESSION_ID) == first.document
    assert first.document.version == 1
    assert len(first.document.supporting_signals) == 1
    assert len(store.versions(SESSION_ID)) == 1


def test_reused_patch_identity_with_changed_content_rejects() -> None:
    store, service = _service()
    service.apply(VALID_PATCH)

    with pytest.raises(PatchValidationError):
        service.apply({**VALID_PATCH, "summary": "Different content."})

    assert len(store.versions(SESSION_ID)) == 1


def test_stale_patch_is_rejected_without_mutation() -> None:
    store, service = _service()
    service.apply(VALID_PATCH)
    stale = {**VALID_PATCH, "patchId": str(uuid4())}
    before = store.document(SESSION_ID)

    with pytest.raises(StaleDocumentVersionError):
        service.apply(stale)

    assert store.document(SESSION_ID) == before
    assert len(store.versions(SESSION_ID)) == 1


def test_partially_invalid_patch_is_atomic() -> None:
    store, service = _service()
    patch = {
        **VALID_PATCH,
        "patchId": str(uuid4()),
        "operations": [
            VALID_PATCH["operations"][0],
            {
                "operationId": str(uuid4()),
                "op": "update_list_item",
                "section": "supportingSignals",
                "itemId": str(uuid4()),
                "value": {
                    "text": "This target does not exist.",
                    "classification": "unknown",
                },
            },
        ],
    }
    before = store.document(SESSION_ID)

    with pytest.raises(PatchValidationError):
        service.apply(patch)

    assert store.document(SESSION_ID) == before
    assert store.versions(SESSION_ID) == ()


def test_unknown_and_mistyped_operations_fail_before_mutation() -> None:
    store, service = _service()
    for operation in (
        {
            "operationId": str(uuid4()),
            "op": "unknown",
            "section": "customerGoal",
            "value": {"text": "Invalid.", "classification": "unknown"},
        },
        {
            "operationId": str(uuid4()),
            "op": "append_list_item",
            "section": "supportingSignals",
            "value": "invalid",
        },
    ):
        with pytest.raises(PatchValidationError):
            service.apply(
                {
                    **VALID_PATCH,
                    "patchId": str(uuid4()),
                    "operations": [operation],
                }
            )

    assert store.document(SESSION_ID).version == 0
    assert store.versions(SESSION_ID) == ()
