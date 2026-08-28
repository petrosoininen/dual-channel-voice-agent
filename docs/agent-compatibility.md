# Agent compatibility

## Canonical files

- `AGENTS.md` is the only cross-agent repository instruction source.
- `.agents/skills/*/SKILL.md` is the only repository skill catalog.
- `CLAUDE.md` imports `AGENTS.md` and points Claude Code to the canonical skills.

There are no copied or symlinked `.claude/skills`, `.cursor/skills`, `.codex/skills`,
`.github/skills`, Cursor rules, Codex rules, or Copilot instruction files.

## Discovery expectations

| Agent | Instructions | Skills |
| --- | --- | --- |
| Codex | Native `AGENTS.md` discovery | Native `.agents/skills` discovery |
| Cursor | Native `AGENTS.md` project rules | Native `.agents/skills` discovery |
| Claude Code | `CLAUDE.md` imports `AGENTS.md` | Import bridge directs explicit lookup |
| Generic Agent Skills consumer | Explicit file load if needed | Open `SKILL.md` packages |

## Verification

CI statically verifies canonical paths, import shape, naming, frontmatter, uniqueness,
line bounds, and absence of compatibility copies. The official reference library
validates every skill.

Safe interactive discovery checks:

1. Codex/Cursor: start at repository root, request the architecture skill, and confirm
   the canonical file path is read.
2. Claude Code: run `/context`, confirm `AGENTS.md` is imported, then request one named
   skill and confirm it reads `.agents/skills/<name>/SKILL.md`.

Record a check as unexecuted when the CLI is unavailable or when invoking it would send
repository content outside the approved data boundary.
