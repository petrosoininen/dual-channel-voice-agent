"""Health and non-sensitive capability endpoints."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.config import Settings, VoiceProvider

router = APIRouter(prefix="/api", tags=["service"])


class HealthResponse(BaseModel):
    """Minimal liveness response."""

    status: str
    state_persistence: str


class CapabilitiesResponse(BaseModel):
    """Public runtime capabilities without resource or identity configuration."""

    agentProvider: str
    voiceProvider: str
    deepWorkAvailable: bool
    voiceAvailable: bool
    voiceTransport: str
    voiceTransportPreview: bool
    statePersistence: str


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return process liveness without probing external services."""

    return HealthResponse(status="ok", state_persistence="process-memory-only")


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(request: Request) -> CapabilitiesResponse:
    """Return only browser-safe feature flags and preview disclosures."""

    settings: Settings = request.app.state.settings
    return CapabilitiesResponse(
        agentProvider=settings.agent_provider.value,
        voiceProvider=settings.voice_provider.value,
        deepWorkAvailable=True,
        voiceAvailable=(
            settings.voice_provider is VoiceProvider.AZURE_VOICE_LIVE
        ),
        voiceTransport=(
            "webrtc-public-preview"
            if settings.voice_provider is VoiceProvider.AZURE_VOICE_LIVE
            else "disabled"
        ),
        voiceTransportPreview=(
            settings.voice_provider is VoiceProvider.AZURE_VOICE_LIVE
        ),
        statePersistence="process-memory-only",
    )
