"""Same-origin application WebSocket for validated commands and events."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.api.websocket_security import (
    APP_EVENTS_SUBPROTOCOL,
    authorize_websocket,
)
from backend.domain.events import (
    ContractValidationError,
    DocumentRevertCommand,
    MAX_WIRE_BYTES,
    TurnCancelCommand,
    TurnSubmitCommand,
    VoiceAcknowledgmentCommand,
    VoiceCompleteCommand,
    VoiceInterruptCommand,
    VoiceStartCommand,
    validate_command,
)
from backend.services.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
)
from backend.services.deep_work_service import DeepWorkConflictError, DeepWorkService
from backend.services.event_hub import AppEventHub, AppEventSubscription
from backend.services.patch_service import PatchValidationError
from backend.telemetry import TelemetryRecorder

router = APIRouter(prefix="/api", tags=["application-events"])


class SessionResponse(BaseModel):
    """App-owned identity and process-memory WebSocket authorization secret."""

    sessionId: UUID
    sessionToken: str = Field(repr=False)


@router.post("/sessions", response_model=SessionResponse)
def create_session(request: Request, response: Response) -> SessionResponse:
    """Create one empty process-memory conversation."""

    store: ConversationStore = request.app.state.conversations
    session_id = store.create_session()
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(
        sessionId=session_id,
        sessionToken=store.session_authorization_token(session_id),
    )


@router.websocket("/app-events/{session_id}")
async def app_events(websocket: WebSocket, session_id: UUID) -> None:
    """Receive authorized commands and deliver replay plus ordered live events."""

    store: ConversationStore = websocket.app.state.conversations
    service: DeepWorkService = websocket.app.state.deep_work
    hub: AppEventHub = websocket.app.state.event_hub
    telemetry: TelemetryRecorder = websocket.app.state.telemetry
    if not await authorize_websocket(
        websocket,
        store=store,
        session_id=session_id,
        application_subprotocol=APP_EVENTS_SUBPROTOCOL,
    ):
        return

    await websocket.accept(subprotocol=APP_EVENTS_SUBPROTOCOL)
    telemetry.record("app_transport_connected", session_id=session_id)
    async with hub.subscribe(session_id) as subscription:
        sender = asyncio.create_task(_send_events(websocket, subscription))
        try:
            await _receive_commands(websocket, session_id, service)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            telemetry.record("app_transport_disconnected", session_id=session_id)


async def _receive_commands(
    websocket: WebSocket,
    session_id: UUID,
    service: DeepWorkService,
) -> None:
    while True:
        try:
            payload = await _receive_json_object(websocket)
            command = validate_command(payload)
            if command.session_id != session_id:
                raise ContractValidationError("Command session is invalid.")
            if isinstance(command, TurnSubmitCommand):
                await service.submit(command)
            elif isinstance(command, TurnCancelCommand):
                await service.cancel(command)
            elif isinstance(command, VoiceStartCommand):
                await service.start_voice(command)
            elif isinstance(command, VoiceAcknowledgmentCommand):
                await service.acknowledge_voice(command)
            elif isinstance(command, VoiceCompleteCommand):
                await service.complete_voice(command)
            elif isinstance(command, VoiceInterruptCommand):
                await service.interrupt_voice(command)
            elif isinstance(command, DocumentRevertCommand):
                await service.revert(command)
        except (
            ContractValidationError,
            ConversationNotFoundError,
            DeepWorkConflictError,
            PatchValidationError,
        ):
            await websocket.send_json(
                {
                    "type": "transport.error",
                    "code": "command_rejected",
                    "message": "The command was rejected. Review the action and retry.",
                    "retryable": False,
                }
            )


async def _send_events(
    websocket: WebSocket,
    subscription: AppEventSubscription,
) -> None:
    for event in subscription.replay:
        await websocket.send_json(event)
    while True:
        if subscription.overflowed.is_set():
            await websocket.close(
                code=4409,
                reason="Event replay is required.",
            )
            return
        event = await subscription.queue.get()
        await websocket.send_json(event)


async def _receive_json_object(websocket: WebSocket) -> dict[str, object]:
    """Receive one bounded text JSON object and reject binary application frames."""

    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(code=message.get("code", 1000))
    raw = message.get("text")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_WIRE_BYTES:
        raise ContractValidationError("Application command frame is invalid.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ContractValidationError("Application command JSON is invalid.") from error
    if not isinstance(value, dict):
        raise ContractValidationError("Application command must be an object.")
    return value
