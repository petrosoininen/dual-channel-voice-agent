"""FastAPI lifespan shutdown coverage."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


def test_lifespan_finally_shuts_down_the_active_deep_work_service() -> None:
    class _DeepWork:
        def __init__(self) -> None:
            self.shutdown_called = False

        async def shutdown(self) -> None:
            self.shutdown_called = True

    app = create_app(environ={})
    deep_work = _DeepWork()
    app.state.deep_work = deep_work

    with TestClient(app):
        pass

    assert deep_work.shutdown_called is True
