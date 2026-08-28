"""Test-only application factory for deterministic browser acceptance."""

from __future__ import annotations

from dataclasses import replace

from backend.deep_work.base import (
    CancellationToken,
    DeepWorkControls,
    DeepWorkInput,
    DeepWorkOutput,
)
from backend.deep_work.deterministic import DeterministicDeepWorker
from backend.main import create_app
from backend.services.deep_work_service import DeepWorkService


class _DelayedFirstTurnWorker:
    """Delay only the first scripted turn without exposing a runtime control API."""

    def __init__(self) -> None:
        self._delegate = DeterministicDeepWorker()

    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        if work_input.sequence == 1:
            work_input = replace(
                work_input,
                controls=DeepWorkControls(delay_ms=800),
            )
        return await self._delegate.run(work_input, cancellation)


app = create_app(environ={})
app.state.deep_work = DeepWorkService(
    store=app.state.conversations,
    patch_service=app.state.patch_service,
    worker=_DelayedFirstTurnWorker(),
    event_sink=app.state.event_hub.publish,
)
