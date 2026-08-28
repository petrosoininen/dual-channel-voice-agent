"""Summarize content-free deterministic acknowledgment timing samples."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Final

DEFAULT_FIELD: Final = "acknowledgmentMs"


def percentile(samples: list[float], percent: float) -> float:
    """Return a linearly interpolated percentile over sorted samples."""

    if not samples:
        raise ValueError("At least one timing sample is required.")
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * percent
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def load_samples(path: Path, *, field: str) -> list[float]:
    """Load a JSON list or an object containing a `samples` list."""

    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    records = value.get("samples") if isinstance(value, dict) else value
    if not isinstance(records, list):
        raise ValueError("Timing input must be a JSON list or contain a samples list.")

    samples: list[float] = []
    for index, record in enumerate(records, start=1):
        raw = record.get(field) if isinstance(record, dict) else record
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"Timing sample {index} is not numeric.")
        sample = float(raw)
        if not math.isfinite(sample) or sample < 0:
            raise ValueError(f"Timing sample {index} must be finite and non-negative.")
        samples.append(sample)
    return samples


def main() -> int:
    """Parse timing data and emit a content-free p50/p95 JSON summary."""

    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--field", default=DEFAULT_FIELD)
    parser.add_argument("--expect-count", type=int)
    parser.add_argument(
        "--label",
        default="deterministic_local_acknowledgment_handling",
    )
    arguments = parser.parse_args()

    samples = load_samples(arguments.path, field=arguments.field)
    if arguments.expect_count is not None and len(samples) != arguments.expect_count:
        raise ValueError(
            f"Expected {arguments.expect_count} timing samples; received {len(samples)}."
        )
    summary = {
        "label": arguments.label,
        "count": len(samples),
        "unit": "milliseconds",
        "p50": round(percentile(samples, 0.50), 3),
        "p95": round(percentile(samples, 0.95), 3),
        "thresholdApplied": False,
        "voiceLiveAudioLatency": False,
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
