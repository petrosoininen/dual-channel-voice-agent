"""Content-free in-memory telemetry for reference lifecycle diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic
from uuid import UUID

_ALLOWED_EVENTS = {
    "app_transport_connected",
    "app_transport_disconnected",
    "voice_connection_started",
    "voice_connection_ready",
    "voice_connection_failed",
    "speech_ended",
    "first_audio",
    "playback_stopped",
    "document_pending",
    "document_committed",
    "document_failed",
    "turn_outcome",
}


@dataclass(frozen=True)
class TelemetryRecord:
    """One bounded telemetry observation with app-owned correlation only."""

    name: str
    recorded_monotonic: float
    session_id: UUID | None = None
    turn_id: UUID | None = None
    duration_ms: int | None = None
    outcome: str | None = None


class TelemetryRecorder:
    """Retain content-free diagnostics in process memory only."""

    def __init__(self) -> None:
        self._records: list[TelemetryRecord] = []
        self._lock = RLock()

    def record(
        self,
        name: str,
        *,
        session_id: UUID | None = None,
        turn_id: UUID | None = None,
        duration_ms: int | None = None,
        outcome: str | None = None,
    ) -> None:
        """Record allowlisted metadata without payloads or provider identifiers."""

        if name not in _ALLOWED_EVENTS:
            raise ValueError("Telemetry event is not allowlisted.")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("Telemetry duration cannot be negative.")
        if outcome is not None and (
            not outcome.isascii() or len(outcome) > 40 or not outcome.replace("_", "").isalnum()
        ):
            raise ValueError("Telemetry outcome is invalid.")
        with self._lock:
            self._records.append(
                TelemetryRecord(
                    name=name,
                    recorded_monotonic=monotonic(),
                    session_id=session_id,
                    turn_id=turn_id,
                    duration_ms=duration_ms,
                    outcome=outcome,
                )
            )

    def snapshot(self) -> tuple[TelemetryRecord, ...]:
        """Return an immutable process-memory snapshot."""

        with self._lock:
            return tuple(self._records)
