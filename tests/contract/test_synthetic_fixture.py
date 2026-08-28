"""Clean-room fixture shape and claim-classification tests."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {"synthetic_evidence", "inference", "unknown"}


def _load(name: str) -> object:
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def _assert_classified(value: object) -> None:
    if isinstance(value, list):
        for item in value:
            _assert_classified(item)
        return
    if not isinstance(value, dict) or "text" not in value:
        return
    assert value.get("classification") in ALLOWED
    if value["classification"] == "synthetic_evidence":
        assert isinstance(value.get("sourceLabel"), str)
    else:
        assert "sourceLabel" not in value


def test_script_contains_exactly_three_related_turns() -> None:
    turns = _load("scripted-turns.json")

    assert isinstance(turns, list)
    assert len(turns) == 3
    assert [turn["sequence"] for turn in turns] == [1, 2, 3]
    assert len({turn["turnId"] for turn in turns}) == 3
    assert "that opportunity" in turns[1]["transcript"]


def test_every_synthetic_opportunity_claim_is_classified() -> None:
    project = _load("synthetic-project.json")
    turns = _load("scripted-turns.json")

    assert isinstance(project, dict)
    for key in (
        "goals",
        "currentCapabilities",
        "stakeholderRoles",
        "signals",
        "unknowns",
    ):
        _assert_classified(project[key])
    _assert_classified(turns)
