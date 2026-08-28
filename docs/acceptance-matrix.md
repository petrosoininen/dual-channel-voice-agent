# Acceptance coverage

This matrix states what the repository demonstrates and the evidence available for each
claim. Evidence labels follow [Testing and evidence](testing.md).

| Area | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| Provider selection | Voice and agent providers are selected independently by server-owned configuration | Factory, configuration, and mode-parity tests | CI-verified |
| Credential-free mode | `off` voice plus `deterministic` agent runs without cloud credentials | Backend, frontend, and Chromium tests | CI-verified |
| Voice authority | Generated acknowledgment audio is played only after its completed transcript passes claim validation | Transport tests and shared contract | CI-verified |
| Voice interruption | Barge-in stops voice playback without cancelling accepted document work | Transport and queue tests | CI-verified |
| Ordered work | One task runs per conversation while at most three wait in FIFO order | Queue and acceptance tests | CI-verified |
| Document authority | Only complete, valid semantic patches can update the canonical document | Patch, contract, and acceptance tests | CI-verified |
| Cancellation | Queued cancellation is immediate; running cancellation suppresses late provider results | Queue and provider tests | CI-verified |
| History | Each commit creates an immutable version; revert creates a new restoring version | Backend and Chromium tests | CI-verified |
| Reconnect | Validated recorded events replay before live events after reconnect | Event-hub, WebSocket, and frontend tests | CI-verified |
| Local transport security | WebSockets require allowed origin, host, and session authorization | Transport and security tests | CI-verified |
| Infrastructure parity | Bicep and Terraform expose the same logical resources, roles, defaults, and outputs | Static build, validation, and parity checks | CI-verified |
| Bicep deployment | Provisioning, agent bootstrap, Foundry execution, and cleanup completed in an isolated environment | [Sanitized tenant evidence](evidence/tenant-validation.md) | Tenant-validated |
| Terraform deployment | Provisioning, agent bootstrap, Foundry execution, and cleanup completed in an independent isolated environment | [Sanitized tenant evidence](evidence/tenant-validation.md) | Tenant-validated |
| Browser voice path | Physical microphone, generated audio, current model availability, and provider behavior depend on the user's environment | [Run guide](run-reference.md) and [Azure setup](azure-setup.md) | Bring your own |
| Media demonstration | No recording or screenshot is included | Repository inventory | Not included |

## Validation entry points

- Run the credential-free commands in [Testing and evidence](testing.md).
- Review contract guarantees in [Shared contract freeze](contract-freeze.md).
- Review provider limitations in [Provider adapters](providers.md).
- Treat unavailable provider, quota, policy, browser, or role checks as blocked rather
  than replacing them with deterministic evidence.
