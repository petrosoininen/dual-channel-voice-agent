"""Sanitized startup configuration for the reference implementation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from typing import Mapping
from urllib.parse import urlsplit
from uuid import UUID

AGENT_PROVIDER_VARIABLE = "AGENT_PROVIDER"
VOICE_PROVIDER_VARIABLE = "VOICE_PROVIDER"
AZURE_TOKEN_CREDENTIALS_VARIABLE = "AZURE_TOKEN_CREDENTIALS"
AZURE_TENANT_ID_VARIABLE = "AZURE_TENANT_ID"
REQUIRED_AZURE_TOKEN_CREDENTIAL = "AzureCliCredential"
LIVE_IDENTITY_VARIABLES = (
    AZURE_TOKEN_CREDENTIALS_VARIABLE,
    AZURE_TENANT_ID_VARIABLE,
)
VOICE_VARIABLES = ("AZURE_VOICE_LIVE_ENDPOINT", "AZURE_VOICE_LIVE_MODEL")
FOUNDRY_VARIABLES = (
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_AGENT_NAME",
    "FOUNDRY_AGENT_VERSION",
)
FOUNDRY_ENDPOINT_VARIABLE = FOUNDRY_VARIABLES[0]
FOUNDRY_AGENT_VARIABLES = FOUNDRY_VARIABLES[1:]
EXPECTED_FOUNDRY_PACKAGES = {
    "agent-framework-foundry": "1.11.0",
    "azure-ai-projects": "2.3.0",
    "azure-identity": "1.25.3",
}


class AgentProvider(StrEnum):
    """Server-owned deep-work provider selection."""

    DETERMINISTIC = "deterministic"
    FOUNDRY = "foundry"


class VoiceProvider(StrEnum):
    """Server-owned voice provider selection."""

    OFF = "off"
    AZURE_VOICE_LIVE = "azure-voice-live"


class ConfigurationError(RuntimeError):
    """A sanitized startup failure containing names, never configuration values."""

    def __init__(
        self,
        *,
        missing_variables: tuple[str, ...] = (),
        invalid_variables: tuple[str, ...] = (),
        compatibility_errors: tuple[str, ...] = (),
    ) -> None:
        self.missing_variables = missing_variables
        self.invalid_variables = invalid_variables
        self.compatibility_errors = compatibility_errors
        super().__init__(self._safe_message())

    def _safe_message(self) -> str:
        parts = ["Startup configuration is invalid."]
        if self.missing_variables:
            parts.append(f"Missing variables: {', '.join(self.missing_variables)}.")
        if self.invalid_variables:
            parts.append(f"Invalid variables: {', '.join(self.invalid_variables)}.")
        if self.compatibility_errors:
            parts.append(
                f"Compatibility errors: {', '.join(self.compatibility_errors)}."
            )
        return " ".join(parts)


@dataclass(frozen=True)
class Settings:
    """Validated settings safe to retain in process memory."""

    agent_provider: AgentProvider
    voice_provider: VoiceProvider
    azure_token_credentials: str | None = None
    azure_tenant_id: str | None = None
    voice_endpoint: str | None = None
    voice_model: str | None = None
    foundry_project_endpoint: str | None = None
    foundry_agent_name: str | None = None
    foundry_agent_version: str | None = None

    def __post_init__(self) -> None:
        """Prevent direct construction from bypassing live identity validation."""

        if (
            self.voice_provider is VoiceProvider.OFF
            and self.agent_provider is not AgentProvider.FOUNDRY
        ):
            return
        missing = tuple(
            name
            for name, value in (
                (AZURE_TOKEN_CREDENTIALS_VARIABLE, self.azure_token_credentials),
                (AZURE_TENANT_ID_VARIABLE, self.azure_tenant_id),
            )
            if value is None or not value.strip()
        )
        invalid: list[str] = []
        if (
            self.azure_token_credentials is not None
            and self.azure_token_credentials != REQUIRED_AZURE_TOKEN_CREDENTIAL
        ):
            invalid.append(AZURE_TOKEN_CREDENTIALS_VARIABLE)
        if self.azure_tenant_id is not None and not is_tenant_id(
            self.azure_tenant_id
        ):
            invalid.append(AZURE_TENANT_ID_VARIABLE)
        if missing or invalid:
            raise ConfigurationError(
                missing_variables=missing,
                invalid_variables=tuple(sorted(set(invalid) - set(missing))),
            )

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str],
        *,
        check_foundry_packages: bool = True,
    ) -> Settings:
        """Create settings from environment variables or fail with sanitized details."""

        missing_variables: list[str] = []
        invalid_variables: list[str] = []
        compatibility_errors: list[str] = []

        raw_agent_provider = environ.get(
            AGENT_PROVIDER_VARIABLE,
            AgentProvider.DETERMINISTIC.value,
        )
        try:
            agent_provider = AgentProvider(raw_agent_provider.strip().lower())
        except ValueError:
            invalid_variables.append(AGENT_PROVIDER_VARIABLE)
            agent_provider = AgentProvider.DETERMINISTIC

        raw_voice_provider = environ.get(
            VOICE_PROVIDER_VARIABLE,
            VoiceProvider.OFF.value,
        )
        try:
            voice_provider = VoiceProvider(raw_voice_provider.strip().lower())
        except ValueError:
            invalid_variables.append(VOICE_PROVIDER_VARIABLE)
            voice_provider = VoiceProvider.OFF

        if voice_provider is VoiceProvider.AZURE_VOICE_LIVE:
            missing_variables.extend(_missing(environ, VOICE_VARIABLES))
            if not _is_service_endpoint(environ.get(VOICE_VARIABLES[0], "")):
                invalid_variables.append(VOICE_VARIABLES[0])

        if agent_provider is AgentProvider.FOUNDRY:
            missing_variables.extend(_missing(environ, (FOUNDRY_ENDPOINT_VARIABLE,)))
            if not _is_https_url(environ.get(FOUNDRY_ENDPOINT_VARIABLE, "")):
                invalid_variables.append(FOUNDRY_ENDPOINT_VARIABLE)
            configured_agent_variables = tuple(
                name
                for name in FOUNDRY_AGENT_VARIABLES
                if environ.get(name, "").strip()
            )
            if len(configured_agent_variables) == 1:
                missing_variables.extend(
                    name
                    for name in FOUNDRY_AGENT_VARIABLES
                    if name not in configured_agent_variables
                )
            if check_foundry_packages:
                compatibility_errors.extend(_foundry_compatibility_errors())

        if (
            voice_provider is VoiceProvider.AZURE_VOICE_LIVE
            or agent_provider is AgentProvider.FOUNDRY
        ):
            missing_variables.extend(_missing(environ, LIVE_IDENTITY_VARIABLES))
            if (
                environ.get(AZURE_TOKEN_CREDENTIALS_VARIABLE, "").strip()
                != REQUIRED_AZURE_TOKEN_CREDENTIAL
            ):
                invalid_variables.append(AZURE_TOKEN_CREDENTIALS_VARIABLE)
            if not is_tenant_id(
                environ.get(AZURE_TENANT_ID_VARIABLE, "").strip()
            ):
                invalid_variables.append(AZURE_TENANT_ID_VARIABLE)

        missing = tuple(sorted(set(missing_variables)))
        invalid = tuple(sorted(set(invalid_variables) - set(missing)))
        compatibility = tuple(sorted(set(compatibility_errors)))
        if missing or invalid or compatibility:
            raise ConfigurationError(
                missing_variables=missing,
                invalid_variables=invalid,
                compatibility_errors=compatibility,
            )

        return cls(
            agent_provider=agent_provider,
            voice_provider=voice_provider,
            azure_token_credentials=(
                environ.get(AZURE_TOKEN_CREDENTIALS_VARIABLE, "").strip() or None
                if (
                    voice_provider is VoiceProvider.AZURE_VOICE_LIVE
                    or agent_provider is AgentProvider.FOUNDRY
                )
                else None
            ),
            azure_tenant_id=(
                environ.get(AZURE_TENANT_ID_VARIABLE, "").strip() or None
                if (
                    voice_provider is VoiceProvider.AZURE_VOICE_LIVE
                    or agent_provider is AgentProvider.FOUNDRY
                )
                else None
            ),
            voice_endpoint=(
                environ.get(VOICE_VARIABLES[0], "").strip() or None
                if voice_provider is VoiceProvider.AZURE_VOICE_LIVE
                else None
            ),
            voice_model=(
                environ.get(VOICE_VARIABLES[1], "").strip() or None
                if voice_provider is VoiceProvider.AZURE_VOICE_LIVE
                else None
            ),
            foundry_project_endpoint=(
                environ.get(FOUNDRY_ENDPOINT_VARIABLE, "").strip() or None
                if agent_provider is AgentProvider.FOUNDRY
                else None
            ),
            foundry_agent_name=(
                environ.get(FOUNDRY_AGENT_VARIABLES[0], "").strip() or None
                if agent_provider is AgentProvider.FOUNDRY
                else None
            ),
            foundry_agent_version=(
                environ.get(FOUNDRY_AGENT_VARIABLES[1], "").strip() or None
                if agent_provider is AgentProvider.FOUNDRY
                else None
            ),
        )


def _missing(environ: Mapping[str, str], variables: tuple[str, ...]) -> list[str]:
    return [name for name in variables if not environ.get(name, "").strip()]


def _is_https_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _is_service_endpoint(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        _is_https_url(value)
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def is_tenant_id(value: str) -> bool:
    """Return whether a value is one canonical Entra tenant UUID."""

    try:
        return str(UUID(value)) == value.lower()
    except (AttributeError, ValueError):
        return False


def _foundry_compatibility_errors() -> list[str]:
    errors: list[str] = []
    for package_name, expected_version in EXPECTED_FOUNDRY_PACKAGES.items():
        try:
            installed_version = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            errors.append(f"{package_name} missing; expected {expected_version}")
            continue
        if installed_version != expected_version:
            errors.append(
                f"{package_name} version mismatch; expected {expected_version}"
            )
    return errors
