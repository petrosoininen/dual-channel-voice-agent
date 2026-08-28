# Repository instructions

## Start here

Always work from the repository root. The reference runtime uses two independent
provider settings:

- `VOICE_PROVIDER=off|azure-voice-live`
- `AGENT_PROVIDER=deterministic|foundry`

The primary browser reference is bring-your-own Azure Voice Live plus Azure Foundry
Agent Service. The credential-free deterministic path is executable documentation and
CI evidence, not the main product promise.

Canonical task procedures live only in `.agents/skills/`. Read a skill when its
frontmatter description matches the task. Do not create copied or symlinked skill
trees for a specific coding agent.

## Commands

```text
python -m pytest -q tests/backend tests/contract
npm run test:frontend
npm run typecheck
npm run build
npm run test:e2e -- --project=chromium
python -m scripts.generate_contract_schemas --check
python -m scripts.verify_contract_freeze
python -m scripts.validate_iac_parity
python -m scripts.validate_release
```

For IaC commands and mutation gates, also read `infra/AGENTS.md`.

## Architectural invariants

1. Voice acknowledgment and detailed agent work are independent channels.
2. Voice may acknowledge intent and a next step; it cannot state findings.
3. Only validated, ordered deep work may mutate the canonical document.
4. Semantic patches are bounded, allowlisted, versioned, validated as a complete set,
   and committed atomically.
5. One running plus three pending deep tasks are allowed per conversation.
6. Cancellation and late provider output cannot commit.
7. Revert creates a new immutable restoring version.
8. Provider IDs are opaque correlation only and never authorize access.
9. Application state is process memory only. Restart means deletion.
10. Raw or synthesized audio is never stored by this application.

## Entry points

- Backend composition: `backend/main.py`
- Provider registries: `backend/providers/`
- Queue and authority boundary: `backend/services/deep_work_service.py`
- Semantic patch authority: `backend/services/patch_service.py`
- Browser composition: `src/app.tsx`
- Voice adapter registry: `src/providers/voice/`
- Shared schemas and fixtures: `contracts/`
- Infrastructure: `infra/bicep/`, `infra/terraform/`
- Agent bootstrap and diagnostics: `scripts/bootstrap_agent.py`, `scripts/doctor.py`
- Agent-readable map: `docs/solution-map.md`

## Always

- Keep provider selection server-owned and visible.
- Keep Azure credentials keyless with `DefaultAzureCredential`.
- Keep real environment values, parameter files, logs, plans, and Terraform state out
  of source.
- Treat provider payloads, model output, WebSocket input, and semantic operations as
  untrusted.
- Update Bicep and Terraform together and run the parity check.
- Label evidence as CI-verified, tenant-validated, illustrative, or bring-your-own.
- Use synthetic/public fixtures and sanitized diagnostics.
- Add or update tests for contract, cancellation, authority, and cleanup behavior.

## Ask first

- Any cloud apply, agent publication, destroy, or resource-group deletion.
- Any new runtime dependency or provider implementation.
- Any shared schema or contract-freeze revision.
- Any production data retention or identity design.

An explicit user request to run a named operation satisfies the corresponding ask-first
gate for that operation only.

## Never

- Never print or commit tokens, keys, tenant/subscription/principal IDs, endpoints,
  resource names, deployment names, raw provider errors, or Terraform state.
- Never silently fall back from a selected live provider to deterministic behavior.
- Never let provider prose bypass the patch service.
- Never claim live validation from mocks, static checks, or old media.
- Never modify or delete a pre-existing cloud resource during reference validation.
- Never add unsupported provider values or production-readiness claims.

## Change-impact checklist

Before finishing, check:

- provider registry and capabilities response;
- Python and TypeScript contract parity;
- schema generation and freeze marker;
- queue, cancellation, no-op, revert, and provider-failure tests;
- Bicep/Terraform parameter, resource, role, and output parity;
- README/docs/evidence labels;
- sensitive-reference, secret, dependency, build, and browser checks.
