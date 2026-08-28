---
name: dual-channel-voice-agent-pattern-provision-azure
description: Previews and provisions the equivalent Bicep or Terraform Azure prerequisites. Use when checking policy, quota, plans, applies, outputs, or exact cleanup for a bring-your-own environment.
license: MIT
compatibility: Requires Azure CLI login and either Bicep through Azure CLI or Terraform. Apply and destroy require explicit user authorization.
---

# Provision Azure prerequisites

## Workflow

1. Read `AGENTS.md`, `infra/AGENTS.md`, and `infra/README.md`.
2. Confirm the active subscription without writing its value into the repository.
3. Check current policy, provider registration, region support, model catalog, and quota.
4. Create a unique suffix and keep real inputs in an ignored or external parameter file.
5. Run Bicep build/lint plus what-if, or Terraform format/init/validate plus plan.
6. Summarize the logical changes without identifiers.
7. Apply only after explicit confirmation.
8. Run `scripts/bootstrap_agent.py` separately; never embed it in IaC.
9. Run `scripts/doctor.py` and application preflights.
10. Destroy only the exact environment created by this run and verify absence.

Never print tokens or persist real parameter, plan, output, state, endpoint, principal,
resource, or deployment values in source.

## Acceptance criteria

- Preview precedes apply and Bicep/Terraform parity passes.
- Bootstrap is confirmation-gated and separate from management-plane IaC.
- Cleanup targets exact created resources and deletion is verified.
- Evidence contains only date, version, logical scope, result class, and cleanup status.

## Prompt scenarios

- "Preview the Bicep prerequisites without creating resources."
- "Plan the Terraform path and explain every logical resource."
- "Provision this authorized ephemeral environment, smoke-test it, and verify cleanup."
