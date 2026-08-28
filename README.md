# Dual-Channel Voice Agent Pattern

A reference implementation that keeps validated realtime voice interaction separate from
ordered, structured agent work on one evolving document.

> **Bring your own:** A running browser reference requires your own Azure Voice Live
> and Azure Foundry Agent Service prerequisites. This repository does not include
> credentials, quota, resources, a hosted demo, or an SLA.

## What this demonstrates

- a concise, non-authoritative voice acknowledgment, buffered until its transcript passes
  the authority guard, while deep work continues;
- one authoritative document updated through bounded semantic patches;
- immediate acceptance of later turns with FIFO deep-work execution;
- cancellation, no-op, immutable history, and history-preserving revert;
- provider-neutral voice and agent contracts with Azure reference adapters;
- equivalent Bicep and Terraform prerequisites plus one shared agent bootstrap;
- repository guidance and Agent Skills intended for coding agents.

It does **not** provide production authentication, durable storage, private networking,
compliance controls, hosted infrastructure, or alternative provider implementations.

## Evidence and provider status

| Surface | Status | Evidence |
| --- | --- | --- |
| Contracts, deterministic agent, disabled voice | Implemented | CI-verified |
| Azure Voice Live adapter | Implemented | Bring your own; WebRTC is preview |
| Azure Foundry Prompt Agent adapter | Implemented | Bring your own |
| Bicep and Terraform | Implemented | CI-verified statically; tenant evidence is recorded separately |
| Other providers | Adapter contract only | Not implemented |
| Screenshots/video | None shipped | No illustrative claim |

Evidence labels:

- **CI-verified:** credential-free static, unit, contract, build, browser, IaC, and scan
  checks.
- **Tenant-validated:** a named IaC path was provisioned, smoke-tested, destroyed, and
  recorded on a stated date.
- **Illustrative:** historical media; not a current live-provider claim.
- **Bring your own:** you provision, pay for, configure, and validate the provider.

## Fastest supported path

1. Install Python 3.11+, Node.js 22+, npm, Azure CLI with Bicep, and Terraform.
2. Install dependencies:

   ```text
   python -m venv .venv
   # Windows PowerShell
   .\.venv\Scripts\Activate.ps1
   # macOS or Linux
   source .venv/bin/activate
   python -m pip install -r requirements-dev.txt
   npm ci
   npx playwright install chromium
   ```

3. Choose [Bicep or Terraform](infra/README.md), check region/model quota, preview,
   and provision your own prerequisites.
4. Map public IaC outputs into an ignored `.env` or external environment file.
5. Preview, then explicitly apply the shared Prompt Agent bootstrap:

   ```text
   python -m scripts.bootstrap_agent --env-file <path>
   python -m scripts.bootstrap_agent --apply --env-file <path> --binding-file <path>
   ```

6. Run sanitized diagnostics and start both providers:

   ```text
   python -m scripts.doctor --env-file <path>
   python -m scripts.run_backend --voice-provider azure-voice-live --agent-provider foundry --env-file <path>
   npm run dev
   ```

7. Open the printed loopback URL in a current desktop Chromium browser and follow
   [the three-turn script](docs/run-reference.md).

Every mutating cloud command is confirmation-gated. Review cost and cleanup first.

## Architecture

```text
browser voice client <---- realtime audio ----> voice provider
         |
         `---- normalized transcript/lifecycle ----.
                                                   |
browser document UI <---- typed app events ---- FastAPI
                                                   |
                                             ordered queue
                                                   |
                                             agent adapter
                                                   |
                                       validated semantic patch
                                                   |
                                        canonical document store
```

Voice failure does not invalidate accepted deep work. Deep-work failure does not remove
committed text. Provider prose never bypasses the semantic patch service.

See [the solution map](docs/solution-map.md) for entry points, sequences, contracts, and
change impact.

## Runtime profiles

| Voice provider | Agent provider | Purpose |
| --- | --- | --- |
| `azure-voice-live` | `foundry` | Primary bring-your-own reference |
| `azure-voice-live` | `deterministic` | Bring-your-own voice with executable document fixture |
| `off` | `foundry` | Typed input with bring-your-own agent |
| `off` | `deterministic` | Credential-free tests and architecture exploration |

Missing selected-provider configuration fails with variable-name-only diagnostics. No
live provider silently falls back to deterministic behavior.

## Safety and limitations

- Voice Live WebRTC is public preview and has no production SLA.
- Voice Live and model deployments can incur usage charges.
- Provider-side data handling depends on your resource configuration and applicable
  service terms.
- The application keeps state only in process memory and never stores audio.
- The local WebSocket secret is a development control, not multi-user authentication.
- Validate current regions, models, roles, quotas, preview terms, and prices before use.

This is an independent reference project. It is not affiliated with, endorsed by, or
supported by any cloud provider, employer, customer, or partner. Product names and
trademarks belong to their respective owners. No production support or SLA is offered.

## Validate

```text
python -m pytest -q tests/backend tests/contract tests/repository
npm run test:frontend
npm run typecheck
npm run build
npm run test:e2e -- --project=chromium
python -m scripts.generate_contract_schemas --check
python -m scripts.verify_contract_freeze
python -m scripts.validate_iac_parity
python -m scripts.validate_release
```

Public CI has no cloud credentials and proves no live provider behavior. See
[testing](docs/testing.md) and [tenant-validation evidence](docs/evidence/tenant-validation.md).

## Documentation

- [Documentation index](docs/README.md)
- [Run the reference](docs/run-reference.md)
- [Azure setup](docs/azure-setup.md)
- [Solution map](docs/solution-map.md)
- [Architecture](docs/architecture.md)
- [Provider adapters](docs/providers.md)
- [Security and privacy](docs/security-and-privacy.md)
- [Testing and evidence](docs/testing.md)
- [Customization](docs/customization.md)
- [Agent Skills](docs/agent-skills.md)
- [Agent compatibility](docs/agent-compatibility.md)

Contributions are welcome under [CONTRIBUTING.md](CONTRIBUTING.md). See
[SUPPORT.md](SUPPORT.md), [SECURITY.md](SECURITY.md), and the [MIT license](LICENSE).
