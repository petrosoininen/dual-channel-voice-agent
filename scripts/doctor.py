"""Report sanitized runtime prerequisite readiness without mutation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from importlib import metadata
from pathlib import Path

from dotenv import dotenv_values

from backend.azure_preflight import run_azure_preflight
from backend.config import (
    AGENT_PROVIDER_VARIABLE,
    EXPECTED_FOUNDRY_PACKAGES,
    VOICE_PROVIDER_VARIABLE,
    ConfigurationError,
    Settings,
)
from backend.foundry_preflight import run_foundry_preflight

ROOT = Path(__file__).resolve().parents[1]


def _environment(path: Path) -> dict[str, str]:
    values = dict(os.environ)
    if path.is_file():
        values.update(
            {
                key: value
                for key, value in dotenv_values(path).items()
                if value is not None
            }
        )
    return values


def _package_status() -> dict[str, bool]:
    status: dict[str, bool] = {}
    for package, expected in EXPECTED_FOUNDRY_PACKAGES.items():
        try:
            status[package] = metadata.version(package) == expected
        except metadata.PackageNotFoundError:
            status[package] = False
    return status


def diagnose(environ: dict[str, str]) -> dict[str, object]:
    """Return only provider names, missing names, booleans, and coarse status."""

    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()
    compatibility_errors: tuple[str, ...] = ()
    try:
        settings = Settings.from_environ(environ)
        voice_provider = settings.voice_provider.value
        agent_provider = settings.agent_provider.value
    except ConfigurationError as error:
        voice_provider = environ.get(VOICE_PROVIDER_VARIABLE, "off")
        agent_provider = environ.get(AGENT_PROVIDER_VARIABLE, "deterministic")
        missing = error.missing_variables
        invalid = error.invalid_variables
        compatibility_errors = error.compatibility_errors

    live_selected = voice_provider == "azure-voice-live" or agent_provider == "foundry"
    token_status: dict[str, object] = {"required": live_selected}
    if live_selected:
        preflight = run_azure_preflight(environ)
        token_status.update(
            {
                "voice": preflight.voice_identity_available,
                "foundry": preflight.foundry_identity_available,
            }
        )

    foundry_status = "not-selected"
    if agent_provider == "foundry" and not missing and not invalid:
        foundry_status = asyncio.run(run_foundry_preflight(environ)).status

    return {
        "agentProvider": agent_provider,
        "voiceProvider": voice_provider,
        "missingVariables": missing,
        "invalidVariables": invalid,
        "packageCompatibility": _package_status(),
        "packageErrors": compatibility_errors,
        "tokenAcquisition": token_status,
        "foundryCompatibility": foundry_status,
        "mutated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    print(json.dumps(diagnose(_environment(args.env_file)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
