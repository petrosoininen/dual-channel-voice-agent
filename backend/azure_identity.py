"""Tenant-bound keyless credential constructors for live Azure call paths."""

from __future__ import annotations

from types import TracebackType
from typing import Any

from azure.core.credentials import (
    AccessToken,
    AccessTokenInfo,
    TokenCredential,
    TokenRequestOptions,
)
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

AZURE_CLI_PROCESS_TIMEOUT_SECONDS = 30


class TenantBoundCredential:
    """Force every synchronous token request into one validated tenant."""

    def __init__(self, credential: TokenCredential, tenant_id: str) -> None:
        self._credential = credential
        self._tenant_id = tenant_id

    def __enter__(self) -> TenantBoundCredential:
        self._credential.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._credential.__exit__(exc_type, exc_value, traceback)

    def get_token(
        self,
        *scopes: str,
        claims: str | None = None,
        tenant_id: str | None = None,
        enable_cae: bool = False,
        **kwargs: Any,
    ) -> AccessToken:
        """Acquire a token only for the configured tenant."""

        del tenant_id
        return self._credential.get_token(
            *scopes,
            claims=claims,
            tenant_id=self._tenant_id,
            enable_cae=enable_cae,
            **kwargs,
        )

    def get_token_info(
        self,
        *scopes: str,
        options: TokenRequestOptions | None = None,
    ) -> AccessTokenInfo:
        """Acquire token metadata only for the configured tenant."""

        bounded_options: TokenRequestOptions = dict(options or {})
        bounded_options["tenant_id"] = self._tenant_id
        credential = self._credential
        if not hasattr(credential, "get_token_info"):
            token = self.get_token(*scopes, **bounded_options)
            return AccessTokenInfo(token.token, token.expires_on)
        return credential.get_token_info(*scopes, options=bounded_options)


class TenantBoundAsyncCredential:
    """Force every asynchronous token request into one validated tenant."""

    def __init__(
        self,
        credential: AsyncTokenCredential,
        tenant_id: str,
    ) -> None:
        self._credential = credential
        self._tenant_id = tenant_id

    async def __aenter__(self) -> TenantBoundAsyncCredential:
        await self._credential.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._credential.__aexit__(exc_type, exc_value, traceback)

    async def close(self) -> None:
        """Release the underlying credential transport."""

        await self._credential.close()

    async def get_token(
        self,
        *scopes: str,
        claims: str | None = None,
        tenant_id: str | None = None,
        enable_cae: bool = False,
        **kwargs: Any,
    ) -> AccessToken:
        """Acquire a token only for the configured tenant."""

        del tenant_id
        return await self._credential.get_token(
            *scopes,
            claims=claims,
            tenant_id=self._tenant_id,
            enable_cae=enable_cae,
            **kwargs,
        )

    async def get_token_info(
        self,
        *scopes: str,
        options: TokenRequestOptions | None = None,
    ) -> AccessTokenInfo:
        """Acquire token metadata only for the configured tenant."""

        bounded_options: TokenRequestOptions = dict(options or {})
        bounded_options["tenant_id"] = self._tenant_id
        credential = self._credential
        if not hasattr(credential, "get_token_info"):
            token = await self.get_token(*scopes, **bounded_options)
            return AccessTokenInfo(token.token, token.expires_on)
        return await credential.get_token_info(*scopes, options=bounded_options)


def create_default_credential(tenant_id: str) -> TenantBoundCredential:
    """Create the required keyless local credential with a tenant-bound wrapper."""

    credential = DefaultAzureCredential(
        exclude_interactive_browser_credential=True,
        process_timeout=AZURE_CLI_PROCESS_TIMEOUT_SECONDS,
        require_envvar=True,
    )
    return TenantBoundCredential(credential, tenant_id)


def create_default_async_credential(
    tenant_id: str,
) -> TenantBoundAsyncCredential:
    """Create the required async keyless credential with a tenant-bound wrapper."""

    credential = AsyncDefaultAzureCredential(
        exclude_interactive_browser_credential=True,
        process_timeout=AZURE_CLI_PROCESS_TIMEOUT_SECONDS,
        require_envvar=True,
    )
    return TenantBoundAsyncCredential(credential, tenant_id)
