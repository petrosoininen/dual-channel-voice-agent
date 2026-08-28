"""History-preserving revert behavior."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from backend.services.conversation_store import ConversationStore
from backend.services.patch_service import PatchService

ROOT = Path(__file__).resolve().parents[2]
PATCH = json.loads(
    (ROOT / "contracts" / "fixtures" / "valid-patches.json").read_text(
        encoding="utf-8"
    )
)[0]["input"]
SESSION_ID = UUID(PATCH["sessionId"])
DOCUMENT_ID = UUID(PATCH["documentId"])


def test_revert_creates_new_version_and_preserves_history() -> None:
    store = ConversationStore()
    store.create_session(SESSION_ID)
    store.create_document(SESSION_ID, document_id=DOCUMENT_ID)
    service = PatchService(store)
    version_one = service.apply(PATCH)
    version_two = service.apply(
        {
            **PATCH,
            "patchId": str(uuid4()),
            "turnId": str(uuid4()),
            "baseVersion": 1,
            "operations": [
                {
                    "operationId": str(uuid4()),
                    "op": "set_field",
                    "field": "title",
                    "value": "Refined synthetic opportunity",
                }
            ],
        }
    )

    reverted = service.revert(
        session_id=SESSION_ID,
        turn_id=uuid4(),
        document_id=DOCUMENT_ID,
        target_version=1,
        summary="Restore the initial synthetic assessment.",
        idempotency_key=uuid4(),
    )

    assert version_one.document.version == 1
    assert version_two.document.version == 2
    assert reverted.document.version == 3
    assert reverted.document.title == version_one.document.title
    assert reverted.diff.restored_from_version == 1
    assert [item.document.version for item in store.versions(SESSION_ID)] == [1, 2, 3]
