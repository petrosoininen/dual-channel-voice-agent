"""Verify the shared-contract marker and file digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / "contracts" / "contract-freeze.json"
EXPECTED_SCOPE = [
    "app commands",
    "app events",
    "semantic document patches",
    "opportunity document model",
    "per-conversation queue semantics",
    "shared synthetic acceptance fixtures",
    "voice acknowledgment authority",
]
EXPECTED_DOCUMENT_SEMANTICS = {
    "canonicalDocumentsPerConversation": 1,
    "initialVersion": 0,
    "commitVersionIncrement": 1,
    "patchApplication": "atomic",
    "baseVersionPolicy": "must-equal-canonical",
    "duplicateDelivery": "idempotent-or-collision-error",
    "revert": "new-restoring-version",
    "reasonedNoOp": "success-without-version-increment",
    "persistence": "process-memory-only",
}
EXPECTED_QUEUE_SEMANTICS = {
    "executionOrder": "fifo-per-conversation",
    "runningCapacity": 1,
    "pendingCapacity": 3,
    "queuedCancellation": "immediate-no-commit",
    "runningCancellation": "best-effort-late-result-suppressed",
    "voiceInterruptionCancelsDeepWork": False,
}
EXPECTED_TRANSPORT_SEMANTICS = {
    "eventRecovery": "recorded-validated-replay",
    "subscriberOverflow": "close-reconnect-replay",
    "websocketAuthorization": "trusted-origin-host-and-session-token",
    "voiceLifecycle": "browser-observed-and-turn-correlated",
    "voiceAcknowledgment": "model-generated-buffered-claim-validated",
}
EXPECTED_REVISION_RATIONALE = (
    "Version 1.0.0 defines the public shared contract for document authority, ordered "
    "work, event recovery, and transcript-gated generative voice acknowledgment."
)
EXPECTED_REVISION_POLICY = (
    "Any shared-contract change requires a new contract version, a written rationale, "
    "regenerated fixtures/schemas, and reruns of every implemented mode and frontend "
    "suite affected."
)


def _digest(path: Path) -> str:
    canonical = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def main() -> int:
    """Fail when a frozen artifact changed without a marker revision."""

    with MARKER.open(encoding="utf-8") as stream:
        marker = json.load(stream)
    if marker.get("freezeStatus") != "frozen":
        raise ValueError("The shared contract freeze status is not frozen.")
    if marker.get("contractVersion") != "1.0.0":
        raise ValueError("The expected public contract version is 1.0.0.")
    if marker.get("scope") != EXPECTED_SCOPE:
        raise ValueError("Frozen shared-contract scope is missing or altered.")
    if marker.get("documentSemantics") != EXPECTED_DOCUMENT_SEMANTICS:
        raise ValueError("Frozen document semantics are missing or altered.")
    if marker.get("queueSemantics") != EXPECTED_QUEUE_SEMANTICS:
        raise ValueError("Frozen queue semantics are missing or altered.")
    if marker.get("transportSemantics") != EXPECTED_TRANSPORT_SEMANTICS:
        raise ValueError("Frozen transport semantics are missing or altered.")
    if marker.get("revisionRationale") != EXPECTED_REVISION_RATIONALE:
        raise ValueError("Frozen revision rationale is missing or altered.")
    guarantees = marker.get("guarantees")
    if not isinstance(guarantees, list) or len(guarantees) != 6:
        raise ValueError("Frozen contract guarantees are missing or altered.")
    if marker.get("revisionPolicy") != EXPECTED_REVISION_POLICY:
        raise ValueError("Frozen revision policy is missing or altered.")

    files = marker.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("The freeze marker contains no frozen files.")
    for relative_path, expected_digest in files.items():
        if not isinstance(relative_path, str) or not isinstance(expected_digest, str):
            raise ValueError("The freeze marker file map is invalid.")
        path = (ROOT / relative_path).resolve()
        if ROOT.resolve() not in path.parents:
            raise ValueError("A frozen path escapes the project root.")
        if not path.is_file():
            raise ValueError(f"Frozen file is missing: {relative_path}")
        if _digest(path) != expected_digest:
            raise ValueError(
                f"Frozen file changed without a contract revision: {relative_path}"
            )
    print(
        f"Shared contract freeze {marker['contractVersion']} verified "
        f"across {len(files)} files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
