---
name: dual-channel-voice-agent-pattern-validate-release
description: Runs credential-free CI checks, IaC parity, Agent Skill validation, sensitive-reference scans, and exact-tree review. Use before an independent public-release review or after repository-wide changes.
license: MIT
compatibility: Requires Python, Node.js, Terraform, Azure CLI Bicep, skills-ref, and Playwright Chromium for the complete local gate.
---

# Validate release readiness

## Workflow

1. Read `AGENTS.md`, `docs/testing.md`, and `docs/evidence/tenant-validation.md`.
2. Ensure dependencies, state, plans, logs, reports, and real bindings are outside the
   publishable tree.
3. Run `python -m scripts.validate_release`.
4. Run the official `skills-ref validate` command for every canonical skill.
5. Run Bicep build/lint and Terraform format/init/validate.
6. Run contracts, backend tests, frontend tests, typecheck, build, and Chromium E2E.
7. Run two independent local secret scanners and the sensitive-reference scan.
8. Review staged/allowlisted files exactly.
9. Verify every live claim has current sanitized evidence and cleanup confirmation.

Do not turn an unavailable CLI, provider, browser, policy, or quota result into a pass.

## Acceptance criteria

- All credential-free gates pass from an isolated tree.
- No `SKILL.md` or duplicated agent instruction exists outside canonical locations.
- No real identifier, endpoint, path, organization/customer reference, secret, or state
  artifact is publishable.
- Tenant evidence distinguishes each IaC path and confirms cleanup.

## Prompt scenarios

- "Run the full credential-free release gate."
- "Check the exact publishable tree for private references and generated state."
- "Summarize which claims are CI-verified, tenant-validated, illustrative, or blocked."
