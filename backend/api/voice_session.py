"""Same-origin broker for the Voice Live WebRTC control channel."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api.websocket_security import (
    VOICE_SUBPROTOCOL,
    authorize_websocket,
)
from backend.services.conversation_store import ConversationStore
from backend.providers.voice import (
    VoiceControlConnection,
    VoiceSessionBroker,
    VoiceSessionBrokerError,
)

router = APIRouter(prefix="/api", tags=["voice"])


@router.websocket("/voice/session/{session_id}")
async def voice_session(websocket: WebSocket, session_id: UUID) -> None:
    """Broker SDP and control without exposing credentials or provider URLs."""

    broker: VoiceSessionBroker = websocket.app.state.voice_broker
    store: ConversationStore = websocket.app.state.conversations
    if not await authorize_websocket(
        websocket,
        store=store,
        session_id=session_id,
        application_subprotocol=VOICE_SUBPROTOCOL,
    ):
        return
    await websocket.accept(subprotocol=VOICE_SUBPROTOCOL)
    try:
        request = await _receive_voice_message(websocket)
        if (
            set(request) != {"type", "sdpOffer"}
            or request.get("type") != "voice.session.start"
            or not isinstance(request.get("sdpOffer"), str)
        ):
            raise VoiceSessionBrokerError(
                "voice_protocol",
                "The voice negotiation request was rejected.",
                retryable=False,
            )
        async with broker.connect(request["sdpOffer"]) as (control, answer):
            await websocket.send_json(
                {
                    "type": "voice.session.answer",
                    "sdpAnswer": answer.sdp_answer,
                }
            )
            browser_monitor = asyncio.create_task(_reject_browser_controls(websocket))
            provider_monitor = asyncio.create_task(_monitor_provider(control))
            try:
                done, _ = await asyncio.wait(
                    {browser_monitor, provider_monitor},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    task.result()
            finally:
                browser_monitor.cancel()
                provider_monitor.cancel()
                await asyncio.gather(
                    browser_monitor,
                    provider_monitor,
                    return_exceptions=True,
                )
    except WebSocketDisconnect:
        return
    except VoiceSessionBrokerError as error:
        await websocket.send_json(
            {
                "type": "voice.session.error",
                "code": error.code,
                "message": str(error),
                "retryable": error.retryable,
            }
        )
        await websocket.close(code=1011)


async def _reject_browser_controls(websocket: WebSocket) -> None:
    """Reject browser control messages; response cancellation uses WebRTC data."""

    while True:
        await _receive_voice_message(websocket)
        raise VoiceSessionBrokerError(
            "voice_protocol",
            "Browser-supplied Voice Live controls are not allowed.",
            retryable=False,
        )


async def _monitor_provider(control: VoiceControlConnection) -> None:
    """Consume control events while converting provider failures to safe errors."""

    async for raw_event in control:
        if (
            not isinstance(raw_event, str)
            or len(raw_event.encode("utf-8")) > 65_536
        ):
            raise VoiceSessionBrokerError(
                "voice_protocol",
                "Voice Live returned an invalid control message.",
                retryable=True,
            )
        try:
            event = json.loads(raw_event)
        except json.JSONDecodeError as error:
            raise VoiceSessionBrokerError(
                "voice_protocol",
                "Voice Live returned an invalid control message.",
                retryable=True,
            ) from error
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise VoiceSessionBrokerError(
                "voice_protocol",
                "Voice Live returned an invalid control message.",
                retryable=True,
            )
        if event["type"] in {"rtc.call.error", "error"}:
            raise VoiceSessionBrokerError(
                "voice_service",
                "Voice Live reported a session error. Stop the session and retry.",
                retryable=True,
            )


async def _receive_voice_message(websocket: WebSocket) -> dict[str, object]:
    """Receive one bounded JSON control object; audio frames are never accepted."""

    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(code=message.get("code", 1000))
    raw = message.get("text")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 65_536:
        raise VoiceSessionBrokerError(
            "voice_protocol",
            "The voice control request was rejected.",
            retryable=False,
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise VoiceSessionBrokerError(
            "voice_protocol",
            "The voice control request was rejected.",
            retryable=False,
        ) from error
    if not isinstance(value, dict):
        raise VoiceSessionBrokerError(
            "voice_protocol",
            "The voice control request was rejected.",
            retryable=False,
        )
    return value
