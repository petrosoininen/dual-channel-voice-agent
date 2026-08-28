"""Release validation remains deterministic and credential-free."""

from scripts.validate_release import (
    SECRET_PATTERNS,
    _contains_internal_process_language,
    _contains_prohibited_company_prose,
    _contains_resolved_registry_url,
    validate,
)


def test_publishable_tree_passes_release_validation() -> None:
    assert validate() == []


def test_company_prose_filter_preserves_required_technical_references() -> None:
    allowed = "\n".join(
        (
            "https://learn.microsoft.com/azure/example",
            "Microsoft.CognitiveServices/accounts@2026-05-01",
            "Microsoft.Authorization/roleAssignments@2022-04-01",
            "Microsoft.Resources/resourceGroups@2024-11-01",
            'rai_policy_name = "Microsoft.DefaultV2"',
        )
    )
    assert not _contains_prohibited_company_prose(allowed)
    company_name = "Micro" + "soft"
    assert _contains_prohibited_company_prose(
        f"This repository is sponsored by {company_name}."
    )


def test_internal_development_process_language_is_rejected() -> None:
    assert _contains_internal_process_language("Phase " + "4 acceptance")
    assert _contains_internal_process_language("release " + "candidate")
    assert _contains_internal_process_language("candidate working " + "tree")
    assert _contains_internal_process_language("technical " + "P" + "OC")
    assert _contains_internal_process_language("proof of " + "concept")
    assert not _contains_internal_process_language(
        "Cancellation reports a queued or running lifecycle phase."
    )


def test_internal_package_feeds_are_rejected() -> None:
    pattern = SECRET_PATTERNS["internal package feed"]
    assert pattern.search(
        "https://feed.pkgs." + "visualstudio.com/project/_packaging/npm/registry/"
    )
    assert pattern.search(
        "https://pkgs.dev." + "azure.com/example/_packaging/npm/registry/"
    )
    assert not pattern.search("https://registry.npmjs.org/package")


def test_resolved_registry_urls_are_rejected() -> None:
    assert _contains_resolved_registry_url(
        {"packages": {"node_modules/example": {"resolved": "https://registry.example"}}}
    )
    assert not _contains_resolved_registry_url(
        {"packages": {"node_modules/example": {"integrity": "sha512-example"}}}
    )
