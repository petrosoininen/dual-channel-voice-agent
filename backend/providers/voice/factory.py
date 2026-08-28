"""Construct registered voice brokers without importing unused Azure packages."""

from backend.config import Settings, VoiceProvider
from backend.providers.voice.base import VoiceSessionBroker
from backend.providers.voice.disabled import DisabledVoiceSessionBroker


def create_voice_broker(settings: Settings) -> VoiceSessionBroker:
    """Create exactly the selected backend voice adapter."""

    if settings.voice_provider is VoiceProvider.OFF:
        return DisabledVoiceSessionBroker()
    if settings.voice_provider is VoiceProvider.AZURE_VOICE_LIVE:
        from backend.providers.voice.azure_voice_live import AzureVoiceLiveBroker

        return AzureVoiceLiveBroker(settings)
    raise ValueError("Unsupported voice provider.")
