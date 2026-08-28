"""Reasoned no-op semantics."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from backend.domain.models import NoOpRecord
from backend.services.conversation_store import ConversationStore
from backend.services.patch_service import PatchService, PatchValidationError

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads(
    (ROOT / "contracts" / "fixtures" / "valid-patches.json").read_text(
        encoding="utf-8"
    )
)
NO_OP = CASES[1]["input"]
SESSION_ID = UUID(NO_OP["sessionId"])
DOCUMENT_ID = UUID(NO_OP["documentId"])


def test_reasoned_no_op_records_success_without_version() -> None:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    store.create_document(SESSION_ID, document_id=DOCUMENT_ID)
    service = PatchService(store)
    proposal = {**NO_OP, "baseVersion": 0}

    result = service.apply(proposal)
    duplicate = service.apply(proposal)

    assert isinstance(result, NoOpRecord)
    assert duplicate == result
    assert store.document(SESSION_ID).version == 0
    assert store.versions(SESSION_ID) == ()
    assert store.no_ops(SESSION_ID) == (result,)


def test_zero_operations_without_reason_rejects() -> None:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    store.create_document(SESSION_ID, document_id=DOCUMENT_ID)

    with pytest.raises(PatchValidationError):
        PatchService(store).apply({key: value for key, value in NO_OP.items() if key != "reason"})

    assert store.document(SESSION_ID).version == 0
