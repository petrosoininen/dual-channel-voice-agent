"""App transport, Voice Live broker, and privacy tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Self
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from backend.config import AgentProvider, Settings, VoiceProvider
from backend.main import create_app
from backend.providers.voice.azure_voice_live import (
    ACKNOWLEDGMENT_INSTRUCTIONS,
    AzureVoiceLiveBroker,
    MAX_RESPONSE_OUTPUT_TOKENS,
)
from backend.providers.voice import VoiceSessionAnswer
from backend.telemetry import TelemetryRecorder

ORIGIN_HEADERS = {"origin": "http://testserver"}


def _session(client: TestClient) -> tuple[str, str]:
    response = client.post("/api/sessions").json()
    return response["sessionId"], response["sessionToken"]


def _app_protocols(token: str) -> list[str]:
    return ["dcr-app-events.v1", f"dcr-session.{token}"]


def _voice_protocols(token: str) -> list[str]:
    return ["dcr-voice.v1", f"dcr-session.{token}"]


def test_session_creation_returns_unique_non_cacheable_handshake_secrets() -> None:
    app = create_app(environ={})
    with TestClient(app) as client:
        first = client.post("/api/sessions")
        second = client.post("/api/sessions")

    assert first.headers["cache-control"] == "no-store"
    assert second.headers["cache-control"] == "no-store"
    assert set(first.json()) == {"sessionId", "sessionToken"}
    assert len(first.json()["sessionToken"]) == 43
    assert first.json()["sessionToken"] != second.json()["sessionToken"]
    assert not first.request.url.query


def test_app_websocket_replays_commit_after_disconnect() -> None:
    app = create_app(environ={})
    with TestClient(app) as client:
        session_id, token = _session(client)
        turn_id = str(uuid4())
        command = {
            "type": "turn.submit",
            "commandId": str(uuid4()),
            "idempotencyKey": str(uuid4()),
            "sessionId": session_id,
            "turnId": turn_id,
            "timestamp": "2026-03-20T10:00:00Z",
            "inputMode": "typed",
            "transcript": (
                "Review this fictional project and identify the strongest "
                "expansion opportunity."
            ),
        }
        with client.websocket_connect(
            f"/api/app-events/{session_id}",
            headers=dict(ORIGIN_HEADERS),
            subprotocols=_app_protocols(token),
        ) as socket:
            socket.send_json(command)
            assert socket.receive_json()["type"] == "turn.started"
            socket.close()

        with client.websocket_connect(
            f"/api/app-events/{session_id}",
            headers=dict(ORIGIN_HEADERS),
            subprotocols=_app_protocols(token),
        ) as socket:
            replay = []
            while "turn.completed" not in replay:
                replay.append(socket.receive_json()["type"])
            assert replay[0] == "turn.started"
            assert "document.committed" in replay
            assert replay[-1] == "turn.completed"
            socket.close()


def test_app_websocket_validates_commands_after_replay() -> None:
    app = create_app(environ={})
    with TestClient(app) as client:
        session_id, token = _session(client)
        with client.websocket_connect(
            f"/api/app-events/{session_id}",
            headers=dict(ORIGIN_HEADERS),
            subprotocols=_app_protocols(token),
        ) as socket:
            socket.send_json({"type": "turn.submit", "unexpected": True})
            error = socket.receive_json()
            assert error == {
                "type": "transport.error",
                "code": "command_rejected",
                "message": "The command was rejected. Review the action and retry.",
                "retryable": False,
            }
            socket.close()


def test_app_websocket_rejects_binary_frames_without_accepting_audio() -> None:
    app = create_app(environ={})
    with TestClient(app) as client:
        session_id, token = _session(client)
        with client.websocket_connect(
            f"/api/app-events/{session_id}",
            headers=dict(ORIGIN_HEADERS),
            subprotocols=_app_protocols(token),
        ) as socket:
            socket.send_bytes(b"not-application-json")
            error = socket.receive_json()
            assert error["type"] == "transport.error"
            assert error["code"] == "command_rejected"


def test_voice_disabled_error_is_sanitized() -> None:
    app = create_app(environ={})
    with TestClient(app) as client:
        session_id, token = _session(client)
        with client.websocket_connect(
            f"/api/voice/session/{session_id}",
            headers=dict(ORIGIN_HEADERS),
            subprotocols=_voice_protocols(token),
        ) as socket:
            socket.send_json(
                {
                    "type": "voice.session.start",
                    "sdpOffer": "synthetic-offer",
                }
            )
            response = socket.receive_json()
            assert response["type"] == "voice.session.error"
            assert response["code"] == "voice_disabled"
            serialized = json.dumps(response).lower()
            assert "endpoint" not in serialized
            assert "token" not in serialized
            assert "tenant" not in serialized


@pytest.mark.parametrize(
    ("path_kind", "headers", "token_mode"),
    [
        ("app", {"origin": "https://foreign.invalid"}, "valid"),
        ("app", {"origin": "http://testserver", "host": "foreign.invalid"}, "valid"),
        ("app", ORIGIN_HEADERS, "missing"),
        ("app", ORIGIN_HEADERS, "foreign"),
        ("voice", {"origin": "https://foreign.invalid"}, "valid"),
        ("voice", ORIGIN_HEADERS, "missing"),
        ("voice", ORIGIN_HEADERS, "foreign"),
    ],
)
def test_websocket_routes_reject_untrusted_handshakes(
    path_kind: str,
    headers: dict[str, str],
    token_mode: str,
) -> None:
    app = create_app(environ={})
    with TestClient(app) as client:
        session_id, token = _session(client)
        selected_token = token if token_mode == "valid" else "A" * 43
        protocols = (
            _app_protocols(selected_token)
            if path_kind == "app"
            else _voice_protocols(selected_token)
        )
        if token_mode == "missing":
            protocols = protocols[:1]
        path = (
            f"/api/app-events/{session_id}"
            if path_kind == "app"
            else f"/api/voice/session/{session_id}"
        )
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(
                path,
                headers=dict(headers),
                subprotocols=protocols,
            ):
                pass
        assert closed.value.code == 4403


@dataclass
class _Token:
    token: str = "synthetic-token-value"


@dataclass
class _Credential:
    closed: bool = False

    async def get_token(
        self,
        scope: str,
        *,
        tenant_id: str | None = None,
    ) -> _Token:
        assert scope == "https://ai.azure.com/.default"
        assert tenant_id == "00000000-0000-4000-8000-000000000001"
        return _Token()

    async def close(self) -> None:
        self.closed = True


@dataclass
class _Control:
    sent: list[str] = field(default_factory=list)
    yielded: bool = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> str:
        if self.yielded:
            raise StopAsyncIteration
        self.yielded = True
        return json.dumps(
            {
                "type": "rtc.call.sdp.created",
                "sdp_answer": "synthetic-answer",
            }
        )


@dataclass
class _RouteControl:
    sent: list[str] = field(default_factory=list)

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self) -> "_RouteControl":
        return self

    async def __anext__(self) -> str:
        await asyncio.Event().wait()
        raise StopAsyncIteration


class _RouteBroker:
    def __init__(self, control: _RouteControl) -> None:
        self.control = control

    @asynccontextmanager
    async def connect(
        self,
        sdp_offer: str,
    ) -> AsyncIterator[tuple[_RouteControl, VoiceSessionAnswer]]:
        assert sdp_offer == "synthetic-offer"
        yield self.control, VoiceSessionAnswer(sdp_answer="synthetic-answer")


def test_voice_route_rejects_browser_supplied_provider_controls() -> None:
    app = create_app(environ={})
    control = _RouteControl()
    app.state.voice_broker = _RouteBroker(control)
    with TestClient(app) as client:
        session_id, token = _session(client)
        with client.websocket_connect(
            f"/api/voice/session/{session_id}",
            headers=dict(ORIGIN_HEADERS),
            subprotocols=_voice_protocols(token),
        ) as socket:
            socket.send_json(
                {
                    "type": "voice.session.start",
                    "sdpOffer": "synthetic-offer",
                }
            )
            assert socket.receive_json()["type"] == "voice.session.answer"
            socket.send_json(
                {
                    "type": "voice.control",
                    "event": {
                        "type": "session.update",
                        "instructions": "Untrusted browser override.",
                    },
                }
            )
            response = socket.receive_json()
            assert response["type"] == "voice.session.error"
            assert response["code"] == "voice_protocol"
            assert control.sent == []


def test_voice_broker_uses_documented_flow_without_exposing_bootstrap() -> None:
    captured: dict[str, object] = {}
    control = _Control()

    @asynccontextmanager
    async def connector(uri: str, **kwargs: object) -> AsyncIterator[_Control]:
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        yield control

    settings = Settings(
        agent_provider=AgentProvider.DETERMINISTIC,
        voice_provider=VoiceProvider.AZURE_VOICE_LIVE,
        azure_token_credentials="AzureCliCredential",
        azure_tenant_id="00000000-0000-4000-8000-000000000001",
        voice_endpoint="https://<resource-name>.services.ai.azure.com",
        voice_model="synthetic-model",
    )
    broker = AzureVoiceLiveBroker(
        settings,
        connector=connector,
        credential_factory=_Credential,
    )

    async def negotiate() -> None:
        async with broker.connect("synthetic-offer") as (_, answer):
            assert answer.sdp_answer == "synthetic-answer"

    import asyncio

    asyncio.run(negotiate())
    request = json.loads(control.sent[0])
    assert request["type"] == "rtc.call.sdp.create"
    assert request["session"]["turn_detection"] == {
        "type": "azure_semantic_vad",
        "create_response": True,
        "interrupt_response": True,
        "auto_truncate": True,
    }
    assert request["session"]["temperature"] == 0.6
    assert request["session"]["max_response_output_tokens"] == 256
    assert request["session"]["max_response_output_tokens"] == (
        MAX_RESPONSE_OUTPUT_TOKENS
    )
    assert request["session"]["instructions"] == ACKNOWLEDGMENT_INSTRUCTIONS
    assert request["session"]["input_audio_transcription"] == {
        "model": "azure-speech",
        "language": "en",
    }
    assert "/voice-live/realtime/calls?" in str(captured["uri"])
    assert "api-version=2026-01-01-preview" in str(captured["uri"])
    assert "synthetic-token-value" not in json.dumps(request)
    headers = captured["kwargs"]["additional_headers"]
    assert headers == {"Authorization": "Bearer " + _Token().token}


def test_voice_broker_does_not_reclassify_browser_disconnect() -> None:
    control = _Control()

    @asynccontextmanager
    async def connector(uri: str, **kwargs: object) -> AsyncIterator[_Control]:
        del uri, kwargs
        yield control

    broker = AzureVoiceLiveBroker(
        Settings(
            agent_provider=AgentProvider.DETERMINISTIC,
            voice_provider=VoiceProvider.AZURE_VOICE_LIVE,
            azure_token_credentials="AzureCliCredential",
            azure_tenant_id="00000000-0000-4000-8000-000000000001",
            voice_endpoint="https://<resource-name>.services.ai.azure.com",
            voice_model="synthetic-model",
        ),
        connector=connector,
        credential_factory=_Credential,
    )

    async def disconnect() -> None:
        with pytest.raises(WebSocketDisconnect):
            async with broker.connect("synthetic-offer"):
                raise WebSocketDisconnect(code=1000)

    import asyncio

    asyncio.run(disconnect())


def test_telemetry_rejects_payload_like_fields() -> None:
    recorder = TelemetryRecorder()
    recorder.record("speech_ended", turn_id=uuid4())
    assert len(recorder.snapshot()) == 1
    try:
        recorder.record("transcript", outcome="synthetic")
    except ValueError as error:
        assert str(error) == "Telemetry event is not allowlisted."
    else:
        raise AssertionError("Unknown telemetry event was accepted.")
