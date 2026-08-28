---
name: dual-channel-voice-agent-pattern-add-provider
description: Implements and registers a new voice or agent adapter against the provider-neutral contracts. Use when adding a tested provider without changing authority, queue, document, or browser event semantics.
license: MIT
---

# Add a provider

## Workflow

1. Read `AGENTS.md`, `docs/providers.md`, and ADR 0003.
2. Complete the provider worksheet before writing code.
3. Implement either the backend voice broker/frontend voice client pair or one
   `DeepWorker`; do not reshape unrelated shared contracts.
4. Keep provider SDK imports inside the selected factory path.
5. Map provider events and failures to normalized bounded contracts.
6. Add factory, lifecycle, cancellation, sanitization, and authority tests.
7. Add opt-in live tests only when credentials and cleanup are explicit.
8. Update truthful provider status documentation.

Do not advertise a provider until the implementation and contract tests exist. Never let
provider prose or tool output mutate the document outside the patch service.

## Acceptance criteria

- Unselected providers are not imported or contacted.
- Shared deterministic contracts still pass.
- Cancellation, interruption, errors, and cleanup are normalized and tested.
- Documentation states unsupported features and live-validation status.

## Prompt scenarios

- "Add a WebSocket voice provider behind the normalized session events."
- "Add an agent adapter that emits the existing DeepWorkOutput."
- "Review this proposed provider for contract and evidence gaps."
