"""Tests for timing summaries and release-verification scripts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.summarize_latency import load_samples, percentile
from scripts.verify_contract_freeze import _digest, main as verify_contract_freeze


def test_latency_summary_loads_content_free_samples_and_interpolates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "samples.json"
    path.write_text(
        json.dumps(
            {
                "samples": [
                    {"sample": index, "acknowledgmentMs": float(index)}
                    for index in range(1, 11)
                ]
            }
        ),
        encoding="utf-8",
    )

    samples = load_samples(path, field="acknowledgmentMs")
    assert percentile(samples, 0.50) == 5.5
    assert percentile(samples, 0.95) == pytest.approx(9.55)


def test_latency_summary_rejects_sensitive_or_invalid_shapes(tmp_path: Path) -> None:
    path = tmp_path / "samples.json"
    path.write_text(
        json.dumps({"samples": [{"acknowledgmentMs": "transcript content"}]}),
        encoding="utf-8",
    )

    try:
        load_samples(path, field="acknowledgmentMs")
    except ValueError as error:
        assert str(error) == "Timing sample 1 is not numeric."
    else:
        raise AssertionError("A nonnumeric timing payload was accepted.")


def test_contract_freeze_marker_matches_authoritative_files() -> None:
    assert verify_contract_freeze() == 0


def test_contract_freeze_digest_is_line_ending_invariant(tmp_path: Path) -> None:
    lf_path = tmp_path / "lf.json"
    crlf_path = tmp_path / "crlf.json"
    lf_path.write_bytes(b'{\n  "value": true\n}\n')
    crlf_path.write_bytes(b'{\r\n  "value": true\r\n}\r\n')

    assert _digest(lf_path) == _digest(crlf_path)


def test_clean_room_scan_handles_empty_authored_files(tmp_path: Path) -> None:
    project = tmp_path / "asset"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(
        Path(__file__).parents[2] / "scripts" / "verify_clean_room.ps1",
        scripts / "verify_clean_room.ps1",
    )
    (project / "empty.md").touch()
    terms = tmp_path / "prohibited-terms.txt"
    terms.write_text("private-marker\n", encoding="utf-8")

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(scripts / "verify_clean_room.ps1"),
            "-ProhibitedTermsPath",
            str(terms),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_clean_room_scan_rejects_import_into_prefix_sibling(tmp_path: Path) -> None:
    project = tmp_path / "asset"
    scripts = project / "scripts"
    source = project / "src"
    scripts.mkdir(parents=True)
    source.mkdir()
    shutil.copy(
        Path(__file__).parents[2] / "scripts" / "verify_clean_room.ps1",
        scripts / "verify_clean_room.ps1",
    )
    (tmp_path / "asset-sibling").mkdir()
    (source / "probe.ts").write_text(
        'import "../../asset-sibling/module.js";\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(scripts / "verify_clean_room.ps1"),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1
    assert "relative import escapes project root" in result.stdout + result.stderr
