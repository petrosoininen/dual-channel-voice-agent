"""Safe Azure preflight tests."""

from backend.azure_preflight import FOUNDRY_SCOPE, VOICE_SCOPE, run_azure_preflight

IDENTITY_ENV = {
    "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
    "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
}


class FakeCredential:
    """Credential fake that records only public scope names."""

    def __init__(self, *, available_scopes: set[str]) -> None:
        self.available_scopes = available_scopes

    def __enter__(self) -> "FakeCredential":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get_token(
        self,
        *scopes: str,
        tenant_id: str | None = None,
    ) -> object:
        assert tenant_id == IDENTITY_ENV["AZURE_TENANT_ID"]
        if scopes[0] not in self.available_scopes:
            raise RuntimeError("unavailable")
        return object()


def test_preflight_returns_only_sanitized_status() -> None:
    result = run_azure_preflight(
        IDENTITY_ENV,
        credential_factory=lambda: FakeCredential(available_scopes={VOICE_SCOPE}),
    )

    assert result.voice_identity_available is True
    assert result.foundry_identity_available is False
    assert result.resource_access_verified is False
    assert result.missing_voice_variables == (
        "AZURE_VOICE_LIVE_ENDPOINT",
        "AZURE_VOICE_LIVE_MODEL",
    )
    assert result.missing_foundry_variables == (
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_AGENT_NAME",
        "FOUNDRY_AGENT_VERSION",
    )


def test_preflight_can_report_ready_without_returning_values() -> None:
    result = run_azure_preflight(
        {
            **IDENTITY_ENV,
            "AZURE_VOICE_LIVE_ENDPOINT": "private-value",
            "AZURE_VOICE_LIVE_MODEL": "private-value",
            "FOUNDRY_PROJECT_ENDPOINT": "private-value",
            "FOUNDRY_AGENT_NAME": "private-value",
            "FOUNDRY_AGENT_VERSION": "private-value",
        },
        credential_factory=lambda: FakeCredential(
            available_scopes={VOICE_SCOPE, FOUNDRY_SCOPE}
        ),
    )

    serialized = str(result.to_dict())
    assert result.status == "ready-for-resource-smoke"
    assert "private-value" not in serialized


def test_preflight_rejects_invalid_identity_selector_without_using_it() -> None:
    result = run_azure_preflight(
        {
            **IDENTITY_ENV,
            "AZURE_TOKEN_CREDENTIALS": "dev",
        },
        credential_factory=lambda: FakeCredential(
            available_scopes={VOICE_SCOPE, FOUNDRY_SCOPE}
        ),
    )

    assert result.status == "incomplete"
    assert result.invalid_identity_variables == ("AZURE_TOKEN_CREDENTIALS",)
    assert result.voice_identity_available is False
    assert "dev" not in str(result.to_dict())
