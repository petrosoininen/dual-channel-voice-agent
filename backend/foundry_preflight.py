"""Read-only Foundry project and Prompt Agent compatibility diagnostics."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

from backend.azure_identity import create_default_async_credential
from backend.config import (
    AZURE_TENANT_ID_VARIABLE,
    AZURE_TOKEN_CREDENTIALS_VARIABLE,
    FOUNDRY_AGENT_VARIABLES,
    FOUNDRY_ENDPOINT_VARIABLE,
    FOUNDRY_VARIABLES,
    LIVE_IDENTITY_VARIABLES,
    REQUIRED_AZURE_TOKEN_CREDENTIAL,
    is_tenant_id,
)
from backend.deep_work.foundry import (
    _classify_agent_definition,
    resolve_prompt_agent,
)

FOUNDRY_SCOPE = "https://ai.azure.com/.default"


@dataclass(frozen=True)
class FoundryPreflightResult:
    """Sanitized booleans, counts, classifications, and missing names only."""

    identity_available: bool
    project_access_verified: bool
    prompt_agent_count: int | None
    configured_agent_verified: bool
    resolved_agent_verified: bool
    selection_source: str | None
    compatible: bool | None
    missing_variables: tuple[str, ...]
    invalid_variables: tuple[str, ...]
    error_classification: str | None
    status: str

    def to_dict(self) -> dict[str, object]:
        """Return the content-free public diagnostics contract."""

        return asdict(self)


async def run_foundry_preflight(
    environ: Mapping[str, str],
    *,
    credential_factory: Callable[[], object] | None = None,
    project_client_factory: Callable[..., object] | None = None,
) -> FoundryPreflightResult:
    """Exhaust safe read-only diagnostics without exposing configuration values."""

    from azure.ai.projects.aio import AIProjectClient

    endpoint = _setting(environ, FOUNDRY_ENDPOINT_VARIABLE)
    agent_name = _setting(environ, FOUNDRY_AGENT_VARIABLES[0])
    agent_version = _setting(environ, FOUNDRY_AGENT_VARIABLES[1])
    missing = (
        *_missing_configuration(endpoint, agent_name, agent_version),
        *(
            name
            for name in LIVE_IDENTITY_VARIABLES
            if _setting(environ, name) is None
        ),
    )
    missing = tuple(dict.fromkeys(missing))
    invalid = _invalid_identity(environ, missing)
    tenant_id = _setting(environ, AZURE_TENANT_ID_VARIABLE)
    identity_available = False
    project_access_verified = False
    prompt_agent_count: int | None = None
    configured_agent_verified = False
    resolved_agent_verified = False
    selection_source: str | None = None
    compatible: bool | None = None
    error_classification: str | None = None

    if endpoint is None or missing or invalid or tenant_id is None:
        return FoundryPreflightResult(
            identity_available=False,
            project_access_verified=False,
            prompt_agent_count=None,
            configured_agent_verified=False,
            resolved_agent_verified=False,
            selection_source=None,
            compatible=None,
            missing_variables=missing,
            invalid_variables=invalid,
            error_classification=None,
            status="incomplete_configuration",
        )

    create_credential = credential_factory or (
        lambda: create_default_async_credential(tenant_id)
    )
    create_client = project_client_factory or AIProjectClient
    try:
        credential = create_credential()
        async with credential:
            await credential.get_token(
                FOUNDRY_SCOPE,
                tenant_id=tenant_id,
            )
            identity_available = True
            async with create_client(
                endpoint=endpoint,
                credential=credential,
            ) as project_client:
                agents = project_client.agents.list(
                    kind="prompt",
                    limit=100,
                    order="desc",
                )
                prompt_agent_count = 0
                async for _ in agents:
                    prompt_agent_count += 1
                project_access_verified = True

                if not missing:
                    selected = await resolve_prompt_agent(
                        project_client,
                        agent_name=agent_name,
                        agent_version=agent_version,
                    )
                    if selected is not None:
                        resolved_agent_verified = True
                        selection_source = selected.source
                        configured_agent_verified = selected.source == "configured"
                        compatible = _classify_agent_definition(
                            selected.details
                        ).compatible
    except Exception as error:
        error_classification = _classify_error(error)

    if missing:
        status = "incomplete_configuration"
    elif compatible is True:
        status = "compatible"
    elif agent_name is None and agent_version is None and project_access_verified:
        status = "no_compatible_agent"
    elif configured_agent_verified:
        status = "incompatible"
    else:
        status = "unavailable"
    return FoundryPreflightResult(
        identity_available=identity_available,
        project_access_verified=project_access_verified,
        prompt_agent_count=prompt_agent_count,
        configured_agent_verified=configured_agent_verified,
        resolved_agent_verified=resolved_agent_verified,
        selection_source=selection_source,
        compatible=compatible,
        missing_variables=missing,
        invalid_variables=invalid,
        error_classification=error_classification,
        status=status,
    )


def _classify_error(error: Exception) -> str:
    from azure.core.exceptions import (
        ClientAuthenticationError,
        HttpResponseError,
        ServiceRequestError,
    )

    if isinstance(error, ClientAuthenticationError):
        return "authentication"
    if isinstance(error, ServiceRequestError):
        return "network"
    if isinstance(error, HttpResponseError):
        return {
            401: "authentication",
            403: "permission",
            404: "not_found",
            429: "rate_or_quota",
        }.get(error.status_code or 0, "service")
    return "provider"


def _setting(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name, "").strip()
    return value or None


def _missing_configuration(
    endpoint: str | None,
    agent_name: str | None,
    agent_version: str | None,
) -> tuple[str, ...]:
    missing: list[str] = []
    if endpoint is None:
        missing.append(FOUNDRY_ENDPOINT_VARIABLE)
    if (agent_name is None) != (agent_version is None):
        missing.append(
            FOUNDRY_AGENT_VARIABLES[0]
            if agent_name is None
            else FOUNDRY_AGENT_VARIABLES[1]
        )
    return tuple(name for name in FOUNDRY_VARIABLES if name in missing)


def _invalid_identity(
    environ: Mapping[str, str],
    missing: tuple[str, ...],
) -> tuple[str, ...]:
    invalid: list[str] = []
    if (
        AZURE_TOKEN_CREDENTIALS_VARIABLE not in missing
        and _setting(environ, AZURE_TOKEN_CREDENTIALS_VARIABLE)
        != REQUIRED_AZURE_TOKEN_CREDENTIAL
    ):
        invalid.append(AZURE_TOKEN_CREDENTIALS_VARIABLE)
    tenant_id = _setting(environ, AZURE_TENANT_ID_VARIABLE)
    if (
        AZURE_TENANT_ID_VARIABLE not in missing
        and tenant_id is not None
        and not is_tenant_id(tenant_id)
    ):
        invalid.append(AZURE_TENANT_ID_VARIABLE)
    return tuple(invalid)
