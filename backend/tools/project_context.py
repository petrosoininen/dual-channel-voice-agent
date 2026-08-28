"""Bounded synthetic project-context tool for one Foundry request."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic import JsonValue

PROJECT_CONTEXT_TOOL_NAME = "project_context"
MAX_PROJECT_CONTEXT_BYTES = 32_768
ROOT = Path(__file__).resolve().parents[2]

ProjectContext = dict[str, JsonValue]
ProjectContextTool = Callable[[], ProjectContext]


def load_synthetic_project_context(
    path: Path = ROOT / "fixtures" / "synthetic-project.json",
) -> ProjectContext:
    """Load and bound the checked-in customer-neutral project fixture."""

    raw = path.read_bytes()
    if len(raw) > MAX_PROJECT_CONTEXT_BYTES:
        raise ValueError("Synthetic project context exceeds its allowed size.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Synthetic project context must be a JSON object.")
    return value


def create_project_context_tool(
    context: Mapping[str, JsonValue],
) -> ProjectContextTool:
    """Create a request-scoped callable with the persisted Prompt Agent tool name."""

    serialized = json.dumps(
        dict(context),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(serialized.encode("utf-8")) > MAX_PROJECT_CONTEXT_BYTES:
        raise ValueError("Synthetic project context exceeds its allowed size.")

    def project_context() -> ProjectContext:
        """Return the bounded synthetic project context for this deep-work request."""

        value = json.loads(serialized)
        if not isinstance(value, dict):  # pragma: no cover - construction proves this
            raise RuntimeError("Synthetic project context is unavailable.")
        return value

    return project_context
