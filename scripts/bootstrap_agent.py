"""Idempotently create or reuse the reference Prompt Agent version."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from agent_framework import FunctionTool as LocalFunctionTool
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.core.exceptions import HttpResponseError
from dotenv import dotenv_values, set_key

from backend.azure_identity import create_default_credential
from backend.deep_work.base import DeepWorkControls, DeepWorkInput
from backend.deep_work.foundry import _classify_agent_definition
from backend.services.conversation_store import ConversationStore
from backend.tools import (
    PatchProposalCapture,
    create_patch_proposal_tool,
    create_project_context_tool,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts" / "foundry-deep-work.md"
DEFAULT_ENV_PATH = ROOT / ".env"
REQUIRED_SETTINGS = (
    "AZURE_TENANT_ID",
    "AZURE_TOKEN_CREDENTIALS",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_AGENT_NAME",
    "FOUNDRY_MODEL_DEPLOYMENT",
)
SCHEMA_SESSION_ID = UUID(int=1)
SCHEMA_TURN_ID = UUID(int=2)


class BootstrapConfigurationError(RuntimeError):
    """Sanitized bootstrap input failure."""


@dataclass(frozen=True)
class BootstrapResult:
    """Content-free bootstrap outcome."""

    applied: bool
    binding_updated: bool
    reused_compatible_version: bool
    strict_tool_count: int


def _patch_tool() -> Callable[..., object]:
    store = ConversationStore()
    store.create_session(SCHEMA_SESSION_ID)
    work_input = DeepWorkInput(
        session_id=SCHEMA_SESSION_ID,
        turn_id=SCHEMA_TURN_ID,
        sequence=1,
        transcript="Synthetic schema generation.",
        document=store.create_document(SCHEMA_SESSION_ID),
        prior_turns=(),
        controls=DeepWorkControls(),
    )
    return create_patch_proposal_tool(work_input, PatchProposalCapture())


def _strict_parameters(function: Callable[..., object]) -> dict[str, Any]:
    parameters = LocalFunctionTool(
        name=function.__name__,
        description=function.__doc__ or "",
        func=function,
    ).to_json_schema_spec()["function"]["parameters"]
    parameters["additionalProperties"] = False
    _validate_strict_objects(parameters)
    return parameters


def _validate_strict_objects(node: object, path: str = "$") -> None:
    if isinstance(node, dict):
        if "$ref" in node and len(node) != 1:
            raise ValueError(f"Function schema has unsupported $ref siblings at {path}.")
        if node.get("type") == "object" or "properties" in node:
            properties = set(node.get("properties", {}))
            required = set(node.get("required", []))
            if properties != required or node.get("additionalProperties") is not False:
                raise ValueError(f"Function schema object is not strict at {path}.")
        for key, value in node.items():
            _validate_strict_objects(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _validate_strict_objects(value, f"{path}[{index}]")


def _load_settings(env_file: Path) -> dict[str, str]:
    values = dict(os.environ)
    if env_file.is_file():
        values.update(
            {
                key: value
                for key, value in dotenv_values(env_file).items()
                if value is not None
            }
        )
    return {
        key: value.strip()
        for key, value in values.items()
        if isinstance(value, str) and value.strip()
    }


def _missing_settings(settings: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(name for name in REQUIRED_SETTINGS if name not in settings)


def _tool(
    function: Callable[..., object],
    *,
    description: str,
) -> FunctionTool:
    return FunctionTool(
        name=function.__name__,
        description=description,
        parameters=_strict_parameters(function),
        strict=True,
    )


def _find_compatible_version(
    agents: object,
    agent_name: str,
    model_deployment: str,
) -> str | None:
    try:
        versions = agents.list_versions(
            agent_name,
            limit=100,
            order="desc",
            include_drafts=False,
        )
        for candidate in versions:
            version = getattr(candidate, "version", None)
            if not isinstance(version, str) or not version:
                continue
            details = agents.get_version(
                agent_name=agent_name,
                agent_version=version,
            )
            definition = getattr(details, "definition", None)
            if isinstance(definition, Mapping):
                configured_model = definition.get("model")
                configured_temperature = definition.get("temperature")
            else:
                configured_model = getattr(definition, "model", None)
                configured_temperature = getattr(definition, "temperature", None)
            if (
                _classify_agent_definition(details).compatible
                and configured_model == model_deployment
                and configured_temperature is None
            ):
                return version
    except HttpResponseError as error:
        if error.status_code == 404:
            return None
        raise
    return None


def _apply(settings: Mapping[str, str], binding_file: Path) -> BootstrapResult:
    if settings["AZURE_TOKEN_CREDENTIALS"] != "AzureCliCredential":
        raise BootstrapConfigurationError(
            "AZURE_TOKEN_CREDENTIALS must select AzureCliCredential."
        )
    os.environ["AZURE_TOKEN_CREDENTIALS"] = settings["AZURE_TOKEN_CREDENTIALS"]
    project_context = create_project_context_tool({})
    definition = PromptAgentDefinition(
        model=settings["FOUNDRY_MODEL_DEPLOYMENT"],
        instructions=PROMPT_PATH.read_text(encoding="utf-8"),
        tools=[
            _tool(
                project_context,
                description="Return bounded synthetic project context.",
            ),
            _tool(
                _patch_tool(),
                description="Propose one validated semantic document patch.",
            ),
        ],
    )
    with create_default_credential(settings["AZURE_TENANT_ID"]) as credential:
        with AIProjectClient(
            endpoint=settings["FOUNDRY_PROJECT_ENDPOINT"],
            credential=credential,
        ) as project:
            version = _find_compatible_version(
                project.agents,
                settings["FOUNDRY_AGENT_NAME"],
                settings["FOUNDRY_MODEL_DEPLOYMENT"],
            )
            reused = version is not None
            if version is None:
                created = project.agents.create_version(
                    settings["FOUNDRY_AGENT_NAME"],
                    definition=definition,
                    description="Strict dual-channel reference contract.",
                )
                version = str(created.version)
    _write_binding(binding_file, version)
    return BootstrapResult(
        applied=True,
        binding_updated=True,
        reused_compatible_version=reused,
        strict_tool_count=2,
    )


def _write_binding(path: Path, version: str) -> None:
    resolved = path.resolve()
    root = ROOT.resolve()
    if path.exists() and path.is_symlink():
        raise BootstrapConfigurationError("The binding file cannot be a symbolic link.")
    if resolved.is_relative_to(root) and resolved != DEFAULT_ENV_PATH.resolve():
        raise BootstrapConfigurationError(
            "Bindings inside the repository are allowed only in ignored .env."
        )
    if not resolved.parent.is_dir():
        raise BootstrapConfigurationError("The binding-file parent must already exist.")
    if not resolved.exists():
        resolved.touch()
    set_key(str(resolved), "FOUNDRY_AGENT_VERSION", version, quote_mode="never")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply the shared Prompt Agent bootstrap."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--binding-file", type=Path, default=DEFAULT_ENV_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = _load_settings(args.env_file)
    missing = _missing_settings(settings)
    if not args.apply:
        print(
            json.dumps(
                {
                    "action": "create-or-reuse-compatible-version",
                    "applyRequired": True,
                    "missingVariables": missing,
                    "ready": not missing,
                },
                sort_keys=True,
            )
        )
        return 0
    if missing:
        print(
            json.dumps(
                {
                    "applied": False,
                    "errorType": "BootstrapConfigurationError",
                    "missingVariables": missing,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    if not args.yes:
        confirmed = input(
            "Create or reuse one compatible Prompt Agent version? [y/N] "
        ).strip()
        if confirmed.lower() not in {"y", "yes"}:
            print(json.dumps({"applied": False, "cancelled": True}, sort_keys=True))
            return 2
    try:
        result = _apply(settings, args.binding_file)
    except Exception as error:
        print(
            json.dumps(
                {
                    "applied": False,
                    "errorType": type(error).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
