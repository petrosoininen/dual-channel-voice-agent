"""Shared fixture acceptance and rejection for the Python contracts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from backend.domain.events import (
    ContractValidationError,
    validate_command,
    validate_event,
    validate_patch,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures"


def _cases(name: str) -> list[dict[str, object]]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, list)
    return value


@pytest.mark.parametrize("case", _cases("valid-events.json"), ids=lambda case: case["name"])
def test_valid_event_fixtures(case: dict[str, object]) -> None:
    assert validate_event(case["input"])


@pytest.mark.parametrize("case", _cases("invalid-events.json"), ids=lambda case: case["name"])
def test_invalid_event_fixtures(case: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        validate_event(case["input"])


@pytest.mark.parametrize("case", _cases("valid-commands.json"), ids=lambda case: case["name"])
def test_valid_command_fixtures(case: dict[str, object]) -> None:
    assert validate_command(case["input"])


@pytest.mark.parametrize("case", _cases("invalid-commands.json"), ids=lambda case: case["name"])
def test_invalid_command_fixtures(case: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        validate_command(case["input"])


@pytest.mark.parametrize("case", _cases("valid-patches.json"), ids=lambda case: case["name"])
def test_valid_patch_fixtures(case: dict[str, object]) -> None:
    assert validate_patch(case["input"])


@pytest.mark.parametrize("case", _cases("invalid-patches.json"), ids=lambda case: case["name"])
def test_invalid_patch_fixtures(case: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        validate_patch(case["input"])


def test_oversized_command_and_event_fail_closed() -> None:
    command = _cases("valid-commands.json")[0]["input"]
    event = _cases("valid-events.json")[1]["input"]
    patch = _cases("valid-patches.json")[0]["input"]
    assert isinstance(command, dict)
    assert isinstance(event, dict)
    assert isinstance(patch, dict)

    with pytest.raises(ContractValidationError):
        validate_command({**command, "transcript": "x" * 70_000})
    with pytest.raises(ContractValidationError):
        validate_event({**event, "nextStep": "x" * 70_000})
    with pytest.raises(ContractValidationError):
        validate_patch({**patch, "summary": "x" * 70_000})


def test_authoritative_schemas_are_checked_in() -> None:
    for name in (
        "app-events.schema.json",
        "app-commands.schema.json",
        "document-patch.schema.json",
    ):
        schema = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["x-maxWireBytes"] == 65_536


def test_generated_schema_bytes_have_no_drift() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.generate_contract_schemas",
            "--check",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
