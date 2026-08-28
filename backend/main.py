"""FastAPI application entry point."""

from __future__ import annotations

import os
import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.app_events import router as app_events_router
from backend.api.health import router as health_router
from backend.api.voice_session import router as voice_session_router
from backend.config import Settings
from backend.deep_work.base import StartupValidatedDeepWorker
from backend.providers.agent import AgentWorkerFactory, create_agent_worker
from backend.providers.voice import create_voice_broker
from backend.services.conversation_store import ConversationStore
from backend.services.deep_work_service import DeepWorkService
from backend.services.event_hub import AppEventHub
from backend.services.patch_service import PatchService
from backend.telemetry import TelemetryRecorder

LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    environ: Mapping[str, str] | None = None,
    agent_worker_factory: AgentWorkerFactory | None = None,
) -> FastAPI:
    """Create the isolated app after fail-closed startup validation."""

    settings = Settings.from_environ(os.environ if environ is None else environ)
    worker = create_agent_worker(
        settings,
        foundry_factory=agent_worker_factory,
    )
    startup_worker = (
        worker if isinstance(worker, StartupValidatedDeepWorker) else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            LOGGER.info(
                "Runtime providers selected: voice=%s agent=%s",
                settings.voice_provider.value,
                settings.agent_provider.value,
            )
            if startup_worker is not None:
                await startup_worker.validate_compatibility()
            yield
        finally:
            await application.state.deep_work.shutdown()

    application = FastAPI(
        title="Dual-Channel Voice Agent Pattern",
        version="0.0.0",
        lifespan=lifespan,
    )
    conversations = ConversationStore()
    patch_service = PatchService(conversations)
    event_hub = AppEventHub(conversations)
    application.state.settings = settings
    application.state.conversations = conversations
    application.state.patch_service = patch_service
    application.state.event_hub = event_hub
    application.state.telemetry = TelemetryRecorder()
    application.state.voice_broker = create_voice_broker(settings)
    application.state.deep_worker = worker
    application.state.deep_work = DeepWorkService(
        store=conversations,
        patch_service=patch_service,
        worker=worker,
        event_sink=event_hub.publish,
    )
    application.include_router(health_router)
    application.include_router(app_events_router)
    application.include_router(voice_session_router)
    return application


app = create_app()
