"""Opt-in live Foundry acceptance; deterministic fakes never satisfy AT-025."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.config import Settings
from backend.deep_work.foundry import FoundryDeepWorker
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.patch_service import PatchService

ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = UUID("10000000-0000-4000-8000-000000000101")
SCRIPTED_TURNS = json.loads(
    (ROOT / "fixtures" / "scripted-turns.json").read_text(encoding="utf-8")
)

pytestmark = pytest.mark.skipif(
    os.environ.get("DCR_RUN_LIVE_FOUNDRY") != "1",
    reason="Live Foundry acceptance requires explicit opt-in and compatible configuration.",
)


def test_live_three_turns_reuse_one_service_conversation() -> None:
    """Run AT-025 only when an authorized compatible Prompt Agent already exists."""

    async def scenario() -> None:
        settings = Settings.from_environ(os.environ)
        worker = FoundryDeepWorker(settings)
        await worker.validate_compatibility()
        store = ConversationStore()
        store.create_session(SESSION_ID)
        service = DeepWorkService(
            store=store,
            patch_service=PatchService(store),
            worker=worker,
        )
        submissions = []
        for scripted in SCRIPTED_TURNS:
            turn_id = uuid4()
            submission = await service.submit(
                {
                    "type": "turn.submit",
                    "commandId": str(uuid4()),
                    "idempotencyKey": str(uuid4()),
                    "sessionId": str(SESSION_ID),
                    "turnId": str(turn_id),
                    "timestamp": "2026-08-27T00:00:00Z",
                    "inputMode": "typed",
                    "transcript": scripted["transcript"],
                }
            )
            submissions.append((submission, turn_id))
        outcomes = [
            await service.wait_for_turn(SESSION_ID, turn_id)
            for _, turn_id in submissions
        ]

        assert [item.committed_document_version for item in outcomes] == [1, 2, 3]
        metadata = [
            turn.provider_metadata
            for turn in store.turns(SESSION_ID)
            if turn.provider_metadata is not None
        ]
        assert len(metadata) == 3
        assert len({item.conversation_id for item in metadata}) == 1

    asyncio.run(scenario())
