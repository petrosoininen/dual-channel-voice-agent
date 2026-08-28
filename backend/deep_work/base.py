"""Typed, mode-independent protocol for cancellable deep-work producers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from backend.domain.models import (
    ConversationTurn,
    DeepWorkCompletion,
    OpportunityDocument,
    ProviderMetadata,
    SanitizedError,
)


class DeepWorkControlEnvironment(StrEnum):
    """Explicit environments in which deterministic fault controls may run."""

    PRODUCTION = "production"
    DEVELOPMENT = "development"
    TEST = "test"


class DeepWorkControlError(RuntimeError):
    """Raised when test-only behavior is requested outside an allowed environment."""


class DeepWorkCancelled(Exception):
    """Internal cooperative-cancellation signal with no content-bearing details."""


class DeepWorkFailure(RuntimeError):
    """Producer failure carrying only an approved client-safe error."""

    def __init__(self, error: SanitizedError) -> None:
        self.error = error
        super().__init__(error.message)


class DeepWorkControls(BaseModel):
    """Development/test-only deterministic delay and failure controls."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    delay_ms: int = Field(default=0, ge=0, le=86_400_000)
    audio_lane_failure: bool = False
    producer_failure: bool = False
    document_failure: bool = False
    malformed_patch: bool = False
    late_result: bool = False

    @property
    def active(self) -> bool:
        """Return whether any non-production behavior is requested."""

        return (
            self.delay_ms > 0
            or self.audio_lane_failure
            or self.producer_failure
            or self.document_failure
            or self.malformed_patch
            or self.late_result
        )


def validate_controls(
    controls: DeepWorkControls,
    *,
    environment: DeepWorkControlEnvironment,
) -> None:
    """Allow deterministic controls only for explicit development/test members."""

    if controls.active and (
        environment is not DeepWorkControlEnvironment.DEVELOPMENT
        and environment is not DeepWorkControlEnvironment.TEST
    ):
        raise DeepWorkControlError(
            "Deterministic controls require explicit development or test configuration."
        )


class CancellationToken:
    """Cooperative best-effort cancellation shared with one producer invocation."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        return self._event.is_set()

    def request(self) -> None:
        """Signal cancellation without assuming producer cooperation."""

        self._event.set()

    async def wait(self) -> None:
        """Wait until cancellation is requested."""

        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        """Stop cooperative work at a safe boundary."""

        if self.is_cancelled:
            raise DeepWorkCancelled("Deep work was cancelled.")


@dataclass(frozen=True)
class DeepWorkInput:
    """Canonical input snapshot resolved only when a queued turn starts."""

    session_id: UUID
    turn_id: UUID
    sequence: int
    transcript: str
    document: OpportunityDocument
    prior_turns: tuple[ConversationTurn, ...]
    controls: DeepWorkControls


class DeepWorkOutput(BaseModel):
    """Bounded producer output that is revalidated by the patch service."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    proposal: dict[str, JsonValue]
    provider_metadata: ProviderMetadata | None = None
    completion: DeepWorkCompletion | None = None


class DeepWorker(Protocol):
    """Producer contract shared by deterministic and future Foundry modes."""

    async def run(
        self,
        work_input: DeepWorkInput,
        cancellation: CancellationToken,
    ) -> DeepWorkOutput:
        """Produce one complete proposal or raise a sanitized failure."""


@runtime_checkable
class StartupValidatedDeepWorker(DeepWorker, Protocol):
    """Provider-neutral worker with an optional startup compatibility check."""

    async def validate_compatibility(self) -> None:
        """Fail closed when the configured Prompt Agent is incompatible."""
