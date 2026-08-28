"""Content-free Foundry project preflight tests."""

from __future__ import annotations

import asyncio

from backend.foundry_preflight import FOUNDRY_SCOPE, run_foundry_preflight

IDENTITY_ENV = {
    "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
    "AZURE_TENANT_ID": "00000000-0000-4000-8000-000000000001",
}


class _Credential:
    async def __aenter__(self) -> "_Credential":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_token(
        self,
        scope: str,
        *,
        tenant_id: str | None = None,
    ) -> object:
        assert scope == FOUNDRY_SCOPE
        assert tenant_id == IDENTITY_ENV["AZURE_TENANT_ID"]
        return object()


class _Agents:
    def list(self, *, kind: str, limit: int, order: str):
        assert kind == "prompt"
        assert limit == 100
        assert order == "desc"

        async def values():
            yield {"name": "candidate", "versions": {"latest": {"version": "2"}}}
            yield {"name": "other", "versions": {"latest": {"version": "1"}}}

        return values()

    def list_versions(
        self,
        agent_name: str,
        *,
        limit: int,
        order: str,
        include_drafts: bool,
    ):
        assert agent_name
        assert limit == 100
        assert order == "desc"
        assert include_drafts is False

        async def values():
            yield {"version": "2" if agent_name == "candidate" else "1"}

        return values()

    async def get_version(self, *, agent_name: str, agent_version: str):
        assert agent_name
        assert agent_version
        return {
            "definition": {
                "kind": "prompt",
                "instructions": (
                    "DCR_DEEP_WORK_CONTRACT_VERSION: 1.0.0\n"
                    "PROJECT_CONTEXT_TOOL: project_context\n"
                    "PATCH_PROPOSAL_TOOL: propose_document_patch\n"
                    "COMPLETION_SUMMARY_CONTRACT: strict-json-v1"
                ),
                "tools": [
                    {"type": "function", "name": "project_context"},
                    {"type": "function", "name": "propose_document_patch"},
                ],
            }
        }


class _Client:
    def __init__(self, **kwargs: object) -> None:
        assert set(kwargs) == {"endpoint", "credential"}
        self.agents = _Agents()

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _IncompatibleAgents(_Agents):
    async def get_version(self, *, agent_name: str, agent_version: str):
        del agent_name, agent_version
        return {
            "definition": {
                "kind": "prompt",
                "instructions": "Different local contract.",
                "tools": [],
            }
        }


class _IncompatibleClient(_Client):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.agents = _IncompatibleAgents()


class _PartlyInaccessibleAgents(_Agents):
    async def get_version(self, *, agent_name: str, agent_version: str):
        if agent_name == "candidate":
            raise RuntimeError("private provider failure")
        return await super().get_version(
            agent_name=agent_name,
            agent_version=agent_version,
        )


class _PartlyInaccessibleClient(_Client):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.agents = _PartlyInaccessibleAgents()


class _OlderCompatibleAgents(_Agents):
    def list_versions(
        self,
        agent_name: str,
        *,
        limit: int,
        order: str,
        include_drafts: bool,
    ):
        assert agent_name
        assert limit == 100
        assert order == "desc"
        assert include_drafts is False

        async def values():
            yield {"version": "3"}
            yield {"version": "2"}

        return values()

    async def get_version(self, *, agent_name: str, agent_version: str):
        if agent_version == "3":
            return {
                "definition": {
                    "kind": "prompt",
                    "instructions": "Incompatible latest version.",
                    "tools": [],
                }
            }
        return await super().get_version(
            agent_name=agent_name,
            agent_version=agent_version,
        )


class _OlderCompatibleClient(_Client):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.agents = _OlderCompatibleAgents()


def test_preflight_safely_resolves_compatible_agent_without_identifiers() -> None:
    result = asyncio.run(
        run_foundry_preflight(
            {
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
            },
            credential_factory=_Credential,
            project_client_factory=_Client,
        )
    )

    assert result.identity_available is True
    assert result.project_access_verified is True
    assert result.prompt_agent_count == 2
    assert result.configured_agent_verified is False
    assert result.resolved_agent_verified is True
    assert result.selection_source == "discovered"
    assert result.compatible is True
    assert result.missing_variables == ()
    assert result.status == "compatible"
    assert "private.invalid" not in str(result.to_dict())


def test_preflight_skips_inaccessible_candidate_and_resolves_next() -> None:
    result = asyncio.run(
        run_foundry_preflight(
            {
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
            },
            credential_factory=_Credential,
            project_client_factory=_PartlyInaccessibleClient,
        )
    )

    assert result.prompt_agent_count == 2
    assert result.resolved_agent_verified is True
    assert result.selection_source == "discovered"
    assert result.status == "compatible"
    assert "private" not in str(result.to_dict())


def test_preflight_can_resolve_older_immutable_compatible_version() -> None:
    result = asyncio.run(
        run_foundry_preflight(
            {
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
            },
            credential_factory=_Credential,
            project_client_factory=_OlderCompatibleClient,
        )
    )

    assert result.resolved_agent_verified is True
    assert result.selection_source == "discovered"
    assert result.status == "compatible"


def test_preflight_reports_external_blocker_when_no_compatible_agent_exists() -> None:
    result = asyncio.run(
        run_foundry_preflight(
            {
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
            },
            credential_factory=_Credential,
            project_client_factory=_IncompatibleClient,
        )
    )

    assert result.project_access_verified is True
    assert result.resolved_agent_verified is False
    assert result.selection_source is None
    assert result.compatible is None
    assert result.status == "no_compatible_agent"
    assert "candidate" not in str(result.to_dict())


def test_preflight_reports_compatible_definition_without_identifiers() -> None:
    result = asyncio.run(
        run_foundry_preflight(
            {
                **IDENTITY_ENV,
                "FOUNDRY_PROJECT_ENDPOINT": "https://private.invalid",
                "FOUNDRY_AGENT_NAME": "private-agent",
                "FOUNDRY_AGENT_VERSION": "private-version",
            },
            credential_factory=_Credential,
            project_client_factory=_Client,
        )
    )

    assert result.configured_agent_verified is True
    assert result.resolved_agent_verified is True
    assert result.selection_source == "configured"
    assert result.compatible is True
    assert result.status == "compatible"
    serialized = str(result.to_dict())
    assert "private" not in serialized
    assert "https://" not in serialized
