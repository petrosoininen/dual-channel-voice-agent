"""Construct registered agent adapters without importing unused provider SDKs."""

from __future__ import annotations

from collections.abc import Callable

from backend.config import AgentProvider, Settings
from backend.deep_work.base import DeepWorker
from backend.deep_work.deterministic import DeterministicDeepWorker

AgentWorkerFactory = Callable[[Settings], DeepWorker]


def create_agent_worker(
    settings: Settings,
    *,
    foundry_factory: AgentWorkerFactory | None = None,
) -> DeepWorker:
    """Create the selected agent adapter and no unselected optional provider."""

    if settings.agent_provider is AgentProvider.DETERMINISTIC:
        return DeterministicDeepWorker()
    if settings.agent_provider is AgentProvider.FOUNDRY:
        if foundry_factory is not None:
            return foundry_factory(settings)
        from backend.deep_work.foundry import FoundryDeepWorker

        return FoundryDeepWorker(settings)
    raise ValueError("Unsupported agent provider.")
