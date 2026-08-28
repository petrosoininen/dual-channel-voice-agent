"""Health and capabilities route tests."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from backend.main import create_app


def _get(path: str) -> Response:
    async def request() -> Response:
        transport = ASGITransport(app=create_app(environ={}))
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_health_is_content_free() -> None:
    response = _get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "state_persistence": "process-memory-only",
    }


def test_provider_capabilities_do_not_expose_configuration() -> None:
    response = _get("/api/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "agentProvider": "deterministic",
        "voiceProvider": "off",
        "deepWorkAvailable": True,
        "voiceAvailable": False,
        "voiceTransport": "disabled",
        "voiceTransportPreview": False,
        "statePersistence": "process-memory-only",
    }
    serialized = response.text.lower()
    assert "endpoint" not in serialized
    assert "tenant" not in serialized
    assert "token" not in serialized
