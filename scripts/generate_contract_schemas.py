"""Generate checked-in authoritative JSON Schemas from strict wire models."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter

from backend.domain.events import AppCommand, AppEvent, MAX_WIRE_BYTES
from backend.domain.models import DocumentPatchProposal

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def _render(
    name: str,
    schema: dict[str, object],
    *,
    title: str,
) -> tuple[Path, bytes]:
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = (
        f"https://example.invalid/dual-channel-voice-agent-pattern/contracts/{name}"
    )
    schema["title"] = title
    schema["x-maxWireBytes"] = MAX_WIRE_BYTES
    path = CONTRACTS / name
    content = (json.dumps(schema, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    return path, content


def canonical_schemas() -> tuple[tuple[Path, bytes], ...]:
    """Render every authoritative schema deterministically in memory."""

    return (
        _render(
            "app-events.schema.json",
            TypeAdapter(AppEvent).json_schema(
                by_alias=True,
                union_format="any_of",
            ),
            title="Dual-channel application events",
        ),
        _render(
            "app-commands.schema.json",
            TypeAdapter(AppCommand).json_schema(
                by_alias=True,
                union_format="any_of",
            ),
            title="Dual-channel application commands",
        ),
        _render(
            "document-patch.schema.json",
            DocumentPatchProposal.model_json_schema(by_alias=True),
            title="Atomic opportunity document patch",
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Generate schemas or fail when checked-in bytes drift from the models."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare canonical in-memory bytes without modifying files.",
    )
    arguments = parser.parse_args(argv)

    drifted: list[str] = []
    for path, content in canonical_schemas():
        if arguments.check:
            if not path.is_file() or path.read_bytes() != content:
                drifted.append(path.name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    if drifted:
        parser.error(
            "Generated contract schema drift: " + ", ".join(sorted(drifted))
        )
    if arguments.check:
        print("Generated contract schemas match canonical model output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
