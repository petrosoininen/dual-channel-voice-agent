"""Fail-closed credential construction and tenant-binding tests."""

from __future__ import annotations

import asyncio

from azure.core.credentials import AccessToken

from backend.azure_identity import (
    create_default_async_credential,
    create_default_credential,
)

TENANT_ID = "00000000-0000-4000-8000-000000000001"


def test_sync_default_credential_requires_selector_and_binds_tenant(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _Credential:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def get_token(self, *scopes: str, **kwargs: object) -> AccessToken:
            captured["scopes"] = scopes
            captured["token_options"] = kwargs
            return AccessToken("synthetic", 1)

    def factory(**kwargs: object) -> _Credential:
        captured["constructor"] = kwargs
        return _Credential()

    monkeypatch.setattr("backend.azure_identity.DefaultAzureCredential", factory)
    with create_default_credential(TENANT_ID) as credential:
        credential.get_token("https://example.invalid/.default")

    assert captured["constructor"] == {
        "exclude_interactive_browser_credential": True,
        "process_timeout": 30,
        "require_envvar": True,
    }
    assert captured["token_options"]["tenant_id"] == TENANT_ID


def test_async_default_credential_requires_selector_and_binds_tenant(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _Credential:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def close(self) -> None:
            return None

        async def get_token(
            self,
            *scopes: str,
            **kwargs: object,
        ) -> AccessToken:
            captured["scopes"] = scopes
            captured["token_options"] = kwargs
            return AccessToken("synthetic", 1)

    def factory(**kwargs: object) -> _Credential:
        captured["constructor"] = kwargs
        return _Credential()

    monkeypatch.setattr(
        "backend.azure_identity.AsyncDefaultAzureCredential",
        factory,
    )

    async def scenario() -> None:
        async with create_default_async_credential(TENANT_ID) as credential:
            await credential.get_token("https://example.invalid/.default")

    asyncio.run(scenario())
    assert captured["constructor"] == {
        "exclude_interactive_browser_credential": True,
        "process_timeout": 30,
        "require_envvar": True,
    }
    assert captured["token_options"]["tenant_id"] == TENANT_ID
