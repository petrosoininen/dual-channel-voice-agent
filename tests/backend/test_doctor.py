"""Doctor output is non-mutating and contains no configured values."""

from scripts.doctor import diagnose


def test_doctor_reports_default_provider_readiness_without_live_access() -> None:
    result = diagnose({})
    assert result["agentProvider"] == "deterministic"
    assert result["voiceProvider"] == "off"
    assert result["missingVariables"] == ()
    assert result["tokenAcquisition"] == {"required": False}
    assert result["foundryCompatibility"] == "not-selected"
    assert result["mutated"] is False


def test_doctor_reports_variable_names_not_values() -> None:
    result = diagnose(
        {
            "AGENT_PROVIDER": "foundry",
            "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
        }
    )
    assert "AZURE_TENANT_ID" in result["missingVariables"]
    assert "private.invalid" not in str(result)
