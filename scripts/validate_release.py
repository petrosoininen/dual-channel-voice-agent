"""Validate the exact credential-free publishable tree."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.validate_iac_parity import validate as validate_iac_parity

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release-manifest.json"
DOCUMENTATION_INDEX = ROOT / "docs" / "README.md"
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".terraform",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "infra-validation",
    "node_modules",
    "playwright-report",
    "release-scan",
    "test-results",
}
TEXT_SUFFIXES = {
    "",
    ".bicep",
    ".css",
    ".example",
    ".hcl",
    ".html",
    ".json",
    ".lock",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".tf",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer value": re.compile(r"\bbearer\s+[a-z0-9._~-]{16,}", re.IGNORECASE),
    "resource identifier": re.compile(
        r"/subscriptions/[0-9a-f-]{8,}",
        re.IGNORECASE,
    ),
    "personal path": re.compile(r"\b[A-Z]:\\Users\\|/(?:home|Users)/[^/]+/"),
    "configured endpoint": re.compile(
        r"https://[a-z0-9][a-z0-9.-]*\."
        r"(?:services\.ai|cognitiveservices|openai)\.azure\.com",
        re.IGNORECASE,
    ),
    "internal package feed": re.compile(
        r"https://[^/\s]*(?:pkgs\.visualstudio\.com|pkgs\.dev\.azure\.com)/",
        re.IGNORECASE,
    ),
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
GUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
COMPANY_NAME = re.compile(r"\bMicro" + r"soft\b")
INTERNAL_PROCESS_LANGUAGE = re.compile(
    r"\b(?:phase\s*\d+|release "
    + r"candidate|working "
    + r"tree|proof of "
    + r"concept|P"
    + r"OC)\b",
    re.IGNORECASE,
)
ALLOWED_COMPANY_TECHNICAL_REFERENCES = (
    re.compile(r"https://learn\.microsoft\.com/", re.IGNORECASE),
    re.compile(
        r"Micro" r"soft\.(?:Authorization|CognitiveServices|DefaultV2|Resources)\b"
    ),
)


def publishable_files() -> list[Path]:
    return sorted(
        (
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
        ),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def manifest() -> dict[str, object]:
    paths = {
        path.relative_to(ROOT).as_posix() for path in publishable_files()
    }
    paths.add(MANIFEST_PATH.relative_to(ROOT).as_posix())
    return {
        "version": 1,
        "files": sorted(paths),
    }


def validate() -> list[str]:
    errors = validate_iac_parity()
    files = publishable_files()
    relative_paths = {path.relative_to(ROOT).as_posix() for path in files}

    forbidden_paths = {
        ".env",
        ".cursorrules",
        ".github/copilot-instructions.md",
        "scripts/publish_foundry_agent.py",
        "scripts/verify_toolchain.ps1",
        "tooling/selected-toolchain.json",
    }
    for path in sorted(forbidden_paths.intersection(relative_paths)):
        errors.append(f"Forbidden publishable path: {path}.")

    for path in files:
        relative = path.relative_to(ROOT)
        relative_text = relative.as_posix()
        if path.is_symlink():
            errors.append(f"Symbolic link is not publishable: {relative_text}.")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"Text file is not UTF-8: {relative_text}.")
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{name} pattern: {relative_text}.")
        if _contains_prohibited_company_prose(content):
            errors.append(f"Prohibited company prose: {relative_text}.")
        if _contains_internal_process_language(relative_text) or (
            _contains_internal_process_language(content)
        ):
            errors.append(f"Internal development-process reference: {relative_text}.")
        if GUID.search(content) and relative.parts[0] not in {
            "contracts",
            "fixtures",
            "tests",
        }:
            errors.append(f"Non-fixture GUID: {relative_text}.")
        if path.suffix.lower() == ".md":
            errors.extend(_validate_links(path, content))

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if package.get("license") != "MIT":
        errors.append("package.json must declare MIT.")
    package_lock = json.loads(
        (ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    if _contains_resolved_registry_url(package_lock):
        errors.append("package-lock.json must not pin registry URLs.")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if 'license = "MIT"' not in pyproject:
        errors.append("pyproject.toml must declare MIT.")
    if not (ROOT / "LICENSE").is_file():
        errors.append("LICENSE is missing.")
    errors.extend(_validate_documentation_index(files))

    if not MANIFEST_PATH.is_file():
        errors.append("release-manifest.json is missing.")
    else:
        recorded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        expected = manifest()
        if recorded != expected:
            errors.append("release-manifest.json does not match the publishable tree.")

    return sorted(set(errors))


def _contains_prohibited_company_prose(content: str) -> bool:
    for line in content.splitlines():
        candidate = line
        for allowed in ALLOWED_COMPANY_TECHNICAL_REFERENCES:
            candidate = allowed.sub("", candidate)
        if COMPANY_NAME.search(candidate):
            return True
    return False


def _contains_internal_process_language(content: str) -> bool:
    return INTERNAL_PROCESS_LANGUAGE.search(content) is not None


def _contains_resolved_registry_url(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (
                key == "resolved"
                and isinstance(child, str)
                and child.startswith(("http://", "https://"))
            )
            or _contains_resolved_registry_url(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_resolved_registry_url(child) for child in value)
    return False


def _validate_documentation_index(files: list[Path]) -> list[str]:
    if not DOCUMENTATION_INDEX.is_file():
        return ["docs/README.md is missing."]

    content = DOCUMENTATION_INDEX.read_text(encoding="utf-8")
    indexed_targets = {
        raw_target.split("#", 1)[0].strip()
        for raw_target in MARKDOWN_LINK.findall(content)
        if not raw_target.startswith(("http://", "https://", "mailto:", "#"))
    }
    expected_targets = {
        path.relative_to(DOCUMENTATION_INDEX.parent).as_posix()
        for path in files
        if path.suffix.lower() == ".md"
        and DOCUMENTATION_INDEX.parent in path.parents
        and path != DOCUMENTATION_INDEX
    }
    missing = sorted(expected_targets - indexed_targets)
    return [f"Documentation index is missing: {target}." for target in missing]


def _validate_links(path: Path, content: str) -> list[str]:
    errors: list[str] = []
    for raw_target in MARKDOWN_LINK.findall(content):
        target = raw_target.split("#", 1)[0].strip()
        if (
            not target
            or target.startswith(("http://", "https://", "mailto:"))
        ):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.is_relative_to(ROOT.resolve()) or not resolved.exists():
            errors.append(
                f"Broken local link in {path.relative_to(ROOT).as_posix()}: {target}."
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        MANIFEST_PATH.write_text(
            json.dumps(manifest(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("Wrote sanitized publishable-tree manifest.")
        return 0
    errors = validate()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Publication-readiness validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
