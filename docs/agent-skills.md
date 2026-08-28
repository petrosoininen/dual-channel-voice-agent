# Repository Agent Skills

Canonical skills live only under `.agents/skills/`.

| Skill | Use |
| --- | --- |
| `dual-channel-voice-agent-pattern-understand-architecture` | Explain seams, authority, contracts, and change impact |
| `dual-channel-voice-agent-pattern-provision-azure` | Preview/apply either IaC path and verify cleanup |
| `dual-channel-voice-agent-pattern-run-reference` | Configure, preflight, run, and diagnose the reference |
| `dual-channel-voice-agent-pattern-add-provider` | Implement a provider against shared contracts |
| `dual-channel-voice-agent-pattern-customize-domain` | Change synthetic fixtures, prompts, schema, and UI coherently |
| `dual-channel-voice-agent-pattern-validate-release` | Run the complete credential-free release gate |

Invocation examples:

- Codex: `$dual-channel-voice-agent-pattern-understand-architecture`
- Cursor: `/dual-channel-voice-agent-pattern-run-reference`
- Claude Code: ask to use the named skill; `CLAUDE.md` points to the canonical catalog.
- Other agents: read the matching `.agents/skills/<name>/SKILL.md` explicitly.

Provision, apply, destroy, agent bootstrap, and release actions require explicit user
intent. Read-only architecture understanding may match implicitly.
