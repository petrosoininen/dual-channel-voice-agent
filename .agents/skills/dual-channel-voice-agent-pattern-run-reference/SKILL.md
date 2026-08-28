---
name: dual-channel-voice-agent-pattern-run-reference
description: Configures and runs the browser reference from bring-your-own IaC outputs, performs preflights, executes the three turns, and diagnoses sanitized failures. Use for local setup, smoke tests, or reference rehearsal.
license: MIT
compatibility: Requires Python, Node.js, a supported browser, and user-provisioned Azure resources for the primary live reference.
---

# Run the reference

## Workflow

1. Read `AGENTS.md`, `docs/run-reference.md`, and `docs/testing.md`.
2. Put real bindings in ignored `.env` or an external file; never echo them.
3. Run `python -m scripts.doctor --env-file <path>`.
4. For the primary reference, select `azure-voice-live` and `foundry`.
5. Start the backend with explicit provider flags, then start the frontend.
6. Execute the exact three synthetic turns from `fixtures/scripted-turns.json`.
7. Verify acknowledgments remain non-authoritative and versions commit in FIFO order.
8. Inspect only content-free diagnostics.
9. Stop local processes and follow the selected IaC cleanup procedure.

Do not call deterministic behavior live Azure evidence. Do not record audio, transcripts,
bindings, provider IDs, raw errors, or resource details.

## Acceptance criteria

- Provider badges match the server configuration.
- Preflights are sanitized and no silent provider fallback occurs.
- One document advances through three ordered versions.
- Live, deterministic, and illustrative evidence are labeled truthfully.

## Prompt scenarios

- "Run the bring-your-own browser reference from this external environment file."
- "Rehearse the three-turn deterministic contract without Azure."
- "Diagnose why the Voice Live preflight is incomplete without printing values."
