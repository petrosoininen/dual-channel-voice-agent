"""Shared Prompt Agent bootstrap safety tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bootstrap_agent import (
    BootstrapConfigurationError,
    BootstrapResult,
    _strict_parameters,
    _write_binding,
    main,
)


def test_bootstrap_is_a_non_mutating_preview_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["applyRequired"] is True
    assert output["action"] == "create-or-reuse-compatible-version"
    assert "FOUNDRY_PROJECT_ENDPOINT" in output["missingVariables"]


def test_apply_requires_explicit_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "no")
    monkeypatch.setattr(
        "scripts.bootstrap_agent._load_settings",
        lambda _: {
            "AZURE_TENANT_ID": "synthetic",
            "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
            "FOUNDRY_PROJECT_ENDPOINT": "synthetic",
            "FOUNDRY_AGENT_NAME": "synthetic",
            "FOUNDRY_MODEL_DEPLOYMENT": "synthetic",
        },
    )
    assert main(["--apply"]) == 2


def test_apply_yes_uses_shared_idempotent_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "scripts.bootstrap_agent._load_settings",
        lambda _: {
            "AZURE_TENANT_ID": "synthetic",
            "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
            "FOUNDRY_PROJECT_ENDPOINT": "synthetic",
            "FOUNDRY_AGENT_NAME": "synthetic",
            "FOUNDRY_MODEL_DEPLOYMENT": "synthetic",
        },
    )
    monkeypatch.setattr(
        "scripts.bootstrap_agent._apply",
        lambda settings, binding: BootstrapResult(True, True, True, 2),
    )
    assert main(["--apply", "--yes"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "applied": True,
        "binding_updated": True,
        "reused_compatible_version": True,
        "strict_tool_count": 2,
    }


def test_binding_write_rejects_publishable_files(tmp_path: Path) -> None:
    public_path = Path(__file__).resolve().parents[2] / "binding.txt"
    with pytest.raises(BootstrapConfigurationError):
        _write_binding(public_path, "synthetic-version")


def test_bootstrap_tool_schema_is_strict() -> None:
    def example(value: str) -> str:
        return value

    parameters = _strict_parameters(example)
    assert parameters["required"] == ["value"]
    assert parameters["additionalProperties"] is False
