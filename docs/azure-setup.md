# Bring-your-own Azure setup

Reviewed: 2026-08-27.

Azure service capabilities, regions, models, quotas, roles, APIs, preview terms, and
prices change. Verify current official guidance before each deployment:

- [Voice Live overview](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live)
- [Voice Live WebRTC preview](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-webrtc)
- [Voice Live regions](https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=voice-live)
- [Foundry Prompt Agent quickstart](https://learn.microsoft.com/azure/foundry/agents/quickstarts/prompt-agent)
- [Foundry RBAC](https://learn.microsoft.com/azure/foundry/concepts/rbac-foundry)
- [Foundry model catalog](https://ai.azure.com/catalog/models)

## Required logical resources

Both IaC paths create:

1. one isolated resource group;
2. one `AIServices` account with project management and system identity;
3. one Foundry project with system identity;
4. one parameterized model deployment for the Prompt Agent;
5. least-privilege account/project role assignments for operator and runtime principals.

Voice Live models are normally fully managed and selected at request time; the Prompt
Agent still needs its own supported model deployment. Do not assume the same model,
quota unit, or lifecycle applies to both.

## Keyless access

Authenticate the Azure CLI in the intended tenant:

```text
az login --tenant <tenant-id>
az account set --subscription <subscription-id>
```

The application uses `DefaultAzureCredential` constrained to `AzureCliCredential` for
local development. There is no key fallback. Resolve current built-in role definition
IDs by role name at deployment time and keep them in the ignored/external parameter
file. The templates expect roles equivalent to:

- Cognitive Services User for Voice Live;
- Foundry Project Manager for agent bootstrap;
- Foundry User for agent execution.

Role naming can change while stable IDs remain; confirm current RBAC documentation.
Creating role assignments also requires authorization at the target scope.

## Region, provider, policy, and quota checks

Before preview:

1. confirm the subscription is enabled;
2. inspect effective Azure Policy assignments;
3. confirm the cognitive services resource provider is registered;
4. check Voice Live region/model support;
5. check Prompt Agent model availability and deployment SKU quota;
6. use the smallest capacity suitable for a disposable smoke test.

If policy, quota, role, provider registration, or preview availability blocks the run,
record only the blocker class and stop. Do not weaken security or reuse unrelated
resources.

## Cost and data processing

The account and model deployment can incur charges. Voice Live bills according to its
selected model and audio/text use. Provider-side prompts, audio, transcripts, and agent
state follow your resource configuration and applicable service terms. This application
does not promise zero retention, residency, compliance, or a fixed price.

## Provision and destroy

Follow [infra/README.md](../infra/README.md). Use unique ephemeral names, preview before
apply, run the shared bootstrap and smoke tests, then destroy and verify deletion. Never
use a pre-existing resource group for the validation workflow.

## Application bindings

Map only public outputs to an ignored/external environment file. Never copy Terraform
state, parameter files, deployment output, logs, or real identifiers into this
repository. Run `python -m scripts.doctor --env-file <path>` before starting.
