---
name: dual-channel-voice-agent-pattern-customize-domain
description: Replaces synthetic fixtures, prompt terminology, document labels, and UI copy coherently. Use when adapting the reference to another public or synthetic domain while preserving schema and authority rules.
license: MIT
---

# Customize the domain

## Workflow

1. Read `AGENTS.md`, `docs/customization.md`, and the contract freeze.
2. Use only public or clearly synthetic source material.
3. Update the project fixture and three-turn fixture together.
4. Update deterministic patches, prompt terminology, document projection, and UI labels.
5. Preserve evidence/inference/unknown classification and stable semantic operations.
6. Regenerate schemas only if a deliberate contract revision is required.
7. Run fixture, patch, parity, frontend, and browser tests.
8. Run the expanded sensitive-reference scan.

Never copy customer records, company terminology, internal prompts, environment values,
or proprietary schemas.

## Acceptance criteria

- Fixtures are clearly synthetic and internally coherent.
- Prompt, patch, schema, and UI terms do not drift.
- Authority, atomicity, classification, history, and cancellation invariants remain.
- Sensitive-reference scanning and shared contract tests pass.

## Prompt scenarios

- "Adapt the pattern to a synthetic maintenance-planning scenario."
- "Change the working-document labels without weakening patch validation."
- "Review these fixtures for real-world or proprietary leakage."
