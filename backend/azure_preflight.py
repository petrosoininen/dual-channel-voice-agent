"""Safe local keyless-identity preflight with content-free results."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Protocol

from backend.azure_identity import create_default_credential
from backend.config import (
    AZURE_TENANT_ID_VARIABLE,
    AZURE_TOKEN_CREDENTIALS_VARIABLE,
    FOUNDRY_VARIABLES,
    LIVE_IDENTITY_VARIABLES,
    REQUIRED_AZURE_TOKEN_CREDENTIAL,
    VOICE_VARIABLES,
    is_tenant_id,
)

VOICE_SCOPE = "https://cognitiveservices.azure.com/.default"
FOUNDRY_SCOPE = "https://ai.azure.com/.default"


class TokenCredential(Protocol):
    """Minimum credential behavior used by the preflight."""

    def __enter__(self) -> TokenCredential:
        """Enter credential lifetime."""

        ...

    def __exit__(self, *args: object) -> None:
        """Close credential lifetime."""

        ...

    def get_token(
        self,
        *scopes: str,
        tenant_id: str | None = None,
    ) -> object:
        """Acquire a token without exposing it to the caller."""

        ...


@dataclass(frozen=True)
class AzurePreflightResult:
    """Sanitized booleans and missing variable names only."""

    voice_identity_available: bool
    foundry_identity_available: bool
    voice_configuration_ready: bool
    foundry_configuration_ready: bool
    missing_voice_variables: tuple[str, ...]
    missing_foundry_variables: tuple[str, ...]
    missing_identity_variables: tuple[str, ...]
    invalid_identity_variables: tuple[str, ...]
    resource_access_verified: bool
    status: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe result with no credential or resource values."""

        return asdict(self)


def run_azure_preflight(
    environ: Mapping[str, str],
    *,
    credential_factory: Callable[[], TokenCredential] | None = None,
) -> AzurePreflightResult:
    """Check local keyless token acquisition without calling project resources."""

    missing_voice = _missing(environ, VOICE_VARIABLES)
    missing_foundry = _missing(environ, FOUNDRY_VARIABLES)
    missing_identity = _missing(environ, LIVE_IDENTITY_VARIABLES)
    invalid_identity = _invalid_identity(environ, missing_identity)
    tenant_id = environ.get(AZURE_TENANT_ID_VARIABLE, "").strip()

    voice_identity_available = False
    foundry_identity_available = False
    if not missing_identity and not invalid_identity:
        factory = credential_factory or (
            lambda: create_default_credential(tenant_id)
        )
        try:
            with factory() as credential:
                voice_identity_available = _can_get_token(
                    credential,
                    VOICE_SCOPE,
                    tenant_id=tenant_id,
                )
                foundry_identity_available = _can_get_token(
                    credential,
                    FOUNDRY_SCOPE,
                    tenant_id=tenant_id,
                )
        except Exception:
            # This process boundary intentionally suppresses provider diagnostics
            # because they can include configuration or identity details.
            pass

    configuration_ready = (
        not missing_voice
        and not missing_foundry
        and not missing_identity
        and not invalid_identity
    )
    identity_ready = voice_identity_available and foundry_identity_available
    status = "ready-for-resource-smoke" if configuration_ready and identity_ready else "incomplete"
    return AzurePreflightResult(
        voice_identity_available=voice_identity_available,
        foundry_identity_available=foundry_identity_available,
        voice_configuration_ready=not missing_voice,
        foundry_configuration_ready=not missing_foundry,
        missing_voice_variables=missing_voice,
        missing_foundry_variables=missing_foundry,
        missing_identity_variables=missing_identity,
        invalid_identity_variables=invalid_identity,
        resource_access_verified=False,
        status=status,
    )


def _can_get_token(
    credential: TokenCredential,
    scope: str,
    *,
    tenant_id: str,
) -> bool:
    try:
        credential.get_token(scope, tenant_id=tenant_id)
    except Exception:
        return False
    return True


def _missing(environ: Mapping[str, str], variables: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in variables if not environ.get(name, "").strip())


def _invalid_identity(
    environ: Mapping[str, str],
    missing: tuple[str, ...],
) -> tuple[str, ...]:
    invalid: list[str] = []
    if (
        AZURE_TOKEN_CREDENTIALS_VARIABLE not in missing
        and environ.get(AZURE_TOKEN_CREDENTIALS_VARIABLE, "").strip()
        != REQUIRED_AZURE_TOKEN_CREDENTIAL
    ):
        invalid.append(AZURE_TOKEN_CREDENTIALS_VARIABLE)
    if (
        AZURE_TENANT_ID_VARIABLE not in missing
        and not is_tenant_id(
            environ.get(AZURE_TENANT_ID_VARIABLE, "").strip()
        )
    ):
        invalid.append(AZURE_TENANT_ID_VARIABLE)
    return tuple(invalid)
