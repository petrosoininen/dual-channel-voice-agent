"""Startup configuration tests."""

from importlib import metadata

import pytest

from backend.config import (
    AgentProvider,
    ConfigurationError,
    Settings,
    VoiceProvider,
)

IDENTITY_ENV = {
    "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
    "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
}


def test_deterministic_agent_and_disabled_voice_start_without_azure() -> None:
    settings = Settings.from_environ({})

    assert settings.agent_provider is AgentProvider.DETERMINISTIC
    assert settings.voice_provider is VoiceProvider.OFF


def test_invalid_agent_provider_reports_only_variable_name() -> None:
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ({"AGENT_PROVIDER": "unsupported"})

    assert captured.value.invalid_variables == ("AGENT_PROVIDER",)
    assert "unsupported" not in str(captured.value)


def test_azure_voice_provider_requires_configuration_names() -> None:
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(
            {"VOICE_PROVIDER": "azure-voice-live", **IDENTITY_ENV}
        )

    assert captured.value.missing_variables == (
        "AZURE_VOICE_LIVE_ENDPOINT",
        "AZURE_VOICE_LIVE_MODEL",
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user@example.invalid",
        "https://example.invalid/path",
        "https://example.invalid?query=value",
        "https://example.invalid/#fragment",
    ],
)
def test_voice_endpoint_rejects_credential_and_url_components(endpoint: str) -> None:
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(
            {
                "VOICE_PROVIDER": "azure-voice-live",
                **IDENTITY_ENV,
                "AZURE_VOICE_LIVE_ENDPOINT": endpoint,
                "AZURE_VOICE_LIVE_MODEL": "synthetic-model",
            }
        )

    assert captured.value.invalid_variables == ("AZURE_VOICE_LIVE_ENDPOINT",)
    assert endpoint not in str(captured.value)


def test_foundry_mode_requires_only_project_endpoint_for_safe_discovery() -> None:
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(
            {"AGENT_PROVIDER": "foundry", **IDENTITY_ENV},
            check_foundry_packages=False,
        )

    assert captured.value.missing_variables == ("FOUNDRY_PROJECT_ENDPOINT",)


def test_foundry_mode_allows_unset_agent_pair_for_read_only_discovery() -> None:
    settings = Settings.from_environ(
        {
            "AGENT_PROVIDER": "foundry",
            **IDENTITY_ENV,
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid",
        },
        check_foundry_packages=False,
    )

    assert settings.foundry_agent_name is None
    assert settings.foundry_agent_version is None


@pytest.mark.parametrize(
    ("configured_name", "expected_missing"),
    [
        ("FOUNDRY_AGENT_NAME", "FOUNDRY_AGENT_VERSION"),
        ("FOUNDRY_AGENT_VERSION", "FOUNDRY_AGENT_NAME"),
    ],
)
def test_foundry_mode_rejects_partial_agent_selection(
    configured_name: str,
    expected_missing: str,
) -> None:
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(
            {
                "AGENT_PROVIDER": "foundry",
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid",
                configured_name: "private-value",
            },
            check_foundry_packages=False,
        )

    assert captured.value.missing_variables == (expected_missing,)
    assert "private-value" not in str(captured.value)


def test_foundry_mode_retains_validated_server_only_configuration() -> None:
    settings = Settings.from_environ(
        {
            "AGENT_PROVIDER": "foundry",
            **IDENTITY_ENV,
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid",
            "FOUNDRY_AGENT_NAME": "synthetic-agent",
            "FOUNDRY_AGENT_VERSION": "1",
        }
    )

    assert settings.agent_provider is AgentProvider.FOUNDRY
    assert settings.foundry_project_endpoint == "https://example.invalid"
    assert settings.foundry_agent_name == "synthetic-agent"
    assert settings.foundry_agent_version == "1"


def test_foundry_mode_reports_missing_package_without_configuration_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def version(package_name: str) -> str:
        if package_name == "agent-framework-foundry":
            raise metadata.PackageNotFoundError(package_name)
        return {
            "azure-ai-projects": "2.3.0",
            "azure-identity": "1.25.3",
        }[package_name]

    monkeypatch.setattr("backend.config.metadata.version", version)
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(
            {
                "AGENT_PROVIDER": "foundry",
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
            }
        )

    assert captured.value.compatibility_errors == (
        "agent-framework-foundry missing; expected 1.11.0",
    )
    assert "private.invalid" not in str(captured.value)


def test_foundry_mode_reports_exact_package_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = {
        "agent-framework-foundry": "1.11.0",
        "azure-ai-projects": "2.5.0",
        "azure-identity": "1.25.3",
    }
    monkeypatch.setattr("backend.config.metadata.version", versions.__getitem__)

    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(
            {
                "AGENT_PROVIDER": "foundry",
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
            }
        )

    assert captured.value.compatibility_errors == (
        "azure-ai-projects version mismatch; expected 2.3.0",
    )
    assert "2.5.0" not in str(captured.value)
    assert "private.invalid" not in str(captured.value)


@pytest.mark.parametrize(
    "environment",
    [
        {
            "VOICE_PROVIDER": "azure-voice-live",
            "AZURE_VOICE_LIVE_ENDPOINT": "https://example.invalid",
            "AZURE_VOICE_LIVE_MODEL": "synthetic-model",
        },
        {
            "AGENT_PROVIDER": "foundry",
            "FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid",
        },
    ],
)
def test_live_modes_require_selector_and_tenant(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(
            environment,
            check_foundry_packages=False,
        )

    assert captured.value.missing_variables == (
        "AZURE_TENANT_ID",
        "AZURE_TOKEN_CREDENTIALS",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AZURE_TOKEN_CREDENTIALS", "azureclicredential"),
        ("AZURE_TOKEN_CREDENTIALS", "dev"),
        ("AZURE_TENANT_ID", "not-a-tenant"),
    ],
)
def test_live_identity_values_fail_closed_and_are_sanitized(
    name: str,
    value: str,
) -> None:
    environment = {
        "VOICE_PROVIDER": "azure-voice-live",
        "AZURE_VOICE_LIVE_ENDPOINT": "https://example.invalid",
        "AZURE_VOICE_LIVE_MODEL": "synthetic-model",
        **IDENTITY_ENV,
        name: value,
    }
    with pytest.raises(ConfigurationError) as captured:
        Settings.from_environ(environment)

    assert captured.value.invalid_variables == (name,)
    assert value not in str(captured.value)


def test_direct_live_settings_cannot_bypass_identity_validation() -> None:
    with pytest.raises(ConfigurationError) as captured:
        Settings(
            agent_provider=AgentProvider.DETERMINISTIC,
            voice_provider=VoiceProvider.AZURE_VOICE_LIVE,
            voice_endpoint="https://example.invalid",
            voice_model="synthetic-model",
        )

    assert captured.value.missing_variables == (
        "AZURE_TOKEN_CREDENTIALS",
        "AZURE_TENANT_ID",
    )
