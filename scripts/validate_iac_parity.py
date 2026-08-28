"""Validate the checked-in Bicep and Terraform logical contract."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "infra" / "logical-contract.json"
BICEP_MAIN = ROOT / "infra" / "bicep" / "main.bicep"
BICEP_RESOURCES = ROOT / "infra" / "bicep" / "resources.bicep"
TERRAFORM_FILES = (
    ROOT / "infra" / "terraform" / "main.tf",
    ROOT / "infra" / "terraform" / "variables.tf",
    ROOT / "infra" / "terraform" / "outputs.tf",
)


def validate() -> list[str]:
    """Return content-free parity errors."""

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    bicep = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (BICEP_MAIN, BICEP_RESOURCES)
    )
    terraform = "\n".join(
        path.read_text(encoding="utf-8") for path in TERRAFORM_FILES
    )
    errors: list[str] = []

    for logical_name, markers in contract["resources"].items():
        _require_marker(errors, "Bicep resource", logical_name, markers["bicep"], bicep)
        _require_marker(
            errors,
            "Terraform resource",
            logical_name,
            markers["terraform"],
            terraform,
        )

    for logical_name, markers in contract["securityChoices"].items():
        _require_marker(errors, "Bicep security", logical_name, markers["bicep"], bicep)
        _require_marker(
            errors,
            "Terraform security",
            logical_name,
            markers["terraform"],
            terraform,
        )

    for logical_name, (bicep_name, terraform_name) in contract["parameters"].items():
        _require_marker(errors, "Bicep parameter", logical_name, f"param {bicep_name} ", bicep)
        _require_marker(
            errors,
            "Terraform variable",
            logical_name,
            f'variable "{terraform_name}"',
            terraform,
        )

    for logical_name, (bicep_marker, terraform_marker) in contract["defaults"].items():
        _require_marker(
            errors,
            "Bicep default",
            logical_name,
            bicep_marker,
            bicep,
        )
        _require_marker(
            errors,
            "Terraform default",
            logical_name,
            terraform_marker,
            terraform,
        )

    for logical_name, (bicep_name, terraform_name) in contract["outputs"].items():
        _require_marker(errors, "Bicep output", logical_name, f"output {bicep_name} ", bicep)
        _require_marker(
            errors,
            "Terraform output",
            logical_name,
            f'output "{terraform_name}"',
            terraform,
        )

    role_markers = {
        "operatorVoice": ("operatorVoiceRole", "operator_voice"),
        "runtimeVoice": ("runtimeVoiceRole", "runtime_voice"),
        "operatorProjectManager": ("operatorProjectRole", "operator_project"),
        "runtimeProjectUser": ("runtimeProjectRole", "runtime_project"),
    }
    for logical_name in contract["roleAssignments"]:
        bicep_name, terraform_name = role_markers[logical_name]
        _require_marker(errors, "Bicep role", logical_name, bicep_name, bicep)
        _require_marker(
            errors,
            "Terraform role",
            logical_name,
            terraform_name,
            terraform,
        )

    return errors


def _require_marker(
    errors: list[str],
    kind: str,
    logical_name: str,
    marker: str,
    content: str,
) -> None:
    if marker not in content:
        errors.append(f"{kind} is missing logical item {logical_name}.")


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Bicep and Terraform logical parity passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
