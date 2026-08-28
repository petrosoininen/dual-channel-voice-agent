"""Keyless Voice Live WebRTC control-channel broker."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import urlencode, urlsplit, urlunsplit

from azure.core.exceptions import ClientAuthenticationError
from azure.core.credentials_async import AsyncTokenCredential
from websockets.asyncio.client import ClientConnection, connect

from backend.azure_identity import create_default_async_credential
from backend.config import Settings, VoiceProvider
from backend.providers.voice.base import (
    VoiceControlConnection,
    VoiceSessionAnswer,
    VoiceSessionBrokerError,
)

VOICE_LIVE_SCOPE = "https://ai.azure.com/.default"
VOICE_LIVE_API_VERSION = "2026-01-01-preview"
MAX_CONTROL_BYTES = 65_536
# The response budget includes generated audio tokens as well as text tokens. Keep
# enough headroom for the requested two-sentence acknowledgment.
MAX_RESPONSE_OUTPUT_TOKENS = 256

ACKNOWLEDGMENT_INSTRUCTIONS = (
    "You are the non-authoritative voice lane for an opportunity-analysis workspace. "
    "Generate a natural acknowledgment in no more than two short sentences. First "
    "acknowledge the user's intent without repeating it verbatim. Then describe only "
    "what you will analyze next, using future-process language such as 'I'll review' "
    "or 'I'll focus on'. You may name the requested analysis topic, but do not state "
    "or imply any finding, recommendation, conclusion, evidence result, confidence, "
    "business outcome, promise, or completed action. The working document, not your "
    "spoken response, is the authoritative analysis surface."
)


Connector = Callable[..., object]


class AzureVoiceLiveBroker:
    """Own credentials and the provider control channel for one browser call."""

    def __init__(
        self,
        settings: Settings,
        *,
        connector: Connector = connect,
        credential_factory: Callable[[], AsyncTokenCredential] | None = None,
    ) -> None:
        self._settings = settings
        self._connector = connector
        self._credential_factory = credential_factory or (
            lambda: create_default_async_credential(
                _required_tenant_id(self._settings)
            )
        )

    @property
    def available(self) -> bool:
        """Return whether complete validated Voice Live configuration is present."""

        return self._settings.voice_provider is VoiceProvider.AZURE_VOICE_LIVE

    @asynccontextmanager
    async def connect(
        self,
        sdp_offer: str,
    ) -> AsyncIterator[tuple[VoiceControlConnection, VoiceSessionAnswer]]:
        """Open the documented calls endpoint and exchange the browser SDP."""

        if not self.available:
            raise VoiceSessionBrokerError(
                "voice_disabled",
                "Voice is disabled. Use typed input or enable Voice Live configuration.",
                retryable=False,
            )
        if not sdp_offer.strip() or len(sdp_offer.encode("utf-8")) > MAX_CONTROL_BYTES:
            raise VoiceSessionBrokerError(
                "voice_protocol",
                "The voice negotiation request was rejected.",
                retryable=False,
            )

        credential = self._credential_factory()
        connections = AsyncExitStack()
        try:
            try:
                token = await credential.get_token(
                    VOICE_LIVE_SCOPE,
                    tenant_id=_required_tenant_id(self._settings),
                )
                uri = _control_uri(
                    self._settings.voice_endpoint,
                    self._settings.voice_model,
                )
                control = await connections.enter_async_context(
                    self._connector(
                        uri,
                        additional_headers={"Authorization": f"Bearer {token.token}"},
                        subprotocols=["realtime"],
                        max_size=MAX_CONTROL_BYTES,
                        open_timeout=10,
                        close_timeout=5,
                    )
                )
                await control.send(
                    json.dumps(
                        {
                            "type": "rtc.call.sdp.create",
                            "sdp_offer": sdp_offer,
                            "session": {
                                "modalities": ["text", "audio"],
                                "instructions": ACKNOWLEDGMENT_INSTRUCTIONS,
                                "input_audio_transcription": {
                                    "model": "azure-speech",
                                    "language": "en",
                                },
                                "turn_detection": {
                                    "type": "azure_semantic_vad",
                                    "create_response": True,
                                    "interrupt_response": True,
                                    "auto_truncate": True,
                                },
                                "temperature": 0.6,
                                "max_response_output_tokens": (
                                    MAX_RESPONSE_OUTPUT_TOKENS
                                ),
                            },
                        },
                        separators=(",", ":"),
                    )
                )
                answer = await _receive_answer(control)
            except VoiceSessionBrokerError:
                raise
            except ClientAuthenticationError:
                raise VoiceSessionBrokerError(
                    "voice_authentication",
                    "Voice authentication failed. Verify keyless access, then retry.",
                    retryable=True,
                ) from None
            except Exception:
                raise VoiceSessionBrokerError(
                    "voice_connection",
                    "Voice Live could not connect. Check access and configuration, then retry.",
                    retryable=True,
                ) from None
            yield control, answer
        finally:
            await connections.aclose()
            await credential.close()


async def _receive_answer(control: VoiceControlConnection) -> VoiceSessionAnswer:
    try:
        async with asyncio.timeout(30):
            async for raw_message in control:
                message = _parse_control_message(raw_message)
                message_type = message.get("type")
                if message_type == "rtc.call.sdp.created":
                    answer = message.get("sdp_answer")
                    if isinstance(answer, str) and answer.strip():
                        return VoiceSessionAnswer(sdp_answer=answer)
                    break
                if message_type in {"rtc.call.error", "error"}:
                    raise VoiceSessionBrokerError(
                        "voice_service",
                        "Voice Live rejected the session. Check access and configuration.",
                        retryable=True,
                    )
    except TimeoutError:
        raise VoiceSessionBrokerError(
            "voice_timeout",
            "Voice Live did not complete negotiation. Retry the connection.",
            retryable=True,
        ) from None
    raise VoiceSessionBrokerError(
        "voice_protocol",
        "Voice Live returned an invalid negotiation response.",
        retryable=True,
    )


def _parse_control_message(raw_message: str | bytes) -> dict[str, object]:
    if isinstance(raw_message, bytes):
        raise VoiceSessionBrokerError(
            "voice_protocol",
            "Voice Live returned an unsupported control message.",
            retryable=True,
        )
    try:
        value = json.loads(raw_message)
    except json.JSONDecodeError as error:
        raise VoiceSessionBrokerError(
            "voice_protocol",
            "Voice Live returned an invalid control message.",
            retryable=True,
        ) from error
    if not isinstance(value, dict):
        raise VoiceSessionBrokerError(
            "voice_protocol",
            "Voice Live returned an invalid control message.",
            retryable=True,
        )
    return value


def _control_uri(endpoint: str | None, model: str | None) -> str:
    if endpoint is None or model is None:
        raise VoiceSessionBrokerError(
            "voice_configuration",
            "Voice configuration is incomplete.",
            retryable=False,
        )
    parsed = urlsplit(endpoint)
    path = parsed.path.rstrip("/")
    if not path.endswith("/voice-live/realtime/calls"):
        path = f"{path}/voice-live/realtime/calls"
    query = urlencode({"api-version": VOICE_LIVE_API_VERSION, "model": model})
    return urlunsplit(("wss", parsed.netloc, path, query, ""))


def _required_tenant_id(settings: Settings) -> str:
    tenant_id = settings.azure_tenant_id
    if tenant_id is None:
        raise VoiceSessionBrokerError(
            "voice_configuration",
            "Voice identity configuration is incomplete.",
            retryable=False,
        )
    return tenant_id
