"""Repository Agent Skills and instruction discovery rules."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / ".agents" / "skills"
PREFIX = "dual-channel-voice-agent-pattern-"
EXPECTED = {
    f"{PREFIX}understand-architecture",
    f"{PREFIX}provision-azure",
    f"{PREFIX}run-reference",
    f"{PREFIX}add-provider",
    f"{PREFIX}customize-domain",
    f"{PREFIX}validate-release",
}


def _frontmatter(path: Path) -> dict[str, str]:
    content = path.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    assert len(parts) == 3
    values: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def test_only_six_canonical_repository_skills_exist() -> None:
    skill_files = {
        path
        for path in ROOT.rglob("SKILL.md")
        if not {".venv", "node_modules"}.intersection(path.relative_to(ROOT).parts)
    }
    expected_files = {SKILLS_ROOT / name / "SKILL.md" for name in EXPECTED}
    assert skill_files == expected_files


def test_skill_names_and_frontmatter_follow_open_spec() -> None:
    for directory in SKILLS_ROOT.iterdir():
        assert directory.is_dir()
        name = directory.name
        assert name in EXPECTED
        assert len(name) <= 64
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        metadata = _frontmatter(directory / "SKILL.md")
        assert metadata["name"] == name
        assert 1 <= len(metadata["description"]) <= 1024
        assert metadata["license"] == "MIT"
        if "compatibility" in metadata:
            assert 1 <= len(metadata["compatibility"]) <= 500


def test_each_skill_has_deterministic_acceptance_scenarios() -> None:
    for path in SKILLS_ROOT.glob("*/SKILL.md"):
        content = path.read_text(encoding="utf-8")
        assert "## Workflow" in content
        assert "## Acceptance criteria" in content
        assert "## Prompt scenarios" in content
        assert content.count('- "') >= 3
        assert len(content.splitlines()) < 500


def test_instruction_bridges_do_not_duplicate_canonical_rules() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.splitlines()[0] == "@AGENTS.md"
    assert ".agents/skills/" in claude
    assert len(claude.splitlines()) <= 4
    assert ".agents/skills/" in agents
    forbidden = (
        ROOT / ".github" / "copilot-instructions.md",
        ROOT / ".cursor" / "rules",
        ROOT / ".cursorrules",
        ROOT / ".codex",
        ROOT / ".claude" / "skills",
        ROOT / ".cursor" / "skills",
        ROOT / ".codex" / "skills",
        ROOT / ".github" / "skills",
    )
    assert all(not path.exists() for path in forbidden)
