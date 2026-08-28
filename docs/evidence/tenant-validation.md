# Sanitized tenant-validation evidence

Repository version: `0.1.0`
Validation date: 2026-08-27; cleanup verified 2026-08-28

| IaC path | Logical scope | Preview/plan | Deploy/apply | Shared bootstrap | Preflight/smoke | Cleanup |
| --- | --- | --- | --- | --- | --- | --- |
| Bicep | Isolated group, AIServices account/project, model deployment, RBAC | Passed | Passed | Passed, including idempotent reuse | Partial: configuration, project access, and three-turn Foundry backend passed; browser voice smoke was inconclusive after transient model throttling | Passed; exact group absence reverified |
| Terraform | Independent equivalent environment | Passed | Passed | Passed, including idempotent reuse | Partial: configuration, project access, and three-turn Foundry backend passed; browser voice smoke was not completed before cleanup | Passed; destroy completed and exact group absence reverified |

Both IaC implementations are tenant-validated for management-plane provisioning, RBAC,
shared Prompt Agent bootstrap, project access, Foundry execution, and cleanup. Physical
microphone, generated audio, and the full browser voice path remain **Bring your own**,
not tenant-validated claims.

This file intentionally contains no subscription, tenant, principal, resource, deployment,
endpoint, hostname, region, raw output, log, parameter value, plan, or Terraform state.
