"""Provider-neutral backend voice-session contract."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol


class VoiceSessionBrokerError(RuntimeError):
    """Sanitized voice-provider connection or protocol failure."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class VoiceControlConnection(Protocol):
    """Minimal outbound provider control surface used by the broker."""

    async def send(self, message: str) -> None: ...

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


@dataclass(frozen=True)
class VoiceSessionAnswer:
    """Browser negotiation output without credentials or provider URLs."""

    sdp_answer: str


class VoiceSessionBroker(Protocol):
    """Backend contract implemented by every registered voice provider."""

    @property
    def available(self) -> bool:
        """Return whether this provider can create voice sessions."""

    def connect(
        self,
        sdp_offer: str,
    ) -> AbstractAsyncContextManager[
        tuple[VoiceControlConnection, VoiceSessionAnswer]
    ]:
        """Open one provider session and return normalized negotiation state."""
