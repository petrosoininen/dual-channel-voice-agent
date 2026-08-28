---
name: dual-channel-voice-agent-pattern-understand-architecture
description: Explains the dual-channel design, authority rules, contracts, reusable seams, and change impact. Use when exploring the repository, planning a change, or tracing voice-to-document behavior.
license: MIT
---

# Understand the architecture

## Workflow

1. Read `AGENTS.md` and `docs/solution-map.md`.
2. Identify whether the question concerns voice, deep work, shared contracts, state, or
   infrastructure.
3. Trace from the relevant entry point to its provider boundary and authoritative
   service.
4. Distinguish repository facts from adaptation ideas.
5. Name the tests and documents affected by a proposed change.

Do not infer production durability, authorization, provider support, or live status.
The working document is authoritative; voice and completion summaries are not.

## Acceptance criteria

- Names both independent channels and their failure isolation.
- Identifies the semantic patch service as the mutation authority.
- Identifies provider selection, contract files, state ownership, and validation commands.
- Labels unimplemented adaptations as suggestions.

## Prompt scenarios

- "Explain why voice interruption does not cancel document work."
- "Where would I change queue capacity, and which tests protect it?"
- "Trace a final transcript into a committed document version."
