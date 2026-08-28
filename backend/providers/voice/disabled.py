"""Disabled voice provider with no Azure imports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from backend.providers.voice.base import (
    VoiceControlConnection,
    VoiceSessionAnswer,
    VoiceSessionBrokerError,
)


class DisabledVoiceSessionBroker:
    """Reject voice negotiation while typed input remains available."""

    @property
    def available(self) -> bool:
        return False

    @asynccontextmanager
    async def connect(
        self,
        sdp_offer: str,
    ) -> AsyncIterator[tuple[VoiceControlConnection, VoiceSessionAnswer]]:
        del sdp_offer
        raise VoiceSessionBrokerError(
            "voice_disabled",
            "Voice is disabled. Use typed input or configure a voice provider.",
            retryable=False,
        )
        yield
