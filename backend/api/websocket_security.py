"""Shared fail-closed authorization for local browser WebSocket handshakes."""

from __future__ import annotations

from uuid import UUID

from fastapi import WebSocket

from backend.services.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
)

APP_EVENTS_SUBPROTOCOL = "dcr-app-events.v1"
VOICE_SUBPROTOCOL = "dcr-voice.v1"
SESSION_TOKEN_SUBPROTOCOL_PREFIX = "dcr-session."
TRUSTED_ORIGINS = frozenset(
    {
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5184",
        "http://127.0.0.1:8100",
        "http://127.0.0.1:8110",
        "http://testserver",
    }
)
TRUSTED_HOSTS = frozenset(
    {
        "127.0.0.1:5174",
        "127.0.0.1:5184",
        "127.0.0.1:8100",
        "127.0.0.1:8110",
        "testserver",
    }
)


async def authorize_websocket(
    websocket: WebSocket,
    *,
    store: ConversationStore,
    session_id: UUID,
    application_subprotocol: str,
) -> bool:
    """Validate local origin, host, session existence, and its secret token."""

    if (
        websocket.headers.get("origin") not in TRUSTED_ORIGINS
        or websocket.headers.get("host") not in TRUSTED_HOSTS
    ):
        await websocket.close(code=4403, reason="WebSocket handshake rejected.")
        return False

    try:
        store.turns(session_id)
    except ConversationNotFoundError:
        await websocket.close(code=4404, reason="Application session is unavailable.")
        return False

    offered = tuple(websocket.scope.get("subprotocols", ()))
    token_protocols = tuple(
        protocol
        for protocol in offered
        if protocol.startswith(SESSION_TOKEN_SUBPROTOCOL_PREFIX)
    )
    if (
        offered.count(application_subprotocol) != 1
        or len(token_protocols) != 1
        or len(offered) != 2
    ):
        await websocket.close(code=4403, reason="WebSocket handshake rejected.")
        return False

    presented_token = token_protocols[0][len(SESSION_TOKEN_SUBPROTOCOL_PREFIX) :]
    if not presented_token or not store.authorize_session(
        session_id,
        presented_token,
    ):
        await websocket.close(code=4403, reason="WebSocket handshake rejected.")
        return False
    return True
